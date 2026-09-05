#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HTML_FILE="${HTML_FILE:-${SCRIPT_DIR}/index.html}"
OUTPUT_DIR="${OUTPUT_DIR:-${SCRIPT_DIR}/output}"
CARD_COUNT="${CARD_COUNT:-8}"
CHROME_BIN="${CHROME_BIN:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"

if [[ ! -x "${CHROME_BIN}" ]]; then
  echo "Chrome executable not found: ${CHROME_BIN}" >&2
  echo "Set CHROME_BIN to a Chromium-compatible browser executable." >&2
  exit 1
fi

mkdir -p "${OUTPUT_DIR}"

for card in $(seq 1 "${CARD_COUNT}"); do
  number="$(printf '%02d' "${card}")"
  "${CHROME_BIN}" \
    --headless=new \
    --disable-gpu \
    --hide-scrollbars \
    --force-device-scale-factor=1 \
    --run-all-compositor-stages-before-draw \
    --virtual-time-budget=1000 \
    --window-size=1080,1440 \
    --screenshot="${OUTPUT_DIR}/${number}.png" \
    "file://${HTML_FILE}?card=${card}" >/dev/null 2>&1
done

echo "Rendered ${CARD_COUNT} cards from ${HTML_FILE} to ${OUTPUT_DIR}"
