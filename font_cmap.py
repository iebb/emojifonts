#!/usr/bin/env python3
"""Remove ASCII digit mappings from emoji-font cmap tables.

Emoji fonts may retain glyphs for keycap sequences, but they must not claim the
standalone text characters U+0030..U+0039.  This module strips both ordinary
cmap entries and format-14 variation-selector records for those codepoints.
"""
import argparse
import os
from pathlib import Path


ASCII_DIGITS = frozenset(range(0x30, 0x3A))


def mapped_ascii_digits(font):
    """Return ASCII digits reachable through any cmap or UVS subtable."""
    found = set()
    if "cmap" not in font:
        return found
    for table in font["cmap"].tables:
        cmap = getattr(table, "cmap", None)
        if isinstance(cmap, dict):
            found.update(ASCII_DIGITS.intersection(cmap))
        uvs_dict = getattr(table, "uvsDict", None)
        if isinstance(uvs_dict, dict):
            for records in uvs_dict.values():
                found.update(record[0] for record in records if record[0] in ASCII_DIGITS)
    return found


def strip_ascii_digit_mappings(font):
    """Strip digit cmap and UVS records from one loaded TTFont; return entry count."""
    removed = 0
    if "cmap" not in font:
        return removed
    for table in font["cmap"].tables:
        cmap = getattr(table, "cmap", None)
        if isinstance(cmap, dict):
            for codepoint in ASCII_DIGITS:
                if codepoint in cmap:
                    del cmap[codepoint]
                    removed += 1

        uvs_dict = getattr(table, "uvsDict", None)
        if isinstance(uvs_dict, dict):
            for selector, records in list(uvs_dict.items()):
                retained = [record for record in records if record[0] not in ASCII_DIGITS]
                removed += len(records) - len(retained)
                if retained:
                    uvs_dict[selector] = retained
                else:
                    del uvs_dict[selector]
    return removed


def _load_fonts(path):
    from fontTools.ttLib import TTCollection, TTFont

    if path.suffix.lower() == ".ttc":
        container = TTCollection(str(path), lazy=False)
        return container, container.fonts
    font = TTFont(str(path), lazy=False)
    return font, [font]


def sanitize_font_file(path):
    """Strip digits from a TTF/TTC atomically; return number of removed entries."""
    path = Path(path)
    container, fonts = _load_fonts(path)
    removed = sum(strip_ascii_digit_mappings(font) for font in fonts)
    temporary = path.with_name(f".{path.name}.sanitize-{os.getpid()}")
    try:
        container.save(str(temporary))
        container.close()
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return removed


def verify_font_file(path):
    """Raise if any font in a TTF/TTC still maps an ASCII digit."""
    path = Path(path)
    container, fonts = _load_fonts(path)
    try:
        violations = [mapped_ascii_digits(font) for font in fonts]
    finally:
        container.close()
    if any(violations):
        detail = "; ".join(
            f"member {index}: " + ", ".join(f"U+{cp:04X}" for cp in sorted(found))
            for index, found in enumerate(violations)
            if found
        )
        raise RuntimeError(f"{path.name} still maps ASCII digits ({detail})")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify only; do not modify files")
    parser.add_argument("fonts", nargs="+", type=Path)
    args = parser.parse_args(argv)

    for path in args.fonts:
        if args.check:
            verify_font_file(path)
            print(f"  verified {path}: no ASCII digit mappings")
        else:
            removed = sanitize_font_file(path)
            verify_font_file(path)
            print(f"  sanitized {path}: removed {removed} ASCII digit cmap/UVS entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
