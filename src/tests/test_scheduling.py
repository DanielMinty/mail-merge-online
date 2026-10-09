from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from merge_core import MergeError
from scheduling import ScheduleRecord, parse_schedule, wait_for_schedule


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class FakeClock:
    def __init__(self, now, jump=None, cancel=False):
        self.current = now
        self.jump = jump
        self.cancel = cancel

    def now(self):
        return self.current

    def is_set(self):
        return self.cancel

    def wait(self, seconds):
        self.current += timedelta(seconds=self.jump or seconds)
        return self.cancel


class SchedulingTests(unittest.TestCase):
    def test_chicago_date_is_converted_with_the_correct_offset(self):
        winter = parse_schedule("2026-01-02", "09:00", "America/Chicago", NOW)
        summer = parse_schedule("2026-07-02", "09:00", "America/Chicago", NOW)
        self.assertEqual(winter.astimezone(timezone.utc).hour, 15)
        self.assertEqual(summer.astimezone(timezone.utc).hour, 14)

    def test_past_dates_are_rejected(self):
        with self.assertRaisesRegex(MergeError, "future"):
            parse_schedule("2025-12-01", "09:00", "UTC", NOW)

    def test_bad_date_time_or_zone_are_rejected(self):
        for date, clock, zone in (("tomorrow", "09:00", "UTC"), ("2026-07-02", "25:00", "UTC"),
                                  ("2026-07-02", "09:00", "Unknown/Zone")):
            with self.subTest(zone=zone, clock=clock), self.assertRaises(MergeError):
                parse_schedule(date, clock, zone, NOW)

    def test_nonexistent_spring_time_is_rejected(self):
        with self.assertRaisesRegex(MergeError, "does not exist"):
            parse_schedule("2026-03-08", "02:30", "America/Chicago", NOW)

    def test_ambiguous_autumn_time_is_rejected(self):
        with self.assertRaisesRegex(MergeError, "occurs twice"):
            parse_schedule("2026-11-01", "01:30", "America/Chicago", NOW)

    def test_timer_waits_until_target_and_reports_time(self):
        clock = FakeClock(NOW)
        target = NOW + timedelta(seconds=3)
        logs = []
        self.assertTrue(wait_for_schedule(target, clock, logs.append, clock.now))
        self.assertEqual(clock.current, target)
        self.assertIn("Keep this app", logs[0])

    def test_stop_cancels_the_timer(self):
        clock = FakeClock(NOW, cancel=True)
        self.assertFalse(wait_for_schedule(NOW + timedelta(seconds=3), clock, lambda _: None, clock.now))

    def test_computer_waking_late_does_not_send(self):
        clock = FakeClock(NOW, jump=180)
        with self.assertRaisesRegex(MergeError, "missed"):
            wait_for_schedule(NOW + timedelta(seconds=3), clock, lambda _: None, clock.now)

    def test_approval_after_target_requires_a_new_time(self):
        clock = FakeClock(NOW)
        with self.assertRaisesRegex(MergeError, "passed"):
            wait_for_schedule(NOW, clock, lambda _: None, clock.now)

    def test_schedule_status_is_saved_with_timezone_and_campaign(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedule.json"
            record = ScheduleRecord(path, NOW, "campaign", 3)
            record.update("waiting")
            self.assertEqual(json.loads(path.read_text())["status"], "waiting")
            record.update("cancelled", "Stopped by user")
            saved = json.loads(path.read_text())
            self.assertEqual(saved["campaign"], "campaign")
            self.assertEqual(saved["recipient_count"], 3)
            self.assertEqual(saved["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
