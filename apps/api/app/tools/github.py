"""Bounded public GitHub lookup; supplied URLs never become request hosts."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.config import get_settings


def github_profile(url: str) -> dict[str, Any]:
    parts = urlsplit(url)
    username = parts.path.strip("/")
    if (parts.scheme != "https" or parts.netloc != "github.com" or parts.query or parts.fragment
            or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", username)):
        raise ValueError("Expected a public https://github.com/<username> profile")
    settings = get_settings()
    headers = {"Accept": "application/vnd.github+json"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    with httpx.Client(timeout=settings.github_timeout_s, follow_redirects=False,
                      headers=headers, trust_env=False) as client:
        response = client.get(f"https://api.github.com/users/{username}")
        response.raise_for_status()
        profile = response.json()
        repos_response = client.get(f"https://api.github.com/users/{username}/repos",
                                    params={"per_page": settings.github_max_repos,
                                            "sort": "updated"})
        repos_response.raise_for_status()
        repos = repos_response.json()
    return {"login": profile.get("login"), "public_repos": profile.get("public_repos"),
            "repositories": [{"name": repo.get("name"), "language": repo.get("language"),
                              "updated_at": repo.get("updated_at")}
                             for repo in repos[:settings.github_max_repos]]}
