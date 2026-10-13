#!/usr/bin/env bash
set -euo pipefail
cd /home/nova/NOVA
export QT_QPA_PLATFORM=xcb
exec /home/nova/NOVA/.tts-venv/bin/python native/nova.py "$@"
