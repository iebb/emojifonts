# emojifonts

macOS-renderable color emoji fonts, rebuilt automatically from upstream.

macOS Core Text renders **sbix**, **COLRv0** and **OT-SVG** — but *not* COLRv1 or
CBDT. Every set is published as **sbix** (`<set>.ttf`) — bitmap, full coverage,
renders everywhere including Chrome. Sets with SVG sources additionally get a
true-vector **COLRv0** build (`<set>-colrv0.ttf`), crisp at any size.

| Set | License | Upstream | sbix | COLRv0 |
|-----|---------|----------|:----:|:------:|
| `noto` | Apache-2.0 / OFL | [googlefonts/noto-emoji](https://github.com/googlefonts/noto-emoji) | ✅ (CBDT→sbix) | ✅¹ |
| `blobmoji` | OFL-1.1 | [C1710/blobmoji](https://github.com/C1710/blobmoji) | ✅ (CBDT→sbix) | ✅¹ |
| `fluent` | MIT | [microsoft/fluentui-emoji](https://github.com/microsoft/fluentui-emoji) | ✅ (CBDT→sbix) | — |
| `twemoji` | CC-BY-4.0 | [jdecked/twemoji](https://github.com/jdecked/twemoji) | ✅ (SVG→sbix) | ✅ |
| `openmoji` | CC-BY-SA-4.0 | [hfg-gmuend/openmoji](https://github.com/hfg-gmuend/openmoji) | ✅ (SVG→sbix) | ✅ |
| `emojitwo` | CC-BY-4.0 | [EmojiTwo/EmojiTwo](https://github.com/EmojiTwo/EmojiTwo) | ✅ (SVG→sbix) | ✅ |
| `tossface` | free | [toss/tossface](https://github.com/toss/tossface) | ✅ (upstream sbix) | — |

¹ COLRv0 stores one glyph per color region, so detailed sets can blow past
TrueType's 65 535-glyph cap. When that happens the build drops the least-common
emoji — skin-tone variants, especially multi-person sequences — until it fits.
sbix builds also get box glyf outlines so they render in Chrome (Skia), not just
Core Text.

## Automation

- **Per-set weekly actions** — each set has its **own** workflow
  (`build-<set>.yml`) on a staggered Monday cron. It compares the upstream's
  latest commit to `versions/<set>.txt` and **only rebuilds if that set changed**,
  publishing to a rolling **`latest`** pre-release. Trigger any one individually
  (Actions → *<set>* → Run workflow), optionally `force`. All share the build
  logic via the reusable [`_build.yml`](.github/workflows/_build.yml).
- **Monthly** ([`release.yml`](.github/workflows/release.yml), 1st): snapshot the
  current `latest` fonts into a dated `YYYY.MM` release.

## Use

```
https://github.com/iebb/emojifonts/releases/latest/download/<set>.ttf
https://github.com/iebb/emojifonts/releases/latest/download/<set>-colrv0.ttf
```

## Build individually (local)

```bash
scripts/build.sh twemoji          # one set → dist/twemoji.ttf (+ -colrv0.ttf)
scripts/build.sh noto blobmoji    # several
python build.py changed           # which upstreams changed
python build.py build-all         # everything
```

Sources are declared in [`sources.json`](sources.json); build logic in
[`build.py`](build.py).
