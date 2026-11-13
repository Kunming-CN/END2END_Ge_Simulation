#!/usr/bin/env bash
# The Mac Control workflow only uses the already installed locked environment.
set -euo pipefail
workflow_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
workflow_pixi="${PIXI_EXECUTABLE:-$(command -v pixi || true)}"
workflow_pixi="${workflow_pixi:-$HOME/.pixi/bin/pixi}"
if [[ ! -x "$workflow_pixi" ]]; then
  echo 'Pixi is unavailable. See the macOS setup guide in tools/site_guide.html.' >&2
  exit 1
fi
exec "$workflow_pixi" run --locked --no-install --manifest-path "$workflow_dir/pixi.toml" "$@"
