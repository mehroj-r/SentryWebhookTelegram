from __future__ import annotations

import hashlib
import hmac


def verify_signature(raw_body: bytes, signature_header: str, client_secret: str) -> bool:
    """
    Verify a Sentry-Hook-Signature header.

    Sentry computes the signature as HMAC-SHA256 of the raw JSON body
    keyed with the integration's Client Secret.
    """
    if not signature_header:
        return False
    expected = hmac.new(
        client_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)
