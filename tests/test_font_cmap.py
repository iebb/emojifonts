import tempfile
import unittest
from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib.tables._c_m_a_p import CmapSubtable

from font_cmap import mapped_ascii_digits, sanitize_font_file, verify_font_file


def make_test_font(path):
    glyph_order = [".notdef", "zero", "one", "face"]
    glyphs = {}
    for name in glyph_order:
        glyphs[name] = TTGlyphPen(None).glyph()

    builder = FontBuilder(unitsPerEm=1000, isTTF=True)
    builder.setupGlyphOrder(glyph_order)
    builder.setupCharacterMap({0x30: "zero", 0x31: "one", 0x1F600: "face"})
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics({name: (1000, 0) for name in glyph_order})
    builder.setupHorizontalHeader(ascent=1000, descent=0)
    builder.setupNameTable({"familyName": "Cmap Test", "styleName": "Regular"})
    builder.setupOS2(sTypoAscender=1000, sTypoDescender=0,
                     usWinAscent=1000, usWinDescent=0)
    builder.setupPost()

    variation = CmapSubtable.newSubtable(14)
    variation.platformID = 0
    variation.platEncID = 5
    variation.language = 0
    variation.cmap = {}
    variation.uvsDict = {0xFE0F: [(0x30, None), (0x1F600, None)]}
    builder.font["cmap"].tables.append(variation)
    builder.save(path)


class FontCmapTests(unittest.TestCase):
    def test_sanitize_removes_digit_cmap_and_uvs_but_keeps_emoji(self):
        from fontTools.ttLib import TTFont

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.ttf"
            make_test_font(path)

            before = TTFont(path)
            self.assertEqual(mapped_ascii_digits(before), {0x30, 0x31})
            self.assertIn(0x1F600, before.getBestCmap())
            before.close()

            removed = sanitize_font_file(path)
            self.assertGreaterEqual(removed, 3)
            verify_font_file(path)

            after = TTFont(path)
            self.assertEqual(mapped_ascii_digits(after), set())
            self.assertIn(0x1F600, after.getBestCmap())
            variation = next(table for table in after["cmap"].tables if table.format == 14)
            self.assertEqual(variation.uvsDict[0xFE0F], [(0x1F600, None)])
            after.close()

    def test_sanitize_removes_digits_from_every_ttc_member(self):
        from fontTools.ttLib import TTCollection, TTFont

        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source = directory / "source.ttf"
            collection_path = directory / "test.ttc"
            make_test_font(source)

            collection = TTCollection()
            collection.fonts = [TTFont(source), TTFont(source)]
            collection.save(collection_path)
            collection.close()

            sanitize_font_file(collection_path)
            verify_font_file(collection_path)

            sanitized = TTCollection(collection_path)
            self.assertEqual(len(sanitized.fonts), 2)
            for font in sanitized.fonts:
                self.assertEqual(mapped_ascii_digits(font), set())
                self.assertIn(0x1F600, font.getBestCmap())
            sanitized.close()


if __name__ == "__main__":
    unittest.main()
