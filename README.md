# Web Mail Merge

Desktop mail merge for Gmail and Outlook on the web. Preview personalized messages, verify a live draft, send a reviewed batch, or schedule it on a local timer.

## Download

| Platform | File | Requirements |
| --- | --- | --- |
| Apple Silicon Mac | [Web-Mail-Merge-macOS-arm64.zip](Web-Mail-Merge-macOS-arm64.zip) | macOS; Chromium downloads on first browser use |
| Windows x64 | [Web-Mail-Merge-Windows-x64.zip](Web-Mail-Merge-Windows-x64.zip) | Windows 10/11; Chromium downloads on first browser use |

Unzip, then open **Web Mail Merge.app** on Mac or **Web Mail Merge.exe** on Windows. These downloads include Python and the app dependencies. The first browser action needs internet access to install Chromium, or you can choose an already installed Google Chrome. macOS may ask you to approve opening an app from an unidentified developer in **System Settings → Privacy & Security**; this build is ad hoc signed and is not Apple notarized.

For setup, sending, scheduling, and storage details, see [INSTRUCTIONS.md](INSTRUCTIONS.md).

## Source

All source code, tests, assets, and build scripts are in [src/](src/). With Python 3.10 or newer and Tkinter, run `python3 src/launch.py` on Mac/Linux or `py -3 src\launch.py` on Windows. The source launcher creates a local virtual environment and installs its dependencies.

To build the platform downloads, run `src/build_mac.sh` on Apple Silicon macOS or `src/build_windows.ps1` on Windows x64. The Windows archive is also built by [GitHub Actions](.github/workflows/build-windows.yml) after source changes.

## Privacy and local storage

The downloads start without any accounts, saved browser sessions, recipient lists, message templates, or send history. Source checkouts also start empty. The app stores data on your computer after you use it: on Mac in `~/Library/Application Support/Web Mail Merge`, on Windows in `%LOCALAPPDATA%\Web Mail Merge`, and for source checkouts in the untracked `.mailmerge_state` folder. Browser sign-in happens on Gmail or Outlook in a visible browser window. Scheduling uses the local app timer, so the app and computer must stay open and awake.

No user data or browser profile is included in the repository or downloads. See [.gitignore](.gitignore) for local data exclusions.
