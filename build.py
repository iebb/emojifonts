#!/usr/bin/env python3
"""Build macOS-renderable color emoji fonts from upstream sources.

Organised as **actions**, one per upstream repo. An action builds one or more
**fonts** (variants) from that repo — e.g. `fluent` builds Color/Flat/HighContrast/
HighContrastInverted, `noto` builds the color font.

macOS Core Text renders sbix, COLRv0 and OT-SVG — not COLRv1 or CBDT. Each font is
built as **sbix** (`<font>.ttf`); SVG-backed fonts also get a vector **COLRv0**
(`<font>-colrv0.ttf`), dropping the least-common skin-tone variants if it would
exceed TrueType's 65 535-glyph cap. `download` fonts are taken as-is (e.g. the
monochrome Noto Emoji glyph font, Toss Face's sbix).

Usage:
  build.py changed [action ...]     # actions whose upstream changed
  build.py build <action> ...       # build all fonts in those actions
  build.py build-all
  build.py render-versions          # regenerate VERSIONS.md from versions/*.json
"""
import datetime
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
WORK = ROOT / "work"
DATA = ROOT / "data"
VERSIONS_DIR = ROOT / "versions"
ACTIONS = json.loads((ROOT / "sources.json").read_text())
SKIN_TONES = {0x1F3FB, 0x1F3FC, 0x1F3FD, 0x1F3FE, 0x1F3FF}
EMOJI_TEST_URL = "https://unicode.org/Public/emoji/16.0/emoji-test.txt"


# ---- upstream change detection (per action) ---------------------------------
def upstream_ref(action):
    spec = ACTIONS[action]
    if spec.get("ref_path"):                      # precise: last commit touching one path
        repo = spec["upstream"].split("github.com/")[1].rstrip("/")
        url = (f"https://api.github.com/repos/{repo}/commits"
               f"?path={urllib.parse.quote(spec['ref_path'])}&per_page=1")
        hdr = ["-H", f"Authorization: Bearer {os.environ['GH_TOKEN']}"] if os.environ.get("GH_TOKEN") else []
        r = subprocess.run(["curl", "-fsSL", *hdr, url], capture_output=True, text=True)
        try:
            return json.loads(r.stdout)[0]["sha"]
        except Exception:
            return "?"
    r = subprocess.run(["git", "ls-remote", spec["upstream"], "HEAD"], capture_output=True, text=True)
    toks = r.stdout.split()
    return toks[0] if toks else "?"

def stored_ref(action):
    p = VERSIONS_DIR / f"{action}.json"
    return json.loads(p.read_text()).get("ref") if p.exists() else None

def record_version(action, info):
    VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
    (VERSIONS_DIR / f"{action}.json").write_text(json.dumps(info, indent=2) + "\n")

def changed_actions(names=None):
    names = names or list(ACTIONS)
    return [a for a in names if upstream_ref(a) != stored_ref(a)]


# ---- emoji-version detection ------------------------------------------------
def ensure_emoji_test():
    p = DATA / "emoji-test.txt"
    if not p.exists():
        DATA.mkdir(parents=True, exist_ok=True)
        subprocess.run(["curl", "-fsSL", "-o", str(p), EMOJI_TEST_URL], check=True)
    return p

def emoji_version_index():
    """{version: [single-codepoint emoji]} from emoji-test.txt's E-tags."""
    idx = {}
    for line in open(ensure_emoji_test(), encoding="utf-8"):
        if "; fully-qualified" not in line:
            continue
        field, _, comment = line.partition("#")
        cps = [int(c, 16) for c in field.split(";")[0].split()]
        base = [c for c in cps if c != 0xFE0F]
        m = re.search(r"E(\d+\.\d+)", comment)
        if len(base) == 1 and m:
            idx.setdefault(float(m.group(1)), []).append(base[0])
    return idx

def detect_emoji_version(font_path, idx):
    from fontTools.ttLib import TTFont
    cmap = set(TTFont(str(font_path), lazy=True, fontNumber=0).getBestCmap().keys())
    best = None
    for v in sorted(idx):
        if sum(c in cmap for c in idx[v]) / len(idx[v]) >= 0.8:
            best = v
    allcps = [c for lst in idx.values() for c in lst]
    overall = round(100 * sum(c in cmap for c in allcps) / len(allcps))
    return (f"{best:.1f}" if best is not None else "?"), overall


# ---- helpers ----------------------------------------------------------------
def curl(url, dest):
    subprocess.run(["curl", "-fsSL", "--retry", "3", "-o", str(dest), url], check=True)

def run_nanoemoji(svgs, color_format, out_path, family):
    build = out_path.parent / (out_path.stem + "-nb")
    shutil.rmtree(build, ignore_errors=True); build.mkdir(parents=True)
    env = dict(os.environ)
    nb = shutil.which("nanoemoji")
    if nb:
        env["PATH"] = os.path.dirname(nb) + os.pathsep + env.get("PATH", "")
    r = subprocess.run(["nanoemoji", "--color_format", color_format, "--reuse_tolerance", "0.3",
                        "--family", family, "--output_file", "out.ttf"] + [str(s) for s in svgs],
                       cwd=str(build), env=env, capture_output=True, text=True)
    built = build / "build" / "out.ttf"
    if r.returncode == 0 and built.exists():
        shutil.copy(built, out_path)
        return True, ""
    return False, (r.stderr or "") + (r.stdout or "")

def is_glyph_overflow(msg):
    return "writeUShort" in msg or "0x10000" in msg or bool(re.search(r"6553[6-9]|655[4-9]\d|6[6-9]\d\d\d", msg))


def sbix_outline_boxes(font):
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    if "sbix" not in font or "glyf" not in font:
        return
    glyf, upm = font["glyf"], font["head"].unitsPerEm
    for st in font["sbix"].strikes.values():
        scale = upm / max(1, st.ppem)
        for gname, sg in st.glyphs.items():
            data = getattr(sg, "imageData", None)
            if not data or getattr(sg, "graphicType", None) != "png " or data[:4] != b"\x89PNG":
                continue
            bw, bh = struct.unpack(">II", data[16:24])
            ox, oy = int(sg.originOffsetX or 0) * scale, int(sg.originOffsetY or 0) * scale
            x0, y0, x1, y1 = round(ox), round(oy), round(ox + bw * scale), round(oy + bh * scale)
            pen = TTGlyphPen(None)
            pen.moveTo((x0, y0)); pen.lineTo((x0, y1)); pen.lineTo((x1, y1)); pen.lineTo((x1, y0)); pen.closePath()
            glyf[gname] = pen.glyph()

def cbdt_to_sbix(src, out):
    from fontTools.ttLib import TTFont, newTable
    from fontTools.ttLib.tables._g_l_y_f import Glyph as GlyfGlyph
    from fontTools.ttLib.tables.sbixStrike import Strike
    from fontTools.ttLib.tables.sbixGlyph import Glyph as SbixGlyph

    f = TTFont(str(src), lazy=True)
    ppem = f["CBLC"].strikes[0].bitmapSizeTable.ppemX
    bitmaps = {}
    for sd in f["CBDT"].strikeData:
        for gname, gd in sd.items():
            png = getattr(gd, "imageData", None)
            if png:
                bitmaps[gname] = (png, int(getattr(gd.metrics, "BearingX", 0)), 0)
    order = f.getGlyphOrder()
    glyf = newTable("glyf"); glyf.glyphOrder = order; glyf.glyphs = {}
    for gname in order:
        g = GlyfGlyph(); g.numberOfContours = 0; glyf.glyphs[gname] = g
    f["glyf"] = glyf
    if "loca" not in f:
        f["loca"] = newTable("loca")
    f["maxp"].tableVersion = 0x00010000
    sbix = newTable("sbix"); sbix.version = 1; sbix.flags = 1; sbix.numStrikes = 1; sbix.strikes = {}
    strike = Strike(ppem=ppem, resolution=72)
    for gname in order:
        if gname in bitmaps:
            png, ox, oy = bitmaps[gname]
            strike.glyphs[gname] = SbixGlyph(glyphName=gname, graphicType="png ", imageData=png,
                                             originOffsetX=ox, originOffsetY=oy)
        else:
            strike.glyphs[gname] = SbixGlyph(glyphName=gname)
    sbix.strikes[ppem] = strike
    f["sbix"] = sbix
    for tag in ("CBDT", "CBLC", "COLR", "CPAL", "SVG "):
        if tag in f:
            del f[tag]
    sbix_outline_boxes(f)
    f.save(str(out)); f.close()


def _cps_from_name(stem, naming):
    if naming == "noto":
        if not stem.startswith("emoji_u"):
            return None
        parts = stem[len("emoji_u"):].split("_")
    elif naming in ("twemoji", "openmoji"):
        parts = stem.lower().split("-")
    else:
        return None
    try:
        return [int(p, 16) for p in parts]
    except ValueError:
        return None

def stage_svgs(fontkey, svg, upstream):
    src = WORK / f"{fontkey}-src"
    if not (src / svg["dir"]).exists():
        shutil.rmtree(src, ignore_errors=True)
        subprocess.run(["git", "clone", "--depth", "1", "--filter=blob:none", "--sparse",
                        "-b", svg.get("branch", "main"), upstream, str(src)], check=True)
        subprocess.run(["git", "-C", str(src), "sparse-checkout", "set", svg["dir"]], check=True)
    stage = WORK / f"{fontkey}-stage"
    shutil.rmtree(stage, ignore_errors=True); stage.mkdir(parents=True)
    n = skipped = 0
    for p in (src / svg["dir"]).glob("*.svg"):
        cps = _cps_from_name(p.stem, svg["naming"])
        if not cps:
            continue
        if b"<text" in p.read_bytes():        # picosvg/nanoemoji can't convert <text>
            skipped += 1
            continue
        shutil.copy(p, stage / ("emoji_u" + "_".join(f"{c:x}" for c in cps) + ".svg"))
        n += 1
    print(f"    staged {n} SVGs" + (f" (skipped {skipped} with <text>)" if skipped else ""))
    return stage

def _drop_skin_tones(stage, multi_person_only):
    removed = 0
    for p in list(stage.glob("emoji_u*.svg")):
        cps = [int(x, 16) for x in p.stem[len("emoji_u"):].split("_")]
        toned = any(c in SKIN_TONES for c in cps)
        multi = sum(1 for c in cps if 0x1F000 <= c <= 0x1FAFF and c not in SKIN_TONES) >= 2
        if toned and (multi or not multi_person_only):
            p.unlink(); removed += 1
    return removed


# ---- per-font build ---------------------------------------------------------
def build_colrv0(fontkey, svg, upstream, label):
    out = DIST / f"{fontkey}-colrv0.ttf"
    stage = stage_svgs(fontkey, svg, upstream)
    for attempt, note in enumerate(("full", "drop multi-person skin tones", "drop all skin tones")):
        if attempt == 1:
            print(f"    COLRv0 over cap → dropped {_drop_skin_tones(stage, True)} multi-person skin-tone variants")
        elif attempt == 2:
            print(f"    still over → dropped {_drop_skin_tones(stage, False)} more skin-tone variants")
        ok, msg = run_nanoemoji(sorted(stage.glob("emoji_u*.svg")), "glyf_colr_0", out, label)
        if ok:
            print(f"    colrv0 → {out.name} ({out.stat().st_size // 1024} KB) [{note}]")
            return
        if not is_glyph_overflow(msg):
            raise RuntimeError(f"{fontkey} colrv0 failed:\n{msg[-500:]}")
    raise RuntimeError(f"{fontkey} colrv0 still over the glyph cap after dropping skin tones")

def build_font(fontkey, fspec, upstream):
    DIST.mkdir(parents=True, exist_ok=True)
    out = DIST / f"{fontkey}.ttf"
    if "download" in fspec:                          # take a ready font (mono, sbix)
        curl(fspec["download"], out)
        if fspec.get("box_glyf"):                    # add box outlines so Chrome (Skia) renders it
            from fontTools.ttLib import TTFont
            try:
                f = TTFont(str(out)); sbix_outline_boxes(f); f.save(str(out)); f.close()
            except Exception as e:
                print(f"::warning::{fontkey} box-glyf skipped: {e}")
        print(f"  {fontkey}: downloaded → {out.name} ({out.stat().st_size // 1024} KB)")
        if "colrv0_download" in fspec:               # upstream ships a ready COLRv0 too
            cout = DIST / f"{fontkey}-colrv0.ttf"; curl(fspec["colrv0_download"], cout)
            print(f"  {fontkey}: colrv0 downloaded → {cout.name} ({cout.stat().st_size // 1024} KB)")
        return
    if "cbdt" in fspec:                              # CBDT bitmaps → sbix
        WORK.mkdir(parents=True, exist_ok=True)
        cbdt = WORK / f"{fontkey}-cbdt.ttf"; curl(fspec["cbdt"], cbdt)
        cbdt_to_sbix(cbdt, out)
    elif "svg" in fspec:                             # SVGs → sbix (via nanoemoji)
        stage = stage_svgs(fontkey, fspec["svg"], upstream)
        ok, msg = run_nanoemoji(sorted(stage.glob("emoji_u*.svg")), "sbix", out, fspec["label"])
        if not ok:
            raise RuntimeError(f"{fontkey} sbix failed:\n{msg[-500:]}")
    else:
        raise RuntimeError(f"{fontkey}: no build source")
    print(f"  {fontkey}: sbix → {out.name} ({out.stat().st_size // 1024} KB)")
    if "svg" in fspec:                               # vector COLRv0 additionally (best-effort)
        try:
            build_colrv0(fontkey, fspec["svg"], upstream, fspec["label"])
        except Exception as e:
            print(f"::warning::{fontkey} COLRv0 skipped (sbix still shipped): {e}")


def build_action(action):
    spec = ACTIONS[action]
    idx = emoji_version_index()
    print(f"::group::action {action} ({spec['upstream']})")
    fonts_info = {}
    for fk, fspec in spec["fonts"].items():
        build_font(fk, fspec, spec["upstream"])
        ver, cov = detect_emoji_version(DIST / f"{fk}.ttf", idx)
        fonts_info[fk] = {"emoji_version": ver, "coverage_pct": cov,
                          "updated": datetime.date.today().isoformat()}
        print(f"  {fk}: Emoji {ver} ({cov}% coverage)")
    record_version(action, {"ref": upstream_ref(action), "fonts": fonts_info})
    print("::endgroup::")


def render_versions_md():
    out = [
        "# Emoji versions",
        "",
        "The highest Unicode **Emoji version** each built font covers — it contains at",
        "least 80% of that version's newly-added (single-codepoint) emoji — with overall",
        "coverage of all standard emoji. Regenerated automatically on each build.",
        "",
        "| Font | Name | Emoji version | Coverage | Updated |",
        "|------|------|--------------:|---------:|---------|",
    ]
    for action, spec in ACTIONS.items():
        p = VERSIONS_DIR / f"{action}.json"
        info = json.loads(p.read_text()).get("fonts", {}) if p.exists() else {}
        for fk, fspec in spec["fonts"].items():
            d = info.get(fk, {})
            out.append(f"| `{fk}` | {fspec['label']} | Emoji {d.get('emoji_version', '?')} | "
                       f"{d.get('coverage_pct', '?')}% | {d.get('updated', '')} |")
    (ROOT / "VERSIONS.md").write_text("\n".join(out) + "\n")


def main(argv):
    if not argv:
        print(__doc__); return 2
    if argv[0] == "changed":
        print("\n".join(changed_actions(argv[1:] or None)))
    elif argv[0] == "render-versions":
        render_versions_md()
    elif argv[0] in ("build", "build-all"):
        actions = list(ACTIONS) if argv[0] == "build-all" else argv[1:]
        ok, failed = [], []
        for a in actions:
            try:
                build_action(a); ok.append(a)
            except Exception as e:
                print(f"::error::{a} failed: {e}")
                failed.append(a)
        render_versions_md()
        print("built:", " ".join(ok) or "(none)", "| failed:", " ".join(failed) or "(none)")
        return 1 if failed and not ok else 0
    else:
        print(__doc__); return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
