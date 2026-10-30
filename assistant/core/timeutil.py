"""UTC time helpers. All backend event timestamps are UTC; browsers localize them for display."""
from datetime import datetime, timezone


def utc_now_iso():
    """Current instant as an ISO-8601 UTC string, e.g. 2026-10-28T09:50:59.954Z."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
