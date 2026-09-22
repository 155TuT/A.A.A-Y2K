"""CRT presentation remains aligned with the original game pixel lattice."""
from time import perf_counter
from statistics import median

import pytest
from PIL import Image, ImageChops, ImageDraw

from arrow_y2k.crt import (CrtShell, GLASS, LED_RED, LED_YELLOW,
                           SHUTDOWN_DURATION, SHUTDOWN_SHAKE_SECONDS, shutdown_phase)

PRESETS = (((1024, 768), 2), ((1280, 720), 2), ((1920, 1080), 3))


def inner(shell, frame):
    x, y, width, height = shell.viewport
    return frame.crop((x, y, x + width, y + height)).resize(shell.logical_size, Image.Resampling.NEAREST)


@pytest.mark.parametrize("size,scale", PRESETS)
def test_three_resolutions_preserve_content_size_and_integer_lattice(size, scale):
    shell = CrtShell(size, scale)
    assert shell.outer_size == (size[0] + 40 * scale, size[1] + 74 * scale)
    assert shell.viewport == (20 * scale, 20 * scale, *size)
    logical = Image.new("RGB", shell.logical_size, (30, 41, 34))
    result = shell.render(logical, .1)
    assert result.size == shell.outer_size
    small = result.resize((shell.outer_size[0] // scale, shell.outer_size[1] // scale), Image.Resampling.NEAREST)
    assert small.resize(shell.outer_size, Image.Resampling.NEAREST).tobytes() == result.tobytes()


@pytest.mark.parametrize("size,scale", PRESETS)
def test_content_and_clicks_stay_in_exactly_the_same_pixels(size, scale):
    shell = CrtShell(size, scale)
    width, height = shell.logical_size
    marks = {(37, 29), (width // 2, height // 2), (width - 5, height // 2),
             (width // 2, 1), (width // 2, height - 2)}
    content = Image.new("RGB", shell.logical_size)
    for x, y in marks:
        content.putpixel((x, y), (255, 255, 255))
    screen = inner(shell, shell.render(content, .1, reduced_motion=True))
    bright = {(x, y) for y in range(height) for x in range(width) if min(screen.getpixel((x, y))) > 200}
    assert bright == marks  # Reflection and scanlines cannot move or blur the content.
    for source in marks:
        point = shell.forward_point(source)
        assert point is not None
        assert shell.input_point(point) == source
        assert shell.contains_screen(point)
        top_left = (shell.viewport[0] + source[0] * scale, shell.viewport[1] + source[1] * scale)
        for dy in range(scale):
            for dx in range(scale):
                assert shell.input_point((top_left[0] + dx, top_left[1] + dy)) == source
    assert shell.input_point((shell.viewport[0], shell.viewport[1])) is None
    assert shell.forward_point((0, 0)) is None
    assert shell.forward_point((-1, 5)) is None
    assert shell.input_point((-1, -1)) is None
    assert shell.input_point((shell.viewport[0] + size[0], shell.viewport[1])) is None


@pytest.mark.parametrize("size,scale", PRESETS)
def test_physical_controls_are_outside_screen_and_pressed_face_has_depth(size, scale):
    shell = CrtShell(size, scale)
    content = Image.new("RGB", shell.logical_size)
    released = shell.render(content, .1, reduced_motion=True)
    assert set(shell.control_rects) == {"menu", "minus", "plus", "power"}
    for name, (x, y, width, height) in shell.control_rects.items():
        centre = (x + width // 2, y + height // 2)
        assert shell.control_at(centre) == name
        assert not shell.contains_screen(centre)
        pressed = shell.render(content, .1, pressed=name, reduced_motion=True)
        changed = ImageChops.difference(released, pressed).getbbox(alpha_only=False)
        assert changed is not None
        assert x <= changed[0] < changed[2] <= x + width
        assert y <= changed[1] < changed[3] <= y + height
    assert shell.control_at(shell.forward_point((30, 30))) is None


def test_indicator_lamps_switch_between_discrete_levels_at_different_periods():
    shell = CrtShell((1280, 720), 2)
    content = Image.new("RGB", shell.logical_size)
    assert shell.indicator_states(.519)[0]
    assert not shell.indicator_states(.521)[0]
    assert not shell.indicator_states(1.429)[1]
    assert shell.indicator_states(1.431)[1]
    yellow, red = shell.indicator_centers
    on1, on2 = shell.render(content, .05), shell.render(content, .45)
    off = shell.render(content, .80)
    assert on1.getpixel(yellow) == on2.getpixel(yellow) == (*LED_YELLOW, 255)
    assert off.getpixel(yellow) != (*LED_YELLOW, 255)
    assert shell.render(content, 1.44).getpixel(red) == (*LED_RED, 255)
    assert shell.render(content, 1.54).getpixel(red) == (*LED_RED, 255)
    assert shell.indicator_states(0.0, reduced_motion=True) == shell.indicator_states(99, reduced_motion=True)


def test_shutdown_shakes_then_shows_no_signal_for_one_second_then_turns_off():
    shell = CrtShell((1280, 720), 2)
    content = Image.new("RGB", shell.logical_size)
    ImageDraw.Draw(content).rectangle((200, 60, 206, 160), fill=(255, 255, 255))
    assert SHUTDOWN_SHAKE_SECONDS == .30
    assert SHUTDOWN_DURATION - SHUTDOWN_SHAKE_SECONDS == 1.0
    assert [shutdown_phase(t) for t in (None, 0, .299, .30, 1.299, 1.30)] == [
        "on", "unstable", "unstable", "no_signal", "no_signal", "off"]
    before = inner(shell, shell.render(content, 0, shutdown_elapsed=.01))
    shake = inner(shell, shell.render(content, 0, shutdown_elapsed=.11))
    assert before.tobytes() != shake.tobytes()
    signal_a = inner(shell, shell.render(content, 2, shutdown_elapsed=.30, reduced_motion=True))
    signal_b = inner(shell, shell.render(content, 6, shutdown_elapsed=1.299, reduced_motion=True))
    assert signal_a.tobytes() == signal_b.tobytes()
    assert max(signal_a.getpixel((x, y))[1] for x in range(250, 390) for y in range(160, 200)) > 100
    off = inner(shell, shell.render(content, 6, shutdown_elapsed=1.30))
    assert set(off.get_flattened_data()) == {(*GLASS, 255)}
    assert shell.indicator_states(6, shutdown_elapsed=1.30) == (False, False)


def test_reduced_motion_keeps_noise_and_lights_steady_and_glass_edge_green():
    shell = CrtShell((1280, 720), 2)
    content = Image.new("RGB", shell.logical_size, (12, 20, 16))
    assert shell.render(content, 0, reduced_motion=True).tobytes() == shell.render(content, 9.1, reduced_motion=True).tobytes()
    output = shell.render(content, 0, reduced_motion=True)
    screen_left, screen_top, _, _ = shell.viewport
    edge = output.getpixel((screen_left - shell.scale, screen_top + 50 * shell.scale))
    assert edge[1] > edge[0] and edge[1] > edge[2]
    assert inner(shell, shell.render(content, 0, shutdown_elapsed=.1, reduced_motion=True)).tobytes() == inner(shell, output).tobytes()


@pytest.mark.parametrize("size,scale", PRESETS)
def test_cached_effects_stay_within_interactive_frame_budget(size, scale):
    shell = CrtShell(size, scale)
    content = Image.new("RGB", shell.logical_size, (17, 27, 23))
    first = shell.render(content, 0, reduced_motion=True)
    times = []
    for index in range(12):
        begin = perf_counter()
        shell.render(content, index / 60)
        times.append(perf_counter() - begin)
    # A loose CI guard catches a Python per-pixel hot loop without assuming
    # dedicated machine timings; local evidence records the tighter <10 ms goal.
    assert median(times) < .050
    assert shell.render(content, 0, reduced_motion=True).tobytes() == first.tobytes()


def test_invalid_content_frame_is_rejected_before_rendering():
    shell = CrtShell((1280, 720), 2)
    with pytest.raises(ValueError, match="logical framebuffer"):
        shell.render(Image.new("RGB", (1280, 720)), 0)


@pytest.mark.parametrize("size,scale", PRESETS)
def test_outer_corners_are_transparent_with_matching_binary_window_mask(size, scale):
    shell = CrtShell(size, scale)
    frame = shell.render(Image.new("RGB", shell.logical_size), 0)
    assert frame.mode == "RGBA"
    assert shell.outer_mask.mode == "L"
    assert shell.outer_mask.size == shell.outer_size
    assert set(shell.outer_mask.get_flattened_data()) == {0, 255}
    assert frame.getchannel("A").tobytes() == shell.outer_mask.tobytes()
    width, height = shell.outer_size
    for point in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
        assert frame.getpixel(point)[3] == 0
    # Rounded corners do not punch transparent holes in the glass or controls.
    assert inner(shell, frame).getchannel("A").getextrema() == (255, 255)
    for bounds in shell.control_rects.values():
        x, y, width, height = bounds
        assert frame.crop((x, y, x + width, y + height)).getchannel("A").getextrema() == (255, 255)


@pytest.mark.parametrize("pressed", [None, "power"])
def test_power_symbol_is_two_pixels_thick_and_centred_in_visible_face(pressed):
    shell = CrtShell((1280, 720), 2)
    frame = shell.render(Image.new("RGB", shell.logical_size), 0, pressed=pressed)
    x, y, width, height = shell.control_rects["power"]
    button = frame.crop((x, y, x + width, y + height)).resize((width // 2, height // 2), Image.Resampling.NEAREST)
    light_colors = {LED_YELLOW, (255, 239, 161)}
    glowing = {(xx, yy) for yy in range(button.height) for xx in range(button.width)
               if button.getpixel((xx, yy))[:3] in light_colors}
    assert any(button.getpixel(point)[:3] == LED_YELLOW for point in glowing)
    left, right = min(xx for xx, _ in glowing), max(xx for xx, _ in glowing)
    top, bottom = min(yy for _, yy in glowing), max(yy for _, yy in glowing)
    assert sum(yy == top for _, yy in glowing) == 2
    assert sum(yy == top + 1 for _, yy in glowing) == 2
    face_colors = {(162, 168, 146), (118, 126, 108)} if pressed else {(210, 211, 188), (242, 239, 217)}
    face = {(xx, yy) for yy in range(button.height) for xx in range(button.width)
            if button.getpixel((xx, yy))[:3] in face_colors}
    assert abs((left + right) - (min(xx for xx, _ in face) + max(xx for xx, _ in face))) <= 1
    assert abs((top + bottom) - (min(yy for _, yy in face) + max(yy for _, yy in face))) <= 1
    # The recessed dark cut surrounds the transmitted yellow light.
    assert any(pixel[:3] == (88, 91, 66) for pixel in button.get_flattened_data())


@pytest.mark.parametrize("shutdown", [None, .1, .7, 1.3])
def test_monochrome_covers_all_screen_layers_and_glass_without_recoloring_case(shutdown):
    shell = CrtShell((1280, 720), 2)
    content = Image.new("RGB", shell.logical_size, (18, 40, 26))
    draw = ImageDraw.Draw(content)
    draw.rectangle((15, 15, 35, 35), fill=(240, 80, 135))
    draw.rectangle((250, 130, 440, 200), fill=(90, 220, 170))
    color = shell.render(content, .1, shutdown_elapsed=shutdown, reduced_motion=True)
    mono = shell.render(content, .1, shutdown_elapsed=shutdown, reduced_motion=True, monochrome=True)
    screen = inner(shell, mono)
    red, green, blue, alpha = screen.split()
    assert red.tobytes() == green.tobytes() == blue.tobytes()
    assert alpha.getextrema() == (255, 255)
    assert mono.getchannel("A").tobytes() == color.getchannel("A").tobytes()
    # Plastic, physical lamp lenses and the illuminated power cutout retain
    # their material colours; only screen light switches to neutral white.
    for point in (*shell.indicator_centers, (120, shell.outer_size[1] - 40)):
        assert mono.getpixel(point) == color.getpixel(point)
    x, y, width, height = shell.control_rects["power"]
    assert mono.crop((x, y, x + width, y + height)).tobytes() == color.crop((x, y, x + width, y + height)).tobytes()
    edge = mono.getpixel((shell.viewport[0] - shell.scale, shell.viewport[1] + 100))
    assert edge[0] == edge[1] == edge[2]
    assert shell.input_point(shell.forward_point((22, 22))) == (22, 22)
