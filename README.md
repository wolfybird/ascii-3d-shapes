# ASCII 3D Shapes

Rotating 3D wireframes rendered as ASCII art in the terminal, with a z-buffer,
depth-based color palettes and optional audio reactivity (onset and BPM
detection from any input device). CPU only: Python and NumPy.

## Run

    pip install -r requirements.txt
    python shapes_v9-6.py

Needs a terminal with 256-color ANSI support (Windows Terminal, macOS Terminal,
iTerm2, most Linux terminals). `sounddevice` is optional; without it, or without
an input device, audio mode stays off.

## Versions

Each `shapes_v*.py` is a standalone snapshot, kept so any version still runs on
its own. The highest number is the newest.

## Shapes

| Key | Shapes (press again to cycle) |
|---|---|
| `1` | Cube, Rhombus |
| `2` | Pyramid, Cone |
| `3` | Sphere, Icosahedron |
| `4` | Hexagon, Octagon, Star |
| `5` | Cylinder, Helix |
| `6` | Torus, Torus Knot |
| `7` | Mobius Strip, Trefoil Knot |
| `8` | Klein 1 (bottle), Klein 2 (figure-8) |
| `9` | Lorenz attractor |
| `0` | Mandelbrot, Julia (height fields) |

## Controls

| Key | Action |
|---|---|
| Space | pause |
| Arrows, `<` `>` | rotate X/Y, Z |
| `o` / `r` | auto-rotate on/off / reset rotation |
| `+` `-` | scale |
| `f` `F` | field of view |
| `[` `]` | rotation speed |
| `d` `D` | density |
| `p` | wireframe / points |
| `c` / `C` / `i` | color mode / depth palette / invert depth |
| Shift+`0`-`9` | fixed color in shape color mode |
| `b` / `B` | brightness shading on/off / next character ramp |
| `z` `Z` | depth range |
| `s` `S` | auto-switch interval |
| `a` / `A` | audio on/off / input device |
| `n` `N` | audio sensitivity |
| `g` | what audio onsets trigger |
| `t` | adaptive density to hold the frame rate |
| `R` | resolution |
| `.` | HUD on/off |
| `m` | settings menu |
| `q` | quit |

## Build

Windows, folder build in `dist/ASCII3DShapes/`:

    pyinstaller ASCII3DShapes.spec

macOS, single executable at `dist/ASCII3DShapes`:

    ./build_mac.sh

Both build the version named inside them, so update that line when a newer
version should ship.
