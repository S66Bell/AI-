"""Optional Web Push (VAPID) delivery for JARVIS.

Mira can push a proactive briefing — today's agenda plus any due reminders — to
the phone even when the app isn't open, via the browser's Push API. Delivery
needs a VAPID keypair (JARVIS_VAPID_PUBLIC_KEY / JARVIS_VAPID_PRIVATE_KEY;
generate one with scripts/gen_vapid.py) and the `pywebpush` library, which the
web image installs.

Like persistence.py and gcal.py, this is entirely optional and degradable: if
either key is missing, or pywebpush isn't installed, push is silently disabled
and the app behaves exactly as before.

Note on the payload: today the briefing is a templated JSON string composed at
the call site (server.send_briefing → persona.build_briefing). That's the seam
where an LLM-written summary could be swapped in later without touching this
transport.
"""

from __future__ import annotations


class PushClient:
    def __init__(self, config) -> None:
        self.vapid_private_key = config.vapid_private_key
        self.vapid_claims = {"sub": config.vapid_subject}

    @classmethod
    def from_config(cls, config) -> "PushClient | None":
        """Build from config, or return None if push isn't configured / usable."""
        if not (config.vapid_public_key and config.vapid_private_key):
            return None
        try:
            import pywebpush  # noqa: F401
        except ImportError:
            print("[push] pywebpush not installed; skipping.")
            return None
        return cls(config)

    def send(self, subscription_info: dict, payload: str) -> "str | bool":
        """Deliver one push. Returns True on success, "gone" when the endpoint
        is dead (404/410 — the subscription should be pruned), and False on any
        other failure (which we log but otherwise tolerate)."""
        from pywebpush import webpush, WebPushException  # lazy; optional dep

        try:
            webpush(
                subscription_info=subscription_info,
                data=payload,
                vapid_private_key=self.vapid_private_key,
                vapid_claims=dict(self.vapid_claims),
            )
            return True
        except WebPushException as exc:
            if exc.response is not None and exc.response.status_code in (404, 410):
                return "gone"
            print(f"[push] send failed ({exc})")
            return False
