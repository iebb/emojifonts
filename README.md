# emojifonts

macOS-renderable color emoji fonts, rebuilt automatically from upstream.

macOS Core Text renders **sbix**, **COLRv0** and **OT-SVG** — but *not* COLRv1 or
CBDT. Every font is published as **sbix** (`<font>.ttf`) — bitmap, full coverage,
renders everywhere incl. Chrome. Sets with vector SVG sources also get a true-vector
**OT-SVG** build (`<font>-svginot.ttf`, macOS/Firefox — full detail incl. gradients);
the **flat** ones additionally get **COLRv0** (`<font>-colrv0.ttf`, vector everywhere
incl. Chrome). `download` fonts (mono Noto, Toss Face) ship as-is.

Work is organised as **actions** — one per upstream repo — each producing one or
more variant fonts:

| Action (upstream) | Font(s) | License | Built as |
|-------------------|---------|---------|----------|
| `noto` · [googlefonts/noto-emoji](https://github.com/googlefonts/noto-emoji) | `noto` | Apache-2.0 / OFL | sbix + OT-SVG |
| `noto-mono` · [google/fonts](https://github.com/google/fonts) | `noto-mono` (monochrome glyph) | OFL-1.1 | as-is (glyf) |
| `blobmoji` · [C1710/blobmoji](https://github.com/C1710/blobmoji) | `blobmoji` | OFL-1.1 | sbix + OT-SVG |
| `fluent` · [tetunori/fluent-emoji-webfont](https://github.com/tetunori/fluent-emoji-webfont)² | `fluent`, `fluent-flat`, `fluent-hc`, `fluent-hc-inverted` | MIT | sbix |
| `twemoji` · [jdecked/twemoji](https://github.com/jdecked/twemoji) | `twemoji` | CC-BY-4.0 | sbix + COLRv0 + OT-SVG |
| `openmoji` · [hfg-gmuend/openmoji](https://github.com/hfg-gmuend/openmoji) | `openmoji` | CC-BY-SA-4.0 | sbix + COLRv0 + OT-SVG (prebuilt) |
| `emojitwo` · [EmojiTwo/EmojiTwo](https://github.com/EmojiTwo/EmojiTwo) | `emojitwo` | CC-BY-4.0 | sbix + COLRv0 + OT-SVG |
| `tossface` · [toss/tossface](https://github.com/toss/tossface) | `tossface` | free | as-is (sbix) |

sbix builds get box glyf outlines so they render in Chrome (Skia), not just Core Text.
OT-SVG (`-svginot.ttf`) is built for every set with per-codepoint SVGs (via nanoemoji
picosvg, normalized to 1 em); it's true vector with full gradient detail and renders
on macOS Core Text and Firefox (Chrome has no OT-SVG — sbix/COLRv0 cover it there).

¹ COLRv0 makes one glyph per color *region*, so detailed sets (Noto, Blobmoji — many
gradient layers each) blow past TrueType's 65 535-glyph cap, build slowly, *and* lose
their gradients when flattened. Their proper macOS form is the bitmap, so they ship
sbix only. COLRv0 is built for the flat sets (Twemoji, EmojiTwo), where it's small,
fast and lossless; if one ever overflows the cap the build drops the least-common
emoji (multi-person skin-tone sequences first, then all skin tones) until it fits.
Their **sbix** is rasterized straight from the SVGs with resvg and assembled over the
COLRv0's cmap+GSUB — ~10× faster than nanoemoji's bitmap pass and normalized to a
clean 1-em advance (nanoemoji emits ~1.245 em, which renders oversized). OpenMoji
ships its own prebuilt sbix + COLRv0 upstream, so we download those directly (the
sbix gets box glyf outlines added for Chrome).
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
https://github.com/iebb/emojifonts/releases/download/latest/<font>.ttf          # sbix
https://github.com/iebb/emojifonts/releases/download/latest/<font>-colrv0.ttf    # COLRv0
https://github.com/iebb/emojifonts/releases/download/latest/<font>-svginot.ttf   # OT-SVG
```

**Programmatically:** [`manifest.json`](manifest.json) (also published to the release)
lists every font with its label, license, upstream, detected Emoji version, and the
download URL for each format it ships:

```
https://github.com/iebb/emojifonts/releases/download/latest/manifest.json
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

Each font names a **builder** in [`sources.json`](sources.json), so its pipeline is
explicit and tuned to its source:

| Builder | Used by | What it does |
|---------|---------|--------------|
| `cbdt_sbix` | Noto, Blobmoji, Fluent ×4 | lift CBDT bitmaps into an sbix strike + box glyf; + OT-SVG if the set has SVGs (Noto, Blobmoji) |
| `download` | Toss Face, mono Noto, OpenMoji | take the upstream font as-is (+ optional box glyf / prebuilt COLRv0 / prebuilt OT-SVG) |
| `svg_color` | Twemoji, EmojiTwo | COLRv0 + OT-SVG via nanoemoji (normalized); sbix via resvg over its cmap+GSUB |

Build logic is in [`build.py`](build.py) (`BUILDERS` registry).
