"""Generate a VAPID keypair for Mira's Web Push briefings.

Run this once, then paste the two printed values into your environment (or the
Space's secrets):

  JARVIS_VAPID_PUBLIC_KEY   the browser's applicationServerKey
  JARVIS_VAPID_PRIVATE_KEY  the signing key pywebpush uses to send

Both are URL-safe base64 without padding. The public key is the uncompressed
P-256 point; the private key is the raw 32-byte scalar — exactly the forms the
Push API (front-end) and pywebpush (server) expect.

Must be run somewhere `pywebpush` / `cryptography` are installed (they ship in
requirements-web.txt). It needs no network and writes nothing — it only prints.
"""

from __future__ import annotations

import base64
import sys


def _b64url(raw: bytes) -> str:
    """URL-safe base64 with the padding stripped, as the Web Push specs want."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def main() -> int:
    try:
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization
    except ImportError:
        print(
            "cryptography isn't installed. Run this where the web extras are "
            "available, e.g.: pip install -r requirements-web.txt",
            file=sys.stderr,
        )
        return 1

    private_key = ec.generate_private_key(ec.SECP256R1())

    # The applicationServerKey is the uncompressed public point (65 bytes:
    # 0x04 || X || Y), URL-safe base64 encoded.
    public_point = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )

    # pywebpush accepts the private key as the raw 32-byte big-endian scalar,
    # URL-safe base64 encoded.
    private_scalar = private_key.private_numbers().private_value.to_bytes(32, "big")

    print(f"JARVIS_VAPID_PUBLIC_KEY={_b64url(public_point)}")
    print(f"JARVIS_VAPID_PRIVATE_KEY={_b64url(private_scalar)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
