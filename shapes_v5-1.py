#!/usr/bin/env python3
"""
shapes_v5.py – ASCII 3D Shape Renderer (wireframe/pointcloud)

Version: 5.0

History (short)
────────────────────────────────────────────────────
• v1–3  : Single cube → zooming → a few extra shapes.
• v4.x  : Multiple shapes (cube, pyramid, sphere, etc.),
          basic FOV/scale, some shading and color.
• v5.0  : Clean refactor with:
            - Wireframe vs pointcloud rendering
            - Density controls
            - Multiple shading ramps
            - Color rotation option
            - FOV up to 100
            - Spacebar pause restored
            - Basic audio-reactive hooks stubbed (RMS + centroid)
"""

import os
import sys
import time
import math
import random
from typing import List, Tuple, Callable, Optional

# ─────────────────────────────────────────────────────
# Global config / constants
# ─────────────────────────────────────────────────────

CLEAR_CMD = "cls" if os.name == "nt" else "clear"

BASE_WIDTH = 100   # logical base, scaled by user factor
BASE_HEIGHT = 40

# brightness ramps (from dark → bright)
BRIGHTNESS_RAMPS = [
    " .:-=+*#%@",
    " .oO@",
    " .:+*#",
]

# default per-shape characters
CUBE_CHAR = "+"
PYRAMID_CHAR = "^"
SPHERE_CHAR = "."
TORUS_CHAR = "."
MOBIUS_CHAR = "."
KLEIN_CHAR = "."

# shape colors (can rotate or be disabled)
SHAPE_COLORS = [
    "\033[38;5;45m",   # cube – cyan-ish
    "\033[38;5;214m",  # pyramid – orange
    "\033[38;5;82m",   # sphere – green
    "\033[38;5;201m",  # torus – magenta
    "\033[38;5;189m",  # mobius – pastel purple
    "\033[38;5;160m",  # klein – red
]
COLOR_RESET = "\033[0m"

WIDTH = BASE_WIDTH
HEIGHT = BASE_HEIGHT


class Config:
    def __init__(self):
        self.scale: float = 1.0
        self.fov: float = 4.0
        self.rot_speed_x: float = 0.06
        self.rot_speed_y: float = 0.05

        self.shape_index: int = 0
        self.auto_switch_seconds: float = 6.0
        self.paused: bool = False

        # rendering mode & density
        # mode: "wire" or "points"
        self.render_mode: str = "wire"
        # density multiplier (affects how many points are drawn for pointcloud shapes)
        self.density: float = 1.0  # 0.25 .. 4

        # shading
        self.brightness_enabled: bool = True
        self.brightness_ramp_idx: int = 0

        # color
        self.color_enabled: bool = True
        self.color_rotate: bool = False


config = Config()


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# ─────────────────────────────────────────────────────
# Vector / projection
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
        depth_offset = 4.0
        denom = self.z + depth_offset
        if denom == 0:
            denom = 0.0001
        factor = config.fov / denom
        x = int(self.x * factor * config.scale + WIDTH // 2)
        y = int(-self.y * factor * config.scale + HEIGHT // 2)
        return x, y, self.z


# ─────────────────────────────────────────────────────
# Input (non-blocking)
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
# Shading / drawing primitives
# ─────────────────────────────────────────────────────

def depth_to_char(base_char: str, z: float) -> str:
    if not config.brightness_enabled:
        return base_char
    ramp = BRIGHTNESS_RAMPS[config.brightness_ramp_idx % len(BRIGHTNESS_RAMPS)]
    # Assume z in roughly [-3, 3]
    z_norm = (z + 3.0) / 6.0
    z_norm = clamp(z_norm, 0.0, 1.0)
    idx = int(z_norm * (len(ramp) - 1))
    return ramp[idx]


def print_point(x: int, y: int, char: str, z: float = 0.0):
    if x < 1 or x > WIDTH or y < 1 or y > HEIGHT:
        return
    ch = depth_to_char(char, z)
    sys.stdout.write(f"\033[{y};{x}H{ch}")


def print_line(start: Tuple[int, int, float],
               end: Tuple[int, int, float],
               char: str):
    x1, y1, z1 = start
    x2, y2, z2 = end
    dx = abs(x2 - x1)
    dy = abs(y2 - y1)
    steps = max(dx, dy)
    if steps == 0:
        print_point(x1, y1, char, (z1 + z2) * 0.5)
        return
    for i in range(steps + 1):
        t = i / max(steps, 1)
        x = int(x1 * (1 - t) + x2 * t)
        y = int(y1 * (1 - t) + y2 * t)
        z = z1 * (1 - t) + z2 * t
        print_point(x, y, char, z)


# ─────────────────────────────────────────────────────
# Shapes
# ─────────────────────────────────────────────────────

# Cube
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
    verts2d = [v.project() for v in verts3d]

    edges = [
        (0, 1), (1, 2), (2, 3), (3, 0),
        (4, 5), (5, 6), (6, 7), (7, 4),
        (0, 4), (1, 5), (2, 6), (3, 7),
    ]

    if config.render_mode == "points":
        for x, y, z in verts2d:
            print_point(x, y, CUBE_CHAR, z)
    else:
        for a, b in edges:
            print_line(verts2d[a], verts2d[b], CUBE_CHAR)


# Pyramid
def get_pyramid_vertices() -> List[Vector3D]:
    s = 1.1
    return [
        Vector3D(0.0, s, 0.0),       # top
        Vector3D(-s, -s, s),        # base front-left
        Vector3D(s, -s, s),         # base front-right
        Vector3D(s, -s, -s),        # base back-right
        Vector3D(-s, -s, -s),       # base back-left
    ]


def draw_pyramid(ax: float, ay: float):
    vs3 = [v.rotateX(ax).rotateY(ay) for v in get_pyramid_vertices()]
    vs2 = [v.project() for v in vs3]

    if config.render_mode == "points":
        for x, y, z in vs2:
            print_point(x, y, PYRAMID_CHAR, z)
        return

    # base loop 1-2-3-4-1
    base = [1, 2, 3, 4, 1]
    for i in range(len(base) - 1):
        print_line(vs2[base[i]], vs2[base[i + 1]], PYRAMID_CHAR)
    # sides 0-1..4
    for i in range(1, 5):
        print_line(vs2[0], vs2[i], PYRAMID_CHAR)


# Sphere (point cloud / sparse wire)
def get_sphere_points(detail: int) -> List[Vector3D]:
    pts = []
    r = 1.3
    for i in range(detail):
        theta = math.pi * (i / (detail - 1))  # 0..pi
        for j in range(detail * 2):
            phi = 2 * math.pi * (j / (detail * 2))  # 0..2pi
            x = r * math.sin(theta) * math.cos(phi)
            y = r * math.sin(theta) * math.sin(phi)
            z = r * math.cos(theta)
            pts.append(Vector3D(x, y, z))
    return pts


def draw_sphere(ax: float, ay: float):
    base_detail = 14
    detail = max(6, int(base_detail * config.density))
    pts = get_sphere_points(detail)

    if config.render_mode == "points":
        for v in pts:
            v2 = v.rotateX(ax).rotateY(ay)
            x, y, z = v2.project()
            print_point(x, y, SPHERE_CHAR, z)
    else:
        # basic "wire": draw some latitude & longitude lines
        lat_step = max(2, detail // 6)
        lon_step = max(2, (detail * 2) // 12)
        # by index: row-major (i, j) → i*(2*detail) + j
        cols = detail * 2
        vs3 = [v.rotateX(ax).rotateY(ay) for v in pts]
        vs2 = [p.project() for p in vs3]

        # latitudes
        for i in range(0, detail, lat_step):
            row = []
            for j in range(0, cols, lon_step):
                idx = i * cols + j
                row.append(vs2[idx])
            for a, b in zip(row, row[1:]):
                print_line(a, b, SPHERE_CHAR)

        # longitudes
        for j in range(0, cols, lon_step):
            col = []
            for i in range(0, detail, lat_step):
                idx = i * cols + j
                col.append(vs2[idx])
            for a, b in zip(col, col[1:]):
                print_line(a, b, SPHERE_CHAR)


# Torus
def get_torus_points(nu: int, nv: int) -> List[Vector3D]:
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
    nu = max(10, int(24 * config.density))
    nv = max(6, int(12 * config.density))
    pts = get_torus_points(nu, nv)

    if config.render_mode == "points":
        for v in pts:
            v2 = v.rotateX(ax).rotateY(ay)
            x, y, z = v2.project()
            print_point(x, y, TORUS_CHAR, z)
    else:
        vs3 = [v.rotateX(ax).rotateY(ay) for v in pts]
        vs2 = [p.project() for p in vs3]

        def idx(i, j):
            return (i % nu) * nv + (j % nv)

        # u & v circles
        for i in range(nu):
            for j in range(nv):
                a = vs2[idx(i, j)]
                b = vs2[idx(i, j + 1)]
                print_line(a, b, TORUS_CHAR)
        for j in range(nv):
            for i in range(nu):
                a = vs2[idx(i, j)]
                b = vs2[idx(i + 1, j)]
                print_line(a, b, TORUS_CHAR)


# Möbius strip
def get_mobius_points(nu: int, nv: int) -> List[Vector3D]:
    pts = []
    R = 1.7
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
    nu = max(20, int(60 * config.density))
    nv = max(4, int(8 * config.density))
    pts = get_mobius_points(nu, nv)

    if config.render_mode == "points":
        for v in pts:
            v2 = v.rotateX(ax).rotateY(ay)
            x, y, z = v2.project()
            print_point(x, y, MOBIUS_CHAR, z)
    else:
        vs3 = [v.rotateX(ax).rotateY(ay) for v in pts]
        vs2 = [p.project() for p in vs3]

        def idx(i, j):
            return (i % nu) * nv + (j % nv)

        for i in range(nu):
            for j in range(nv):
                a = vs2[idx(i, j)]
                b = vs2[idx(i, j + 1)]
                print_line(a, b, MOBIUS_CHAR)
        for j in range(nv):
            for i in range(nu):
                a = vs2[idx(i, j)]
                b = vs2[idx(i + 1, j)]
                print_line(a, b, MOBIUS_CHAR)


# Klein bottle (figure-8 style)
def get_klein_points(nu: int, nv: int) -> List[Vector3D]:
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
    nu = max(20, int(50 * config.density))
    nv = max(8, int(16 * config.density))
    pts = get_klein_points(nu, nv)

    if config.render_mode == "points":
        for v in pts:
            v2 = v.rotateX(ax).rotateY(ay)
            x, y, z = v2.project()
            print_point(x, y, KLEIN_CHAR, z)
    else:
        vs3 = [v.rotateX(ax).rotateY(ay) for v in pts]
        vs2 = [p.project() for p in vs3]

        def idx(i, j):
            return (i % nu) * nv + (j % nv)

        for i in range(nu):
            for j in range(nv):
                a = vs2[idx(i, j)]
                b = vs2[idx(i, j + 1)]
                print_line(a, b, KLEIN_CHAR)
        for j in range(nv):
            for i in range(nu):
                a = vs2[idx(i, j)]
                b = vs2[idx(i + 1, j)]
                print_line(a, b, KLEIN_CHAR)


# Registry of shapes
ShapeFunc = Callable[[float, float], None]
SHAPES: List[Tuple[str, ShapeFunc]] = [
    ("Cube", draw_cube),
    ("Pyramid", draw_pyramid),
    ("Sphere", draw_sphere),
    ("Torus", draw_torus),
    ("Möbius Strip", draw_mobius),
    ("Klein Bottle", draw_klein),
]


# ─────────────────────────────────────────────────────
# Audio reactive hooks (stubs)
# ─────────────────────────────────────────────────────

def apply_audio_reactivity(rms: float, centroid: float):
    """
    Hook for future audio-reactive behavior.

    Args:
        rms: normalized RMS level (0..1)
        centroid: normalized spectral centroid (0..1)

    Example mapping idea (currently disabled):
        - use rms to bump scale or density
        - use centroid to vary color or brightness ramp
    """
    # Example (commented out – enable when you have audio data):
    # config.scale = 0.5 + 1.5 * clamp(rms, 0.0, 1.0)
    # config.density = 0.5 + 3.0 * clamp(rms, 0.0, 1.0)
    # config.brightness_ramp_idx = int(centroid * (len(BRIGHTNESS_RAMPS) - 1))
    pass


# ─────────────────────────────────────────────────────
# UI / menu
# ─────────────────────────────────────────────────────

def show_help_overlay():
    sys.stdout.write("\033[1;1H")
    print(
        "[space]=pause  m=menu  q=quit  1-6=shape  "
        "p=wire/points  +/-=scale  [ / ]=speed  "
        "b=brightness  B=ramp  c=color  C=color-rotate  d/D=density"
    )


def menu_screen():
    os.system(CLEAR_CMD)
    print("ASCII 3D Shapes – v5.0 Menu")
    print("────────────────────────────")
    print(f"Shape:          {config.shape_index+1} – {SHAPES[config.shape_index][0]}")
    print(f"Scale:          {config.scale:.3f}")
    print(f"FOV:            {config.fov:.3f}")
    print(f"Rot speed X:    {config.rot_speed_x:.3f}")
    print(f"Rot speed Y:    {config.rot_speed_y:.3f}")
    print(f"Render mode:    {config.render_mode}")
    print(f"Density:        {config.density:.2f}")
    print(f"Brightness:     {'ON' if config.brightness_enabled else 'OFF'}")
    print(f"Ramp index:     {config.brightness_ramp_idx}")
    print(f"Color:          {'ON' if config.color_enabled else 'OFF'}")
    print(f"Color rotate:   {'ON' if config.color_rotate else 'OFF'}")
    print(f"Auto switch:    {config.auto_switch_seconds:.1f} s")
    print()
    print("Menu keys:")
    print("  1-6 : select shape")
    print("  + / - : scale up/down")
    print("  f / F : FOV down/up (0.5–100)")
    print("  [ / ] : rotation speed slower/faster")
    print("  p     : toggle wire / points mode")
    print("  d / D : density down/up (0.25–4)")
    print("  b     : toggle brightness")
    print("  B     : cycle brightness ramp")
    print("  c     : toggle color")
    print("  C     : toggle color rotation")
    print("  s / S : auto-switch slower/faster")
    print("  r     : reset angles")
    print("  x     : exit menu")
    print("  q     : quit program")
    print()
    print("Press keys; changes apply immediately.")


def run_menu() -> str:
    """
    Returns one of: 'continue', 'quit', 'reset_angles'
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

        elif ch == "p":
            config.render_mode = "points" if config.render_mode == "wire" else "wire"

        elif ch == "d":
            config.density = max(0.25, config.density / 1.2)
        elif ch == "D":
            config.density = min(4.0, config.density * 1.2)

        elif ch == "b":
            config.brightness_enabled = not config.brightness_enabled

        elif ch == "B":
            config.brightness_ramp_idx = (config.brightness_ramp_idx + 1) % len(BRIGHTNESS_RAMPS)

        elif ch == "c":
            config.color_enabled = not config.color_enabled

        elif ch == "C":
            config.color_rotate = not config.color_rotate

        elif ch == "s":
            config.auto_switch_seconds = max(1.0, config.auto_switch_seconds - 0.5)
        elif ch == "S":
            config.auto_switch_seconds = min(30.0, config.auto_switch_seconds + 0.5)

        elif ch == "r":
            return "reset_angles"

        elif ch == "x":
            return "continue"

        elif ch == "q":
            return "quit"


# ─────────────────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────────────────

def main():
    global WIDTH, HEIGHT

    # Scale factor prompt
    try:
        s_val = input("Scale factor (0.1–3.0) [1.0]: ").strip()
        if s_val:
            config.scale = float(s_val)
        else:
            config.scale = 1.0
    except Exception:
        config.scale = 1.0
    config.scale = clamp(config.scale, 0.1, 3.0)

    # FOV prompt (max 100 per your note)
    try:
        f_val = input("FOV (0.5–100) [4.0]: ").strip()
        if f_val:
            config.fov = float(f_val)
        else:
            config.fov = 4.0
    except Exception:
        config.fov = 4.0
    config.fov = clamp(config.fov, 0.5, 100.0)

    WIDTH = int(BASE_WIDTH * config.scale * 1.5)
    HEIGHT = int(BASE_HEIGHT * config.scale * 1.2)

    angle_x = 0.0
    angle_y = 0.0
    last_switch = time.time()
    frame_count = 0

    os.system(CLEAR_CMD)

    while True:
        # handle input
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
            elif ch == "p":
                config.render_mode = "points" if config.render_mode == "wire" else "wire"
            elif ch == "b":
                config.brightness_enabled = not config.brightness_enabled
            elif ch == "B":
                config.brightness_ramp_idx = (config.brightness_ramp_idx + 1) % len(BRIGHTNESS_RAMPS)
            elif ch == "c":
                config.color_enabled = not config.color_enabled
            elif ch == "C":
                config.color_rotate = not config.color_rotate
            elif ch == "d":
                config.density = max(0.25, config.density / 1.2)
            elif ch == "D":
                config.density = min(4.0, config.density * 1.2)

        # auto shape switching
        now = time.time()
        if now - last_switch > config.auto_switch_seconds:
            config.shape_index = random.randrange(len(SHAPES))
            last_switch = now

        # (future) audio-reactive hook could be called here
        # apply_audio_reactivity(rms, centroid)

        os.system(CLEAR_CMD)
        sys.stdout.write("\033[0;0H")
        show_help_overlay()

        name, draw_func = SHAPES[config.shape_index]

        # color selection / rotation
        color_idx = config.shape_index
        if config.color_rotate:
            color_idx = (config.shape_index + frame_count // 10) % len(SHAPE_COLORS)

        if config.color_enabled:
            sys.stdout.write(SHAPE_COLORS[color_idx])

        if not config.paused:
            draw_func(angle_x, angle_y)
        else:
            draw_func(angle_x, angle_y)  # still draw, just freeze rotation

        if config.color_enabled:
            sys.stdout.write(COLOR_RESET)

        if not config.paused:
            angle_x += config.rot_speed_x
            angle_y += config.rot_speed_y

        sys.stdout.flush()
        frame_count += 1
        time.sleep(0.03)  # control render speed


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        os.system(CLEAR_CMD)
        print("Interrupted by user.")
