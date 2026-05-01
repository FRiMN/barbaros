from barbaros.common import is_valid_url
import pytest

@pytest.mark.parametrize("url", [
    "http://google.com",
    "https://google.com",
    "http://localhost",
    "http://localhost:8080",
    "https://api.openai.com/v1",
    "http://127.0.0.1",
    "http://192.168.0.1:1234",
])
def test_is_valid_url_valid(url):
    assert is_valid_url(url) is True

@pytest.mark.parametrize("url", [
    "",
    None,
    "google.com",
    "http://",
    "ftp://google.com",
    "http://.com",
    "http://-google.com",
    "http://256.256.256.256",
])
def test_is_valid_url_invalid(url):
    assert is_valid_url(url) is False
