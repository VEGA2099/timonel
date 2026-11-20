#!/bin/sh
# Timonel - Linux / macOS: ./timonel.sh   (--no-browser, --autostart on|off)
cd "$(dirname "$0")" || exit 1
for py in python3 python; do
  if command -v "$py" >/dev/null 2>&1 && "$py" -c 'import sys; sys.exit(sys.version_info < (3, 8))'; then
    exec "$py" timonel.py "$@"
  fi
done
echo "Python 3.8+ is not installed. / Python 3.8+ no está instalado."
echo "  Debian/Ubuntu: sudo apt install python3   ·   Fedora: sudo dnf install python3   ·   macOS: https://www.python.org/downloads/"
exit 1
