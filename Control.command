#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
project_root="$(pwd -P)"
source "$project_root/tools/macos_launch.sh"
mac_require_native

if [[ -n "${SITE_PYTHON:-}" ]]; then
  python="$(mac_tool "$SITE_PYTHON" python3 /usr/bin/python3)"
  exec "$python" -B "$project_root/tools/local_ui.py" "$@"
fi
exec /bin/bash "$project_root/transport/macos/workflow.sh" python -B "$project_root/tools/local_ui.py" "$@"
