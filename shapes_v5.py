#!/usr/bin/env python3
"""
shapes_v5.py – ASCII 3D Shape Renderer (wireframe & pointcloud, v5)

History / Changelog
────────────────────────────────────────────────────────
v0.x (GPT-3 era, ~2023)
    • Single rotating cube in ASCII
    • Basic projection, no scaling
    • Zoom added later, then extra shapes (sphere/pyramid)
    • Functions sometimes nested/duplicated, some bugs
      (e.g., draw_cube logic leaking into print_line)

v1.0 (Rebuild, GPT-5.1 era, 2025-11)
    • Clean separation of:
        - Vector math
        - Projection
        - Shape generation
        - Drawing / rendering
    • Global scale + FOV
    • Multiple shapes:
        - Cube, Pyramid, Sphere, Torus, Möbius strip, Klein bottle
    • Random automatic shape switching
    • Keyboard controls for pause, shape selection, speed, FOV, scale
    • Simple distance-based brightness + optional ANSI color

v4.x
    • Added wireframe vs point-cloud modes
    • Adjustable densities for sampling parametric surfaces
    • Multiple brightness ramps (shading models)
    • Color rotation option in addition to fixed per-shape colors

v5.0 (this version)
    • FOV range extended (0.5–100) for large / hi-res terminals
    • 4K-friendly: auto-detects terminal rows/cols and adapts
    • Restores all 6 shapes with wire/point options:
        - Cube, Pyramid, Sphere, Torus, Möbius strip, Klein bottle
    • Realtime menu:
        - Change shape, FOV, scale, density, speed
        - Toggle wireframe vs pointcloud
        - Toggle brightness & choose ramp
        - Toggle static vs rotating colors
        - Stub hook for future audio-reactive control
"""

import os
import sys
import time
import math
import random
import shutil
from typing import List, Tuple, Callable, Optional

CLEAR_CMD = "cls" if os.name == "nt" else "clear"

# Base logical size (actual used size adapts to terminal)
BASE_WIDTH = 80
BASE_HEIGHT = 40

# Per-shape base sampling densities (scaled by config.density_scale)
SPHERE_BASE_DETAIL = 22
TORUS_BASE_NU = 32
TORUS_BASE_NV = 16
MOBIUS_BASE_NU = 80
MOBIUS_BASE_NV = 8
KLEIN_BASE_NU = 50
KLEIN_BASE_NV = 20

# ANSI color codes (can be disabled / rotated)
SHAPE_COLORS = [
    "\033[38;5;45m",   # cube – cyan
    "\033[38;5;214m",  # pyramid – orange
    "\033[38;5;82m",   # sphere – green
    "\033[38;5;201m",  # torus – magenta
    "\033[38;5;189m",  # mobius – light purple
    "\033[38;5;160m",  # klein – red
]
COLOR_RESET = "\033[0m"

# Characters per shape
CUBE_CHAR = "+"
PYRAMID_CHAR = "^"
SPHERE_CHAR = "."
TORUS_CHAR = "."
MOBIUS_CHAR = "."
KLEIN_CHAR = "."

# Brightness ramps (dark → bright)
BRIGHTNESS_RAMPS = [
    " .:-=+*#%@",       # classic
    " .:+*#",           # sharp
    " ░▒▓█",            # blocky (terminal dependent)
    " .oO@",            # bubbly
    " `'\",^*#",        # noisy
]
DEFAULT_RAMP_INDEX = 0

# These get set in main() based on terminal size and user input
WIDTH = BASE_WIDTH
HEIGHT = BASE_HEIGHT


class Config:
    def __init__(self):
        self.scale: float = 1.0
        self.base_scale: float = 1.0  # for future audio-reactive use
        self.fov: float = 4.0
        self.rot_speed_x: float = 0.06
        self.rot_speed_y: float = 0.05
        self.color_enabled: bool = True
        self.color_rotate: bool = False
        self.color_offset: int = 0
        self.brightness_enabled: bool = True
        self.ramp_index: int = DEFAULT_RAMP_INDEX
        self.render_mode: str = "wire"  # "wire" or "points"
        self.density_scale: float = 1.0
        self.shape_index: int = 0
        self.auto_switch_seconds: float = 7.0
        self.paused: bool = False
        # Audio-reactive stub
        self.audio_reactive: bool = False
        self.audio_rms: float = 0.0
        self.audio_centroid: float = 0.0


config = Config()


# ─────────────────────────────────────────────────────
# Vector & Projection
# ─────────────────────────────────────────────────────

class Vector3D:
    def __init__(self, x: float, y: float, z: float):
        self.x = x
        self.y = y
        self.z = z

    def rotateX(self, angle: float) -> "Vector3D":
        c = math.cos(angle)
        s = math.sin(angle)
        y = self.y * c - self.z * s
        z = self.y * s + self.z * c
        return Vector3D(self.x, y, z)

    def rotateY(self, angle: float) -> "Vector3D":
        c = math.cos(angle)
        s = math.sin(angle)
        z = self.z * c - self.x * s
        x = self.z * s + self.x * c
        return Vector3D(x, self.y, z)

    def project(self) -> Tuple[int, int, float]:
        """Perspective project using global WIDTH/HEIGHT, config.fov/scale."""
        depth_offset = 4.0
        denom = self.z + depth_offset
        if denom == 0:
            denom = 1e-4
        factor = config.fov / denom
        x = int(self.x * factor * config.scale + WIDTH // 2)
        y = int(-self.y * factor * config.scale + HEIGHT // 2)
        return x, y, self.z


# ─────────────────────────────────────────────────────
# Input Handling (Non-blocking)
# ─────────────────────────────────────────────────────

def get_key_nonblocking() -> Optional[str]:
    """Return a single character if available, else None (non-blocking)."""
    if os.name == "nt":
        try:
            import msvcrt
        except ImportError:
            return None
        if msvcrt.kbhit():
            ch = msvcrt.getwch()
            return ch
        return None
    else:
        import select
        import termios
        import tty

        if not sys.stdin.isatty():
            return None

        fd = sys.stdin.fileno()
        dr, _, _ = select.select([sys.stdin], [], [], 0)
        if not dr:
            return None

        old_settings = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return ch


# ─────────────────────────────────────────────────────
# Drawing helpers
# ─────────────────────────────────────────────────────

def clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def get_brightness_char(z: float) -> str:
    ramp = BRIGHTNESS_RAMPS[config.ramp_index % len(BRIGHTNESS_RAMPS)]
    # Map z in approx [-3,3] → [0,1]
    z_norm = (z + 3.0) / 6.0
    z_norm = clamp(z_norm, 0.0, 1.0)
    idx = int(z_norm * (len(ramp) - 1))
    return ramp[idx]


def print_point(x: int, y: int, base_char: str, z: float = 0.0):
    if x < 1 or x > WIDTH or y < 1 or y > HEIGHT:
        return

    ch = base_char
    if config.brightness_enabled:
        ch = get_brightness_char(z)

    sys.stdout.write(f"\033[{y};{x}H{ch}")


def print_line(
    start: Tuple[int, int, float],
    end: Tuple[int, int, float],
    base_char: str
):
    x1, y1, z1 = start
    x2, y2, z2 = end
    dx = abs(x2 - x1)
    dy = abs(y2 - y1)
    steps = max(dx, dy)
    if steps == 0:
        print_point(x1, y1, base_char, (z1 + z2) / 2.0)
        return
    for i in range(steps + 1):
        t = i / steps
        x = int(x1 * (1 - t) + x2 * t)
        y = int(y1 * (1 - t) + y2 * t)
        z = z1 * (1 - t) + z2 * t
        print_point(x, y, base_char, z)


# ─────────────────────────────────────────────────────
# Shapes
# ─────────────────────────────────────────────────────

# 1) Cube
def get_cube_vertices() -> List[Vector3D]:
    s = 1.0
    return [
        Vector3D(-s, -s, -s),
        Vector3D(s, -s, -s),
        Vector3D(s, s, -s),
        Vector3D(-s, s, -s),
        Vector3D(-s, -s, s),
        Vector3D(s, -s, s),
        Vector3D(s, s, s),
        Vector3D(-s, s, s),
    ]


def draw_cube(ax: float, ay: float):
    vs3 = [v.rotateX(ax).rotateY(ay) for v in get_cube_vertices()]
    vs2 = [v.project() for v in vs3]

    edges = [
        (0, 1), (1, 2), (2, 3), (3, 0),
        (4, 5), (5, 6), (6, 7), (7, 4),
        (0, 4), (1, 5), (2, 6), (3, 7),
    ]

    if config.render_mode == "points":
        for x, y, z in vs2:
            print_point(x, y, CUBE_CHAR, z)
    else:
        for a, b in edges:
            print_line(vs2[a], vs2[b], CUBE_CHAR)


# 2) Pyramid
def get_pyramid_vertices() -> List[Vector3D]:
    s = 1.3
    return [
        Vector3D(0.0, s, 0.0),        # top
        Vector3D(-s, -s, s),
        Vector3D(s, -s, s),
        Vector3D(s, -s, -s),
        Vector3D(-s, -s, -s),
    ]


def draw_pyramid(ax: float, ay: float):
    vs3 = [v.rotateX(ax).rotateY(ay) for v in get_pyramid_vertices()]
    vs2 = [v.project() for v in vs3]

    if config.render_mode == "points":
        for x, y, z in vs2:
            print_point(x, y, PYRAMID_CHAR, z)
        return

    # wireframe
    base_indices = [1, 2, 3, 4, 1]
    for i in range(len(base_indices) - 1):
        print_line(vs2[base_indices[i]], vs2[base_indices[i+1]], PYRAMID_CHAR)
    for i in range(1, 5):
        print_line(vs2[0], vs2[i], PYRAMID_CHAR)


# 3) Sphere (point cloud)
def get_sphere_points() -> List[Vector3D]:
    detail = max(6, int(SPHERE_BASE_DETAIL * config.density_scale))
    pts = []
    r = 1.2
    for i in range(detail):
        theta = math.pi * (i / (detail - 1))
        for j in range(detail * 2):
            phi = 2 * math.pi * (j / (detail * 2))
            x = r * math.sin(theta) * math.cos(phi)
            y = r * math.sin(theta) * math.sin(phi)
            z = r * math.cos(theta)
            pts.append(Vector3D(x, y, z))
    return pts


def draw_sphere(ax: float, ay: float):
    pts = get_sphere_points()
    for v in pts:
        v2 = v.rotateX(ax).rotateY(ay)
        x, y, z = v2.project()
        print_point(x, y, SPHERE_CHAR, z)


# 4) Torus (point cloud)
def get_torus_points() -> List[Vector3D]:
    nu = max(8, int(TORUS_BASE_NU * config.density_scale))
    nv = max(4, int(TORUS_BASE_NV * config.density_scale))
    R = 1.5
    r = 0.6
    pts = []
    for i in range(nu):
        u = 2 * math.pi * (i / nu)
        cu = math.cos(u)
        su = math.sin(u)
        for j in range(nv):
            v = 2 * math.pi * (j / nv)
            cv = math.cos(v)
            sv = math.sin(v)
            x = (R + r * cv) * cu
            y = (R + r * cv) * su
            z = r * sv
            pts.append(Vector3D(x, y, z))
    return pts


def draw_torus(ax: float, ay: float):
    pts = get_torus_points()
    for v in pts:
        v2 = v.rotateX(ax).rotateY(ay)
        x, y, z = v2.project()
        print_point(x, y, TORUS_CHAR, z)


# 5) Möbius strip (point cloud)
def get_mobius_points() -> List[Vector3D]:
    nu = max(20, int(MOBIUS_BASE_NU * config.density_scale))
    nv = max(4, int(MOBIUS_BASE_NV * config.density_scale))
    pts = []
    R = 1.5
    wmax = 0.5
    for i in range(nu):
        u = 2 * math.pi * (i / nu)
        cu = math.cos(u)
        su = math.sin(u)
        for j in range(nv):
            w = wmax * (2 * j / (nv - 1) - 1)
            x = (R + w * math.cos(u / 2)) * cu
            y = (R + w * math.cos(u / 2)) * su
            z = w * math.sin(u / 2)
            pts.append(Vector3D(x, y, z))
    return pts


def draw_mobius(ax: float, ay: float):
    pts = get_mobius_points()
    for v in pts:
        v2 = v.rotateX(ax).rotateY(ay)
        x, y, z = v2.project()
        print_point(x, y, MOBIUS_CHAR, z)


# 6) Klein bottle (figure-8 embedding)
def get_klein_points() -> List[Vector3D]:
    nu = max(20, int(KLEIN_BASE_NU * config.density_scale))
    nv = max(8, int(KLEIN_BASE_NV * config.density_scale))
    pts = []
    for i in range(nu):
        u = 2 * math.pi * (i / nu)
        for j in range(nv):
            v = 2 * math.pi * (j / nv)
            if 0 <= u < math.pi:
                x = (2.5 - 1.5 * math.cos(u)) * math.cos(v)
                z = (2.5 - 1.5 * math.cos(u)) * math.sin(v)
            else:
                x = (2.5 - 1.5 * math.cos(u)) * math.cos(v + math.pi)
                z = (2.5 - 1.5 * math.cos(u)) * math.sin(v + math.pi)
            y = -1.5 * math.sin(u)
            pts.append(Vector3D(x * 0.4, y * 0.4, z * 0.4))
    return pts


def draw_klein(ax: float, ay: float):
    pts = get_klein_points()
    for v in pts:
        v2 = v.rotateX(ax).rotateY(ay)
        x, y, z = v2.project()
        print_point(x, y, KLEIN_CHAR, z)


SHAPES: List[Tuple[str, Callable[[float, float], None]]] = [
    ("Cube", draw_cube),
    ("Pyramid", draw_pyramid),
    ("Sphere", draw_sphere),
    ("Torus", draw_torus),
    ("Möbius Strip", draw_mobius),
    ("Klein Bottle", draw_klein),
]


# ─────────────────────────────────────────────────────
# Audio-reactive stub
# ─────────────────────────────────────────────────────

def update_audio_features_stub():
    """
    Placeholder for future audio-reactive control.

    Intended usage:
        - Compute RMS loudness and spectral centroid from a live audio buffer.
        - Normalize values (e.g., RMS in [0,1], centroid in [0,1]).
        - Assign:
            config.audio_rms = ...
            config.audio_centroid = ...

    This stub keeps values at 0 so it has no visual effect yet.
    """
    if not config.audio_reactive:
        return
    # For now we just keep zeros; hook real audio here later.
    config.audio_rms = 0.0
    config.audio_centroid = 0.0


# ─────────────────────────────────────────────────────
# UI / Menu
# ─────────────────────────────────────────────────────

def show_help_overlay():
    sys.stdout.write("\033[1;1H")
    sys.stdout.write(
        "[space]=pause  m=menu  q=quit  1-6=shape  "
        "+/-=scale  [/] speed  w=wire/points  d/D=density  "
        "b=bright  r=reset  R=ramp  c=color  h=rotColor  a=audioStub"
    )


def menu_screen():
    os.system(CLEAR_CMD)
    print("ASCII 3D Shapes v5 – Menu")
    print("────────────────────────────")
    print(f"Current shape: {config.shape_index+1} – {SHAPES[config.shape_index][0]}")
    print(f"Scale:          {config.scale:.3f}")
    print(f"FOV:            {config.fov:.3f}")
    print(f"Rot speed X:    {config.rot_speed_x:.3f}")
    print(f"Rot speed Y:    {config.rot_speed_y:.3f}")
    print(f"Density scale:  {config.density_scale:.3f}")
    print(f"Brightness:     {'ON' if config.brightness_enabled else 'OFF'}")
    print(f"Ramp index:     {config.ramp_index}")
    print(f"Color:          {'ON' if config.color_enabled else 'OFF'}")
    print(f"Color rotate:   {'ON' if config.color_rotate else 'OFF'}")
    print(f"Render mode:    {config.render_mode}")
    print(f"Auto switch:    {config.auto_switch_seconds:.1f} s")
    print(f"Audio reactive: {'ON' if config.audio_reactive else 'OFF'}")
    print()
    print("Controls in menu:")
    print("  1-6 : select shape")
    print("  + / - : scale up/down")
    print("  f / F : FOV down/up")
    print("  [ / ] : rotation speed slower/faster")
    print("  d / D : density down/up")
    print("  b     : toggle brightness")
    print("  r     : reset angles (applies after menu)")
    print("  w     : toggle wireframe/points (where applicable)")
    print("  c     : toggle color")
    print("  h     : toggle rotating colors")
    print("  R     : cycle brightness ramp")
    print("  a     : toggle audio-reactive stub")
    print("  s / S : auto-switch slower/faster")
    print("  x     : exit menu")
    print("  q     : quit program")
    print()
    print("Press a key…")


def run_menu() -> Optional[str]:
    """
    Returns:
        'reset_angles' if user chose reset,
        'quit' if they chose quit,
        None otherwise.
    """
    while True:
        menu_screen()
        ch = get_key_nonblocking()
        if ch is None:
            time.sleep(0.05)
            continue

        if ch in "123456":
            idx = int(ch) - 1
            if 0 <= idx < len(SHAPES):
                config.shape_index = idx

        elif ch == "+":
            config.scale = min(5.0, config.scale * 1.1)

        elif ch == "-":
            config.scale = max(0.05, config.scale / 1.1)

        elif ch == "f":
            config.fov = max(0.5, config.fov - 0.5)
        elif ch == "F":
            config.fov = min(100.0, config.fov + 0.5)

        elif ch == "[":
            config.rot_speed_x *= 0.9
            config.rot_speed_y *= 0.9
        elif ch == "]":
            config.rot_speed_x *= 1.1
            config.rot_speed_y *= 1.1

        elif ch == "d":
            config.density_scale = max(0.2, config.density_scale * 0.8)
        elif ch == "D":
            config.density_scale = min(4.0, config.density_scale * 1.25)

        elif ch == "b":
            config.brightness_enabled = not config.brightness_enabled

        elif ch == "w":
            config.render_mode = "points" if config.render_mode == "wire" else "wire"

        elif ch == "c":
            config.color_enabled = not config.color_enabled

        elif ch == "h":
            config.color_rotate = not config.color_rotate

        elif ch == "R":
            config.ramp_index = (config.ramp_index + 1) % len(BRIGHTNESS_RAMPS)

        elif ch == "a":
            config.audio_reactive = not config.audio_reactive

        elif ch == "s":
            config.auto_switch_seconds = max(1.0, config.auto_switch_seconds - 0.5)
        elif ch == "S":
            config.auto_switch_seconds = min(60.0, config.auto_switch_seconds + 0.5)

        elif ch == "r":
            return "reset_angles"

        elif ch == "x":
            return None

        elif ch == "q":
            return "quit"


# ─────────────────────────────────────────────────────
# Main Animation Loop
# ─────────────────────────────────────────────────────

def main():
    global WIDTH, HEIGHT

    # Detect terminal size for 4K / large displays
    size = shutil.get_terminal_size(fallback=(BASE_WIDTH, BASE_HEIGHT))
    WIDTH, HEIGHT = size.columns, size.lines
    # Leave a small margin at bottom for safety
    HEIGHT = max(HEIGHT - 1, 10)

    # Scale prompt
    try:
        val = input("Enter scale factor (0.001–2.0) [default 1.0]: ").strip()
        if val:
            config.scale = float(val)
            config.base_scale = config.scale
        else:
            config.scale = 1.0
            config.base_scale = 1.0
    except Exception:
        config.scale = 1.0
        config.base_scale = 1.0
    config.scale = clamp(config.scale, 0.001, 2.0)

    # FOV prompt (up to 100 now)
    try:
        val = input("Enter FOV (0.5–100.0) [default 4.0]: ").strip()
        if val:
            config.fov = float(val)
        else:
            config.fov = 4.0
    except Exception:
        config.fov = 4.0
    config.fov = clamp(config.fov, 0.5, 100.0)

    angle_x = 0.0
    angle_y = 0.0
    last_switch = time.time()

    # Hide cursor
    sys.stdout.write("\033[?25l")
    sys.stdout.flush()
    os.system(CLEAR_CMD)

    try:
        while True:
            update_audio_features_stub()

            ch = get_key_nonblocking()
            if ch:
                if ch == " ":
                    config.paused = not config.paused
                elif ch == "q":
                    os.system(CLEAR_CMD)
                    print("Goodbye.")
                    return
                elif ch in "123456":
                    idx = int(ch) - 1
                    if 0 <= idx < len(SHAPES):
                        config.shape_index = idx
                elif ch == "m":
                    result = run_menu()
                    os.system(CLEAR_CMD)
                    if result == "quit":
                        print("Goodbye.")
                        return
                    elif result == "reset_angles":
                        angle_x = angle_y = 0.0
                elif ch == "+":
                    config.scale = min(5.0, config.scale * 1.1)
                elif ch == "-":
                    config.scale = max(0.05, config.scale / 1.1)
                elif ch == "[":
                    config.rot_speed_x *= 0.9
                    config.rot_speed_y *= 0.9
                elif ch == "]":
                    config.rot_speed_x *= 1.1
                    config.rot_speed_y *= 1.1
                elif ch == "b":
                    config.brightness_enabled = not config.brightness_enabled
                elif ch == "w":
                    config.render_mode = "points" if config.render_mode == "wire" else "wire"
                elif ch == "c":
                    config.color_enabled = not config.color_enabled
                elif ch == "h":
                    config.color_rotate = not config.color_rotate
                elif ch == "R":
                    config.ramp_index = (config.ramp_index + 1) % len(BRIGHTNESS_RAMPS)
                elif ch == "d":
                    config.density_scale = max(0.2, config.density_scale * 0.8)
                elif ch == "D":
                    config.density_scale = min(4.0, config.density_scale * 1.25)
                elif ch == "a":
                    config.audio_reactive = not config.audio_reactive
                elif ch == "r":
                    angle_x = angle_y = 0.0
                elif ch == "s":
                    config.auto_switch_seconds = max(1.0, config.auto_switch_seconds - 0.5)
                elif ch == "S":
                    config.auto_switch_seconds = min(60.0, config.auto_switch_seconds + 0.5)

            # Auto shape switching
            now = time.time()
            if now - last_switch > config.auto_switch_seconds:
                config.shape_index = random.randrange(len(SHAPES))
                last_switch = now

            # Audio-reactive mapping stub (no-op for now)
            if config.audio_reactive:
                # Example of how you might map audio features later:
                # config.scale = clamp(config.base_scale * (1.0 + config.audio_rms), 0.1, 3.0)
                # config.rot_speed_y = 0.05 + 0.2 * config.audio_centroid
                pass

            os.system(CLEAR_CMD)
            sys.stdout.write("\033[0;0H")
            show_help_overlay()

            name, draw_func = SHAPES[config.shape_index]

            # Color handling
            if config.color_enabled:
                if config.color_rotate:
                    config.color_offset = (config.color_offset + 1) % len(SHAPE_COLORS)
                    color = SHAPE_COLORS[config.color_offset]
                else:
                    color = SHAPE_COLORS[config.shape_index % len(SHAPE_COLORS)]
                sys.stdout.write(color)

            # Draw shape
            draw_func(angle_x, angle_y)

            if config.color_enabled:
                sys.stdout.write(COLOR_RESET)

            if not config.paused:
                angle_x += config.rot_speed_x
                angle_y += config.rot_speed_y

            sys.stdout.flush()
            time.sleep(0.03)
    finally:
        # Show cursor again
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()
        os.system(CLEAR_CMD)
        print("Interrupted or finished.")


if __name__ == "__main__":
    main()
