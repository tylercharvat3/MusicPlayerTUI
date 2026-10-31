from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image as PILImage
from textual import events, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, ProgressBar, Static, Tree
from textual_image.widget import Image

from navidrome import Album, Artist, NavidromeClient, NavidromeError, Song
from player import Player

PLAY_ICON = "▶"
PAUSE_ICON = "❚❚"
CONFIG_PATH = Path(__file__).parent / "server.config"


def load_config(path: Path = CONFIG_PATH) -> tuple[str, str]:
    """Read URL and user from a KEY="value" file. Keys are case-insensitive."""
    if not path.exists():
        raise SystemExit(f"Config file not found: {path}")
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip().lower()] = value.strip().strip('"').strip("'")
    missing = [k for k in ("url", "user") if not values.get(k)]
    if missing:
        raise SystemExit(f"{path} is missing: {', '.join(missing)}")
    return values["url"], values["user"]


def placeholder_cover() -> PILImage.Image:
    return PILImage.new("RGB", (64, 64), (60, 60, 60))


def fmt_time(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


class LoginScreen(ModalScreen[NavidromeClient]):
    """Asks for the password and only closes once the server accepts it."""

    DEFAULT_CSS = """
    LoginScreen {
        align: center middle;
    }
    #login {
        width: 50;
        height: auto;
        padding: 1 2;
        border: round $accent;
        background: $surface;
    }
    #login-error {
        color: $error;
        height: auto;
    }
    """

    def __init__(self, url: str, user: str) -> None:
        super().__init__()
        self.url = url
        self.user = user

    def compose(self) -> ComposeResult:
        with Vertical(id="login"):
            yield Label(f"Server: {self.url}", markup=False)
            yield Label(f"User: {self.user}", markup=False)
            yield Input(password=True, placeholder="Password", id="password")
            yield Label("", id="login-error", markup=False)

    def on_mount(self) -> None:
        self.query_one("#password", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.input.disabled = True
        self.query_one("#login-error", Label).update("Signing in...")
        self.attempt(event.value)

    @work(thread=True, exclusive=True)
    def attempt(self, password: str) -> None:
        client = NavidromeClient(self.url, self.user, password)
        try:
            client.ping()
        except NavidromeError as e:
            message = str(e)
        except httpx.HTTPError as e:
            message = f"Could not reach server: {e}"
        else:
            self.app.call_from_thread(self.dismiss, client)
            return
        self.app.call_from_thread(self.show_error, message)

    def show_error(self, message: str) -> None:
        self.query_one("#login-error", Label).update(message)
        field = self.query_one("#password", Input)
        field.disabled = False
        field.value = ""
        field.focus()


class MusicApp(App[str]):
    CSS_PATH = "style.tcss"

    playing = reactive(False)
    currentSong: Song | None = None
    song_length: float = 0.0
    position: float = 0.0
    client: NavidromeClient | None = None

    def __init__(self) -> None:
        super().__init__()
        self.url, self.user = load_config()
        self.player = Player()

    # ---------- layout ----------

    def compose(self) -> ComposeResult:
        yield Tree("Library", id="songs")
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
        self.query_one("#songs", Tree).show_root = False
        self.set_interval(0.25, self.tick)
        self.push_screen(LoginScreen(self.url, self.user), self.on_login)

    def on_unmount(self) -> None:
        self.player.close()

    def on_login(self, client: NavidromeClient | None) -> None:
        if client is None:
            return
        self.client = client
        self.load_artists()

    # ---------- library loading (network calls run in threads) ----------

    @work(thread=True)
    def load_artists(self) -> None:
        try:
            artists = self.client.artists()
        except Exception as e:
            self.call_from_thread(self.notify, f"Could not load library: {e}", severity="error")
            return
        self.call_from_thread(self.add_artists, artists)

    def add_artists(self, artists: list[Artist]) -> None:
        root = self.query_one("#songs", Tree).root
        for a in artists:
            root.add(a.name, data=a, allow_expand=True)

    def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        node = event.node
        if isinstance(node.data, (Artist, Album)) and not node.children:
            self.load_children(node)  # only fetch once

    @work(thread=True)
    def load_children(self, node) -> None:
        data = node.data
        try:
            kids = (
                self.client.albums(data.id)
                if isinstance(data, Artist)
                else self.client.songs(data.id)
            )
        except Exception as e:
            self.call_from_thread(self.notify, f"Load failed: {e}", severity="error")
            return
        self.call_from_thread(self.add_children, node, kids)

    def add_children(self, node, kids) -> None:
        for k in kids:
            if isinstance(k, Album):
                node.add(k.name, data=k, allow_expand=True)
            else:
                node.add_leaf(k.title, data=k)

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        if isinstance(event.node.data, Song):
            self.start_song(event.node.data)

    # ---------- playback ----------

    def start_song(self, song: Song) -> None:
        self.currentSong = song
        self.song_length = song.duration
        self.position = 0.0
        self.query_one("#title", Label).update(song.title)
        self.query_one("#artist", Label).update(song.artist)
        self.query_one("#cover", Image).image = placeholder_cover()
        self.refresh_progress()
        self.load_cover(song)
        self.playing = self.player.play(self.client.stream_url(song.id))

    @work(thread=True)
    def load_cover(self, song: Song) -> None:
        if not song.cover_id:
            return
        try:
            img = PILImage.open(
                BytesIO(self.client.cover_art(song.cover_id))
            ).convert("RGB")
        except Exception:
            return  # keep the placeholder
        # ignore the result if the user already switched to another song
        if self.currentSong is song:
            self.call_from_thread(self.set_cover, img)

    def set_cover(self, img: PILImage.Image) -> None:
        self.query_one("#cover", Image).image = img

    def watch_playing(self, playing: bool) -> None:
        button = self.query_one("#play", Button)
        button.set_class(playing, "playing")
        button.label = PAUSE_ICON if playing else PLAY_ICON

    def tick(self) -> None:
        if self.currentSong is None:
            return
        if self.player.has_finished():
            self.playing = False
            self.position = 0.0
        elif self.playing:
            self.position = min(self.player.position, self.song_length or 1e9)
        self.refresh_progress()

    def refresh_progress(self) -> None:
        self.query_one("#bar", ProgressBar).update(
            total=self.song_length or 1, progress=self.position
        )
        self.query_one("#elapsed", Label).update(fmt_time(self.position))
        self.query_one("#duration", Label).update(fmt_time(self.song_length))

    # ---------- input ----------

    def on_key(self, event: events.Key) -> None:
        if self.client is None:  # still on the login screen
            return
        if event.key == "p":
            self.query_one("#play", Button).press()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "play" and self.currentSong:
            self.playing = self.player.toggle()


if __name__ == "__main__":
    MusicApp().run()