import locale

import mpv


class Player:
    """Audio player for stream URLs, backed by libmpv."""

    def __init__(self) -> None:
        locale.setlocale(locale.LC_NUMERIC, "C")  # required by libmpv
        self._mpv = mpv.MPV(
            video=False,
            ytdl=False,
            terminal=False,
            really_quiet=True,
            osc=False,
            input_default_bindings=False,
            input_vo_keyboard=False,
        )
        self._url: str | None = None
        self._loaded = False
        self._finished = False

        @self._mpv.event_callback("file-loaded")
        def _on_loaded(event) -> None:
            self._loaded = True

    def play(self, url: str) -> bool:
        """Start streaming a URL from the beginning. Returns True (now playing)."""
        self._url = url
        self._loaded = False
        self._finished = False
        self._mpv.pause = False
        self._mpv.play(url)
        return True

    def toggle(self) -> bool:
        """Pause/resume. Restarts the track if it already ended.
        Returns True if audio is now playing."""
        if self._url is None:
            return False
        if self._finished:
            return self.play(self._url)
        self._mpv.pause = not self._mpv.pause
        return not self._mpv.pause

    @property
    def position(self) -> float:
        return self._mpv.time_pos or 0.0

    def has_finished(self) -> bool:
        """True once, right after the current track reaches its end."""
        if self._loaded and self._mpv.idle_active:
            self._loaded = False
            self._finished = True
            return True
        return False

    def close(self) -> None:
        self._mpv.terminate()