#!/usr/bin/env bash
# Builds the Viewer on first use and serves the demo plant with it on port 8765.
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f viewer/dist/index.html ] || (cd viewer && npm ci && npm run build)

# `cheme serve` refuses Host names it does not know; a Codespace may pass on its forwarded one.
allow_host=()
if [ -n "${CODESPACE_NAME:-}" ]; then
  allow_host=(--allow-host "$CODESPACE_NAME-8765.$GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN")
fi
exec cheme serve --repo demo-plant --ui viewer/dist "${allow_host[@]}" "$@"
