#!/usr/bin/env python3
"""Build macOS-renderable color emoji fonts from upstream sources.

macOS Core Text renders sbix, COLRv0 and OT-SVG — not COLRv1 or CBDT. So each
set is built to the best macOS-renderable form:
  • cbdt2sbix : download the CBDT (Android-bitmap) build and transcode its PNGs
                into Apple's sbix table (Noto, Blobmoji, Fluent).
  • colrv0    : build a COLRv0 vector font from per-codepoint SVGs via nanoemoji
                (Twemoji — flat art stays under the 65 535-glyph cap).
  • download  : fetch an already macOS-renderable build as-is (OpenMoji/EmojiTwo
                COLRv0, Toss Face sbix).

Usage:
  build.py changed              # print sets whose upstream changed (vs versions.json)
  build.py build <set> ...      # build sets → dist/<set>.ttf and record their refs
  build.py build-all            # build every set
"""
import json
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
WORK = ROOT / "work"
SOURCES = json.loads((ROOT / "sources.json").read_text())
VERSIONS_FILE = ROOT / "versions.json"


# ---- upstream change detection ----------------------------------------------
def upstream_ref(spec):
    """Current upstream commit SHA (cheap, no clone) for change detection."""
    repo = spec.get("ref_repo") or spec.get("repo")
    branch = spec.get("ref_branch") or spec.get("branch") or "HEAD"
    r = subprocess.run(["git", "ls-remote", repo, branch], capture_output=True, text=True)
    toks = r.stdout.split()
    return toks[0] if toks else "?"

def load_versions():
    return json.loads(VERSIONS_FILE.read_text()) if VERSIONS_FILE.exists() else {}

def changed_sets():
    v = load_versions()
    return [name for name, spec in SOURCES.items() if upstream_ref(spec) != v.get(name)]


# ---- helpers ----------------------------------------------------------------
def curl(url, dest):
    subprocess.run(["curl", "-fsSL", "--retry", "3", "-o", str(dest), url], check=True)

def sbix_outline_boxes(font):
    """Give each sbix bitmap glyph a glyf box matching the bitmap's extent — Core
    Text draws the bitmap regardless, but Skia/HarfBuzz (Chrome) skips empty
    outlines and clips to the box, so emoji are invisible/cropped without this."""
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    if "sbix" not in font or "glyf" not in font:
        return
    glyf = font["glyf"]
    upm = font["head"].unitsPerEm
    for st in font["sbix"].strikes.values():
        scale = upm / max(1, st.ppem)
        for gname, sg in st.glyphs.items():
            data = getattr(sg, "imageData", None)
            if not data or getattr(sg, "graphicType", None) != "png " or data[:4] != b"\x89PNG":
                continue
            bw, bh = struct.unpack(">II", data[16:24])
            ox, oy = int(sg.originOffsetX or 0) * scale, int(sg.originOffsetY or 0) * scale
            x0, y0 = round(ox), round(oy)
            x1, y1 = round(ox + bw * scale), round(oy + bh * scale)
            pen = TTGlyphPen(None)
            pen.moveTo((x0, y0)); pen.lineTo((x0, y1))
            pen.lineTo((x1, y1)); pen.lineTo((x1, y0)); pen.closePath()
            glyf[gname] = pen.glyph()


# ---- build methods ----------------------------------------------------------
def build_download(name, spec):
    DIST.mkdir(parents=True, exist_ok=True)
    curl(spec["url"], DIST / f"{name}.ttf")

def build_cbdt2sbix(name, spec):
    """Download a CBDT/CBLC bitmap font and transcode it into Apple's sbix."""
    from fontTools.ttLib import TTFont, newTable
    from fontTools.ttLib.tables._g_l_y_f import Glyph as GlyfGlyph
    from fontTools.ttLib.tables.sbixStrike import Strike
    from fontTools.ttLib.tables.sbixGlyph import Glyph as SbixGlyph

    WORK.mkdir(parents=True, exist_ok=True)
    DIST.mkdir(parents=True, exist_ok=True)
    cbdt = WORK / f"{name}-cbdt.ttf"
    curl(spec["url"], cbdt)

    f = TTFont(str(cbdt), lazy=True)
    ppem = f["CBLC"].strikes[0].bitmapSizeTable.ppemX
    bitmaps = {}
    for sd in f["CBDT"].strikeData:
        for gname, gd in sd.items():
            png = getattr(gd, "imageData", None)
            if not png:
                continue
            m = gd.metrics
            off_x = int(getattr(m, "BearingX", 0))
            bitmaps[gname] = (png, off_x, 0)   # baseline-aligned (offY=0), like Apple

    order = f.getGlyphOrder()
    glyf = newTable("glyf"); glyf.glyphOrder = order; glyf.glyphs = {}
    for gname in order:
        g = GlyfGlyph(); g.numberOfContours = 0
        glyf.glyphs[gname] = g
    f["glyf"] = glyf
    if "loca" not in f:
        f["loca"] = newTable("loca")
    f["maxp"].tableVersion = 0x00010000

    sbix = newTable("sbix"); sbix.version = 1; sbix.flags = 1
    sbix.numStrikes = 1; sbix.strikes = {}
    strike = Strike(ppem=ppem, resolution=72)
    for gname in order:
        if gname in bitmaps:
            png, ox, oy = bitmaps[gname]
            strike.glyphs[gname] = SbixGlyph(glyphName=gname, graphicType="png ",
                                             imageData=png, originOffsetX=ox, originOffsetY=oy)
        else:
            strike.glyphs[gname] = SbixGlyph(glyphName=gname)
    sbix.strikes[ppem] = strike
    f["sbix"] = sbix
    for tag in ("CBDT", "CBLC", "COLR", "CPAL", "SVG "):
        if tag in f:
            del f[tag]
    sbix_outline_boxes(f)
    f.save(str(DIST / f"{name}.ttf"))
    f.close()

def build_colrv0(name, spec):
    """Build a COLRv0 vector font from a set's per-codepoint SVGs via nanoemoji."""
    WORK.mkdir(parents=True, exist_ok=True)
    DIST.mkdir(parents=True, exist_ok=True)
    src = WORK / f"{name}-src"
    if not (src / spec["svg_dir"]).exists():
        shutil.rmtree(src, ignore_errors=True)
        subprocess.run(["git", "clone", "--depth", "1", "--filter=blob:none", "--sparse",
                        "-b", spec.get("branch", "main"), spec["repo"], str(src)], check=True)
        subprocess.run(["git", "-C", str(src), "sparse-checkout", "set", spec["svg_dir"]], check=True)

    # stage SVGs under nanoemoji's emoji_u<cp>[_<cp>].svg naming
    stage = WORK / f"{name}-stage"
    shutil.rmtree(stage, ignore_errors=True); stage.mkdir(parents=True)
    for svg in (src / spec["svg_dir"]).glob("*.svg"):
        base = svg.stem.lower().replace("-", "_")          # twemoji: 1f1e6-1f1e8 → 1f1e6_1f1e8
        shutil.copy(svg, stage / f"emoji_u{base}.svg")

    build = WORK / f"{name}-build"
    shutil.rmtree(build, ignore_errors=True); build.mkdir(parents=True)
    env = dict(os.environ)
    nano = shutil.which("nanoemoji")
    if nano:                                               # ensure subtools (picosvg) resolve
        env["PATH"] = os.path.dirname(nano) + os.pathsep + env.get("PATH", "")
    subprocess.run(["nanoemoji", "--color_format", "glyf_colr_0", "--reuse_tolerance", "0.3",
                    "--family", spec["label"], "--output_file", "out.ttf"] +
                   [str(p) for p in sorted(stage.glob("emoji_u*.svg"))],
                   cwd=str(build), env=env, check=True)
    shutil.copy(build / "build" / "out.ttf", DIST / f"{name}.ttf")

METHODS = {"download": build_download, "cbdt2sbix": build_cbdt2sbix, "colrv0": build_colrv0}


def build(name):
    spec = SOURCES[name]
    print(f"::group::build {name} ({spec['method']})")
    METHODS[spec["method"]](name, spec)
    out = DIST / f"{name}.ttf"
    print(f"  → {out} ({out.stat().st_size // 1024} KB)")
    print("::endgroup::")


def main(argv):
    if not argv:
        print(__doc__); return 2
    cmd = argv[0]
    if cmd == "changed":
        print("\n".join(changed_sets()))
    elif cmd in ("build", "build-all"):
        sets = list(SOURCES) if cmd == "build-all" else argv[1:]
        v = load_versions()
        for s in sets:
            build(s)
            v[s] = upstream_ref(SOURCES[s])
        VERSIONS_FILE.write_text(json.dumps(v, indent=2, sort_keys=True) + "\n")
        print("updated versions.json for:", " ".join(sets))
    else:
        print(__doc__); return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
