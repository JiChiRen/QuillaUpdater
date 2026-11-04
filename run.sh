#!/usr/bin/env bash
# Launch the Quilla Updater GUI (Linux / macOS).
set -e
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
if ! "$PY" -c "import tkinter" 2>/dev/null; then
  echo "Python 3 with tkinter is required (Debian/Ubuntu: sudo apt install python3-tk)" >&2
  exit 1
fi
if ! "$PY" -c "import serial" 2>/dev/null; then
  echo "Installing pyserial ..."
  "$PY" -m pip install --quiet pyserial
fi
exec "$PY" -m quilla_updater.gui
