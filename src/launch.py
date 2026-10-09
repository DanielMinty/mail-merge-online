"""Install dependencies in this folder, then open the local desktop app."""
import hashlib
import os
import subprocess
import sys
import venv
from pathlib import Path


def main():
    if sys.version_info < (3, 10):
        raise SystemExit("Please install Python 3.10 or newer from python.org, then run this launcher again.")
    try:
        import tkinter
    except ImportError:
        raise SystemExit("This Python installation needs Tkinter. Windows/macOS: use Python from python.org. Linux: install your distribution's python3-tk package.")
    root = Path(__file__).resolve().parent
    os.chdir(root)
    environment = root / ".venv"
    interpreter = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not interpreter.exists():
        print("Preparing a private Python environment for this app…", flush=True)
        venv.EnvBuilder(with_pip=True).create(environment)
    requirements = root / "requirements.txt"
    stamp = environment / ".mail-merge-ready"
    fingerprint = hashlib.sha256(requirements.read_bytes()).hexdigest()
    if not stamp.exists() or stamp.read_text() != fingerprint:
        print("Installing Excel support and the browser. The first run needs internet access…", flush=True)
        subprocess.run([str(interpreter), "-m", "pip", "install", "-r", str(requirements)], check=True)
        subprocess.run([str(interpreter), "-m", "playwright", "install", "chromium"], check=True)
        stamp.write_text(fingerprint)
    return subprocess.call([str(interpreter), str(root / "mail_merge.py")])


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"Setup could not finish (exit {exc.returncode}). Check the installation message above and run the launcher again.")
