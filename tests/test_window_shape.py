"""Native window silhouette uses the exact rounded alpha of the renderer."""
import pytest
from PIL import Image, ImageChops, ImageDraw
from arrow_y2k.crt import CrtShell
from arrow_y2k.windowing import mask_rectangles, WindowShape

@pytest.mark.parametrize("size,scale", [((1024,768),2),((1280,720),2),((1920,1080),3)])
def test_region_rectangles_reproduce_every_opaque_pixel(size, scale):
    shell = CrtShell(size, scale)
    mask = shell.outer_mask
    rectangles = mask_rectangles(mask)
    assert len(rectangles) < 30
    reconstructed = Image.new("L", mask.size)
    draw = ImageDraw.Draw(reconstructed)
    for left, top, right, bottom in rectangles:
        draw.rectangle((left,top,right-1,bottom-1),fill=255)
    assert ImageChops.difference(mask,reconstructed).getbbox() is None
    assert mask.getpixel((0,0)) == 0
    assert mask.getpixel((mask.width//2,mask.height//2)) == 255

def test_headless_shape_does_not_load_platform_apis(monkeypatch):
    from types import SimpleNamespace
    import ctypes
    fake = SimpleNamespace(display=SimpleNamespace(get_driver=lambda: "dummy"))
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: pytest.fail("headless used native API"), raising=False)
    shape = WindowShape(fake)
    assert shape.apply(Image.new("L", (10,10), 255)) is False
    assert not shape.applied
