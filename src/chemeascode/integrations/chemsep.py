"""Download of a ChemSep data archive (http://www.chemsep.org) as bytes.

The standard library only. The caller passes the URL and checks the archive's sha256; ChemSep
serves its downloads over plain HTTP, so the checksum is what makes the download trustworthy.
Tests never call this: they build an archive and pass its bytes or path.
"""

from __future__ import annotations

import urllib.error
import urllib.request

from chemeascode.integrations.http import USER_AGENT, HttpError

#: Larger downloads are refused (ChemSep-LITE 8.50 is about 12 MB).
MAX_BYTES = 200 * 1024 * 1024


def download(url: str, *, timeout_s: float = 120.0, max_bytes: int = MAX_BYTES) -> bytes:
    """The body of a GET of *url*; :class:`HttpError` on no connection, an error status or a
    body larger than *max_bytes*."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as reply:
            body = reply.read(max_bytes + 1)
    except urllib.error.HTTPError as failure:
        raise HttpError(f"GET {url}: HTTP {failure.code}", url=url, status=failure.code) from None
    except (urllib.error.URLError, TimeoutError, OSError) as failure:
        raise HttpError(f"GET {url}: {failure}", url=url) from failure
    if len(body) > max_bytes:
        raise HttpError(f"GET {url}: larger than {max_bytes} bytes", url=url)
    return body
