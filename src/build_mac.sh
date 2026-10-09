#!/bin/sh
set -eu

project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
build=$(mktemp -d "${TMPDIR:-/tmp}/web-mail-merge-build.XXXXXX")
trap 'rm -rf "$build"' EXIT HUP INT TERM

# Build away from the developer checkout so local paths, caches, and account
# state cannot become inputs to the distributable.
mkdir -p "$build/src"
cp "$project"/src/*.py "$project"/src/*.js "$project"/src/requirements.txt "$build/src/"
cp -R "$project/src/assets" "$build/src/assets"
python3 -m venv "$build/venv"
"$build/venv/bin/python" -m pip install -r "$build/src/requirements.txt" 'pyinstaller>=6,<7'
"$build/venv/bin/python" -m PyInstaller --noconfirm --clean --windowed --onedir \
  --target-arch arm64 --name 'Web Mail Merge' \
  --osx-bundle-identifier 'local.webmailmerge.desktop' \
  --icon "$build/src/assets/AppIcon.icns" \
  --add-data "$build/src/assets/app-icon-512.png:assets" \
  --add-data "$build/src/picker.js:." \
  --collect-all playwright \
  --distpath "$build/dist" --workpath "$build/work" --specpath "$build" \
  "$build/src/mail_merge.py"
codesign --force --deep --sign - "$build/dist/Web Mail Merge.app"
ditto -c -k --sequesterRsrc --keepParent "$build/dist/Web Mail Merge.app" \
  "$project/Web-Mail-Merge-macOS-arm64.zip"
echo "Created $project/Web-Mail-Merge-macOS-arm64.zip"
