#!/usr/bin/env bash
# One-time setup in a PythonAnywhere Bash console, run from the cloned repo:
#   bash deploy/setup_pythonanywhere.sh
set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-python3.12}"   # must match the Python version chosen on the Web tab

echo "Creating virtualenv with $PYTHON..."
"$PYTHON" -m venv .venv
.venv/bin/pip install -q -r requirements.txt

if [ ! -f .env ]; then
  read -rp "Choose a team code to share with your coworkers: " team_code
  {
    echo "SECRET_KEY=$("$PYTHON" -c 'import secrets; print(secrets.token_hex(32))')"
    echo "TEAM_CODE=$team_code"
  } > .env
  chmod 600 .env
  echo "Wrote .env"
else
  echo ".env already exists, leaving it alone"
fi

echo
echo "Done. On the Web tab, set:"
echo "  Source code:  $PWD"
echo "  Virtualenv:   $PWD/.venv"
echo "Then paste deploy/pythonanywhere_wsgi.py into the WSGI configuration file and click Reload."
