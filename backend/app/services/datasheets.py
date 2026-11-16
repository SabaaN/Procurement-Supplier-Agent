"""Downloads a product's datasheet PDF so the browser can save it as a file.

The URL was found on a web page, so it is untrusted: only public http(s) addresses are fetched
(every redirect is checked too), only real PDFs are returned, and the size is capped.
"""
import ipaddress
import re
import socket
from urllib.parse import unquote, urljoin, urlsplit

import httpx

from ..config import settings

MAX_BYTES = 25_000_000
MAX_REDIRECTS = 5


class DatasheetError(RuntimeError):
    """The datasheet could not be downloaded; the message is safe to show the user."""


def _resolve(host: str) -> list[str]:  # a function so tests can fake DNS
    return [info[4][0] for info in socket.getaddrinfo(host, None)]


def _check_public(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise DatasheetError("Datasheet link is not a web address")
    try:
        addresses = _resolve(parts.hostname)
    except OSError:
        raise DatasheetError(f"Could not reach {parts.hostname}")
    for addr in addresses:
        ip = ipaddress.ip_address(addr.split("%")[0])
        if not ip.is_global:
            raise DatasheetError("Datasheet link points to a private address; not downloaded")


def filename_for(url: str, title: str | None) -> str:
    """A safe file name: the PDF's own name if it has one, else one made from the product title."""
    name = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
    if not name.lower().endswith(".pdf"):
        name = f"{title or 'product'}-datasheet.pdf"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", name[:-4]).strip("-._")[:80] or "datasheet"
    return f"{stem}.pdf"


def download(url: str, client: httpx.Client | None = None) -> bytes:
    """The PDF's bytes. Raises DatasheetError with a readable reason."""
    own = client is None
    client = client or httpx.Client(
        timeout=settings.fetch_timeout * 2,
        follow_redirects=False,  # redirects are followed by hand so each hop is checked
        headers={"User-Agent": settings.user_agent, "Accept": "application/pdf,*/*;q=0.5"},
    )
    try:
        for _ in range(MAX_REDIRECTS + 1):
            _check_public(url)
            with client.stream("GET", url) as resp:
                if resp.is_redirect and resp.headers.get("location"):
                    url = urljoin(url, resp.headers["location"])
                    continue
                if resp.status_code != 200:
                    raise DatasheetError(f"Supplier site answered HTTP {resp.status_code}")
                ctype = resp.headers.get("content-type", "").lower()
                if "html" in ctype:
                    raise DatasheetError("The datasheet link opens a web page, not a PDF")
                data = bytearray()
                for chunk in resp.iter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_BYTES:
                        raise DatasheetError("Datasheet is larger than 25 MB")
            if not bytes(data[:1024]).lstrip().startswith(b"%PDF"):
                raise DatasheetError("The file at the datasheet link is not a PDF")
            return bytes(data)
        raise DatasheetError("Too many redirects")
    except httpx.TimeoutException:
        raise DatasheetError("Supplier site timed out")
    except httpx.HTTPError as e:
        raise DatasheetError(f"Download failed: {type(e).__name__}")
    finally:
        if own:
            client.close()
