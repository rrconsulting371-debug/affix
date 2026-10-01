"""fetch_with_retry: public URL fetch with retries, backoff, and robots.txt respect.

PLACEHOLDER IMPLEMENTATION written from the spec's description of the WealthForge
pattern. Replace with the real WealthForge fetch_with_retry() when the repo is
available; the real code wins where they differ (spec §0).
"""
from __future__ import annotations

import time
import urllib.robotparser
from dataclasses import dataclass
from urllib.parse import urlparse

from . import audit

USER_AGENT = "AffixBot/0.1 (+mailto:bri@getrrconsulting.com)"
LOGIN_MARKERS = ("submittable.com", "fluxx.io", "foundant", "/login", "/signin", "/sign-in")


class FetchError(RuntimeError):
    pass


class LoginRequired(FetchError):
    """Raised for gated portals. Bri must download the application manually (spec §5.1)."""


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    content: bytes
    content_type: str


def robots_allowed(url: str) -> bool:
    parts = urlparse(url)
    rp = urllib.robotparser.RobotFileParser(f"{parts.scheme}://{parts.netloc}/robots.txt")
    try:
        rp.read()
    except Exception:
        return True  # unreachable robots.txt: treat as allowed, as most crawlers do
    return rp.can_fetch(USER_AGENT, url)


def fetch_with_retry(url: str, retries: int = 3, backoff: float = 2.0, timeout: float = 30.0,
                     check_robots: bool = True) -> FetchResult:
    if any(m in url.lower() for m in LOGIN_MARKERS):
        raise LoginRequired(f"{url} looks like a login-gated portal; download the application manually.")
    if check_robots and not robots_allowed(url):
        raise FetchError(f"robots.txt disallows fetching {url}")

    import httpx  # imported lazily so the CLI runs without network deps installed

    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with httpx.Client(follow_redirects=True, timeout=timeout,
                              headers={"User-Agent": USER_AGENT}) as client:
                r = client.get(url)
            if any(m in str(r.url).lower() for m in LOGIN_MARKERS):
                raise LoginRequired(f"{url} redirected to a login page; download the application manually.")
            if r.status_code in (401, 403):
                raise LoginRequired(f"{url} returned {r.status_code}; it may require a login.")
            if r.status_code >= 500 or r.status_code == 429:
                raise FetchError(f"HTTP {r.status_code}")
            r.raise_for_status()
            audit.log("system", action="fetch", url=url, status=r.status_code, attempt=attempt)
            return FetchResult(url, str(r.url), r.status_code, r.content,
                               r.headers.get("content-type", ""))
        except LoginRequired:
            raise
        except Exception as e:  # network errors and retryable statuses
            last_err = e
            if attempt < retries:
                time.sleep(backoff ** attempt)
    audit.log("system", action="fetch_failed", url=url, error=str(last_err))
    raise FetchError(f"Failed to fetch {url} after {retries} attempts: {last_err}")
