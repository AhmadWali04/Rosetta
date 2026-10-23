"""GitHub external tool never fetches arbitrary URLs or follows redirects."""

import httpx
import pytest

from app.tools import github


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/user",
        "https://127.0.0.1/user",
        "https://github.com.evil/user",
        "https://github.com@evil/user",
        "https://github.com/user/repo",
        "https://github.com/",
        "https://github.com/user?redirect=evil",
        "https://github.com/user#fragment",
        "https://github.com:443/user",
        "https://github.com/../secret",
    ],
)
def test_rejects_non_profile_urls_without_network(monkeypatch, url):
    monkeypatch.setattr(github.httpx, "Client", lambda **kwargs: pytest.fail("network attempted"))
    with pytest.raises(ValueError):
        github.github_profile(url)


def test_fixed_api_host_bounded_repos_timeout_and_no_redirects(monkeypatch):
    calls = []
    real_client = httpx.Client

    def handler(request):
        calls.append(request)
        assert request.url.host == "api.github.com"
        if request.url.path.endswith("/repos"):
            return httpx.Response(
                200, json=[{"name": f"repo{i}", "language": "Python"} for i in range(20)]
            )
        return httpx.Response(200, json={"login": "user", "public_repos": 20})

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        assert kwargs["timeout"] == github.get_settings().github_timeout_s
        return real_client(**kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(github.httpx, "Client", client)
    result = github.github_profile("https://github.com/user")
    assert len(result["repositories"]) == github.get_settings().github_max_repos
    assert calls[1].url.params["per_page"] == str(github.get_settings().github_max_repos)


def test_redirect_response_is_not_followed(monkeypatch):
    real_client = httpx.Client
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/private"})

    monkeypatch.setattr(
        github.httpx,
        "Client",
        lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(httpx.HTTPStatusError):
        github.github_profile("https://github.com/user")
    assert len(calls) == 1
