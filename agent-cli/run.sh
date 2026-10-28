#!/bin/zsh
# Runs agent.py with ANTHROPIC_API_KEY from ~/.zshrc (non-login shells don't have it).
source ~/.zshrc >/dev/null 2>&1
cd "${0:A:h}" && mkdir -p logs && exec uv run agent.py "$@"
