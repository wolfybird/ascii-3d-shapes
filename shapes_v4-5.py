#!/usr/bin/env python3
"""
shapes.py – ASCII 3D Shape Renderer

History / Changelog
────────────────────────────────────────────────────────
v0.x (GPT-3 era, ~2023)
    • Single rotating cube in ASCII
    • Basic projection, no scaling
    • Zoom added later, then extra shapes (sphere/pyramid)
    • Functions sometimes nested/duplicated, some bugs
      (e.g., draw_cube logic leaking into print_line)

v1.0 (This rebuild, GPT-5.1 era, 2025-11)
    • Clean separation of:
        - Vector math
        - Projection
        - Shape generation
        - Drawing / rendering
    • Global scale + FOV
    • Multiple shapes:
        - Cube
        - Pyramid
        - Sphere
        - Torus
        - Möbius strip
        - Klein bottle (figure-8 style embedding)
    • Random automatic shape switching

v1.1 (2025-11)
    • Increased FOV ceiling to 100.0 and updated prompts/clamps
    • Added audio-reactive config flag & keyboard/menu toggle ('a')
    • Stubbed get_audio_features()/apply_audio_reactivity() hooks for
      future RMS / spectral-centroid driven visuals
"""

import math
import os
import random
import sys
import time
from dataclasses import dataclass
from typing import Callable, List, Tuple, Optional

# ─────────────────────────────────────────────────────
# Terminal / ANSI helpers
# ─────────────────────────────────────────────────────

CLEAR_CMD = "cls" if os.name == "nt" else "clear"

# Some basic ANSI colors – these are optional; color can be toggled.
COLORS = [
    "\033[38;5;196m",  # red
    "\033[38;5;202m",  # orange
    "\033[38;5;226m",  # yellow
    "\033[38;5;46m",   # green
    "\033[38;5;51m",   # cyan
    "\033[38;5;21m",   # blue
    "\033[38;5;201m",  # magenta
]
COLOR_RESET = "\033[0m"

# ─────────────────────────────────────────────────────
# Global “base” rendering parameters
# (Width/height can be scaled; FOV is also configurable.)
# ─────────────────────────────────────────────────────

BASE_WIDTH = 80
BASE_HEIGHT = 40

WIDTH = BASE_WIDTH
HEIGHT = BASE_HEIGHT
FOV = 4.0
SCALE = 1.0

# Characters for shapes / shading
CUBE_CHAR = "+"
SPHERE_CHAR = "."
PYRAMID_CHAR = "^"
PYRAMID_LINE_CHAR = "`~"

# ─────────────────────────────────────────────────────
# Config Dataclass
# ─────────────────────────────────────────────────────

@dataclass
class Config:
    scale: float = 1.0
    fov: float = 4.0
    rot_speed_x: float = 0.06
    rot_speed_y: float = 0.08
    brightness_enabled: bool = True
    color_enabled: bool = True
    auto_switch_seconds: float = 5.0
    paused: bool = False
    audio_reactive: bool = False   # NEW: audio-react flag


config = Config()

# ─────────────────────────────────────────────────────
# 3D Vector and Projection
# ─────────────────────────────────────────────────────

class Vec3:
    __slots__ = ("x", "y", "z")

    def __init__(self, x: float, y: float, z: float):
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)

    def rotate_x(self, angle: float) -> "Vec3":
        c = math.cos(angle)
        s = math.sin(angle)
        y = self.y * c - self.z * s
        z = self.y * s + self.z * c
        return Vec3(self.x, y, z)

    def rotate_y(self, angle: float) -> "Vec3":
        c = math.cos(angle)
        s = math.sin(angle)
        z = self.z * c - self.x * s
        x = self.z * s + self.x * c
        return Vec3(x, self.y, z)

    def rotate_z(self, angle: float) -> "Vec3":
        c = math.cos(angle)
        s = math.sin(angle)
        x = self.x * c - self.y * s
        y = self.x * s + self.y * c
        return Vec3(x, y, self.z)

    def project(self, width: int, height: int, fov: float, distance: float) -> Tuple[int, int, float]:
        # Simple perspective projection
        denom = (self.z + distance)
        if denom == 0:
            denom = 1e-6
        factor = fov / denom
        x = self.x * factor + width / 2
        y = -self.y * factor + height / 2
        return int(x), int(y), self.z


# ─────────────────────────────────────────────────────
# Math / Utility
# ─────────────────────────────────────────────────────

def clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def get_audio_features():
    """
    Placeholder for audio-reactive hooks.

    Intended usage:
      • Compute RMS (loudness) and spectral centroid from live audio
        (e.g., via sounddevice/pyaudio + numpy/scipy).
      • Return a pair (rms, centroid_hz).

    For now, this returns (None, None) so the rest of the script behaves
    exactly as before until you wire in real audio code.
    """
    return None, None


def apply_audio_reactivity(cfg: "Config", rms, centroid_hz):
    """
    Map audio features onto visual parameters.

    This is a *sketch* only – edit freely once you have real
    (rms, centroid_hz) values coming in. Example ideas:

      • Use RMS to modulate overall scale or rotation speed.
      • Use spectral centroid to bias FOV or shape choice.

    Right now this is a no-op if features are missing.
    """
    if rms is None or centroid_hz is None:
        return

    # Example (commented out – enable/tune once audio is wired up):
    # loudness = max(0.0, min(1.0, rms))  # assume normalized 0–1
    # cfg.scale = 0.5 + loudness * 2.0
    # cfg.rot_speed_x = 0.02 + loudness * 0.2
    # cfg.rot_speed_y = 0.02 + loudness * 0.2
    # # Map centroid (in Hz) roughly into a FOV band:
    # cfg.fov = clamp(0.5 + (centroid_hz / 8000.0) * 40.0, 0.5, 100.0)


def depth_to_char(base_char: str, z: float) -> str:
    if not config.brightness_enabled:
        return base_char
    # Map z to brightness; assume z in approx [-3, 3]
    # We just approximate a set of characters by "distance"
    shades = " .:-=+*#%@"
    # Normalize z into [0,1]
    t = (z + 3.0) / 6.0
    t = clamp(t, 0.0, 1.0)
    idx = int(t * (len(shades) - 1))
    ch = shades[idx]
    return ch if ch != " " else base_char


# ─────────────────────────────────────────────────────
# Shape Generators
# ─────────────────────────────────────────────────────

def gen_cube_points(step: float = 0.5) -> List[Vec3]:
    pts = []
    for x in frange(-1, 1, step):
        for y in frange(-1, 1, step):
            pts.append(Vec3(x, y, -1))
            pts.append(Vec3(x, y, 1))
    for x in frange(-1, 1, step):
        for z in frange(-1, 1, step):
            pts.append(Vec3(x, -1, z))
            pts.append(Vec3(x, 1, z))
    for y in frange(-1, 1, step):
        for z in frange(-1, 1, step):
            pts.append(Vec3(-1, y, z))
            pts.append(Vec3(1, y, z))
    return pts


def gen_pyramid_points(step: float = 0.5) -> List[Vec3]:
    # Simple square pyramid with base on y=-1, apex at y=1
    pts = []
    base_y = -1.0
    apex = Vec3(0, 1, 0)
    # Base square
    for x in frange(-1, 1, step):
        for z in frange(-1, 1, step):
            pts.append(Vec3(x, base_y, z))
    # Edges to apex
    corners = [
        Vec3(-1, base_y, -1),
        Vec3(1, base_y, -1),
        Vec3(1, base_y, 1),
        Vec3(-1, base_y, 1),
    ]
    for c in corners:
        for t in frange(0, 1, step):
            pts.append(Vec3(
                c.x + (apex.x - c.x) * t,
                c.y + (apex.y - c.y) * t,
                c.z + (apex.z - c.z) * t,
            ))
    return pts


def gen_sphere_points(step_theta: float = math.pi / 16, step_phi: float = math.pi / 16) -> List[Vec3]:
    pts = []
    for theta in frange(0, math.pi, step_theta):
        for phi in frange(0, 2 * math.pi, step_phi):
            x = math.sin(theta) * math.cos(phi)
            y = math.cos(theta)
            z = math.sin(theta) * math.sin(phi)
            pts.append(Vec3(x, y, z))
    return pts


def gen_torus_points(R: float = 1.0, r: float = 0.4,
                     step_u: float = math.pi / 16,
                     step_v: float = math.pi / 16) -> List[Vec3]:
    pts = []
    for u in frange(0, 2 * math.pi, step_u):
        for v in frange(0, 2 * math.pi, step_v):
            x = (R + r * math.cos(v)) * math.cos(u)
            y = (R + r * math.cos(v)) * math.sin(u)
            z = r * math.sin(v)
            pts.append(Vec3(x, y, z))
    return pts


def gen_mobius_points(step_u: float = math.pi / 32,
                      step_v: float = 0.2) -> List[Vec3]:
    pts = []
    for u in frange(0, 2 * math.pi, step_u):
        for v in frange(-0.5, 0.5, step_v):
            x = (1 + (v * math.cos(u / 2))) * math.cos(u)
            y = (1 + (v * math.cos(u / 2))) * math.sin(u)
            z = v * math.sin(u / 2)
            pts.append(Vec3(x, y, z))
    return pts


def gen_klein_points(step_u: float = math.pi / 32,
                     step_v: float = math.pi / 32) -> List[Vec3]:
    # Figure-8 Klein bottle embedding (approx.)
    pts = []
    for u in frange(0, 2 * math.pi, step_u):
        for v in frange(0, 2 * math.pi, step_v):
            # A simple Klein-ish param; not perfect mathematics, but visually interesting.
            r = 0.5 * (1 + math.cos(u))
            x = (r * math.cos(v))
            y = (r * math.sin(v))
            z = 0.5 * math.sin(u)
            pts.append(Vec3(x, y, z))
    return pts


def frange(start: float, stop: float, step: float) -> List[float]:
    vals = []
    x = start
    # Avoid infinite loops: step must not be 0.
    if step == 0:
        return [start]
    if step > 0:
        while x <= stop:
            vals.append(x)
            x += step
    else:
        while x >= stop:
            vals.append(x)
            x += step
    return vals


# Pre-generate shape point clouds at unit scale
SHAPE_POINTS = {
    "Cube": gen_cube_points(0.4),
    "Pyramid": gen_pyramid_points(0.4),
    "Sphere": gen_sphere_points(),
    "Torus": gen_torus_points(),
    "Mobius": gen_mobius_points(),
    "Klein": gen_klein_points(),
}

SHAPE_NAMES = list(SHAPE_POINTS.keys())
SHAPE_COLORS = COLORS  # reuse

# ─────────────────────────────────────────────────────
# Drawing Functions
# ─────────────────────────────────────────────────────

def draw_pointcloud(points: List[Vec3], angle_x: float, angle_y: float,
                    base_char: str) -> None:
    """
    Draws only points (no explicit edges).
    """
    distance = 3.0
    # buffer for the frame
    buf = [[" " for _ in range(WIDTH)] for _ in range(HEIGHT)]
    zbuf = [[float("inf") for _ in range(WIDTH)] for _ in range(HEIGHT)]

    for p in points:
        # scale
        px, py, pz = p.x * config.scale, p.y * config.scale, p.z * config.scale
        v = Vec3(px, py, pz).rotate_x(angle_x).rotate_y(angle_y)
        sx, sy, z = v.project(WIDTH, HEIGHT, config.fov, distance)
        if 0 <= sx < WIDTH and 0 <= sy < HEIGHT:
            if z < zbuf[sy][sx]:
                zbuf[sy][sx] = z
                buf[sy][sx] = depth_to_char(base_char, z)

    # print buffer
    for row in buf:
        sys.stdout.write("".join(row) + "\n")


def draw_wireframe(points: List[Vec3], angle_x: float, angle_y: float,
                   base_char: str) -> None:
    """
    Simple "wireframe" by joining near-neighbor points in the param grid.
    For simplicity, we treat the point list as ordered in some param loops,
    and connect sequential points in that order.
    """
    distance = 3.0
    buf = [[" " for _ in range(WIDTH)] for _ in range(HEIGHT)]
    zbuf = [[float("inf") for _ in range(WIDTH)] for _ in range(HEIGHT)]

    projected: List[Tuple[int, int, float]] = []
    for p in points:
        px, py, pz = p.x * config.scale, p.y * config.scale, p.z * config.scale
        v = Vec3(px, py, pz).rotate_x(angle_x).rotate_y(angle_y)
        sx, sy, z = v.project(WIDTH, HEIGHT, config.fov, distance)
        projected.append((sx, sy, z))

    def draw_line(x0, y0, x1, y1, z0, z1):
        dx = x1 - x0
        dy = y1 - y0
        steps = max(abs(dx), abs(dy))
        if steps == 0:
            if 0 <= x0 < WIDTH and 0 <= y0 < HEIGHT:
                if z0 < zbuf[y0][x0]:
                    zbuf[y0][x0] = z0
                    buf[y0][x0] = depth_to_char(base_char, z0)
            return
        for i in range(steps + 1):
            t = i / steps
            x = int(round(x0 + dx * t))
            y = int(round(y0 + dy * t))
            z = z0 * (1 - t) + z1 * t
            if 0 <= x < WIDTH and 0 <= y < HEIGHT:
                if z < zbuf[y][x]:
                    zbuf[y][x] = z
                    buf[y][x] = depth_to_char(base_char, z)

    for i in range(len(projected) - 1):
        x0, y0, z0 = projected[i]
        x1, y1, z1 = projected[i + 1]
        draw_line(x0, y0, x1, y1, z0, z1)

    for row in buf:
        sys.stdout.write("".join(row) + "\n")


# Map shape index to draw function & base character
def draw_shape(angle_x: float, angle_y: float, shape_name: str) -> None:
    points = SHAPE_POINTS[shape_name]
    # For now we always use pointcloud for most shapes; you can later
    # toggle between draw_pointcloud and draw_wireframe.
    if shape_name == "Sphere":
        base_char = SPHERE_CHAR
    elif shape_name == "Pyramid":
        base_char = PYRAMID_CHAR
    else:
        base_char = CUBE_CHAR

    draw_pointcloud(points, angle_x, angle_y, base_char)


# For menu mapping
SHAPES: List[Tuple[str, Callable[[float, float], None]]] = [
    ("Cube",      lambda ax, ay: draw_shape(ax, ay, "Cube")),
    ("Pyramid",   lambda ax, ay: draw_shape(ax, ay, "Pyramid")),
    ("Sphere",    lambda ax, ay: draw_shape(ax, ay, "Sphere")),
    ("Torus",     lambda ax, ay: draw_shape(ax, ay, "Torus")),
    ("Mobius",    lambda ax, ay: draw_shape(ax, ay, "Mobius")),
    ("Klein",     lambda ax, ay: draw_shape(ax, ay, "Klein")),
]

# Default: first shape
config.shape_index: int = 0


# ─────────────────────────────────────────────────────
# Input handling (non-blocking keypress)
# ─────────────────────────────────────────────────────

def get_key_nonblocking() -> Optional[str]:
    """
    Basic non-blocking key read. On Windows this uses msvcrt;
    on POSIX it uses termios/select.
    """
    if os.name == "nt":
        import msvcrt
        if msvcrt.kbhit():
            ch = msvcrt.getch()
            try:
                return ch.decode("utf-8")
            except UnicodeDecodeError:
                return None
        return None
    else:
        import sys
        import select
        import termios
        import tty

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            r, _, _ = select.select([fd], [], [], 0.0)
            if r:
                ch = sys.stdin.read(1)
                return ch
            return None
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


# ─────────────────────────────────────────────────────
# Menu UI
# ─────────────────────────────────────────────────────

def show_help_overlay():
    # A little in-frame legend at the top
    sys.stdout.write("\033[1;1H")  # move to row 1, col 1
    sys.stdout.write(
        "ASCII Shapes v1.1 | "
        "Current shape: {} | Scale: {:.2f} | FOV: {:.2f} | RotX: {:.3f}, RotY: {:.3f}\n".format(
            SHAPES[config.shape_index][0],
            config.scale,
            config.fov,
            config.rot_speed_x,
            config.rot_speed_y,
        )
    )
    sys.stdout.write(
        "Controls: "
        "[space]=pause/resume  m=menu  q=quit  1-6=shape  "
        "+/-=scale  [ / ]=speed  b=brightness  c=color  a=audio-react\n"
    )


def menu_screen():
    os.system(CLEAR_CMD)
    print("ASCII 3D Shapes – Menu")
    print("======================")
    print()
    print(f"Current shape:   {SHAPES[config.shape_index][0]}")
    print(f"Scale:           {config.scale:.2f}")
    print(f"FOV:             {config.fov:.2f}")
    print(f"Rot speed X:     {config.rot_speed_x:.3f}")
    print(f"Rot speed Y:     {config.rot_speed_y:.3f}")
    print(f"Brightness:      {'ON' if config.brightness_enabled else 'OFF'}")
    print(f"Color:           {'ON' if config.color_enabled else 'OFF'}")
    print(f"Auto switch:     {config.auto_switch_seconds:.1f} s")
    print(f"Audio reactive:  {'ON' if getattr(config, 'audio_reactive', False) else 'OFF'}")
    print()
    print("Controls in menu:")
    print("  1-6   : select shape")
    print("  + / - : scale up/down")
    print("  f / F : FOV down/up")
    print("  [ / ] : rotate slower/faster")
    print("  b     : toggle brightness")
    print("  c     : toggle color")
    print("  a     : toggle audio-react (stub)")
    print("  s / S : auto-switch slower/faster")
    print("  r     : reset angles")
    print("  x     : exit menu")
    print("  q     : quit program entirely")


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
            config.scale = min(3.0, config.scale * 1.1)

        elif ch == "-":
            config.scale = max(0.05, config.scale / 1.1)

        elif ch == "f":
            config.fov = max(0.2, config.fov - 0.2)
        elif ch == "F":
            config.fov = min(100.0, config.fov + 0.2)

        elif ch == "a":
            config.audio_reactive = not config.audio_reactive

        elif ch == "[":
            config.rot_speed_x *= 0.9
            config.rot_speed_y *= 0.9
        elif ch == "]":
            config.rot_speed_x *= 1.1
            config.rot_speed_y *= 1.1

        elif ch == "b":
            config.brightness_enabled = not config.brightness_enabled

        elif ch == "c":
            config.color_enabled = not config.color_enabled

        elif ch == "s":
            config.auto_switch_seconds = max(1.0, config.auto_switch_seconds - 0.5)
        elif ch == "S":
            config.auto_switch_seconds = min(30.0, config.auto_switch_seconds + 0.5)

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
    global WIDTH, HEIGHT, FOV, SCALE

    # Initial interactive scale prompt
    try:
        val = input("Enter scale factor (0.05–3.0) [default 1.0]: ").strip()
        if val:
            SCALE = clamp(float(val), 0.05, 3.0)
    except Exception:
        SCALE = 1.0

    config.scale = SCALE

    # Optional FOV prompt
    try:
        val = input("Enter FOV (0.5–100.0) [default 4.0]: ").strip()
        if val:
            FOV = clamp(float(val), 0.5, 100.0)
    except Exception:
        FOV = 4.0

    config.fov = FOV

    WIDTH = BASE_WIDTH
    HEIGHT = BASE_HEIGHT

    angle_x = 0.0
    angle_y = 0.0
    last_switch = time.time()

    os.system(CLEAR_CMD)

    while True:
        # Handle keypresses
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
                config.scale = min(3.0, config.scale * 1.1)
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
            elif ch == "c":
                config.color_enabled = not config.color_enabled
            elif ch == "a":
                config.audio_reactive = not config.audio_reactive

        # Auto shape switching
        now = time.time()
        if now - last_switch > config.auto_switch_seconds:
            config.shape_index = random.randrange(len(SHAPES))
            last_switch = now

        # Draw frame
        os.system(CLEAR_CMD)
        sys.stdout.write("\033[0;0H")
        show_help_overlay()

        name, draw_func = SHAPES[config.shape_index]

        if config.color_enabled:
            color = SHAPE_COLORS[config.shape_index % len(SHAPE_COLORS)]
            sys.stdout.write(color)

        if not config.paused:
            draw_func(angle_x, angle_y)
        else:
            draw_func(angle_x, angle_y)  # still draw, just don’t update angles

        if config.color_enabled:
            sys.stdout.write(COLOR_RESET)

        # Update angles
        if not config.paused:
            angle_x += config.rot_speed_x
            angle_y += config.rot_speed_y

        # Optional audio-reactive update (stub)
        if getattr(config, "audio_reactive", False):
            rms, centroid = get_audio_features()
            apply_audio_reactivity(config, rms, centroid)

        sys.stdout.flush()
        time.sleep(0.03)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        os.system(CLEAR_CMD)
        print("Interrupted by user.")
    