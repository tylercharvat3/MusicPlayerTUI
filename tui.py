import time
from io import BytesIO
from pathlib import Path
from typing import Iterable

from mutagen import File as MutagenFile
from mutagen.id3 import ID3
from PIL import Image as PILImage
from textual import events
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Button, DirectoryTree, Label, ProgressBar, Static
from textual_image.widget import Image

from music import play

AUDIO_EXTS = {".mp3", ".wav", ".flac", ".ogg", ".m4a"}
PLAY_ICON = "▶"
PAUSE_ICON = "❚❚"


def placeholder_cover() -> PILImage.Image:
    return PILImage.new("RGB", (64, 64), (60, 60, 60))


def fmt_time(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


def read_metadata(path: str) -> tuple[str, str, PILImage.Image, float]:
    """Return (title, artist, cover, length_in_seconds) with fallbacks."""
    p = Path(path)
    title, artist, cover, length = p.stem, "Unknown artist", placeholder_cover(), 0.0
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


class MusicApp(App[str]):
    CSS_PATH = "style.tcss"

    playing = reactive(False)
    currentSong: str | None = None
    song_length: float = 0.0
    position: float = 0.0

    def compose(self) -> ComposeResult:
        yield SongTree("Songs/", id="songs")
        with Vertical(id="player"):
            with Horizontal(id="progress-row"):
                yield Label("0:00", id="elapsed")
                yield ProgressBar(
                    total=1, show_eta=False, show_percentage=False, id="bar"
                )
                yield Label("0:00", id="duration")
            with Horizontal(id="controls"):
                with Horizontal(id="nowplaying"):
                    yield Image(placeholder_cover(), id="cover")
                    with Vertical(id="info"):
                        yield Label("Nothing playing", id="title", markup=False)
                        yield Label("", id="artist", markup=False)
                yield Button(PLAY_ICON, id="play")
                yield Static(id="spacer")

    def on_mount(self) -> None:
        self.query_one("#songs", SongTree).show_root = False
        self._last_tick = time.monotonic()
        self.set_interval(0.25, self.tick)

    def watch_playing(self, playing: bool) -> None:
        button = self.query_one("#play", Button)
        button.set_class(playing, "playing")
        button.label = PAUSE_ICON if playing else PLAY_ICON

    def tick(self) -> None:
        now = time.monotonic()
        delta = now - self._last_tick
        self._last_tick = now
        if not self.playing or not self.song_length:
            return
        self.position = min(self.position + delta, self.song_length)
        if self.position >= self.song_length:  # song finished
            self.playing = False
            self.position = 0.0
        self.refresh_progress()

    def refresh_progress(self) -> None:
        self.query_one("#bar", ProgressBar).update(
            total=self.song_length or 1, progress=self.position
        )
        self.query_one("#elapsed", Label).update(fmt_time(self.position))
        self.query_one("#duration", Label).update(fmt_time(self.song_length))

    def update_now_playing(self, path: str) -> None:
        title, artist, cover, length = read_metadata(path)
        self.query_one("#cover", Image).image = cover
        self.query_one("#title", Label).update(title)
        self.query_one("#artist", Label).update(artist)
        self.song_length = length
        self.position = 0.0
        self.refresh_progress()

    def on_key(self, event: events.Key) -> None:
        if event.key == "p":
            self.query_one("#play", Button).press()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "play" and self.currentSong:
            self.playing = play(self.currentSong)

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        self.currentSong = str(event.path)
        self.update_now_playing(self.currentSong)
        self.playing = play(self.currentSong)


if __name__ == "__main__":
    MusicApp().run()