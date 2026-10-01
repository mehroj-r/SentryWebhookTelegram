from src.config import settings


def test_admin_ids_comma_separated():
    assert settings.admin_ids == [1, 2]


def test_base_url_trailing_slash_stripped():
    assert settings.webhook_base_url == "https://example.test"
