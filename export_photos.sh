#!/usr/bin/env sh
set -euo pipefail

# === Settings (env first) ===
BASE_DIR="${ROOT:-$HOME/Downloads/reexport}"

USE_JPEG_EXT="${EXPORT_USE_JPEG_EXT:-0}"    # 0 = off, 1 = on
EXPORT_ALBUM="${EXPORT_ALBUM:-reexport}"
EXPORT_DB_PATH="${EXPORT_DB_PATH:-$HOME/osxphotos-export.db}"
EXPORT_REPORT_FILE="${EXPORT_REPORT_FILE:-osxphotos-export.csv}"

# Check for osxphotos
command -v osxphotos >/dev/null 2>&1 || {
  echo "osxphotos not found. Install: pipx install osxphotos (or pip install osxphotos)"
  exit 1
}

DEST="${BASE_DIR}"
EXPORT_DB="$EXPORT_DB_PATH"
REPORT_FILE="$EXPORT_REPORT_FILE"

mkdir -p "$DEST"

echo "=== Export to ${DEST} ==="

cmd=(osxphotos export "$DEST" \
    --directory "{created.year}/{created.strftime,%Y-%m-%d}" \
    --filename "{original_name}" \
    --ignore-date-modified \
    --sidecar xmp \
    --touch-file \
    --download-missing --use-photokit --retry 3 \
    --exportdb "$EXPORT_DB" \
    --report "$REPORT_FILE" --append \
    --not-shared \
    --album "$EXPORT_ALBUM" \
    --update \
    -V)

# Optionally add --jpeg-ext jpg
if [[ "$USE_JPEG_EXT" -eq 1 ]]; then
  cmd+=(--jpeg-ext jpg)
fi

# Run
"${cmd[@]}"

echo "✅ Export completed."
