#!/usr/bin/env python3
"""Generate the OpenMoji emoji font(s).

Thin per-font entry point; all shared build logic lives in common.py.
  python build_openmoji.py build      # build this font's variants (+ refresh docs)
  python build_openmoji.py changed    # print "openmoji" iff its upstream changed
"""
import sys
import common

if __name__ == "__main__":
    sys.exit(common.cli("openmoji", sys.argv[1:]))
