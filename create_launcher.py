"""
Creates a "Cliniko Assistant.app" launcher on the Desktop.
Run once: python create_launcher.py
"""
import os
import stat
from pathlib import Path

APP_DIR = Path(__file__).parent.resolve()
DESKTOP = Path.home() / "Desktop"
APP_BUNDLE = DESKTOP / "Cliniko Assistant.app"
MACOS_DIR = APP_BUNDLE / "Contents" / "MacOS"
RESOURCES_DIR = APP_BUNDLE / "Contents" / "Resources"

MACOS_DIR.mkdir(parents=True, exist_ok=True)
RESOURCES_DIR.mkdir(parents=True, exist_ok=True)

# Info.plist
plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>launch</string>
    <key>CFBundleName</key>
    <string>Cliniko Assistant</string>
    <key>CFBundleIdentifier</key>
    <string>com.clinikoassistant.app</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
"""
(APP_BUNDLE / "Contents" / "Info.plist").write_text(plist)

import shutil
PYTHON = shutil.which("python3") or "/usr/bin/python3"

# Launch script
script = f"""#!/bin/bash
cd "{APP_DIR}"
# Silent background git pull
git pull --ff-only > /dev/null 2>&1 &
# Launch app
"{PYTHON}" main.py
"""
launch_path = MACOS_DIR / "launch"
launch_path.write_text(script)
launch_path.chmod(launch_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

# Remove macOS quarantine flag so it opens without Gatekeeper blocking
os.system(f'xattr -rd com.apple.quarantine "{APP_BUNDLE}"')
os.system(f'xattr -cr "{APP_BUNDLE}"')

print(f"✓ Launcher created: {APP_BUNDLE}")
print("  Double-click 'Cliniko Assistant' on your Desktop to launch the app.")
