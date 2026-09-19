#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
if [ -e .env ]; then
  echo '.env already exists; leaving it unchanged.'
  exit 0
fi
umask 077
python3 - <<'PY'
import base64
import os
import secrets
from pathlib import Path

password = secrets.token_hex(24)
invite_key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
content = (
    f"POSTGRES_PASSWORD={password}\n"
    f"LOCAL_INVITE_KEY={invite_key}\n"
    "API_PORT=8000\n"
    "WEB_PORT=8080\n"
    "PUBLIC_ORIGIN=http://127.0.0.1:8080\n"
    "GEMINI_MODEL=\n"
    "GEMINI_VISION_MODEL=\n"
    "GOOGLE_API_KEY=\n"
    "ENABLE_UNREVIEWED_DEMO_RULES=0\n"
)
fd = os.open('.env', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as output:
    output.write(content)
print('Created .env with local database and invitation keys.')
PY
