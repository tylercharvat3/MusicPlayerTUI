import hashlib
import re
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx


class NavidromeError(Exception):
    pass


@dataclass
class Artist:
    id: str
    name: str


@dataclass
class Album:
    id: str
    name: str
    artist: str


@dataclass
class Song:
    id: str
    title: str
    artist: str
    album: str
    duration: float
    cover_id: str | None


def normalize_base_url(url: str) -> str:
    """Clean up a user-supplied server URL.

    Handles stray quotes/whitespace, a missing scheme, and URLs copied from the
    browser such as http://host:4533/app/ or http://host:4533/rest/.
    """
    url = url.strip().strip("\"'\u201c\u201d\u2018\u2019").strip()
    if "://" not in url:
        url = "http://" + url
    parts = urlsplit(url)
    path = parts.path.rstrip("/")
    changed = True
    while changed:
        changed = False
        for suffix in ("/app", "/rest"):
            if path.lower().endswith(suffix):
                path = path[: -len(suffix)].rstrip("/")
                changed = True
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def redact(url) -> str:
    """Hide auth values so URLs are safe to show in error messages."""
    return re.sub(r"([?&](?:t|s|p)=)[^&]+", r"\1***", str(url))


class NavidromeClient:
    def __init__(self, base_url: str, user: str, password: str) -> None:
        self.base_url = normalize_base_url(base_url)
        self.user = user
        self.password = password
        self._http = httpx.Client(timeout=10, follow_redirects=True)

    def _auth(self) -> dict:
        # Subsonic token auth: md5(password + random salt), so the password isn't sent
        salt = secrets.token_hex(8)
        token = hashlib.md5((self.password + salt).encode()).hexdigest()
        return {"u": self.user, "t": token, "s": salt,
                "v": "1.16.1", "c": "textual-music", "f": "json"}

    def _get(self, endpoint: str, **params) -> dict:
        url = f"{self.base_url}/rest/{endpoint}"
        r = self._http.get(url, params={**self._auth(), **params})

        if r.status_code >= 400:
            raise NavidromeError(
                f"HTTP {r.status_code} from {redact(r.url)}: {r.text[:120]!r}"
            )
        try:
            data = r.json()["subsonic-response"]
        except (ValueError, KeyError, TypeError):
            hops = " -> ".join(redact(h.url) for h in r.history)
            raise NavidromeError(
                f"Not a Subsonic API response. Requested {url}, ended at "
                f"{redact(r.url)} (HTTP {r.status_code}, "
                f"{r.headers.get('content-type')}). "
                f"Redirects: {hops or 'none'}. Body: {r.text[:120]!r}"
            )
        if data["status"] != "ok":
            raise NavidromeError(data.get("error", {}).get("message", "unknown error"))
        return data

    def ping(self) -> None:
        self._get("ping")

    def artists(self) -> list[Artist]:
        data = self._get("getArtists")
        return [Artist(a["id"], a["name"])
                for index in data["artists"].get("index", [])
                for a in index.get("artist", [])]

    def albums(self, artist_id: str) -> list[Album]:
        data = self._get("getArtist", id=artist_id)["artist"]
        return [Album(a["id"], a["name"], data["name"]) for a in data.get("album", [])]

    def songs(self, album_id: str) -> list[Song]:
        data = self._get("getAlbum", id=album_id)["album"]
        return [Song(s["id"], s["title"], s.get("artist", ""), s.get("album", ""),
                     float(s.get("duration", 0)), s.get("coverArt"))
                for s in data.get("song", [])]

    def stream_url(self, song_id: str) -> str:
        return f"{self.base_url}/rest/stream?{urlencode({**self._auth(), 'id': song_id})}"

    def cover_art(self, cover_id: str, size: int = 128) -> bytes:
        r = self._http.get(f"{self.base_url}/rest/getCoverArt",
                           params={**self._auth(), "id": cover_id, "size": size})
        r.raise_for_status()
        return r.content