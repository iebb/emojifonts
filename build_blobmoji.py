#!/usr/bin/env python3
"""Generate the Blobmoji (Android blobs) emoji font(s).

Thin per-font entry point; all shared build logic lives in common.py.
  python build_blobmoji.py build      # build this font's variants (+ refresh docs)
  python build_blobmoji.py changed    # print "blobmoji" iff its upstream changed
"""
import sys
import common

if __name__ == "__main__":
    sys.exit(common.cli("blobmoji", sys.argv[1:]))
