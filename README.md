# emojifonts

macOS-renderable color emoji fonts, rebuilt automatically from upstream.

macOS Core Text renders **sbix**, **COLRv0** and **OT-SVG** — but *not* COLRv1 or
CBDT. Every font is published as **sbix** (`<font>.ttf`) — bitmap, full coverage,
renders everywhere incl. Chrome. The **flat** SVG sets additionally get a true-vector
**COLRv0** build (`<font>-colrv0.ttf`); detailed/gradient sets don't (see ¹).
`download` fonts (mono Noto, Toss Face) ship as-is.

Work is organised as **actions** — one per upstream repo — each producing one or
more variant fonts:

| Action (upstream) | Font(s) | License | Built as |
|-------------------|---------|---------|----------|
| `noto` · [googlefonts/noto-emoji](https://github.com/googlefonts/noto-emoji) | `noto` | Apache-2.0 / OFL | sbix |
| `noto-mono` · [google/fonts](https://github.com/google/fonts) | `noto-mono` (monochrome glyph) | OFL-1.1 | as-is (glyf) |
| `blobmoji` · [C1710/blobmoji](https://github.com/C1710/blobmoji) | `blobmoji` | OFL-1.1 | sbix |
| `fluent` · [tetunori/fluent-emoji-webfont](https://github.com/tetunori/fluent-emoji-webfont)² | `fluent`, `fluent-flat`, `fluent-hc`, `fluent-hc-inverted` | MIT | sbix |
| `twemoji` · [jdecked/twemoji](https://github.com/jdecked/twemoji) | `twemoji` | CC-BY-4.0 | sbix + COLRv0 |
| `openmoji` · [hfg-gmuend/openmoji](https://github.com/hfg-gmuend/openmoji) | `openmoji` | CC-BY-SA-4.0 | sbix + COLRv0 (prebuilt) |
| `emojitwo` · [EmojiTwo/EmojiTwo](https://github.com/EmojiTwo/EmojiTwo) | `emojitwo` | CC-BY-4.0 | sbix + COLRv0 |
| `tossface` · [toss/tossface](https://github.com/toss/tossface) | `tossface` | free | as-is (sbix) |

sbix builds get box glyf outlines so they render in Chrome (Skia), not just Core Text.

¹ COLRv0 makes one glyph per color *region*, so detailed sets (Noto, Blobmoji — many
gradient layers each) blow past TrueType's 65 535-glyph cap, build slowly, *and* lose
their gradients when flattened. Their proper macOS form is the bitmap, so they ship
sbix only. COLRv0 is built for the flat sets (Twemoji, EmojiTwo), where it's small,
fast and lossless; if one ever overflows the cap the build drops the least-common
emoji (skin-tone, then multi-person sequences) until it fits. OpenMoji ships its own
prebuilt sbix + COLRv0 upstream, so we download those directly (the sbix gets box
glyf outlines added for Chrome).
² Fluent's art is Microsoft's [fluentui-emoji](https://github.com/microsoft/fluentui-emoji)
(MIT); we build from tetunori's webfont, which is the upstream this action tracks.

See **[VERSIONS.md](VERSIONS.md)** for each font's detected Unicode Emoji version.

## Automation

- **Per-action weekly** (`build-<action>.yml`, staggered Mondays): each compares its
  upstream's latest commit to `versions/<action>.json` and **rebuilds only if that
  upstream changed**, publishing every font it produces to a rolling **`latest`**
  pre-release. Run any one individually (Actions → *<action>* → Run workflow). Shared
  logic lives in the reusable [`_build.yml`](.github/workflows/_build.yml).
- **Docs** ([`docs.yml`](.github/workflows/docs.yml)): single writer of `VERSIONS.md`,
  triggered after each build (and weekly), regenerating it from `versions/*.json`.
- **Monthly** ([`release.yml`](.github/workflows/release.yml), 1st): snapshots `latest`
  into a dated `YYYY.MM` release.

## Use

```
https://github.com/iebb/emojifonts/releases/latest/download/<font>.ttf
https://github.com/iebb/emojifonts/releases/latest/download/<font>-colrv0.ttf
```

**Programmatically:** [`manifest.json`](manifest.json) (also published to the release)
lists every font with its label, license, upstream, detected Emoji version, and the
download URL for each format it ships:

```
https://github.com/iebb/emojifonts/releases/latest/download/manifest.json
```
```json
{ "key": "openmoji", "emoji_version": "16.0", "kind": "color",
  "formats": { "sbix": ".../openmoji.ttf", "colrv0": ".../openmoji-colrv0.ttf" } }
```

## Build locally

```bash
scripts/build.sh twemoji      # build an action's fonts → dist/
scripts/build.sh fluent       # → fluent.ttf, fluent-flat.ttf, fluent-hc.ttf, fluent-hc-inverted.ttf
python build.py changed       # which upstreams changed
python build.py build-all
```

Sources are in [`sources.json`](sources.json); build logic in [`build.py`](build.py).
