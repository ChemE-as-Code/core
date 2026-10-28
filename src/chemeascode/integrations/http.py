"""HTTP for the web adapters (PubChem, CACTUS, NIST, OSHA, DDBST, GRAPPA, HANNA, RMG).

The standard library only, so no adapter needs an extra for its transport. Every adapter takes an
:class:`HttpClient`; tests pass one with a fake ``transport`` and never touch the network. No
module reads an API key or an endpoint from the environment: the caller passes them.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

#: Statuses worth retrying: rate limits and transient server failures.
RETRY_STATUSES = frozenset({429, 502, 503, 504})
USER_AGENT = "cheme-as-code (https://github.com/process-intelligence-research)"


@dataclass(frozen=True)
class Request:
    method: str
    url: str
    """With the query string already appended."""
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes | None = None
    timeout_s: float = 30.0


@dataclass(frozen=True)
class Response:
    status: int
    text: str
    url: str

    def json(self) -> Any:
        return json.loads(self.text)


class HttpError(RuntimeError):
    """A request failed: no connection, or an error status after the retries."""

    def __init__(self, message: str, *, url: str, status: int | None = None) -> None:
        super().__init__(message)
        self.url = url
        self.status = status


Transport = Callable[[Request], Response]


def urllib_transport(
    request: Request, *, opener: urllib.request.OpenerDirector | None = None
) -> Response:
    """Send *request* with :mod:`urllib`; an error status is returned, not raised. *opener*
    replaces urllib's default one (e.g. :func:`no_redirect_opener`)."""
    raw = urllib.request.Request(
        request.url, data=request.body, headers=dict(request.headers), method=request.method
    )
    open_ = opener.open if opener is not None else urllib.request.urlopen
    try:
        with open_(raw, timeout=request.timeout_s) as reply:
            charset = reply.headers.get_content_charset() or "utf-8"
            return Response(reply.status, reply.read().decode(charset, "replace"), reply.url)
    except urllib.error.HTTPError as failure:
        with failure:
            text = failure.read().decode("utf-8", "replace") if failure.fp else ""
        return Response(failure.code, text, request.url)
    except (urllib.error.URLError, TimeoutError, OSError) as failure:
        raise HttpError(f"{request.method} {request.url}: {failure}", url=request.url) from failure


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None  # the 3xx comes back as the response


def no_redirect_opener() -> urllib.request.OpenerDirector:
    """An opener that returns a redirect instead of following it: urllib would send the
    request's headers, an Authorization among them, on to the new host."""
    return urllib.request.build_opener(_NoRedirect)


def with_query(url: str, params: Mapping[str, Any] | None) -> str:
    if not params:
        return url
    return f"{url}{'&' if '?' in url else '?'}{urllib.parse.urlencode(params)}"


@dataclass
class HttpClient:
    """GET/POST with retries on :data:`RETRY_STATUSES` and connection failures.

    ``raise_for_status`` (default) turns a final status >= 400 into :class:`HttpError`; pass
    ``False`` to a call to read the error page instead (CACTUS answers 404 for "not found").
    """

    transport: Transport = urllib_transport
    attempts: int = 3
    backoff_s: float = 0.5
    user_agent: str = USER_AGENT
    sleep: Callable[[float], None] = time.sleep

    def get(
        self,
        url: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout_s: float = 30.0,
        raise_for_status: bool = True,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        """*headers* are added to the client's own (e.g. an Authorization the caller holds)."""
        merged = {**self._headers(), **(headers or {})}
        request = Request("GET", with_query(url, params), merged, None, timeout_s)
        return self._send(request, raise_for_status)

    def post_form(
        self,
        url: str,
        data: Mapping[str, Any],
        params: Mapping[str, Any] | None = None,
        *,
        timeout_s: float = 30.0,
    ) -> Response:
        headers = {**self._headers(), "Content-Type": "application/x-www-form-urlencoded"}
        body = urllib.parse.urlencode(data).encode()
        return self._send(Request("POST", with_query(url, params), headers, body, timeout_s), True)

    def post_json(self, url: str, payload: Any, *, timeout_s: float = 60.0) -> Response:
        headers = {**self._headers(), "Content-Type": "application/json"}
        body = json.dumps(payload).encode()
        return self._send(Request("POST", url, headers, body, timeout_s), True)

    def _headers(self) -> dict[str, str]:
        return {"User-Agent": self.user_agent, "Accept": "application/json, text/html, */*"}

    def _send(self, request: Request, raise_for_status: bool) -> Response:
        for attempt in range(1, self.attempts + 1):
            last = attempt == self.attempts
            try:
                response = self.transport(request)
            except HttpError:
                if last:
                    raise
                self.sleep(self.backoff_s * attempt)
                continue
            if response.status in RETRY_STATUSES and not last:
                self.sleep(self.backoff_s * attempt)
                continue
            if raise_for_status and response.status >= 400:
                raise HttpError(
                    f"{request.method} {request.url}: HTTP {response.status}",
                    url=request.url,
                    status=response.status,
                )
            return response
        raise AssertionError("unreachable")
