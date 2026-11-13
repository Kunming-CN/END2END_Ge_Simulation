#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
project_root="$(pwd -P)"
source "$project_root/tools/macos_launch.sh"
mac_require_native

if ! xcrun --sdk macosx --show-sdk-path >/dev/null; then
  echo 'Install the Apple Command Line Tools with xcode-select --install, then rerun Setup.command.' >&2
  exit 1
fi
PIXI_EXECUTABLE="$(mac_tool "${PIXI_EXECUTABLE:-}" pixi "$HOME/.pixi/bin/pixi")"
export PIXI_EXECUTABLE

if [[ -z "${JULIA_EXE:-}" ]]; then
  juliaup="$(mac_tool "${JULIAUP_EXECUTABLE:-}" juliaup "$HOME/.juliaup/bin/juliaup")"
  julia="$(mac_tool "$(dirname -- "$juliaup")/julia" julia "$HOME/.juliaup/bin/julia")"
  "$juliaup" add 1.13.0
  JULIA_EXE="$("$julia" +1.13.0 --startup-file=no -e 'print(realpath(joinpath(Sys.BINDIR, "julia")))')"
fi
JULIA_EXE="$(mac_tool "$JULIA_EXE" julia "$HOME/.juliaup/bin/julia")"
export JULIA_EXE
if [[ "$("$JULIA_EXE" --startup-file=no -e 'print(VERSION, " ", Sys.ARCH)')" != "1.13.0 $(uname -m | sed 's/^arm64$/aarch64/')" ]]; then
  echo 'Setup requires a native Julia 1.13.0 executable for this Mac.' >&2
  exit 1
fi

echo 'Installing the locked transport environment.'
"$PIXI_EXECUTABLE" install --locked --manifest-path "$project_root/transport/macos/pixi.toml"
/bin/bash "$project_root/transport/macos/workflow.sh" python -B "$project_root/tools/macos_setup.py"

echo 'Preparing the Julia 1.13.0 CPU environment.'
env JULIA_NUM_THREADS=1 JULIA_NUM_PRECOMPILE_TASKS=1 OPENBLAS_NUM_THREADS=1 \
  "$JULIA_EXE" --startup-file=no --project="$project_root/simulation" \
  -e 'using Pkg; Pkg.instantiate(; allow_autoprecomp=false); using SolidStateDetectors, JSON, Unitful'

echo 'Mac setup complete. Open Control.command.'
