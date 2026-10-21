#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PYTHON=""
for candidate in python3.12 python3.13 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    version="$($candidate -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)"
    case "$version" in
      3.11|3.12|3.13) PYTHON="$(command -v "$candidate")"; break ;;
    esac
  fi
done

if [[ -z "$PYTHON" ]]; then
  if [[ "$(uname -s)" == "Darwin" ]] && command -v brew >/dev/null 2>&1; then
    echo "Python 3.12 not found; installing with Homebrew..."
    brew install python@3.12
  elif command -v apt-get >/dev/null 2>&1 && command -v sudo >/dev/null 2>&1; then
    echo "Python 3.12 not found; attempting to install it with apt..."
    sudo apt-get update
    sudo apt-get install -y python3.12 python3.12-venv python3-pip
  else
    echo "Python 3.11–3.13 is required. Install Python 3.12, then run ./start.sh again."
    echo "macOS: brew install python@3.12"
    echo "Ubuntu/Debian: install python3.12 and python3.12-venv using your package manager."
    exit 2
  fi
  for candidate in python3.12 python3.13 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      version="$($candidate -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)"
      case "$version" in
        3.11|3.12|3.13) PYTHON="$(command -v "$candidate")"; break ;;
      esac
    fi
  done
fi
if [[ -z "$PYTHON" ]]; then
  echo "Could not locate Python after installation. Open a new terminal and rerun ./start.sh."
  exit 2
fi

if ! command -v git >/dev/null 2>&1; then
  if [[ "$(uname -s)" == "Darwin" ]] && command -v brew >/dev/null 2>&1; then
    brew install git
  elif command -v apt-get >/dev/null 2>&1 && command -v sudo >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y git
  else
    echo "Git is required to install ComfyUI. Install Git and rerun ./start.sh."
    exit 2
  fi
fi

exec "$PYTHON" setup_environment.py "$@"
