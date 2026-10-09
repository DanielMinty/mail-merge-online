# Source tree

`mail_merge.py` is the desktop UI, `merge_core.py` handles spreadsheet merging and send history, `owa_browser.py` controls Gmail and Outlook, and `browser_session.py` keeps the browser open across steps. `scheduling.py` handles the local timer. `picker.js` supports website field mapping. The `assets/` directory contains the app icons, and `tests/` contains regression tests.

Run the source launcher with `python3 src/launch.py` from the repository root. Run tests with `PYTHONPATH=src .venv/bin/python -m unittest discover -s src/tests` after installing `src/requirements.txt` in a virtual environment.
