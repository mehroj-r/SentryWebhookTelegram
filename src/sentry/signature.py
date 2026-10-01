from __future__ import annotations

import hashlib
import hmac
from typing import Mapping, Optional


def _digest(raw_body: bytes, client_secret: str) -> str:
    return hmac.new(client_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


def verify_signature(raw_body: bytes, signature_header: str, client_secret: str) -> bool:
    """
    Verify a Sentry-Hook-Signature header.

    Sentry computes the signature as HMAC-SHA256 of the raw JSON body
    keyed with the integration's Client Secret.
    """
    if not signature_header or not client_secret:
        return False
    return hmac.compare_digest(_digest(raw_body, client_secret), signature_header.strip().lower())


def verify_any(
    raw_body: bytes, signature_header: str, secrets: Mapping[str, str]
) -> Optional[str]:
    """
    Try every configured client secret; return the label of the one that
    matches, or None. Labels identify the Sentry organisation / integration
    the hook came from, which multi-org deployments use for routing.
    """
    if not signature_header:
        return None
    for label, secret in secrets.items():
        if secret and verify_signature(raw_body, signature_header, secret):
            return label
    return None
