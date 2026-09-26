#!/usr/bin/env bash
# Run the pinned transport environment; no Julia or GPU settings are changed.
set -euo pipefail
here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd -- "$here/.." && pwd)"
pixi="${PIXI_EXECUTABLE:-$HOME/.pixi/bin/pixi}"
if [[ ! -x "$pixi" ]]; then
  echo 'Pixi is not installed. See transport/README.md.' >&2
  exit 1
fi
case "${1:-versions}" in
  versions)
    exec "$pixi" run --locked --manifest-path "$here/pixi.toml" versions
    ;;
  smoke)
    output="$root/.local/transport/smoke.lh5"
    if [[ -e "$output" ]]; then
      echo "Output already exists: $output. Preserve or remove it before a rerun." >&2
      exit 1
    fi
    mkdir -p -- "$(dirname -- "$output")"
    exec "$pixi" run --locked --manifest-path "$here/pixi.toml" remage -t 1 -o "$output" -g "$here/smoke.gdml" -- "$here/smoke.mac"
    ;;
  *) exec "$pixi" run --locked --manifest-path "$here/pixi.toml" "$@" ;;
esac
