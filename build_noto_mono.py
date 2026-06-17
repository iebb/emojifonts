#!/usr/bin/env python3
"""Generate the Noto Emoji (monochrome glyph) emoji font(s).

Thin per-font entry point; all shared build logic lives in common.py.
  python build_noto_mono.py build      # build this font's variants (+ refresh docs)
  python build_noto_mono.py changed    # print "noto-mono" iff its upstream changed
"""
import sys
import common

if __name__ == "__main__":
    sys.exit(common.cli("noto-mono", sys.argv[1:]))
