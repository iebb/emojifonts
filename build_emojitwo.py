#!/usr/bin/env python3
"""Generate the EmojiTwo (open EmojiOne) emoji font(s).

Thin per-font entry point; all shared build logic lives in common.py.
  python build_emojitwo.py build      # build this font's variants (+ refresh docs)
  python build_emojitwo.py changed    # print "emojitwo" iff its upstream changed
"""
import sys
import common

if __name__ == "__main__":
    sys.exit(common.cli("emojitwo", sys.argv[1:]))
