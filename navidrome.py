import hashlib
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

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


class NavidromeClient:
    def __init__(self, base_url: str, user: str, password: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.user = user
        self.password = password
        self._http = httpx.Client(timeout=10)

    def _auth(self) -> dict:
        # Subsonic token auth: md5(password + random salt), so the password isn't sent
        salt = secrets.token_hex(8)
        token = hashlib.md5((self.password + salt).encode()).hexdigest()
        return {"u": self.user, "t": token, "s": salt,
                "v": "1.16.1", "c": "textual-music", "f": "json"}

    def _get(self, endpoint: str, **params) -> dict:
        r = self._http.get(f"{self.base_url}/rest/{endpoint}",
                           params={**self._auth(), **params})
        r.raise_for_status()
        data = r.json()["subsonic-response"]
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