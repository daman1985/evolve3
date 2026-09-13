#!/bin/bash
# Fetch the prebuilt Perses v2.7 deploy jar (77MB, too large to vendor in git).
# Requires a JDK (tested with OpenJDK 21).
set -euo pipefail
DEST="${1:-/tmp/perses_deploy.jar}"
[ -f "$DEST" ] && { echo "already present: $DEST"; exit 0; }
curl -fsSL -o "$DEST" https://github.com/uw-pluverse/perses/releases/download/v2.7/perses_deploy.jar
java -jar "$DEST" --version >/dev/null 2>&1 || true
echo "fetched: $DEST"
