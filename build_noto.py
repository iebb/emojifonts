#!/usr/bin/env python3
"""Generate the Google Noto Color emoji font(s).

Thin per-font entry point; all shared build logic lives in common.py.
  python build_noto.py build      # build this font's variants (+ refresh docs)
  python build_noto.py changed    # print "noto" iff its upstream changed
"""
import sys
import common

if __name__ == "__main__":
    sys.exit(common.cli("noto", sys.argv[1:]))
