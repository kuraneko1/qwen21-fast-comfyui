#!/usr/bin/env bash
# Render docs/diagram.html (Japanese) and docs/diagram.en.html (English) to PNG
# with headless Chrome. Both pages use a fixed 1200x620 px canvas; the screenshot
# is taken at 2x device scale so the result is crisp when the README shows it at
# about 800 px wide.
#
#   ./render_diagram.sh          # writes docs/pipeline_ja.png, docs/pipeline_en.png
#
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHROME="${CHROME:-/usr/bin/google-chrome}"

WIDTH=1200          # must match the #stage size in the HTML
HEIGHT=620
SCALE=2             # 1x would be 1200x620; 2x gives 2400x1240

if [ ! -x "$CHROME" ]; then
  CHROME="$(command -v google-chrome || command -v chromium || command -v chromium-browser || true)"
fi
if [ -z "$CHROME" ] || [ ! -x "$CHROME" ]; then
  echo "error: no Chrome/Chromium binary found (set CHROME=/path/to/chrome)" >&2
  exit 1
fi

render() {
  local html="$1" out="$2"
  [ -f "$html" ] || { echo "error: missing $html" >&2; exit 1; }
  rm -f "$out"
  "$CHROME" \
    --headless=new \
    --disable-gpu \
    --hide-scrollbars \
    --force-device-scale-factor="$SCALE" \
    --window-size="$WIDTH,$HEIGHT" \
    --virtual-time-budget=3000 \
    --screenshot="$out" \
    "file://$html"
  [ -s "$out" ] || { echo "error: $out was not written" >&2; exit 1; }
}

render "$DIR/diagram.html"    "$DIR/pipeline_ja.png"
render "$DIR/diagram.en.html" "$DIR/pipeline_en.png"

echo "wrote:"
ls -l "$DIR/pipeline_ja.png" "$DIR/pipeline_en.png"
