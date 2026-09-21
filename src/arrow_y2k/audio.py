"""One owner for short, generated retro effects; no audio assets or network.

Settings are retained by this controller and can be serialised by the app's
settings repository. SDL mixer is opened lazily, so terminal sessions and
machines without an audio device remain fully playable.
"""

from __future__ import annotations

from array import array
from math import pi, sin


# (frequency Hz, duration seconds) sequences. Collision slides downward within
# each note; every sample has a short attack/release to avoid speaker clicks.
_NOTES = {
    "click": ((740.0, 0.035),),
    "collision": ((155.0, 0.07), (93.0, 0.085)),
    "win": ((523.25, 0.085), (659.25, 0.085), (783.99, 0.085), (1046.5, 0.14)),
    "lose": ((329.63, 0.12), (261.63, 0.12), (196.0, 0.20)),
    "achievement": ((783.99, 0.075), (987.77, 0.075), (1174.66, 0.075), (1567.98, 0.15)),
}
EVENTS = tuple(_NOTES)


def _synthesize(event: str, sample_rate: int = 22050, channels: int = 1) -> bytes:
    """Generate native-endian signed 16-bit PCM at the mixer's actual format."""
    if event not in _NOTES:
        raise ValueError(f"Unknown audio event: {event}")
    samples = array("h")
    for frequency, duration in _NOTES[event]:
        count = round(sample_rate * duration)
        phase = 0.0
        for index in range(count):
            progress = index / max(1, count - 1)
            pitch = frequency * (1 - 0.38 * progress) if event == "collision" else frequency
            phase += pitch / sample_rate
            # Quiet square-wave colour mixed with a sine fundamental preserves
            # the retro character without harsh full-volume square-wave edges.
            square = 1.0 if phase % 1 < 0.5 else -1.0
            wave = 0.35 * square + 0.65 * sin(2 * pi * phase)
            envelope = min(1.0, index / max(1, sample_rate * 0.003),
                           (count - 1 - index) / max(1, sample_rate * 0.012))
            envelope *= 1 - 0.3 * progress
            value = round(32767 * 0.22 * envelope * wave)
            samples.extend([value] * channels)
    return samples.tobytes()


class AudioController:
    """Persistent volume controls around one lazily opened pygame mixer.

    Public volumes are floats in [0, 1]. ``play`` returns whether an effect was
    submitted; unavailable devices and a muted controller return False. SDL
    availability is an optional presentation detail, never a game-rule error.
    """

    def __init__(self, master_volume: float = 1.0, effects_volume: float = 0.7,
                 muted: bool = False) -> None:
        self.master_volume = 1.0
        self.effects_volume = 0.7
        self.muted = False
        self._mixer = None
        self._sounds = {}
        self._format = None
        self._owns_mixer = False
        self._failed = False
        self._closed = False
        self.configure(master_volume, effects_volume, muted)

    @property
    def volume(self) -> float:
        return 0.0 if self.muted else self.master_volume * self.effects_volume

    def configure(self, master_volume: float, effects_volume: float, muted: bool) -> None:
        if not 0 <= master_volume <= 1 or not 0 <= effects_volume <= 1:
            raise ValueError("Audio volumes must be between zero and one")
        self.master_volume = float(master_volume)
        self.effects_volume = float(effects_volume)
        self.muted = bool(muted)
        for sound in self._sounds.values():
            sound.set_volume(self.volume)
            if self.volume == 0:
                sound.stop()

    def _ensure_mixer(self) -> bool:
        if self._closed or self._failed:
            return False
        if self._mixer is not None:
            return True
        try:
            from pygame import error, mixer
        except ImportError:
            self._failed = True
            return False
        try:
            if mixer.get_init() is None:
                mixer.init(frequency=22050, size=-16, channels=1, buffer=512)
                self._owns_mixer = True
            self._format = mixer.get_init()
            if self._format is None or self._format[1] != -16:
                self._failed = True
                return False
            self._mixer = mixer
            return True
        except error:
            self._failed = True
            return False

    def play(self, event: str) -> bool:
        if event not in _NOTES:
            raise ValueError(f"Unknown audio event: {event}")
        if self.volume == 0 or not self._ensure_mixer():
            return False
        from pygame import error
        try:
            if event not in self._sounds:
                sample_rate, _, channels = self._format
                self._sounds[event] = self._mixer.Sound(buffer=_synthesize(event, sample_rate, channels))
            sound = self._sounds[event]
            sound.set_volume(self.volume)
            return sound.play() is not None
        except error:
            self._failed = True
            return False

    def close(self) -> None:
        """Release our effects; do not shut down a mixer owned by another host."""
        if self._closed:
            return
        for sound in self._sounds.values():
            sound.stop()
        self._sounds.clear()
        if self._owns_mixer and self._mixer is not None:
            self._mixer.quit()
        self._mixer = None
        self._closed = True
