#!/usr/bin/env python3
"""Generate the Twemoji (jdecked) emoji font(s).

Thin per-font entry point; all shared build logic lives in common.py.
  python build_twemoji.py build      # build this font's variants (+ refresh docs)
  python build_twemoji.py changed    # print "twemoji" iff its upstream changed
"""
import sys
import common

if __name__ == "__main__":
    sys.exit(common.cli("twemoji", sys.argv[1:]))
