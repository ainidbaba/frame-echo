#!/bin/zsh
set -e
cd -- "$(dirname -- "$0")"
if [[ ! -x .venv/bin/python ]]; then
  echo "Please complete the setup in README.md first."
  exit 1
fi
echo "Frame Echo: http://127.0.0.1:8000"
echo "Keep this terminal open. Press Control-C to stop."
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
