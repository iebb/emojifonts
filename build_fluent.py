#!/usr/bin/env python3
"""Generate the Microsoft Fluent 3D + Flat emoji font(s).

Thin per-font entry point; all shared build logic lives in common.py.
  python build_fluent.py build      # build this font's variants (+ refresh docs)
  python build_fluent.py changed    # print "fluent" iff its upstream changed
"""
import sys
import common

if __name__ == "__main__":
    sys.exit(common.cli("fluent", sys.argv[1:]))
