#!/usr/bin/env python3
"""Generate the Microsoft Fluent (monochrome) emoji font(s).

Thin per-font entry point; all shared build logic lives in common.py.
  python build_fluent_mono.py build      # build this font's variants (+ refresh docs)
  python build_fluent_mono.py changed    # print "fluent-mono" iff its upstream changed
"""
import sys
import common

if __name__ == "__main__":
    sys.exit(common.cli("fluent-mono", sys.argv[1:]))
