"""Timezone-aware, cancellable scheduling while the desktop app stays open."""
from datetime import datetime, timezone
import json
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from merge_core import MergeError


DEFAULT_ZONE = "UTC"
MAX_LATENESS_SECONDS = 120


def utc_now():
    return datetime.now(timezone.utc)


def parse_schedule(date_text, time_text, zone_name, now=None):
    try:
        local = datetime.strptime(f"{date_text.strip()} {time_text.strip()}", "%Y-%m-%d %H:%M")
    except ValueError as exc:
        raise MergeError("Enter a date as YYYY-MM-DD and a 24-hour time as HH:MM.") from exc
    try:
        zone = ZoneInfo(zone_name.strip())
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise MergeError("Choose a valid timezone, such as America/Chicago or UTC.") from exc
    candidates = []
    for fold in (0, 1):
        candidate = local.replace(tzinfo=zone, fold=fold)
        # A nonexistent spring-forward time changes when converted back.
        if candidate.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) == local:
            if all(candidate.utcoffset() != c.utcoffset() for c in candidates):
                candidates.append(candidate)
    if not candidates:
        raise MergeError("That local time does not exist because of a daylight-saving change. Choose another time.")
    if len(candidates) > 1:
        raise MergeError("That local time occurs twice because of a daylight-saving change. Choose another time or use UTC.")
    when = candidates[0]
    if when.astimezone(timezone.utc) <= (now or utc_now()):
        raise MergeError("Choose a scheduled time in the future.")
    return when


def schedule_label(when):
    return when.strftime("%Y-%m-%d at %H:%M %Z") + f" ({when.tzinfo})"


def wait_for_schedule(when, stop, log, now=utc_now):
    """Return False on cancellation; never catch up silently after a long sleep."""
    target = when.astimezone(timezone.utc)
    remaining = (target - now()).total_seconds()
    if remaining <= 0:
        raise MergeError("The scheduled time passed before the batch was approved. Choose a new time.")
    log(f"Scheduled for {schedule_label(when)}. Keep this app, browser and computer awake. Stop cancels the timer.")
    while True:
        if stop.is_set():
            return False
        remaining = (target - now()).total_seconds()
        if remaining <= 0:
            if -remaining > MAX_LATENESS_SECONDS:
                raise MergeError("The scheduled time was missed by more than two minutes. Nothing was sent by this timer. Choose a new time.")
            return True
        if stop.wait(min(remaining, 1)):
            return False


class ScheduleRecord:
    """A durable status record; restarting the app never automatically sends."""
    def __init__(self, path, when, campaign, count):
        self.path = Path(path)
        self.data = {"scheduled_at": when.isoformat(), "timezone": str(when.tzinfo),
                     "campaign": campaign, "recipient_count": count}

    def update(self, status, detail=""):
        self.data.update(status=status, detail=detail, updated=utc_now().isoformat())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.data, indent=2) + "\n", encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(self.path)
