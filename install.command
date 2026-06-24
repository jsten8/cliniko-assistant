#!/bin/bash
# Cliniko Assistant — one-time setup script for Steven
# Double-click this file to install everything

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "================================================"
echo "  Cliniko Assistant — Setup"
echo "================================================"
echo ""

# ── 1. Check Python 3 ────────────────────────────────────────────────────────
echo "Checking Python 3..."
PYTHON=""
for candidate in python3 /Library/Frameworks/Python.framework/Versions/*/bin/python3; do
  if command -v "$candidate" &>/dev/null; then
    VER=$("$candidate" --version 2>&1 | awk '{print $2}')
    MAJOR=$(echo "$VER" | cut -d. -f1)
    MINOR=$(echo "$VER" | cut -d. -f2)
    if [ "$MAJOR" -ge 3 ] && [ "$MINOR" -ge 9 ]; then
      PYTHON="$candidate"
      break
    fi
  fi
done

if [ -z "$PYTHON" ]; then
  echo ""
  echo "ERROR: Python 3.9 or later is required."
  echo "Download it from https://python.org and run this script again."
  echo ""
  read -p "Press Enter to exit..."
  exit 1
fi

echo "  Found: $($PYTHON --version)"
echo ""

# ── 2. Install Python dependencies ──────────────────────────────────────────
echo "Installing dependencies (this may take a minute)..."
"$PYTHON" -m pip install --quiet --upgrade pip
"$PYTHON" -m pip install --quiet -r requirements.txt
echo "  Done."
echo ""

# ── 3. Create .env if it doesn't exist ───────────────────────────────────────
if [ ! -f ".env" ]; then
  echo "Setting up credentials..."
  echo ""

  read -p "  Cliniko API Key: " CLINIKO_KEY
  read -p "  Sender email (Outlook): " SENDER_EMAIL
  read -p "  Anthropic API Key: " ANTHROPIC_KEY

  cat > .env << EOF
CLINIKO_API_KEY=${CLINIKO_KEY}
CLINIKO_BASE_URL=https://api.au2.cliniko.com/v1
SENDER_EMAIL=${SENDER_EMAIL}
ANTHROPIC_API_KEY=${ANTHROPIC_KEY}
MS_TENANT_ID=
MS_CLIENT_ID=
MS_CLIENT_SECRET=
OUTPUT_PATH=~/Desktop/
WORKLIST_FILE_KEYWORDS=EPC,DVA,Workcover
PREFERRED_FILE_KEYWORDS=EPC,DVA,Workcover
SCAN_DAYS=7
EOF

  echo ""
  echo "  Credentials saved."
  echo ""
else
  echo "Credentials file already exists — skipping."
  echo ""
fi

# ── 4. Configure Terminal to close window when shell exits ───────────────────
"$PYTHON" -c "
import plistlib, os
path = os.path.expanduser('~/Library/Preferences/com.apple.Terminal.plist')
try:
    with open(path, 'rb') as f:
        p = plistlib.load(f)
    ws = p.get('Window Settings', {})
    for k in ws:
        ws[k]['shellExitAction'] = 1
    with open(path, 'wb') as f:
        plistlib.dump(p, f)
except Exception:
    pass
" 2>/dev/null

# ── 5. Create Desktop launcher ───────────────────────────────────────────────
LAUNCHER="$HOME/Desktop/Cliniko Assistant.command"

cat > "$LAUNCHER" << EOF
#!/bin/bash
cd "$SCRIPT_DIR"
nohup "$PYTHON" main.py > /tmp/cliniko.log 2>&1 < /dev/null &
disown
exec sleep 0
EOF

chmod +x "$LAUNCHER"
echo "  Desktop launcher created."
echo ""

# ── 5. Done ──────────────────────────────────────────────────────────────────
echo "================================================"
echo "  Setup complete!"
echo ""
echo "  Double-click 'Cliniko Assistant' on your"
echo "  Desktop to launch the app."
echo "================================================"
echo ""
read -p "Press Enter to close..."
