"""GitHub issues of a repository, read with the REST API (read-only).

The token comes from the caller, else ``GITHUB_TOKEN`` or ``GH_TOKEN``, else ``gh auth token``
(the GitHub CLI), and it is only ever sent to :data:`API` (the endpoint is not configurable, so
a plant file cannot direct it elsewhere), with redirects not followed. Pull requests, which the
issues endpoint also returns, are left out.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from functools import partial
from typing import Any

from chemeascode.integrations.http import (
    HttpClient,
    HttpError,
    no_redirect_opener,
    urllib_transport,
)

API = "https://api.github.com"
PER_PAGE = 100
MAX_PAGES = 20


class GitHubError(RuntimeError):
    """The issues cannot be read: no token, no network, or the API refused."""


def token() -> str | None:
    """A GitHub token from the environment or the GitHub CLI, or None."""
    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    gh = shutil.which("gh")
    if gh is None:
        return None
    try:
        run = subprocess.run(
            [gh, "auth", "token"], check=False, capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if run.returncode != 0:
        return None
    return run.stdout.strip() or None


def list_issues(
    repository: str,
    label: str,
    *,
    access_token: str | None = None,
    client: HttpClient | None = None,
) -> list[dict[str, Any]]:
    """Every issue of *repository* labelled *label*, open and closed, as the API returns them.
    Raises :class:`GitHubError` rather than return a partial list."""
    access_token = access_token or token()
    if not access_token:
        raise GitHubError("no GitHub token: set GITHUB_TOKEN or log in with `gh auth login`")
    client = client or HttpClient(
        transport=partial(urllib_transport, opener=no_redirect_opener()), attempts=2
    )
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    found: list[dict[str, Any]] = []
    for page in range(1, MAX_PAGES + 1):
        try:
            response = client.get(
                f"{API}/repos/{repository}/issues",
                {"labels": label, "state": "all", "per_page": PER_PAGE, "page": page},
                headers=headers,
            )
        except HttpError as failure:
            raise GitHubError(f"{repository}: {failure}") from failure
        if response.status >= 300:
            raise GitHubError(
                f"{repository}: HTTP {response.status} (moved or renamed? check plant.yaml issues)"
            )
        batch = response.json()
        if not isinstance(batch, list):
            raise GitHubError(f"{repository}: unexpected answer {str(batch)[:120]}")
        found += [item for item in batch if "pull_request" not in item]
        if len(batch) < PER_PAGE:
            return found
    raise GitHubError(f"{repository}: more than {MAX_PAGES * PER_PAGE} issues labelled {label}")
