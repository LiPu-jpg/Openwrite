# OpenWrite Xiaohongshu carousel

This folder contains 1080 x 1440 promotional carousels built with plain HTML
and CSS. Versions 1 and 2 contain eight pages; version 4 contains nine pages.

Open `index.html`, `index-v2.html`, or `index-v4.html` directly to preview every
page. Add `?card=N` to preview a single page.

Run the renderer on macOS with Google Chrome installed:

```bash
./render.sh
```

Set `CHROME_BIN` to use another Chromium-compatible executable. Rendered PNGs
are written to `output/`.

Render the second version without overwriting the first:

```bash
HTML_FILE="$PWD/index-v2.html" OUTPUT_DIR="$PWD/output-v2" ./render.sh
```

Render the nine-page comparison version:

```bash
HTML_FILE="$PWD/index-v4.html" OUTPUT_DIR="$PWD/output-v4" CARD_COUNT=9 ./render.sh
```
