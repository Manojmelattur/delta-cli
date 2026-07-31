#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -d "venv" ]; then
    VENV_PATH="venv"
elif [ -d ".venv" ]; then
    VENV_PATH=".venv"
else
    echo "🐍 Creating Python virtual environment..."
    python3 -m venv venv
    VENV_PATH="venv"
fi

source "$VENV_PATH/bin/activate"
pip install -q -r requirements.txt

chmod +x main.py
python3 main.py "$@"
