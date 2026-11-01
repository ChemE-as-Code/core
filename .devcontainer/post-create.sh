#!/usr/bin/env bash
# Runs once when the dev container is created: uv, the toolkit from this checkout, a demo plant.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"

command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/0.13.6/install.sh | sh
uv tool install --force '.[serve]'

# demo-plant/ is in .gitignore. Kept on a rebuild: it may hold the visitor's edits.
# Its own repository, so the Viewer shows its history and not that of this checkout.
[ -f demo-plant/plant.yaml ] || { cheme init demo-plant --name "Demo plant"; git -C demo-plant init -q; }

echo "Start the Viewer on the demo plant with: bash .devcontainer/serve.sh"
