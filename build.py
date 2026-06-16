#!/usr/bin/env python3
"""Build macOS-renderable color emoji fonts from upstream sources.

macOS Core Text renders sbix, COLRv0 and OT-SVG — not COLRv1 or CBDT.

Every set is built as **sbix** (bitmap; works everywhere incl. Chrome, full
coverage). Vector-capable sets (those with SVG sources) ALSO get a **COLRv0**
build (crisp at any size) as `<set>-colrv0.ttf`. COLRv0 stores one glyph per
color region, so detailed sets can exceed TrueType's 65 535-glyph cap; when that
happens the build drops the least-common emoji (skin-tone variants, esp.
multi-person sequences) until it fits.

Outputs (dist/):
  <set>.ttf          sbix  (always)
  <set>-colrv0.ttf   COLRv0 (vector sets)

Usage:
  build.py changed             # sets whose upstream changed (vs versions.json)
  build.py build <set> ...     # build sets → dist/, record refs
  build.py build-all
"""
import json
import os
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
WORK = ROOT / "work"
SOURCES = json.loads((ROOT / "sources.json").read_text())
VERSIONS_DIR = ROOT / "versions"          # one file per set → independent per-set actions
SKIN_TONES = {0x1F3FB, 0x1F3FC, 0x1F3FD, 0x1F3FE, 0x1F3FF}


# ---- per-set change detection -----------------------------------------------
def upstream_ref(spec):
    r = subprocess.run(["git", "ls-remote", spec["upstream"], "HEAD"], capture_output=True, text=True)
    toks = r.stdout.split()
    return toks[0] if toks else "?"

def stored_ref(name):
    p = VERSIONS_DIR / f"{name}.txt"
    return p.read_text().strip() if p.exists() else None

def record_ref(name, ref):
    VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
    (VERSIONS_DIR / f"{name}.txt").write_text(ref + "\n")

def changed_sets(names=None):
    names = names or list(SOURCES)
    return [n for n in names if upstream_ref(SOURCES[n]) != stored_ref(n)]


# ---- helpers ----------------------------------------------------------------
def curl(url, dest):
    subprocess.run(["curl", "-fsSL", "--retry", "3", "-o", str(dest), url], check=True)

def nanoemoji_bin():
    return shutil.which("nanoemoji")

def run_nanoemoji(svgs, color_format, out_path, family):
    """Returns (ok, message). Adds nanoemoji's dir to PATH so picosvg resolves."""
    build = out_path.parent / (out_path.stem + "-nb")
    shutil.rmtree(build, ignore_errors=True); build.mkdir(parents=True)
    env = dict(os.environ)
    nb = nanoemoji_bin()
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
    return "writeUShort" in msg or "0x10000" in msg or re.search(r"6553[6-9]|655[4-9]\d|6[6-9]\d\d\d", msg)


# ---- sbix transcode from CBDT ----------------------------------------------
def sbix_outline_boxes(font):
    """Box glyf outline per sbix bitmap so Chrome/Skia renders (and doesn't clip) it."""
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


# ---- SVG staging (→ nanoemoji's emoji_u<cp>[_<cp>].svg naming) --------------
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

def stage_svgs(name, spec):
    """Clone a set's SVGs and stage them as emoji_u<cp>.svg. Returns the dir."""
    svg = spec["svg"]
    src = WORK / f"{name}-src"
    if not (src / svg["dir"]).exists():
        shutil.rmtree(src, ignore_errors=True)
        subprocess.run(["git", "clone", "--depth", "1", "--filter=blob:none", "--sparse",
                        "-b", svg.get("branch", "main"), spec["upstream"], str(src)], check=True)
        subprocess.run(["git", "-C", str(src), "sparse-checkout", "set", svg["dir"]], check=True)
    stage = WORK / f"{name}-stage"
    shutil.rmtree(stage, ignore_errors=True); stage.mkdir(parents=True)
    n = 0
    for p in (src / svg["dir"]).glob("*.svg"):
        cps = _cps_from_name(p.stem, svg["naming"])
        if not cps:
            continue
        shutil.copy(p, stage / ("emoji_u" + "_".join(f"{c:x}" for c in cps) + ".svg"))
        n += 1
    print(f"  staged {n} SVGs")
    return stage


def _drop_skin_tones(stage, multi_person_only):
    """Remove staged SVGs that carry skin-tone modifiers (the least-common variants)."""
    removed = 0
    for p in list(stage.glob("emoji_u*.svg")):
        cps = [int(x, 16) for x in p.stem[len("emoji_u"):].split("_")]
        toned = any(c in SKIN_TONES for c in cps)
        multi = sum(1 for c in cps if 0x1F000 <= c <= 0x1FAFF and c not in SKIN_TONES) >= 2
        if toned and (multi or not multi_person_only):
            p.unlink(); removed += 1
    return removed


# ---- per-set build ----------------------------------------------------------
def build_sbix(name, spec):
    DIST.mkdir(parents=True, exist_ok=True)
    out = DIST / f"{name}.ttf"
    if "cbdt" in spec:
        WORK.mkdir(parents=True, exist_ok=True)
        cbdt = WORK / f"{name}-cbdt.ttf"; curl(spec["cbdt"], cbdt)
        cbdt_to_sbix(cbdt, out)
    elif "sbix" in spec:
        curl(spec["sbix"], out)
    elif "svg" in spec:
        stage = stage_svgs(name, spec)
        ok, msg = run_nanoemoji(sorted(stage.glob("emoji_u*.svg")), "sbix", out, spec["label"])
        if not ok:
            raise RuntimeError(f"{name} sbix build failed:\n{msg[-600:]}")
    else:
        raise RuntimeError(f"{name}: no sbix source")
    print(f"  sbix → {out} ({out.stat().st_size // 1024} KB)")

def build_colrv0(name, spec):
    out = DIST / f"{name}-colrv0.ttf"
    if "svg" not in spec:
        if "colrv0" in spec:                     # use upstream's COLRv0 directly
            DIST.mkdir(parents=True, exist_ok=True)
            curl(spec["colrv0"], out)
            print(f"  colrv0 (upstream) → {out} ({out.stat().st_size // 1024} KB)")
        return
    stage = stage_svgs(name, spec)
    for attempt, label in enumerate(("full", "drop multi-person skin tones", "drop all skin tones")):
        if attempt == 1:
            r = _drop_skin_tones(stage, multi_person_only=True)
            print(f"  COLRv0 over 65k cap → dropped {r} multi-person skin-tone variants, retrying")
        elif attempt == 2:
            r = _drop_skin_tones(stage, multi_person_only=False)
            print(f"  still over → dropped {r} more skin-tone variants, retrying")
        ok, msg = run_nanoemoji(sorted(stage.glob("emoji_u*.svg")), "glyf_colr_0", out, spec["label"])
        if ok:
            print(f"  colrv0 → {out} ({out.stat().st_size // 1024} KB) [{label}]")
            return
        if not is_glyph_overflow(msg):
            raise RuntimeError(f"{name} colrv0 build failed:\n{msg[-600:]}")
    raise SystemExit(f"{name} colrv0 still exceeds the glyph cap after dropping skin tones")

def build(name):
    spec = SOURCES[name]
    print(f"::group::build {name}")
    build_sbix(name, spec)
    if "svg" in spec or "colrv0" in spec:
        build_colrv0(name, spec)
    print("::endgroup::")


def main(argv):
    if not argv:
        print(__doc__); return 2
    if argv[0] == "changed":
        print("\n".join(changed_sets(argv[1:] or None)))   # optional: changed <set>
    elif argv[0] in ("build", "build-all"):
        sets = list(SOURCES) if argv[0] == "build-all" else argv[1:]
        ok, failed = [], []
        for s in sets:
            try:
                build(s)
                record_ref(s, upstream_ref(SOURCES[s]))   # record only on success
                ok.append(s)
            except Exception as e:                        # one bad set must not abort the rest
                print(f"::error::{s} build failed: {e}")
                failed.append(s)
        print("built:", " ".join(ok) or "(none)", "| failed:", " ".join(failed) or "(none)")
        return 1 if failed and not ok else 0              # succeed if at least one built
    else:
        print(__doc__); return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
