from io import BytesIO
from pathlib import Path
from typing import Iterable

from mutagen import File as MutagenFile
from mutagen.id3 import ID3
from PIL import Image as PILImage
from textual.widgets import DirectoryTree

AUDIO_EXTS = {".mp3", ".wav", ".flac", ".ogg", ".m4a"}


def read_metadata(path: str) -> tuple[str, str, PILImage.Image | None, float]:
    """Return (title, artist, cover or None, length_in_seconds) with fallbacks."""
    p = Path(path)
    title, artist, cover, length = p.stem, "Unknown artist", None, 0.0
    try:
        easy = MutagenFile(p, easy=True)
        if easy is not None and easy.tags:
            title = easy.tags.get("title", [title])[0]
            artist = easy.tags.get("artist", [artist])[0]

        audio = MutagenFile(p)
        data = None
        if audio is not None:
            if audio.info is not None:
                length = float(audio.info.length)
            if isinstance(audio.tags, ID3):                        # mp3
                apics = audio.tags.getall("APIC")
                data = apics[0].data if apics else None
            elif getattr(audio, "pictures", None):                 # flac
                data = audio.pictures[0].data
            elif audio.tags is not None and "covr" in audio.tags:  # m4a
                data = bytes(audio.tags["covr"][0])
        if data:
            cover = PILImage.open(BytesIO(data)).convert("RGB")
    except Exception:
        pass
    return title, artist, cover, length


class SongTree(DirectoryTree):
    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        return [p for p in paths if p.is_dir() or p.suffix.lower() in AUDIO_EXTS]