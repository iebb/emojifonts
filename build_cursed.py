#!/usr/bin/env python3
"""Generate the Cursed Noto emoji font(s).

Thin per-font entry point; all shared build logic lives in common.py.
  python build_cursed.py build      # build this font's variants (+ refresh docs)
  python build_cursed.py changed    # print "cursed" iff its upstream changed
"""
import sys
import common

if __name__ == "__main__":
    sys.exit(common.cli("cursed", sys.argv[1:]))
