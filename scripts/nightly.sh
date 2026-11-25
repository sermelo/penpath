#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

time_bin="${PENPATH_NIGHTLY_TIME:-/usr/bin/time}"

uv sync --python 3.14 --extra dev --extra vpype
uv pip install pytest pytest-cov

"$time_bin" -f 'penpath convert wall time: %e s' \
  uv run penpath convert tests/fixtures/images/reference/photo.jpg \
    -o /tmp/nightly-photo.svg --pfm-setting seed=42 --quiet

uv run pytest tests/unit tests/integration -vs
