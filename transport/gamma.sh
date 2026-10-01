#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
pixi="${PIXI_EXECUTABLE:-$HOME/.pixi/bin/pixi}"
if [[ ! -x "$pixi" ]]; then
  echo 'Existing Pixi executable missing; gamma transport refused.' >&2
  exit 1
fi
exec "$pixi" run --locked --no-install --manifest-path ./pixi.toml python -B ./scenario_transport.py "$@"
