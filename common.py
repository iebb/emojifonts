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

This module is the shared library. Each font has its own one-line generation
script `build_<font>.py` that calls `cli(<action>, …)` and reuses everything here.

  python build_noto.py build        # generate one font's variants
  python build_noto.py changed      # print the action if its upstream changed
  python common.py build-all        # generate every font (local convenience)
  python common.py render-docs      # regenerate VERSIONS.md + manifest.json
"""
import datetime
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
WORK = ROOT / "work"
DATA = ROOT / "data"
VERSIONS_DIR = ROOT / "versions"
ACTIONS = json.loads((ROOT / "sources.json").read_text())
SKIN_TONES = {0x1F3FB, 0x1F3FC, 0x1F3FD, 0x1F3FE, 0x1F3FF}
# emoji-test.txt is cumulative (all E-tags). Try the in-development draft first so we
# pick up the newest versions (E17, E18, …); fall back to latest stable, then a floor.
EMOJI_TEST_URLS = [
    "https://www.unicode.org/Public/draft/emoji/emoji-test.txt",   # next version — E18 today
    "https://unicode.org/Public/emoji/latest/emoji-test.txt",      # latest stable — E17 today
    "https://unicode.org/Public/emoji/16.0/emoji-test.txt",        # pinned floor
]
REPO = "iebb/emojifonts"
# tag-based URL: the rolling release is a *prerelease* tagged "latest"; the
# /releases/latest/download/ form only resolves to full releases, so use the tag.
RELEASE_BASE = f"https://github.com/{REPO}/releases/download/latest"
# Wall-clock budget (seconds) for each best-effort nanoemoji pass (COLRv0 / OT-SVG).
# nanoemoji is ~20 min on GitHub's 2-core runners and can grind for an hour on an
# over-cap set — bounding it means a slow/failed vector variant never hangs the job
# (the sbix, the primary font, is built separately without nanoemoji). Env-overridable.
NANOEMOJI_BUDGET = int(os.environ.get("NANOEMOJI_BUDGET_SEC", "1800"))


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
    if not p.exists() or p.stat().st_size == 0:
        DATA.mkdir(parents=True, exist_ok=True)
        for url in EMOJI_TEST_URLS:
            subprocess.run(["curl", "-fsSL", "-o", str(p), url])
            if p.exists() and p.stat().st_size > 0:
                return p
        raise RuntimeError("could not fetch emoji-test.txt from any known source")
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

def run_nanoemoji(svgs, color_format, out_path, family, timeout=None):
    """Run a nanoemoji build, optionally bounded by `timeout` seconds. On timeout the
    whole process group (nanoemoji + its ninja/picosvg children) is killed so nothing is
    left grinding, and (False, "…timed out…") is returned for the caller to handle."""
    build = out_path.parent / (out_path.stem + "-nb")
    shutil.rmtree(build, ignore_errors=True); build.mkdir(parents=True)
    env = dict(os.environ)
    nb = _tool("nanoemoji")
    env["PATH"] = os.path.dirname(nb) + os.pathsep + env.get("PATH", "")  # find picosvg/ninja/resvg
    cmd = [nb, "--color_format", color_format, "--reuse_tolerance", "0.3",
           "--family", family, "--output_file", "out.ttf"] + [str(s) for s in svgs]
    # new session → its own process group, so a timeout can kill ninja's whole subtree.
    p = subprocess.Popen(cmd, cwd=str(build), env=env, text=True,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         start_new_session=True)
    try:
        out, _ = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        import signal
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            p.kill()
        p.communicate()
        return False, f"nanoemoji timed out after {int(timeout)}s"
    built = build / "build" / "out.ttf"
    if p.returncode == 0 and built.exists():
        shutil.copy(built, out_path)
        return True, ""
    return False, out or ""

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
            if not png:
                continue
            # Centre the bitmap on the em (offsets in px at the strike ppem) so the art sits
            # at the em-centre like Apple's — not resting on the baseline and riding high.
            # Source bitmaps are often larger than the em (Noto ≈ 1.2 em), so offsets go
            # negative; centring is exact: art-centre = (off + bh/2)·scale = ppem/2·scale = UPM/2.
            if png[:4] == b"\x89PNG":
                bw, bh = struct.unpack(">II", png[16:24])
                bitmaps[gname] = (png, round((ppem - bw) / 2), round((ppem - bh) / 2))
            else:
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


# ---- shared SVG-set primitives (used by the svg_color builder) --------------
SBIX_PPEM = 128   # bitmap is SBIX_PPEM px == 1 em (strike ppem is the em size)

def _tool(name):
    # pip console scripts (nanoemoji, resvg, picosvg, ninja) install next to the
    # running Python — check there first so a non-activated venv still resolves them.
    cand = os.path.join(os.path.dirname(sys.executable), name)
    if os.path.exists(cand):
        return cand
    return shutil.which(name) or name

def rasterize_svgs(stage, ppem):
    """resvg each emoji_u*.svg → a ppem×ppem PNG. Returns {stem: png-bytes}.
    resvg is ~instant per SVG, so this replaces nanoemoji's ~0.4s/SVG raster pass."""
    resvg = _tool("resvg")
    out = stage.parent / (stage.name + "-png")
    shutil.rmtree(out, ignore_errors=True); out.mkdir(parents=True)
    pngs = {}
    for svg in stage.glob("emoji_u*.svg"):
        png = out / (svg.stem + ".png")
        subprocess.run([resvg, "-w", str(ppem), "-h", str(ppem), str(svg), str(png)],
                       capture_output=True)
        if png.exists():
            pngs[svg.stem] = png.read_bytes()
    return pngs

def picosvg_prefilter(stage):
    """Drop SVGs picosvg/nanoemoji can't convert (malformed transforms, <text>, …)
    so the COLRv0 build doesn't abort on one bad file."""
    from picosvg.svg import SVG
    dropped = 0
    for p in list(stage.glob("emoji_u*.svg")):
        try:
            SVG.parse(str(p)).topicosvg()
        except Exception:
            p.unlink(); dropped += 1
    if dropped:
        print(f"    pre-filtered {dropped} SVGs picosvg can't convert")

def glyph_resolver(font):
    """cps-list → glyph name, via cmap (singles) + GSUB type-4 ligatures (sequences)."""
    cmap = font.getBestCmap()
    ligs = {}
    if "GSUB" in font:
        for lk in font["GSUB"].table.LookupList.Lookup:
            for st in getattr(lk, "SubTable", []):
                for first, ligset in getattr(st, "ligatures", {}).items():
                    for lig in ligset:
                        ligs[(first, tuple(lig.Component))] = lig.LigGlyph
    def resolve(cps):
        gs = [cmap.get(c) for c in cps]
        if any(g is None for g in gs):
            return None
        return gs[0] if len(gs) == 1 else ligs.get((gs[0], tuple(gs[1:])))
    return resolve

def normalize_metrics(font):
    """nanoemoji emits emoji at ~1.245 em (advance 1275 / UPM 1024) — oversized and
    over-spaced. Rescale art to 1 em (sbix: ×ppem; glyf/COLR: ×UPM), set every advance
    to 1 em, and flatten vertical metrics so a line with an emoji isn't inflated."""
    from collections import Counter
    hmtx, order = font["hmtx"], font.getGlyphOrder()
    upm0 = font["head"].unitsPerEm
    adv = Counter(hmtx[g][0] for g in order if hmtx[g][0] > 0).most_common(1)[0][0]
    art_em = max(0.5, min(2.0, adv / upm0))
    if "sbix" in font:
        for st in font["sbix"].strikes.values():
            st.ppem = max(1, round(st.ppem * art_em))
        upm = upm0
        sbix_outline_boxes(font)
    else:
        upm = max(16, round(upm0 * art_em))
        font["head"].unitsPerEm = upm
    for g in order:
        hmtx[g] = (upm, 0)
    font["hhea"].ascent, font["hhea"].descent, font["hhea"].lineGap = upm, 0, 0
    if "OS/2" in font:
        o = font["OS/2"]
        o.sTypoAscender, o.sTypoDescender, o.sTypoLineGap = upm, 0, 0
        o.usWinAscent, o.usWinDescent = upm, 0


def build_structure_font(stems, upm=1024, family="Emoji"):
    """Synthesize the cmap + GSUB skeleton an sbix emoji font needs — directly from the
    staged SVG filenames, with NO nanoemoji color build. Each `emoji_u<cp>[_<cp>…].svg`
    names a codepoint sequence (verbatim, the same way nanoemoji reads them): singles get
    a cmap entry, multis a `ccmp` ligature whose components are the single-cp glyphs.
    Reuses nanoemoji's own glyph_name + generate_fea, so the cmap/GSUB are identical to
    what its COLRv0 build would emit — but in milliseconds instead of ~20 min. Returns a
    TTFont with empty glyf outlines; the caller packs the sbix bitmaps over it."""
    from io import StringIO
    from fontTools.fontBuilder import FontBuilder
    from fontTools.feaLib.builder import addOpenTypeFeatures
    from fontTools.ttLib.tables._g_l_y_f import Glyph as GlyfGlyph
    from nanoemoji import features
    from nanoemoji.glyph import glyph_name

    seqs = [tuple(int(x, 16) for x in s[len("emoji_u"):].split("_")) for s in stems]
    comp_cps = sorted({c for seq in seqs for c in seq} | {0x20})   # nanoemoji always maps space
    single = {cp: glyph_name([cp]) for cp in comp_cps}
    multi = {seq: glyph_name(seq) for seq in seqs if len(seq) > 1}
    order, seen = [".notdef"], {".notdef"}
    for name in [single[cp] for cp in comp_cps] + [multi[s] for s in sorted(multi)]:
        if name not in seen:                       # guard the rare hashed-name collision
            order.append(name); seen.add(name)

    fb = FontBuilder(unitsPerEm=upm, isTTF=True)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap({cp: single[cp] for cp in comp_cps})
    empty = {}
    for n in order:
        g = GlyfGlyph(); g.numberOfContours = 0; empty[n] = g
    fb.setupGlyf(empty)
    fb.setupHorizontalMetrics({n: (upm, 0) for n in order})   # 1-em advance like Apple
    fb.setupHorizontalHeader(ascent=upm, descent=0)
    fb.setupNameTable({"familyName": family, "styleName": "Regular"})
    fb.setupOS2(sTypoAscender=upm, sTypoDescender=0, sTypoLineGap=0,
                usWinAscent=upm, usWinDescent=0)
    fb.setupPost()
    addOpenTypeFeatures(fb.font, StringIO(features.generate_fea(seqs)))   # ccmp ligatures
    return fb.font


def assemble_sbix(struct_font, pngs, out):
    """Pack `pngs` ({stem: PNG bytes}) into one sbix strike over `struct_font` (a cmap+GSUB
    skeleton), resolving each emoji's codepoints to its glyph via the cmap/GSUB. Full-cell
    box outlines so Chrome (Skia) renders the bitmaps. Saves to `out`; returns count placed."""
    from fontTools.ttLib import newTable
    from fontTools.ttLib.tables.sbixStrike import Strike
    from fontTools.ttLib.tables.sbixGlyph import Glyph as SbixGlyph

    f = struct_font
    upm = f["head"].unitsPerEm
    resolve = glyph_resolver(f)
    by_glyph = {}
    for stem, data in pngs.items():
        cps = [int(x, 16) for x in stem[len("emoji_u"):].split("_")]
        g = resolve(cps)
        if g:
            by_glyph[g] = data
    sbix = newTable("sbix"); sbix.version = 1; sbix.flags = 1; sbix.numStrikes = 1; sbix.strikes = {}
    strike = Strike(ppem=SBIX_PPEM, resolution=72)
    for g in f.getGlyphOrder():
        strike.glyphs[g] = (SbixGlyph(glyphName=g, graphicType="png ", imageData=by_glyph[g],
                                      originOffsetX=0, originOffsetY=0)
                            if g in by_glyph else SbixGlyph(glyphName=g))
    sbix.strikes[SBIX_PPEM] = strike
    f["sbix"] = sbix
    hmtx = f["hmtx"]
    for g in f.getGlyphOrder():
        hmtx[g] = (upm, 0)              # uniform 1-em advance
    sbix_outline_boxes(f)              # full-cell box-glyf so Chrome (Skia) renders it
    f.save(str(out)); f.close()
    return len(by_glyph)


def nanoemoji_colrv0(stage, out, label, budget=None):
    """COLRv0 via nanoemoji; if it overflows the 65 535-glyph cap, drop the least-common
    emoji (multi-person skin-tone sequences first, then all skin tones) until it fits.
    Bounded by `budget` seconds total: a set whose COLRv0 is slow or simply can't fit the
    cap (e.g. EmojiTwo's dense art) gives up instead of burning ~20 min per retry — the
    sbix is already built separately, so dropping the COLRv0 variant doesn't block release."""
    deadline = (time.monotonic() + budget) if budget else None
    for attempt in range(3):
        if attempt == 1:
            print(f"    COLRv0 over cap → dropped {_drop_skin_tones(stage, True)} multi-person skin-tone variants")
        elif attempt == 2:
            print(f"    still over → dropped {_drop_skin_tones(stage, False)} more skin-tone variants")
        remaining = (deadline - time.monotonic()) if deadline else None
        if remaining is not None and remaining <= 30:
            raise RuntimeError(f"colrv0 time budget ({budget}s) exhausted")
        ok, msg = run_nanoemoji(sorted(stage.glob("emoji_u*.svg")), "glyf_colr_0", out, label,
                                timeout=remaining)
        if ok:
            return
        if "timed out" in msg:
            raise RuntimeError(msg)
        if not is_glyph_overflow(msg):
            raise RuntimeError(f"colrv0 failed:\n{msg[-500:]}")
    raise RuntimeError("colrv0 still over the glyph cap after dropping skin tones")

def build_svginot(stage, out, label):
    """OT-SVG (`SVG ` table) via nanoemoji picosvg — true vector, full gradient detail,
    renders on macOS Core Text and Firefox (Chrome has no OT-SVG, so it shows nothing —
    the sbix/COLRv0 cover Chrome). Normalized to a 1-em advance like the other formats;
    the SVG docs' transforms are in font units, so scaling the UPM rescales the art."""
    from fontTools.ttLib import TTFont
    ok, msg = run_nanoemoji(sorted(stage.glob("emoji_u*.svg")), "picosvg", out, label,
                            timeout=NANOEMOJI_BUDGET)
    if not ok:
        raise RuntimeError(f"svginot failed:\n{msg[-500:]}")
    f = TTFont(str(out)); normalize_metrics(f); f.save(str(out)); f.close()

def svginot_from_colr(colr_path, out):
    """Derive an OT-SVG font from an already-built COLRv0 — no second nanoemoji pass.
    nanoemoji.colr_to_svg renders each COLR glyph to an SVG in OT-SVG coordinate space
    (it's flat art, so this is lossless); we wrap each in a glyph<gid> element and pack
    the `SVG ` table. ~6 s for 4 000 glyphs vs ~20 min for a picosvg build. The COLRv0
    is already normalized, so its 1-em metrics carry over."""
    from fontTools.ttLib import TTFont, newTable
    from nanoemoji import colr_to_svg
    from lxml import etree
    SVGNS = "{http://www.w3.org/2000/svg}"
    f = TTFont(str(colr_path))
    gid = {n: i for i, n in enumerate(f.getGlyphOrder())}
    svgs = colr_to_svg.colr_to_svg(lambda gn: colr_to_svg.glyph_region(f, gn), f)
    docs = []
    for gname, svg in svgs.items():
        i = gid[gname]
        root = svg.svg_root
        g = etree.Element(SVGNS + "g"); g.set("id", f"glyph{i}")
        for child in list(root):
            g.append(child)
        root.append(g)
        docs.append((etree.tostring(root).decode("utf-8"), i, i))
    docs.sort(key=lambda d: d[1])
    for t in ("COLR", "CPAL"):
        if t in f:
            del f[t]
    tab = newTable("SVG "); tab.compressed = True; tab.docList = docs
    f["SVG "] = tab
    f.save(str(out)); f.close()

def svginot_from_svgs(fontkey, svg, upstream, label):
    """Stage a set's SVGs (picosvg-clean) and build its OT-SVG → <fontkey>-svginot.ttf."""
    stage = WORK / f"{fontkey}-svg"
    shutil.rmtree(stage, ignore_errors=True)
    shutil.copytree(stage_svgs(fontkey, svg, upstream), stage)
    picosvg_prefilter(stage)
    out = DIST / f"{fontkey}-svginot.ttf"
    build_svginot(stage, out, label)
    print(f"  {fontkey}: svginot → {out.name} ({out.stat().st_size // 1024} KB)")


# ---- per-font builders ------------------------------------------------------
def build_cbdt_sbix(fontkey, fspec, upstream):
    """CBDT bitmap fonts → sbix (Noto, Blobmoji, Fluent variants). If the set also has
    vector SVGs (Noto, Blobmoji), additionally build a true-vector OT-SVG."""
    WORK.mkdir(parents=True, exist_ok=True)
    out = DIST / f"{fontkey}.ttf"
    cbdt = WORK / f"{fontkey}-cbdt.ttf"; curl(fspec["cbdt"], cbdt)
    cbdt_to_sbix(cbdt, out)
    print(f"  {fontkey}: sbix → {out.name} ({out.stat().st_size // 1024} KB)")
    if "svg" in fspec:
        try:
            svginot_from_svgs(fontkey, fspec["svg"], upstream, fspec["label"])
        except Exception as e:
            print(f"::warning::{fontkey} svginot skipped: {e}")

def build_download(fontkey, fspec, upstream):
    """Ready-made fonts taken as-is (Toss Face sbix, mono Noto glyf, OpenMoji prebuilt).
    Optionally add Chrome box-glyf and fetch a prebuilt COLRv0 alongside."""
    from fontTools.ttLib import TTFont
    out = DIST / f"{fontkey}.ttf"
    curl(fspec["download"], out)
    if fspec.get("box_glyf"):
        try:
            f = TTFont(str(out)); sbix_outline_boxes(f); f.save(str(out)); f.close()
        except Exception as e:
            print(f"::warning::{fontkey} box-glyf skipped: {e}")
    print(f"  {fontkey}: downloaded → {out.name} ({out.stat().st_size // 1024} KB)")
    if "colrv0_download" in fspec:
        cout = DIST / f"{fontkey}-colrv0.ttf"; curl(fspec["colrv0_download"], cout)
        print(f"  {fontkey}: colrv0 downloaded → {cout.name} ({cout.stat().st_size // 1024} KB)")
    if "svginot_download" in fspec:
        sout = DIST / f"{fontkey}-svginot.ttf"; curl(fspec["svginot_download"], sout)
        print(f"  {fontkey}: svginot downloaded → {sout.name} ({sout.stat().st_size // 1024} KB)")

def build_otsvg(fontkey, fspec, upstream):
    """Keep a source webfont's vector OT-SVG (`SVG ` table — macOS Core Text renders it)
    and drop the bitmap/COLRv1 tables macOS can't use. For the flat-style Fluent variants
    this is a few MB of vector instead of ~20 MB of CBDT bitmaps (a bitmap font's size is
    driven by resolution × glyph count, not color count, so a monochrome set gains nothing
    from being bitmap). The 3D color Fluent stays cbdt_sbix — its detailed OT-SVG is
    actually larger than its bitmaps. Metrics are left as-is; the swapper normalizes to
    Apple's geometry at install time, same as the other sets."""
    from fontTools.ttLib import TTFont
    WORK.mkdir(parents=True, exist_ok=True)
    src = WORK / f"{fontkey}-webfont.ttf"; curl(fspec["webfont"], src)
    f = TTFont(str(src))
    if "SVG " not in f:
        raise RuntimeError(f"{fontkey}: source webfont has no OT-SVG table")
    for tag in ("CBDT", "CBLC", "COLR", "CPAL"):   # the tables macOS can't render / we don't need
        if tag in f:
            del f[tag]
    out = DIST / f"{fontkey}.ttf"
    f.save(str(out)); f.close()
    print(f"  {fontkey}: otsvg → {out.name} ({out.stat().st_size // 1024} KB)")

def stage_mono_svgs(fontkey, upstream):
    """Clone microsoft/fluentui-emoji (sparse: metadata.json + High-Contrast SVGs) and stage
    each emoji's HC SVG named by its codepoint(s) from metadata.json. Skin-tone-capable emoji
    keep their HC under a 'Default/' subdir, so check both layouts."""
    src = WORK / f"{fontkey}-src"
    if not (src / "assets").exists():
        shutil.rmtree(src, ignore_errors=True)
        subprocess.run(["git", "clone", "--depth", "1", "--filter=blob:none", "--no-checkout",
                        upstream, str(src)], check=True)
        subprocess.run(["git", "-C", str(src), "sparse-checkout", "init", "--no-cone"], check=True)
        subprocess.run(["git", "-C", str(src), "sparse-checkout", "set",
                        "/assets/**/metadata.json", "/assets/**/High Contrast/*.svg"], check=True)
        subprocess.run(["git", "-C", str(src), "checkout"], check=True)
    stage = WORK / f"{fontkey}-stage"
    shutil.rmtree(stage, ignore_errors=True); stage.mkdir(parents=True)
    n = 0
    for md in (src / "assets").glob("*/metadata.json"):
        try:
            u = json.loads(md.read_text()).get("unicode", "").strip()
        except Exception:
            u = ""
        if not u:
            continue
        hc = (list((md.parent / "High Contrast").glob("*.svg"))                 # non-skin emoji
              or list((md.parent / "Default" / "High Contrast").glob("*.svg")))  # skin-capable → Default/
        if not hc:
            continue
        cps = u.split()
        shutil.copy(hc[0], stage / ("emoji_u" + "_".join(cps) + ".svg")); n += 1
        # also stage the unqualified (no-FE0F) form so the bare codepoint renders too —
        # MS maps e.g. the heart as "2764 fe0f", which would leave plain ❤ (U+2764) blank.
        unq = [c for c in cps if c.lower() != "fe0f"]
        if unq and unq != cps:
            shutil.copy(hc[0], stage / ("emoji_u" + "_".join(unq) + ".svg"))
    print(f"    staged {n} High-Contrast SVGs (+ unqualified variants)")
    return stage

def build_svg_mono(fontkey, fspec, upstream):
    """Single-color sets (Fluent High Contrast): a true monochrome glyf OUTLINE font that
    renders in the text colour (so it adapts to light/dark) — not a colour emoji table, so it
    needs no bitmaps/gradients and is ~600 KB. Built from per-emoji SVGs via nanoemoji's mono
    `glyf` format (picosvg handles fills/winding correctly), time-bounded like the other svg
    sets so it can't hang the job."""
    from fontTools.ttLib import TTFont
    stage = stage_mono_svgs(fontkey, upstream)
    picosvg_prefilter(stage)
    out = DIST / f"{fontkey}.ttf"
    ok, msg = run_nanoemoji(sorted(stage.glob("emoji_u*.svg")), "glyf", out, fspec["label"],
                            timeout=NANOEMOJI_BUDGET)
    if not ok:
        raise RuntimeError(f"{fontkey} mono glyf failed:\n{msg[-500:]}")
    f = TTFont(str(out)); normalize_metrics(f); f.save(str(out)); f.close()
    print(f"  {fontkey}: mono glyf → {out.name} ({out.stat().st_size // 1024} KB)")

def build_svg_color(fontkey, fspec, upstream):
    """Flat SVG sets (Twemoji, EmojiTwo).

    The sbix (`<font>.ttf`, the primary font the swapper installs) is built WITHOUT
    nanoemoji: resvg rasterizes each SVG (≈instant) and the cmap+GSUB are synthesized from
    the filenames (build_structure_font) — a few seconds, full coverage, never gated on a
    slow tool. The vector COLRv0 + OT-SVG derived from it are then a best-effort, time-
    bounded extra: nanoemoji is ~20 min on CI's 2-core runners and can't fit the glyph cap
    for dense sets (EmojiTwo), so it runs under NANOEMOJI_BUDGET and a slow/failed COLRv0
    is skipped with a warning rather than blocking or hanging the job."""
    from fontTools.ttLib import TTFont

    svg, label = fspec["svg"], fspec["label"]
    stage = stage_svgs(fontkey, svg, upstream)
    pngs = rasterize_svgs(stage, SBIX_PPEM)
    print(f"  {fontkey}: rasterized {len(pngs)} SVGs @ {SBIX_PPEM}px (resvg)")

    # PRIMARY: sbix from a synthesized cmap+GSUB skeleton + the resvg PNGs (no nanoemoji).
    out = DIST / f"{fontkey}.ttf"
    stems = [p.stem for p in stage.glob("emoji_u*.svg")]
    placed = assemble_sbix(build_structure_font(stems, family=label), pngs, out)
    print(f"  {fontkey}: sbix → {out.name} ({out.stat().st_size // 1024} KB, {placed} emoji)")

    # OPTIONAL (best-effort, time-bounded): COLRv0 vector + OT-SVG derived from it. Never
    # required for the sbix above, so a slow or over-cap COLRv0 just drops these variants.
    cstage = WORK / f"{fontkey}-colr"
    shutil.rmtree(cstage, ignore_errors=True); shutil.copytree(stage, cstage)
    picosvg_prefilter(cstage)
    colr_out = DIST / f"{fontkey}-colrv0.ttf"
    try:
        nanoemoji_colrv0(cstage, colr_out, label, budget=NANOEMOJI_BUDGET)
        cf = TTFont(str(colr_out)); normalize_metrics(cf); cf.save(str(colr_out)); cf.close()
        print(f"  {fontkey}: colrv0 → {colr_out.name} ({colr_out.stat().st_size // 1024} KB)")
        try:
            sout = DIST / f"{fontkey}-svginot.ttf"
            svginot_from_colr(colr_out, sout)        # ~6 s, lossless for flat art
            print(f"  {fontkey}: svginot → {sout.name} ({sout.stat().st_size // 1024} KB)")
        except Exception as e:
            print(f"::warning::{fontkey} svginot skipped: {e}")
    except Exception as e:
        print(f"::warning::{fontkey} colrv0 skipped (sbix already built): {e}")


BUILDERS = {
    "cbdt_sbix": build_cbdt_sbix,
    "download": build_download,
    "svg_color": build_svg_color,
    "otsvg": build_otsvg,
    "svg_mono": build_svg_mono,
}

def build_font(fontkey, fspec, upstream):
    DIST.mkdir(parents=True, exist_ok=True)
    builder = BUILDERS.get(fspec.get("builder"))
    if not builder:
        raise RuntimeError(f"{fontkey}: unknown builder {fspec.get('builder')!r}")
    builder(fontkey, fspec, upstream)


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


def _release_assets():
    """Files actually present in the `latest` release (CI) or local dist/ — so the
    manifest reflects what really shipped, incl. best-effort COLRv0 that may be absent."""
    try:
        r = subprocess.run(["gh", "release", "view", "latest", "--json", "assets",
                            "--jq", ".assets[].name"], capture_output=True, text=True, cwd=str(ROOT))
        if r.returncode == 0 and r.stdout.strip():
            return set(r.stdout.split())
    except Exception:
        pass
    return {p.name for p in DIST.glob("*.ttf")} if DIST.exists() else set()

def render_manifest():
    assets = _release_assets()
    fonts = []
    for action, spec in ACTIONS.items():
        p = VERSIONS_DIR / f"{action}.json"
        info = json.loads(p.read_text()).get("fonts", {}) if p.exists() else {}
        for fk, fspec in spec["fonts"].items():
            d = info.get(fk, {})
            primary = {"mono": "glyf", "svg": "svginot"}.get(fspec.get("kind"), "sbix")
            formats = {}
            if f"{fk}.ttf" in assets or not assets:
                formats[primary] = f"{RELEASE_BASE}/{fk}.ttf"
            if f"{fk}-colrv0.ttf" in assets:
                formats["colrv0"] = f"{RELEASE_BASE}/{fk}-colrv0.ttf"
            if f"{fk}-svginot.ttf" in assets:
                formats["svginot"] = f"{RELEASE_BASE}/{fk}-svginot.ttf"
            if f"{fk}.ttc" in assets:   # macOS system drop-in (Apple Color Emoji.ttc)
                formats["ttc"] = f"{RELEASE_BASE}/{fk}.ttc"
            fonts.append({
                "key": fk, "label": fspec["label"], "license": fspec.get("license"),
                "kind": fspec.get("kind", "color"), "action": action, "upstream": spec["upstream"],
                "emoji_version": d.get("emoji_version"), "coverage_pct": d.get("coverage_pct"),
                "updated": d.get("updated"), "formats": formats,
            })
    manifest = {"generated": datetime.date.today().isoformat(), "repo": REPO,
                "release": f"https://github.com/{REPO}/releases/latest", "fonts": fonts}
    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

def render_docs():
    render_versions_md()
    render_manifest()


def cli(action, argv):
    """Entry point for a per-font `build_<font>.py` script.

      changed → print the action name iff its upstream changed (empty otherwise),
                so CI can skip an unchanged font with `[ -z "$(… changed)" ]`.
      build   → build the action's font(s) and refresh VERSIONS.md + manifest.json.
    """
    cmd = argv[0] if argv else "build"
    if cmd == "changed":
        if upstream_ref(action) != stored_ref(action):
            print(action)
        return 0
    if cmd == "build":
        try:
            build_action(action)
        except Exception as e:
            print(f"::error::{action} failed: {e}")
            return 1
        render_docs()
        return 0
    print(f"usage: build_{action.replace('-', '_')}.py [changed|build]")
    return 2


def main(argv):
    if not argv:
        print(__doc__); return 2
    if argv[0] == "changed":
        print("\n".join(changed_actions(argv[1:] or None)))
    elif argv[0] in ("render-versions", "render-docs"):
        render_docs()
    elif argv[0] in ("build", "build-all"):
        actions = list(ACTIONS) if argv[0] == "build-all" else argv[1:]
        ok, failed = [], []
        for a in actions:
            try:
                build_action(a); ok.append(a)
            except Exception as e:
                print(f"::error::{a} failed: {e}")
                failed.append(a)
        render_docs()
        print("built:", " ".join(ok) or "(none)", "| failed:", " ".join(failed) or "(none)")
        return 1 if failed and not ok else 0
    else:
        print(__doc__); return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
