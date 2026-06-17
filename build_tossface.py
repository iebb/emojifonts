#!/usr/bin/env python3
"""Generate the Toss Face emoji font(s).

Thin per-font entry point; all shared build logic lives in common.py.
  python build_tossface.py build      # build this font's variants (+ refresh docs)
  python build_tossface.py changed    # print "tossface" iff its upstream changed
"""
import sys
import common

if __name__ == "__main__":
    sys.exit(common.cli("tossface", sys.argv[1:]))
