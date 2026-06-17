#!/usr/bin/env python3
"""Build the macOS system drop-in `<key>.ttc` from a built sbix `<key>.ttf`.

macOS resolves typed emoji through font *substitution*, which is hardwired to the
sealed system font `/System/Library/Fonts/Apple Color Emoji.ttc`. The only way to
change emoji everywhere is to replace that file — with a 2-member collection named
exactly `Apple Color Emoji` + `.Apple Color Emoji UI`, whose art is normalised to
Apple's geometry (art = advance = 1 em) so third-party emoji don't render oversized.

This is the build_system_ttc logic from the `emojiswap` tool, made standalone and
CI-friendly: the one macOS-only step (measuring art size via Core Text) is replaced
by reading the sbix bitmap's opaque bbox with **Pillow**, so it runs on Linux.

Usage:  python build_ttc.py <in.ttf> <out.ttc>
"""
import io
import struct
import sys
from fontTools.ttLib import TTFont, TTCollection
from fontTools.pens.ttGlyphPen import TTGlyphPen
from PIL import Image

# 2-member collection, named exactly as the system font's members.
SYSTEM_TTC_MEMBERS = [
    {1: "Apple Color Emoji",      2: "Regular", 4: "Apple Color Emoji",
     6: "AppleColorEmoji",        16: "Apple Color Emoji",      17: "Regular"},
    {1: ".Apple Color Emoji UI",  2: "Regular", 4: ".Apple Color Emoji UI",
     6: ".AppleColorEmojiUI",     16: ".Apple Color Emoji UI",  17: "Regular"},
]
REF_SAMPLES = [0x1F600, 0x1F601, 0x1F642, 0x1F60A]   # glyphs that tend to fill the cell


def measure_art_em(font):
    """How big the emoji art is, in ems (1.0 = fills the em, like Apple) — measured
    from the sbix PNG's opaque bbox. Mirrors artsize.swift without Core Text."""
    if "sbix" not in font:
        return 1.0
    cmap = font.getBestCmap()
    strike = max(font["sbix"].strikes.values(), key=lambda s: s.ppem)
    ppem = max(1, strike.ppem)
    sizes = []
    for cp in REF_SAMPLES:
        gname = cmap.get(cp)
        sg = strike.glyphs.get(gname) if gname else None
        data = getattr(sg, "imageData", None) if sg else None
        if not data or data[:4] != b"\x89PNG":
            continue
        alpha = Image.open(io.BytesIO(data)).convert("RGBA").split()[3]
        bbox = alpha.getbbox()
        if not bbox:
            continue
        sizes.append(max(bbox[2] - bbox[0], bbox[3] - bbox[1]) / ppem)
    if not sizes:
        return 1.0
    sizes.sort()
    return sizes[len(sizes) // 2]


def sbix_outline_boxes(font):
    """Give each sbix bitmap glyph a glyf box outline matching the bitmap's extent,
    so Chrome/Skia (which skips empty-outline glyphs and clips to the outline) both
    draws the bitmap and doesn't crop it."""
    if "sbix" not in font or "glyf" not in font:
        return
    glyf = font["glyf"]
    upm = font["head"].unitsPerEm
    margin = round(upm * 0.04)
    for st in font["sbix"].strikes.values():
        scale = upm / max(1, st.ppem)
        for gname, sg in st.glyphs.items():
            data = getattr(sg, "imageData", None)
            if not data or getattr(sg, "graphicType", None) != "png " or data[:4] != b"\x89PNG":
                continue
            bw, bh = struct.unpack(">II", data[16:24])
            ox, oy = int(sg.originOffsetX or 0) * scale, int(sg.originOffsetY or 0) * scale
            x0, y0 = round(ox) - margin, round(oy) - margin
            x1, y1 = round(ox + bw * scale) + margin, round(oy + bh * scale) + margin
            pen = TTGlyphPen(None)
            pen.moveTo((x0, y0)); pen.lineTo((x0, y1))
            pen.lineTo((x1, y1)); pen.lineTo((x1, y0)); pen.closePath()
            glyf[gname] = pen.glyph()


def normalize_to_apple_metrics(font, art_em):
    """Rescale art to exactly 1 em (sbix: scale strike ppem), set every advance = UPM,
    and flatten vertical metrics to 1 em — Apple Color Emoji's geometry."""
    art_em = max(0.5, min(2.0, art_em))
    order = font.getGlyphOrder()
    hmtx = font["hmtx"]
    if "sbix" in font:
        for st in font["sbix"].strikes.values():
            st.ppem = max(1, round(st.ppem * art_em))
            for sg in st.glyphs.values():
                data = getattr(sg, "imageData", None)
                if data and getattr(sg, "graphicType", None) == "png " and data[:4] == b"\x89PNG":
                    bw, bh = struct.unpack(">II", data[16:24])
                    sg.originOffsetX = round((st.ppem - bw) / 2)
                    sg.originOffsetY = round((st.ppem - bh) / 2)
        upm = font["head"].unitsPerEm
        sbix_outline_boxes(font)
    else:
        upm = max(16, round(font["head"].unitsPerEm * art_em))
        font["head"].unitsPerEm = upm
    for g in order:
        hmtx[g] = (upm, 0)
    font["hhea"].ascent = upm
    font["hhea"].descent = 0
    font["hhea"].lineGap = 0
    if "OS/2" in font:
        os2 = font["OS/2"]
        os2.sTypoAscender, os2.sTypoDescender, os2.sTypoLineGap = upm, 0, 0
        os2.usWinAscent, os2.usWinDescent = upm, 0


def set_names(nm, mapping):
    for rec in list(nm.names):
        if rec.nameID in mapping:
            rec.string = mapping[rec.nameID]
    for nid, val in mapping.items():
        nm.setName(val, nid, 1, 0, 0)
        nm.setName(val, nid, 3, 1, 0x409)


def build_ttc(src, out):
    probe = TTFont(src, lazy=True, fontNumber=0)
    if "sbix" not in probe:
        print(f"  {src}: no sbix table — skipping (.ttc is for color/sbix fonts)")
        return False
    art = measure_art_em(probe)
    print(f"  art_em = {art:.3f}")
    members = []
    for namemap in SYSTEM_TTC_MEMBERS:
        f = TTFont(src, lazy=True, fontNumber=0)
        normalize_to_apple_metrics(f, art)
        set_names(f["name"], namemap)
        members.append(f)
    ttc = TTCollection()
    ttc.fonts = members
    ttc.save(out)
    print(f"  wrote {out}")
    return True


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: build_ttc.py <in.ttf> <out.ttc>")
    build_ttc(sys.argv[1], sys.argv[2])
