# Pixel and sound presentation

The board, editor and life sprites share one 1 px source lattice. Each map cell
has a 15 × 15 interior and a shared 1 px dashed boundary (16 px stride). Native
art zoom remains an integer of one or two, followed by the window preset's
integer scale; nearest-neighbour presentation is the only image resize mode.
A 20 × 16 mask needs at least 321 × 257 source pixels in the board viewport.
Smaller viewports must be rearranged; the renderer never blurs a board to fit.

Arrows use a 2 px directed stroke and one canonical chevron rotated through all
four cardinal directions. Right-angle corners lose one outside raster pixel,
creating a restrained bevel without antialiasing. Motion still samples the
original orthogonal path by arc length. Hover is muted fluorescent green
`#72d69c`; collision is muted pink `#d96b9e`. White-outlined hearts retain their
outline after damage, with fixed red shadow/highlight pixels that travel with
the falling fragments.

`AudioController` is the sole mixer owner. It synthesises click, collision,
win, lose and achievement effects as signed 16-bit PCM; no sound files or
network are required. Master and effect levels are floats from 0 to 1; the app
persists those settings. Muting stops existing effects immediately. A missing
audio device is silent and does not alter gameplay.

The home menu uses native pixel play, folder, trophy, map and gear icons.
`icons.py` owns these finite-palette sprites; the credit heart is cropped from
`render_hearts`, keeping its outline, highlight and shadow identical to LIFE.
The first button row shares the full-width rows' left and right edges. Exit
and GitHub occupy visually square outline buttons at the two bottom corners.
Exit actions on other pages share the red outline and white exit icon, with
text retained to distinguish returning home from exiting the application.
The footer reads `Made By 155TuT with GPT and ♥ Love`.

`PixelButton` only decorates Textual's content area; Textual retains layout,
focus, keyboard activation and hit testing.

The SDL host forwards close, Alt+F4 and the close capability to
`app.request_desktop_exit()` so the app can save first. Window dragging is
allowed only when `app.allow_window_drag` is true; it never consumes gameplay
board clicks. The `open_url` capability opens only the verified project page.
