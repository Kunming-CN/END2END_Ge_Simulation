# Shared prerequisites for the macOS setup and Control launchers.
mac_require_native() {
  if [[ "$(uname -s)" != Darwin ]]; then
    echo 'This launcher is for macOS. On Windows, see tools/site_guide.html.' >&2
    return 1
  fi
  if [[ "$(sysctl -n sysctl.proc_translated 2>/dev/null || true)" == 1 ]]; then
    echo 'Open a native Apple Silicon Terminal to run this launcher.' >&2
    return 1
  fi
  local version="$(sw_vers -productVersion)"
  if [[ "${version%%.*}" -lt 13 ]]; then
    echo 'The locked transport environment requires macOS 13 or newer.' >&2
    return 1
  fi
}

mac_tool() {
  local path="${1:-$(command -v "$2" || true)}"
  path="${path:-$3}"
  if [[ "$path" != /* || ! -x "$path" ]]; then
    echo "An installed $2 is required. See tools/site_guide.html." >&2
    return 1
  fi
  printf '%s\n' "$path"
}
