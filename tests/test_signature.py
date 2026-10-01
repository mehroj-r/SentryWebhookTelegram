import hashlib
import hmac

from src.sentry.signature import verify_signature


def test_valid_signature():
    body = b'{"a": 1}'
    sig = hmac.new(b"sentry_secret", body, hashlib.sha256).hexdigest()
    assert verify_signature(body, sig, "sentry_secret")


def test_invalid_or_missing_signature():
    body = b'{"a": 1}'
    assert not verify_signature(body, "deadbeef", "sentry_secret")
    assert not verify_signature(body, "", "sentry_secret")
