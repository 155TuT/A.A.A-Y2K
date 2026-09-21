"""PCM, persistent controls and audio-device-optional behaviour."""

from array import array

import pytest

from arrow_y2k.audio import AudioController, EVENTS, _synthesize


@pytest.mark.parametrize("event", EVENTS)
def test_retro_effect_pcm_is_short_bipolar_bounded_and_click_free(event):
    samples = array("h", _synthesize(event))
    assert 0.02 < len(samples) / 22050 < 0.6
    assert min(samples) < 0 < max(samples)
    assert max(abs(sample) for sample in samples) < 8000
    assert samples[0] == samples[-1] == 0
    stereo = array("h", _synthesize(event, channels=2))
    assert stereo[::2] == stereo[1::2] == samples


def test_muted_controller_retains_levels_without_opening_mixer(monkeypatch):
    audio = AudioController(0.8, 0.5, True)
    monkeypatch.setattr(audio, "_ensure_mixer", lambda: pytest.fail("Muted sound opened mixer"))
    assert not audio.play("click")
    assert audio.master_volume == 0.8
    assert audio.effects_volume == 0.5
    assert audio.volume == 0
    audio.close()


def test_unavailable_audio_device_is_silent_and_attempted_once(monkeypatch):
    import pygame
    pygame.mixer.quit()
    calls = []
    def fail(**kwargs):
        calls.append(kwargs)
        raise pygame.error("No audio device")
    monkeypatch.setattr(pygame.mixer, "init", fail)
    audio = AudioController()
    assert not audio.play("collision")
    assert not audio.play("win")
    assert len(calls) == 1
    audio.close()


def test_dummy_mixer_plays_every_effect_and_applies_updated_volume(monkeypatch):
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")
    monkeypatch.setenv("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    import pygame
    pygame.mixer.quit()
    audio = AudioController(0.5, 0.5, False)
    try:
        for event in EVENTS:
            assert audio.play(event)
        assert pygame.mixer.get_init() == (22050, -16, 1)
        assert audio._sounds["click"].get_volume() == pytest.approx(0.25, abs=1/128)
        audio.configure(0.8, 0.5, False)
        assert audio.volume == 0.4
        assert audio._sounds["click"].get_volume() == pytest.approx(0.4, abs=1/128)
        audio.configure(0.8, 0.5, True)
        assert not pygame.mixer.get_busy()
        assert not audio.play("click")
    finally:
        audio.close()
    assert pygame.mixer.get_init() is None
    assert not audio.play("click")


def test_invalid_controls_and_events_are_explicit_errors():
    with pytest.raises(ValueError):
        AudioController(effects_volume=1.1)
    with pytest.raises(ValueError):
        AudioController().play("unknown")
