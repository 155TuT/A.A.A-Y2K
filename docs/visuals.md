# Pixel and sound presentation

The board, editor and life sprites share one 1 px source lattice. Each map cell
has a 15 × 15 interior and a shared 1 px dashed boundary (16 px stride). Native
art zoom remains an integer of one or two, followed by the window preset's
integer scale. Board/game sprites and the final displayed frame use only
nearest-neighbour scaling.
A 20 × 16 mask needs at least 321 × 257 source pixels in the board viewport.
Smaller viewports must be rearranged; the renderer never blurs a board to fit.

Arrows use a 2 px directed stroke and one canonical chevron rotated through all
four cardinal directions. Right-angle corners lose one outside raster pixel,
creating a restrained bevel without antialiasing. Motion still samples the
original orthogonal path by arc length. Hover uses the muted fluorescent green `accent` token; collision uses the
muted pink `collision` token. White-outlined hearts retain their
outline after damage, with fixed red shadow/highlight pixels that travel with
the falling fragments. Each arrow and each damaged heart has an independent
timeline composed by `GameplayEffects`: other arrows remain clickable while
an exit or rebound is playing. Multiple losses preserve separate heart
fragments; pausing freezes every timeline. Rendering never changes occupancy,
life counts or countdown penalties.

`AudioController` is the sole mixer owner. It synthesises click, collision,
win, lose and achievement effects as signed 16-bit PCM; no sound files or
network are required. Master and effect levels are floats from 0 to 1; the app
persists those settings. The physical + / − keys change master volume by
five integer percentage points and clamp it to 0–100%, avoiding accumulated
floating-point steps. An audio-settings field with a valid current edit is
the starting value; an invalid field falls back to the stored value. Only
master volume is committed, leaving other unsaved fields intact. A successful
write immediately updates the mixer and the visible master-volume number.
Muting stops existing effects immediately. A missing
audio device is silent and does not alter gameplay.

The home menu uses native pixel play, folder, trophy, map and gear icons.
`icons.py` owns these finite-palette sprites; the credit heart is cropped from
`render_hearts`, keeping its outline, highlight and shadow identical to LIFE.
The first button row shares the full-width rows' left and right edges. GitHub
and Exit occupy visually square outline buttons at the bottom left and right
respectively.
The GitHub button and the About page share the official white Invertocat asset;
its original PNG/SVG and attribution are retained under `assets/icons`. The
asset is resampled once with LANCZOS and its alpha is thresholded into a
binary 16 px mask; all subsequent display scaling uses the integer pixel grid. Exit
actions share the red outline and white exit icon, with text where needed to
distinguish returning home from exiting the application.
The footer reads `Made By 155TuT with GPT and ♥ Love`.

`palette.py` supplies one semantic token set to Textual CSS, Rich text and
native pixel rendering. CSS uses injected `$aaa-*` variables and native
renderers use the same tokens through `rgb()`. Monochrome is a final screen
filter, so controls and artwork do not maintain separate color definitions.

`PixelButton` draws its complete pixel face while Textual retains layout,
focus, keyboard activation and hit testing. Its outline encloses the hover
fill with an equal one-source-pixel inset on all four sides. Icons and labels
are centered by their visible ink bounds, including icon-only buttons. Form
controls compose the same pixel outline treatment around their native inputs. Buttons disable the framework's
0.2-second active gate, and focus no longer imitates a filled hover state.
Settings tabs mark selection by outline. The disclosure component in each
Select draws three integer-pixel dots using its outline colour; Switch has a
complete green-toned outline and no default blue focus tint. Page-wide text
selection is disabled so rapid double/triple clicks cannot highlight the
board's surrounding text; Input editing remains available.

Pages other than Home and Game compose a shared `PageHeader`: a compact
return-home button on the upper right and a vertically centered page title
on the left. The pause-menu minimize action uses a yellow outline. Game
keeps its board/sidebar layout. The native compositor follows Textual's
actual layers and clipping; tooltips, dropdowns and notifications cover
underlying icons instead of being repainted underneath them. Wide Chinese
glyphs stay complete even where a lower widget's boundary crosses the popup.

The SDL host forwards close, Alt+F4 and the close capability to
`app.request_desktop_exit()` so the app can settle time and save a live
checkpoint once before starting the visual shutdown.
Failed or timed-out runs never replace the previous automatic save.
`window_drag_region` follows the shared header's actual height; Home and Game
use their existing top 12-source-pixel margin. Interactive controls in that
region receive their normal clicks. The header title and blank space remain
draggable without taking board space. The surrounding CRT shell is also draggable; physical controls retain their
own hit regions. The host captures the desktop pointer for stable dragging, falling back to relative motion where global coordinates
are unavailable.

`windowing.py` reads SDL's monitor work areas, including taskbar/Dock exclusions
and negative multi-monitor origins. Startup and resolution changes keep the
window in the current usable area; an oversized preset anchors its top-left
corner there while preserving the requested integer pixel size. Minimizing,
restoring, losing focus or changing pages clears stale pointer and press
states. Passive motion events may be coalesced without dropping click events
or held-button drawing. The `open_url` capability opens only the verified
project page.


`CrtShell` composes the internal display and its case inside one SDL window.
The selected 1024×768, 1280×720 or 1920×1080 display retains its original size;
the outer window adds `40 × scale` horizontally and `74 × scale` vertically,
resulting in 1104×916, 1360×868 and 2040×1302. Monitor placement uses these
outer dimensions, while Textual continues to lay out the same logical frame.

Light scanlines, fine noise, a slight curve at the screen edge and a green
glass glow decorate the display. Board cells, text and buttons keep their
original positions. Pointer mapping uses only the display offset and integer
scale; the content has no geometry warp or correction lookup. The case's
power key requests shutdown, + / − change master volume, and M toggles the
persisted monochrome mode. The centered, bold power mark is recessed through
the button face with `LED_YELLOW` showing through and a bright upper edge.
After the application's one-time save boundary, gameplay and input freeze
while the host presents roughly 0.3 seconds of flicker/shake and 1 second of
`NO SIGNAL`, then closes the application. Reduced motion disables shutdown
shake/flicker and animated noise. Home Escape shows a confirmation page;
cancel or Escape returns home, while confirmation starts the same shutdown.


Monochrome is applied after the entire internal display is composed, including
text, board sprites, input controls, tooltips, noise, reflections and the
`NO SIGNAL` card. The glass rim also becomes gray-white. The enclosure,
physical buttons and indicator LEDs retain their original colors. Settings
persist `monochrome` as a boolean; missing fields in older settings default to
full color. Failed preference writes do not alter the active presentation.

The CRT renderer returns RGBA with zero alpha outside the rounded enclosure.
On Windows, `WindowShape` converts the same mask through `mask_rectangles()`
and Win32 `SetWindowRgn`, clipping the actual SDL window to that contour.
Desktop pixels show through the removed corners. On backends without native
region support, the portable frame still has transparent alpha but the
window corners are filled with the warm-white `CASE` color. This requires no
new dependencies. macOS/Linux native corner behavior has not been verified
on this Windows host.
