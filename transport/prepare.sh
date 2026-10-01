#!/usr/bin/env bash
# No install, build, environment fallback, radiation, Julia or PATH mutation.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
pixi="${PIXI_EXECUTABLE:-$HOME/.pixi/bin/pixi}"
if [[ ! -x "$pixi" ]]; then
  echo 'Existing Pixi executable missing; preparation refused.' >&2
  exit 1
fi
exec "$pixi" run --locked --no-install --manifest-path ./pixi.toml python -B ./scenario_prepare.py "$@"
