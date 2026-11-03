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
    • Keyboard controls:
        - Space: pause / resume
        - m: open menu (change shape, speed, scale, FOV, etc.)
        - 1–6: jump directly to specific shape
        - q: quit
    • Simple distance-based brightness for point-cloud shapes
    • Optional ANSI color per shape (when terminal supports it)
    • Scale factor prompt to support many terminal sizes
"""

import os
import sys
import time
import math
import random
from typing import List, Tuple, Callable, Optional

# ─────────────────────────────────────────────────────
# Global / Config
# ─────────────────────────────────────────────────────

CLEAR_CMD = "cls" if os.name == "nt" else "clear"

# Default rendering window (scaled later)
BASE_WIDTH = 80
BASE_HEIGHT = 40

# ANSI color codes (can be disabled)
SHAPE_COLORS = [
    "\033[38;5;45m",   # cube – cyan-ish
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

# Brightness ramp (dark → bright)
BRIGHTNESS_CHARS = " .:-=+*#%@"

# We’ll fill these after reading user input
WIDTH = BASE_WIDTH
HEIGHT = BASE_HEIGHT
FOV = 4.0
SCALE = 1.0


class Config:
    def __init__(self):
        self.scale: float = 1.0
        self.fov: float = 4.0
        self.rot_speed_x: float = 0.06
        self.rot_speed_y: float = 0.05
        self.color_enabled: bool = True
        self.brightness_enabled: bool = True
        self.shape_index: int = 0
        self.auto_switch_seconds: float = 5.0
        self.paused: bool = False


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
        # Simple perspective; push scene away from camera a little
        depth_offset = 4.0
        denom = self.z + depth_offset
        if denom == 0:
            denom = 0.0001
        factor = config.fov / denom
        x = int(self.x * factor * config.scale + WIDTH // 2)
        y = int(-self.y * factor * config.scale + HEIGHT // 2)
        return x, y, self.z


# ─────────────────────────────────────────────────────
# Input Handling (Non-blocking)
# ─────────────────────────────────────────────────────

def get_key_nonblocking() -> Optional[str]:
    """Return a single character if available, else None."""
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

        fd = sys.stdin.fileno()
        # If stdin is not a TTY (e.g. piped), skip
        if not sys.stdin.isatty():
            return None

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


def depth_to_char(base_char: str, z: float) -> str:
    if not config.brightness_enabled:
        return base_char
    # Map z to brightness; assume z in approx [-3, 3]
    z_norm = (z + 3.0) / 6.0  # → [0, 1]
    z_norm = clamp(z_norm, 0.0, 1.0)
    idx = int(z_norm * (len(BRIGHTNESS_CHARS) - 1))
    return BRIGHTNESS_CHARS[idx]


def print_point(x: int, y: int, char: str, z: float = 0.0):
    if x < 1 or x > WIDTH or y < 1 or y > HEIGHT:
        return
    ch = depth_to_char(char, z)
    sys.stdout.write(f"\033[{y};{x}H{ch}")


def print_line(
    start: Tuple[int, int, float],
    end: Tuple[int, int, float],
    char: str
):
    x1, y1, z1 = start
    x2, y2, z2 = end
    dx = abs(x2 - x1)
    dy = abs(y2 - y1)
    steps = max(dx, dy)
    if steps == 0:
        print_point(x1, y1, char, (z1 + z2) / 2.0)
        return
    for i in range(steps + 1):
        t = i / steps
        x = int(x1 * (1 - t) + x2 * t)
        y = int(y1 * (1 - t) + y2 * t)
        z = z1 * (1 - t) + z2 * t
        print_point(x, y, char, z)


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
    verts3d = [v.rotateX(ax).rotateY(ay) for v in get_cube_vertices()]
    verts2d = [(*v.project(),) for v in verts3d]  # (x,y,z)

    edges = [
        (0, 1), (1, 2), (2, 3), (3, 0),
        (4, 5), (5, 6), (6, 7), (7, 4),
        (0, 4), (1, 5), (2, 6), (3, 7)
    ]
    for a, b in edges:
        print_line(verts2d[a], verts2d[b], CUBE_CHAR)


# 2) Pyramid
def get_pyramid_vertices() -> List[Vector3D]:
    s = 1.3
    return [
        Vector3D(0.0, s, 0.0),          # top
        Vector3D(-s, -s, s),           # base front-left
        Vector3D(s, -s, s),            # base front-right
        Vector3D(s, -s, -s),           # base back-right
        Vector3D(-s, -s, -s),          # base back-left
    ]


def draw_pyramid(ax: float, ay: float):
    vs3 = [v.rotateX(ax).rotateY(ay) for v in get_pyramid_vertices()]
    vs2 = [(*v.project(),) for v in vs3]

    # base (1-2-3-4-1)
    base_indices = [1, 2, 3, 4, 1]
    for i in range(len(base_indices) - 1):
        print_line(vs2[base_indices[i]], vs2[base_indices[i+1]], PYRAMID_CHAR)

    # sides (0 to 1..4)
    for i in range(1, 5):
        print_line(vs2[0], vs2[i], PYRAMID_CHAR)


# 3) Sphere (point cloud)
def get_sphere_points(detail: int = 22) -> List[Vector3D]:
    points = []
    r = 1.2
    for i in range(detail):
        theta = math.pi * (i / (detail - 1))  # 0..pi
        for j in range(detail * 2):
            phi = 2 * math.pi * (j / (detail * 2))  # 0..2pi
            x = r * math.sin(theta) * math.cos(phi)
            y = r * math.sin(theta) * math.sin(phi)
            z = r * math.cos(theta)
            points.append(Vector3D(x, y, z))
    return points


def draw_sphere(ax: float, ay: float):
    for v in get_sphere_points():
        v2 = v.rotateX(ax).rotateY(ay)
        x, y, z = v2.project()
        print_point(x, y, SPHERE_CHAR, z)


# 4) Torus (point cloud)
def get_torus_points(nu: int = 32, nv: int = 16) -> List[Vector3D]:
    R = 1.5  # major radius
    r = 0.6  # minor radius
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
    for v in get_torus_points():
        v2 = v.rotateX(ax).rotateY(ay)
        x, y, z = v2.project()
        print_point(x, y, TORUS_CHAR, z)


# 5) Möbius strip (point cloud)
def get_mobius_points(nu: int = 80, nv: int = 8) -> List[Vector3D]:
    pts = []
    R = 1.5
    wmax = 0.5
    for i in range(nu):
        u = 2 * math.pi * (i / nu)
        cu = math.cos(u)
        su = math.sin(u)
        for j in range(nv):
            w = wmax * (2 * j / (nv - 1) - 1)  # -wmax..wmax
            x = (R + w * math.cos(u / 2)) * cu
            y = (R + w * math.cos(u / 2)) * su
            z = w * math.sin(u / 2)
            pts.append(Vector3D(x, y, z))
    return pts


def draw_mobius(ax: float, ay: float):
    for v in get_mobius_points():
        v2 = v.rotateX(ax).rotateY(ay)
        x, y, z = v2.project()
        print_point(x, y, MOBIUS_CHAR, z)


# 6) Klein bottle (figure-8 style embedding)
def get_klein_points(nu: int = 50, nv: int = 20) -> List[Vector3D]:
    pts = []
    for i in range(nu):
        u = 2 * math.pi * (i / nu)
        for j in range(nv):
            v = 2 * math.pi * (j / nv)

            # Classic figure-8 Klein bottle embedding
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
    for v in get_klein_points():
        v2 = v.rotateX(ax).rotateY(ay)
        x, y, z = v2.project()
        print_point(x, y, KLEIN_CHAR, z)


# Registry of shapes
SHAPES: List[Tuple[str, Callable[[float, float], None]]] = [
    ("Cube", draw_cube),
    ("Pyramid", draw_pyramid),
    ("Sphere", draw_sphere),
    ("Torus", draw_torus),
    ("Möbius Strip", draw_mobius),
    ("Klein Bottle", draw_klein),
]


# ─────────────────────────────────────────────────────
# Menu / UI
# ─────────────────────────────────────────────────────

def show_help_overlay():
    sys.stdout.write("\033[1;1H")
    print(
        "[space]=pause/resume  m=menu  q=quit  1-6=shape  "
        "+/-=scale  [ / ]=speed  b=brightness  c=color"
    )


def menu_screen():
    os.system(CLEAR_CMD)
    print("ASCII 3D Shapes – Menu")
    print("────────────────────────────")
    print(f"Current shape: {config.shape_index+1} – {SHAPES[config.shape_index][0]}")
    print(f"Scale:          {config.scale:.3f}")
    print(f"FOV:            {config.fov:.3f}")
    print(f"Rot speed X:    {config.rot_speed_x:.3f}")
    print(f"Rot speed Y:    {config.rot_speed_y:.3f}")
    print(f"Brightness:     {'ON' if config.brightness_enabled else 'OFF'}")
    print(f"Color:          {'ON' if config.color_enabled else 'OFF'}")
    print(f"Auto switch:    {config.auto_switch_seconds:.1f} s")
    print()
    print("Controls in menu:")
    print("  1-6 : select shape")
    print("  + / - : scale up/down")
    print("  f / F : FOV down/up")
    print("  [ / ] : rotation speed slower/faster")
    print("  b     : toggle brightness")
    print("  c     : toggle color")
    print("  s / S : auto-switch slower/faster")
    print("  r     : reset angles (applies after menu)")
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
            config.scale = min(3.0, config.scale * 1.1)

        elif ch == "-":
            config.scale = max(0.05, config.scale / 1.1)

        elif ch == "f":
            config.fov = max(0.2, config.fov - 0.2)
        elif ch == "F":
            config.fov = min(10.0, config.fov + 0.2)

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
        val = input("Enter scale factor (0.001–2.0) [default 1.0]: ").strip()
        if val:
            SCALE = float(val)
        else:
            SCALE = 1.0
    except Exception:
        SCALE = 1.0

    SCALE = clamp(SCALE, 0.001, 2.0)
    config.scale = SCALE

    # Basic FOV prompt (optional)
    try:
        val = input("Enter FOV (0.5–8.0) [default 4.0]: ").strip()
        if val:
            FOV = float(val)
        else:
            FOV = 4.0
    except Exception:
        FOV = 4.0
    FOV = clamp(FOV, 0.5, 8.0)
    config.fov = FOV

    WIDTH = int(BASE_WIDTH * SCALE * 1.5)
    HEIGHT = int(BASE_HEIGHT * SCALE * 1.5)

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

        sys.stdout.flush()
        time.sleep(0.03)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        os.system(CLEAR_CMD)
        print("Interrupted by user.")
