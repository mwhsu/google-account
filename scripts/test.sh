#!/usr/bin/env bash

set -euo pipefail

suite="${1:-all}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$(pwd)/.uv-cache}"

run_pytest() {
  interpreter="$1"
  target="$2"
  if "$interpreter" -c "import pytest" >/dev/null 2>&1; then
    "$interpreter" -m pytest "$target" -v
    exit 0
  fi
}

case "$suite" in
  all)
    if uv run --extra dev python -m pytest tests/ -v; then
      exit 0
    fi
    if [ -x .venv/bin/python ]; then
      run_pytest .venv/bin/python tests/
    fi
    run_pytest python3 tests/
    echo "pytest is not available in uv, .venv, or python3" >&2
    exit 1
    ;;
  *)
    if uv run --extra dev python -m pytest "$suite" -v; then
      exit 0
    fi
    if [ -x .venv/bin/python ]; then
      run_pytest .venv/bin/python "$suite"
    fi
    run_pytest python3 "$suite"
    echo "pytest is not available in uv, .venv, or python3" >&2
    exit 1
    ;;
esac
