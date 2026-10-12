"""Frozen apps must install and launch Chromium from the same user cache."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from browser_session import BrowserSessions, configure_browser_cache
from merge_core import MergeError


class BrowserCacheTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.frozen = patch("browser_session.sys.frozen", True, create=True)
        self.frozen.start()
        self.addCleanup(self.frozen.stop)

    def test_mac_uses_the_standard_user_cache(self):
        with patch("browser_session.sys.platform", "darwin"), patch("browser_session.Path.home", return_value=Path("/Users/test")):
            configure_browser_cache()
        self.assertEqual(os.environ["PLAYWRIGHT_BROWSERS_PATH"], "/Users/test/Library/Caches/ms-playwright")

    def test_windows_uses_local_app_data(self):
        with patch("browser_session.sys.platform", "win32"), patch.dict(os.environ, {"LOCALAPPDATA": "/Users/test/AppData/Local"}):
            configure_browser_cache()
            self.assertEqual(os.environ["PLAYWRIGHT_BROWSERS_PATH"], "/Users/test/AppData/Local/ms-playwright")

    def test_linux_uses_xdg_cache(self):
        with patch("browser_session.sys.platform", "linux"), patch.dict(os.environ, {"XDG_CACHE_HOME": "/tmp/custom-cache"}):
            configure_browser_cache()
            self.assertEqual(os.environ["PLAYWRIGHT_BROWSERS_PATH"], "/tmp/custom-cache/ms-playwright")

    def test_explicit_browser_location_is_preserved(self):
        for value in ("/tmp/custom-browsers", "0"):
            with self.subTest(value=value), patch.dict(os.environ, {"PLAYWRIGHT_BROWSERS_PATH": value}):
                configure_browser_cache()
                self.assertEqual(os.environ["PLAYWRIGHT_BROWSERS_PATH"], value)

    def test_source_runs_keep_playwright_defaults(self):
        with patch("browser_session.sys.frozen", False):
            configure_browser_cache()
        self.assertNotIn("PLAYWRIGHT_BROWSERS_PATH", os.environ)

    def test_first_launch_and_installer_share_the_cache_and_retry(self):
        observed_paths = []
        driver = MagicMock()
        context = MagicMock()
        driver.chromium.launch_persistent_context.side_effect = [
            RuntimeError("Executable doesn't exist at /bundle/.local-browsers/chrome"), context]

        def start():
            observed_paths.append(os.environ["PLAYWRIGHT_BROWSERS_PATH"])
            return driver

        manager = MagicMock()
        manager.start.side_effect = start
        with tempfile.TemporaryDirectory() as directory, patch("playwright.sync_api.sync_playwright", return_value=manager), patch("browser_session.subprocess.run") as install:
            sessions = BrowserSessions(headless=True)
            opened, created = sessions.get_context(Path(directory))
            cache = os.environ["PLAYWRIGHT_BROWSERS_PATH"]
            self.assertEqual(observed_paths, [cache])
            self.assertEqual(install.call_args.kwargs["env"]["PLAYWRIGHT_BROWSERS_PATH"], cache)
            self.assertEqual(install.call_args.args[0][-2:], ["install", "chromium"])
            self.assertTrue(created)
            self.assertIs(opened, context)
            self.assertEqual(driver.chromium.launch_persistent_context.call_count, 2)
            reused, created = sessions.get_context(Path(directory))
            self.assertIs(reused, context)
            self.assertFalse(created)
            install.assert_called_once()
            sessions.close()

    def test_failed_download_reports_an_actionable_error(self):
        driver = MagicMock()
        driver.chromium.launch_persistent_context.side_effect = RuntimeError("Executable doesn't exist")
        manager = MagicMock()
        manager.start.return_value = driver
        with tempfile.TemporaryDirectory() as directory, patch("playwright.sync_api.sync_playwright", return_value=manager), patch("browser_session.subprocess.run", side_effect=subprocess.CalledProcessError(1, "install")):
            sessions = BrowserSessions()
            with self.assertRaisesRegex(MergeError, "Check your internet connection"):
                sessions.get_context(Path(directory))
            self.assertEqual(sessions.contexts, {})
            sessions.close()

    def test_chrome_and_other_launch_errors_do_not_download_chromium(self):
        for channel, error, expected in (("chrome", "Executable doesn't exist", MergeError), (None, "Profile is locked", RuntimeError)):
            with self.subTest(channel=channel), tempfile.TemporaryDirectory() as directory, patch("playwright.sync_api.sync_playwright") as factory, patch("browser_session.subprocess.run") as install:
                driver = factory.return_value.start.return_value
                driver.chromium.launch_persistent_context.side_effect = RuntimeError(error)
                sessions = BrowserSessions()
                with self.assertRaises(expected):
                    sessions.get_context(Path(directory), channel)
                install.assert_not_called()
                sessions.close()


if __name__ == "__main__":
    unittest.main()
