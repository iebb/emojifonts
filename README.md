# emojifonts

macOS-renderable color emoji fonts, rebuilt automatically from upstream.

macOS Core Text renders **sbix**, **COLRv0** and **OT-SVG** — but *not* COLRv1 or
CBDT. So each set is built to the best macOS-renderable form, then published as a
release asset you can drop in as a font.

| Set | License | Built as | How |
|-----|---------|----------|-----|
| `noto` | Apache-2.0 / OFL | sbix | CBDT → sbix transcode |
| `blobmoji` | OFL-1.1 | sbix | CBDT → sbix transcode |
| `fluent` | MIT | sbix | CBDT → sbix transcode |
| `twemoji` | CC-BY-4.0 | **COLRv0** (vector) | jdecked SVGs → nanoemoji |
| `openmoji` | CC-BY-SA-4.0 | **COLRv0** (vector) | upstream COLRv0 |
| `emojitwo` | CC-BY-4.0 | **COLRv0** (vector) | upstream COLRv0 |
| `tossface` | free | sbix | upstream sbix |

Each font also gets box glyf outlines so it renders in Chrome (Skia), not just
Core Text. Detailed sets (Noto/Blobmoji/Fluent) are bitmap because COLRv0 would
overflow TrueType's 65 535-glyph cap on that much per-emoji detail.

## Automation

- **Weekly** (`build.yml`, Mondays): checks each upstream's latest commit against
  `versions.json` and **rebuilds only the sets that changed**, publishing them to a
  rolling **`latest`** pre-release. Unchanged sets are left untouched.
- **Monthly** (`release.yml`, 1st of month): snapshots the current `latest` fonts
  into a dated `YYYY.MM` release.

## Use

Download a font from the latest release and install it, or wire it into a tool:

```
https://github.com/iebb/emojifonts/releases/latest/download/<set>.ttf
```

## Build locally

```bash
pip install -r requirements.txt
python build.py changed            # which sets' upstream changed
python build.py build noto twemoji # build specific sets → dist/
python build.py build-all          # build everything
```

Sources are declared in [`sources.json`](sources.json); the build logic is in
[`build.py`](build.py).
