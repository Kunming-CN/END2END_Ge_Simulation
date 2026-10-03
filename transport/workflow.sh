#!/usr/bin/env bash
# Control only uses an already installed locked environment.
set -euo pipefail
workflow_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
workflow_pixi="${PIXI_EXECUTABLE:-$HOME/.pixi/bin/pixi}"
if [[ ! -x "$workflow_pixi" ]]; then
  echo 'Pixi is unavailable. Follow the setup guide before running Control.' >&2
  exit 1
fi
exec "$workflow_pixi" run --locked --no-install --manifest-path "$workflow_dir/pixi.toml" "$@"
