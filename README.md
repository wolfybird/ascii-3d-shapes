# ASCII 3D Shapes

Rotating 3D wireframes drawn as ASCII art, with a z-buffer, depth-based
color palettes and optional audio reactivity (onset and BPM detection from
any input device). It opens in its own window on Windows, macOS and Linux,
or runs in a terminal. CPU only: Python and NumPy.

## Get it

### Ready-made apps

GitHub Actions builds the apps (see [Build](#build)). Open the latest
**Build apps** run on the Actions tab and download the file for your system:

| System | File | Start it |
|---|---|---|
| Windows | `ASCII3DShapes-windows.zip` | Unzip, then double-click `ASCII3DShapes.exe`. `ASCII3DShapes-terminal.exe` is the terminal version. |
| macOS (Apple silicon) | `ASCII3DShapes-macos.zip` | Unzip and move `ASCII3DShapes.app` to Applications. |
| Linux | `ASCII3DShapes-linux.tar.gz` | `tar xzf ASCII3DShapes-linux.tar.gz`, then run `ASCII3DShapes/ASCII3DShapes` (add `--terminal` for the terminal version). |

The apps aren't signed, so the first launch shows a warning:

- **Windows:** on "Windows protected your PC", click **More info**, then **Run anyway**.
- **macOS:** right-click the app, choose **Open**, then **Open** again.
  Audio mode asks for microphone access the first time.

### Terminal version, set up for you

The installer sets up everything the terminal version needs. It puts the
packages in a private `.venv` folder, so the rest of your system is left
alone.

1. Download this project (green **Code** button, then **Download ZIP**) and unzip it.
2. Run the installer for your system:
   - **Windows:** double-click `install_windows.bat`.
   - **macOS:** double-click `install_mac.command`. If macOS blocks it, right-click it, choose **Open**, then **Open**.
   - **Linux:** in a terminal in the project folder, run `./install_linux.sh`.
3. Start the program with the launcher the installer makes in the same
   folder: `Run ASCII 3D Shapes.bat` on Windows,
   `Run ASCII 3D Shapes.command` on macOS, `./run_ascii3dshapes.sh` on
   Linux.

If Python is missing, the installer explains how to get it. Running it
again updates the packages. To remove it, delete the `.venv` folder and the
launcher.

### From source

    pip install -r requirements.txt
    python shapes_v10.py              # in its own window
    python shapes_v10.py --terminal   # in this terminal

`pygame` gives the window; without it the program runs in the terminal.
`sounddevice` is optional and needs PortAudio, which Linux may need
installed (`sudo apt install libportaudio2`). The terminal version needs
256-color ANSI support (Windows Terminal, macOS Terminal, iTerm2, most
Linux terminals).

## Mouse and keys

In the window, the button bar along the bottom does the most common things,
**Menu** has every setting, and **Settings** opens a panel with sliders and
dropdowns.

| Mouse (window) | Action |
|---|---|
| Left-drag | rotate |
| Right-drag | spin |
| Wheel | zoom (over a menu setting: change it) |
| Middle-click | reset rotation |

| Key | Action |
|---|---|
| Space | pause |
| Arrows, `<` `>` or `,` `.` | rotate X/Y, Z |
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
| `h` | HUD on/off |
| `m` | menu |
| `P` | settings panel |
| `?` or F1 | help |
| F11 or Alt+Enter | fullscreen (window); Esc leaves it |
| `q` | quit |

Settings are remembered between runs. They are stored, with a `crash.log`
if something goes wrong, in `%APPDATA%\ASCII3DShapes` on Windows,
`~/Library/Application Support/ASCII3DShapes` on macOS and
`~/.config/ascii3dshapes` on Linux. **Menu → Reset all settings** goes back
to the defaults.

## Shapes

| Key | Shapes (press again to cycle) |
|---|---|
| `1` | Cube, Octahedron |
| `2` | Pyramid, Cone |
| `3` | Sphere, Icosahedron |
| `4` | Hexagon, Octagon, Star |
| `5` | Cylinder, Helix |
| `6` | Torus, Torus Knot |
| `7` | Mobius Strip, Trefoil Knot |
| `8` | Klein 1 (bottle), Klein 2 (figure-8) |
| `9` | Lorenz attractor |
| `0` | Mandelbrot, Julia (height fields) |

## Versions

`shapes_v10.py` is the current version, a single self-contained file. Each
version is developed as a new numbered copy; older ones are kept outside
the repo (they are still in the git history).

## Build

PyInstaller can only build for the system it runs on. On each system, run

    pyinstaller ASCII3DShapes.spec

or `./build_mac.sh` on a Mac. The result is in `dist/`: a folder with
`ASCII3DShapes.exe` and `ASCII3DShapes-terminal.exe` on Windows,
`ASCII3DShapes.app` on macOS, and an `ASCII3DShapes` folder on Linux.

GitHub Actions builds all three and test-starts each one whenever a version
tag is pushed (`git tag v10.0 && git push origin v10.0`), or when **Build
apps** is run by hand from the Actions tab. It also tests the installer on
each system.

The spec builds the version named in its `SCRIPT` line, so update that line
when a newer version should ship.
