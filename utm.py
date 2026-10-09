"""Pure UTM logic — no Telegram, no Google. Kept separate so it can be tested."""
import re
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from zoneinfo import ZoneInfo

SGT = ZoneInfo("Asia/Singapore")

# Edit these lists to change the buttons. Values are what lands in the URL.
SOURCES = ["telegram", "whatsapp", "linkedin", "facebook", "instagram", "x", "reddit", "email"]
MEDIUMS = ["social", "messaging", "email", "referral", "outreach"]

URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


class BadURL(ValueError):
    pass


def find_url(text: str | None) -> str | None:
    if not text:
        return None
    m = URL_RE.search(text)
    return m.group(0).rstrip(").,;!?»”'\"") if m else None


def check_url(url: str, allowed_hosts: set[str]) -> str:
    """Return a cleaned https URL or raise BadURL."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not host:
        raise BadURL("That doesn't look like a link.")
    if host not in allowed_hosts:
        raise BadURL(f"Only Unpacked links are allowed ({', '.join(sorted(allowed_hosts))}).")
    return urlunsplit(("https", host, parts.path, parts.query, ""))


def normalise(value: str) -> str:
    """Lowercase, spaces/underscores → hyphens, drop anything else odd."""
    v = value.strip().lower()
    v = re.sub(r"[\s_]+", "-", v)
    v = re.sub(r"[^a-z0-9.-]", "", v)
    v = re.sub(r"-{2,}", "-", v).strip("-.")
    return v[:40]


def slug_for(url: str) -> str:
    path = urlsplit(url).path.strip("/")
    if not path:
        return "homepage"
    parts = path.split("/")
    if parts[0] == "p" and len(parts) > 1:
        return normalise(parts[1]) or "post"
    return normalise(parts[-1]) or "page"


def campaign_for(url: str, now: datetime | None = None) -> str:
    now = now or datetime.now(SGT)
    return f"{slug_for(url)}-{now.astimezone(SGT):%Y%m%d}"


def build(url: str, source: str, medium: str, campaign: str) -> str:
    parts = urlsplit(url)
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not k.lower().startswith("utm_")]
    kept += [("utm_source", source), ("utm_medium", medium), ("utm_campaign", campaign)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), ""))
