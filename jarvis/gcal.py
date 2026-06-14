"""Optional Google Calendar integration for JARVIS.

Mira can read the day's agenda (to fold into the opening greeting) and create,
update, or delete events on a real Google Calendar. We authenticate with a
*service account*: you create one in the Google Cloud console, download its JSON
key, and share the target calendar with the service account's email. The key is
supplied via JARVIS_GCAL_CREDENTIALS — either the inline JSON string or a path
to the key file — and the calendar via JARVIS_GCAL_ID (default "primary").

Like persistence.py, this is entirely optional and degradable: if the key is
missing, or the google libraries aren't installed, every calendar feature is
silently disabled and JARVIS behaves exactly as before.

Note on drift: we only push *one way* (reminders → calendar). Events created or
deleted directly in Google Calendar are not mirrored back into reminders.
"""

from __future__ import annotations

import json
from datetime import datetime, time, timedelta

# OAuth scope granting read/write on the user's calendars.
SCOPES = ["https://www.googleapis.com/auth/calendar"]


class CalendarClient:
    def __init__(self, config) -> None:
        from google.oauth2 import service_account  # lazy; optional dependency
        from googleapiclient.discovery import build

        self.config = config
        self.calendar_id = config.gcal_id

        # The key is either inline JSON or a path to the key file; detect which.
        raw = config.gcal_credentials
        if raw.strip().startswith("{"):
            info = json.loads(raw)
            creds = service_account.Credentials.from_service_account_info(
                info, scopes=SCOPES
            )
        else:
            creds = service_account.Credentials.from_service_account_file(
                raw, scopes=SCOPES
            )
        # cache_discovery=False avoids a noisy warning and a useless on-disk cache.
        self.service = build("calendar", "v3", credentials=creds, cache_discovery=False)

    @classmethod
    def from_config(cls, config) -> "CalendarClient | None":
        """Build from config, or return None if not configured / unavailable."""
        if not config.gcal_credentials:
            return None
        try:
            import google.oauth2.service_account  # noqa: F401
            import googleapiclient.discovery  # noqa: F401
        except ImportError:
            print("[gcal] google libs not installed; skipping.")
            return None
        try:
            inst = cls(config)
        except Exception as exc:  # bad key / parse error / auth failure
            print(f"[gcal] disabled ({exc}).")
            return None
        if inst.calendar_id == "primary":
            print(
                "[gcal] using 'primary' — to use your own calendar, share it "
                "with the service account and set JARVIS_GCAL_ID to its id."
            )
        return inst

    # ── reading ─────────────────────────────────────────────────────────
    def _parse_when(self, value: str) -> datetime:
        """Parse an RFC3339 datetime or a bare YYYY-MM-DD (all-day) into a
        timezone-aware datetime, attaching `config.tz` when none is present."""
        # RFC3339 uses a trailing 'Z' for UTC, which fromisoformat rejected on
        # older Pythons; normalise it to an explicit offset.
        text = value.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            # Bare date (all-day event): midnight in the configured zone.
            dt = datetime.fromisoformat(text + "T00:00:00")
        if dt.tzinfo is None and self.config.tz is not None:
            dt = dt.replace(tzinfo=self.config.tz)
        return dt

    def list_events(
        self, time_min: datetime, time_max: datetime, max_results: int = 25
    ) -> list[dict]:
        """Events overlapping [time_min, time_max), normalised to plain dicts."""
        resp = (
            self.service.events()
            .list(
                calendarId=self.calendar_id,
                timeMin=time_min.isoformat(),
                timeMax=time_max.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                maxResults=max_results,
            )
            .execute()
        )
        out = []
        for ev in resp.get("items", []):
            start_raw = ev.get("start", {})
            end_raw = ev.get("end", {})
            # All-day events carry a "date"; timed events carry a "dateTime".
            all_day = "date" in start_raw
            start_val = start_raw.get("dateTime") or start_raw.get("date")
            end_val = end_raw.get("dateTime") or end_raw.get("date")
            out.append(
                {
                    "id": ev.get("id"),
                    "summary": ev.get("summary", "(no title)"),
                    "start": self._parse_when(start_val) if start_val else None,
                    "end": self._parse_when(end_val) if end_val else None,
                    "all_day": all_day,
                }
            )
        return out

    def today_events(self) -> list[dict]:
        """Today's events in the configured timezone. Wrapped so a calendar or
        network hiccup never breaks the greeting — we just show no agenda."""
        try:
            now = self.config.now()
            tz = now.tzinfo
            start = datetime.combine(now.date(), time.min, tzinfo=tz)
            end = start + timedelta(days=1)
            return self.list_events(start, end)
        except Exception as exc:
            print(f"[gcal] could not fetch today's events: {exc}")
            return []

    # ── writing ─────────────────────────────────────────────────────────
    def _when(self, dt: datetime) -> dict:
        """Build a Calendar API time object. The RFC3339 offset from isoformat()
        already pins the instant, so we only attach an explicit timeZone when one
        is configured — never send timeZone: null (Google rejects it)."""
        when = {"dateTime": dt.isoformat()}
        if self.config.timezone:
            when["timeZone"] = self.config.timezone
        return when

    def create_event(
        self,
        summary: str,
        start: datetime,
        end: datetime | None = None,
        description: str = "",
    ) -> dict:
        if end is None:
            end = start + timedelta(hours=1)
        body = {
            "summary": summary,
            "description": description,
            "start": self._when(start),
            "end": self._when(end),
        }
        ev = (
            self.service.events()
            .insert(calendarId=self.calendar_id, body=body)
            .execute()
        )
        return {
            "id": ev.get("id"),
            "htmlLink": ev.get("htmlLink"),
            "summary": ev.get("summary"),
            "start": ev.get("start"),
        }

    def update_event(self, event_id: str, **fields) -> dict:
        """Patch selected fields on an event. Accepts summary / description as
        plain strings, and start / end as datetimes (sent with the config tz)."""
        body: dict = {}
        if "summary" in fields and fields["summary"] is not None:
            body["summary"] = fields["summary"]
        if "description" in fields and fields["description"] is not None:
            body["description"] = fields["description"]
        if fields.get("start") is not None:
            body["start"] = self._when(fields["start"])
        if fields.get("end") is not None:
            body["end"] = self._when(fields["end"])
        ev = (
            self.service.events()
            .patch(calendarId=self.calendar_id, eventId=event_id, body=body)
            .execute()
        )
        return {
            "id": ev.get("id"),
            "htmlLink": ev.get("htmlLink"),
            "summary": ev.get("summary"),
            "start": ev.get("start"),
        }

    def delete_event(self, event_id: str) -> None:
        """Delete an event, swallowing 404/410 so cancel-sync stays idempotent —
        an event the user already removed simply isn't there to delete again."""
        from googleapiclient.errors import HttpError

        try:
            self.service.events().delete(
                calendarId=self.calendar_id, eventId=event_id
            ).execute()
        except HttpError as exc:
            if getattr(exc, "resp", None) is not None and exc.resp.status in (404, 410):
                return
            raise
