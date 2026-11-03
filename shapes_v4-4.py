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

v1.0 (Rebuild, GPT-5.1 era, 2025-11)
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

v4.3
    • Extended FOV range for higher-res terminals (e.g., 1080p)
    • Minor tweaks to projection & prompts

v4.4
    • Global render mode:
        - auto: wireframe for poly shapes, point-cloud for surfaces
        - wire: force wireframe where possible
        - points: force point-cloud for all shapes
    • Adjustable density (sampling resolution) for parametric shapes
    • Multiple brightness ramps; ramp cycling in menu
    • Wireframe vs point-cloud can be toggled at runtime
    • Color rotation mode (colors can cycle instead of being fixed)
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

# Brightness ramps (from dark → bright)
BRIGHTNESS_RAMPS = [
    " .:-=+*#%@",
    " .`^*#@",
    " .,'\"^*#@",
]

# Global drawing window (set in main)
WIDTH = BASE_WIDTH
HEIGHT = BASE_HEIGHT

# Active render style for this frame ("wire" or "points")
ACTIVE_STYLE = "points"


class Config:
    def __init__(self):
        self.scale: float = 1.0
        self.fov: float = 4.0
        self.rot_speed_x: float = 0.06
        self.rot_speed_y: float = 0.05
        self.color_enabled: bool = True
        self.color_rotate: bool = False
        self.brightness_enabled: bool = True
        self.brightness_ramp_index: int = 0
        self.shape_index: int = 0
        self.auto_switch_seconds: float = 5.0
        self.paused: bool = False
        self.density: float = 1.0   # sampling density for param surfaces
        # 0 = auto (poly shapes wire, surfaces points)
        # 1 = wireframe
        # 2 = point-cloud
        self.render_mode: int = 0


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
    ramp = BRIGHTNESS_RAMPS[config.brightness_ramp_index]
    # Map z to brightness; assume z in approx [-3, 3]
    z_norm = (z + 3.0) / 6.0  # → [0, 1]
    z_norm = clamp(z_norm, 0.0, 1.0)
    idx = int(z_norm * (len(ramp) - 1))
    return ramp[idx]


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

    if ACTIVE_STYLE == "points":
        for x, y, z in verts2d:
            print_point(x, y, CUBE_CHAR, z)
        return

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

    if ACTIVE_STYLE == "points":
        for x, y, z in vs2:
            print_point(x, y, PYRAMID_CHAR, z)
        return

    # base (1-2-3-4-1)
    base_indices = [1, 2, 3, 4, 1]
    for i in range(len(base_indices) - 1):
        print_line(vs2[base_indices[i]], vs2[base_indices[i+1]], PYRAMID_CHAR)

    # sides (0 to 1..4)
    for i in range(1, 5):
        print_line(vs2[0], vs2[i], PYRAMID_CHAR)


# 3) Sphere (grid, wire or points)
def draw_sphere(ax: float, ay: float):
    # Base resolution; scaled by density
    base_nu = 22
    base_nv = 44
    nu = max(6, int(base_nu * config.density))
    nv = max(12, int(base_nv * config.density))
    r = 1.2

    grid: List[List[Tuple[int, int, float]]] = []
    for i in range(nu):
        theta = math.pi * (i / (nu - 1))  # 0..pi
        row = []
        for j in range(nv):
            phi = 2 * math.pi * (j / nv)  # 0..2pi
            x = r * math.sin(theta) * math.cos(phi)
            y = r * math.sin(theta) * math.sin(phi)
            z = r * math.cos(theta)
            v = Vector3D(x, y, z).rotateX(ax).rotateY(ay)
            row.append((*v.project(),))
        grid.append(row)

    if ACTIVE_STYLE == "points":
        for row in grid:
            for x, y, z in row:
                print_point(x, y, SPHERE_CHAR, z)
    else:
        # wireframe: connect along u and v
        for i in range(nu):
            for j in range(nv):
                p = grid[i][j]
                p_right = grid[i][(j + 1) % nv]
                print_line(p, p_right, SPHERE_CHAR)
                if i < nu - 1:
                    p_down = grid[i + 1][j]
                    print_line(p, p_down, SPHERE_CHAR)


# 4) Torus (grid, wire or points)
def draw_torus(ax: float, ay: float):
    base_nu = 32
    base_nv = 16
    nu = max(8, int(base_nu * config.density))
    nv = max(6, int(base_nv * config.density))
    R = 1.5  # major radius
    r = 0.6  # minor radius

    grid: List[List[Tuple[int, int, float]]] = []
    for i in range(nu):
        u = 2 * math.pi * (i / nu)
        cu = math.cos(u)
        su = math.sin(u)
        row = []
        for j in range(nv):
            v = 2 * math.pi * (j / nv)
            cv = math.cos(v)
            sv = math.sin(v)
            x = (R + r * cv) * cu
            y = (R + r * cv) * su
            z = r * sv
            p = Vector3D(x, y, z).rotateX(ax).rotateY(ay)
            row.append((*p.project(),))
        grid.append(row)

    if ACTIVE_STYLE == "points":
        for row in grid:
            for x, y, z in row:
                print_point(x, y, TORUS_CHAR, z)
    else:
        for i in range(nu):
            for j in range(nv):
                p = grid[i][j]
                p_right = grid[i][(j + 1) % nv]
                print_line(p, p_right, TORUS_CHAR)
                p_down = grid[(i + 1) % nu][j]
                print_line(p, p_down, TORUS_CHAR)


# 5) Möbius strip (grid, wire or points)
def draw_mobius(ax: float, ay: float):
    base_nu = 80
    base_nv = 8
    nu = max(10, int(base_nu * config.density))
    nv = max(4, int(base_nv * config.density))
    R = 1.5
    wmax = 0.5

    grid: List[List[Tuple[int, int, float]]] = []
    for i in range(nu):
        u = 2 * math.pi * (i / nu)
        cu = math.cos(u)
        su = math.sin(u)
        row = []
        for j in range(nv):
            w = wmax * (2 * j / (nv - 1) - 1)  # -wmax..wmax
            x = (R + w * math.cos(u / 2)) * cu
            y = (R + w * math.cos(u / 2)) * su
            z = w * math.sin(u / 2)
            p = Vector3D(x, y, z).rotateX(ax).rotateY(ay)
            row.append((*p.project(),))
        grid.append(row)

    if ACTIVE_STYLE == "points":
        for row in grid:
            for x, y, z in row:
                print_point(x, y, MOBIUS_CHAR, z)
    else:
        for i in range(nu):
            for j in range(nv):
                p = grid[i][j]
                p_right = grid[i][(j + 1) % nv]
                print_line(p, p_right, MOBIUS_CHAR)
                p_down = grid[(i + 1) % nu][j]
                print_line(p, p_down, MOBIUS_CHAR)


# 6) Klein bottle (grid, wire or points; figure-8 style embedding)
def draw_klein(ax: float, ay: float):
    base_nu = 50
    base_nv = 20
    nu = max(12, int(base_nu * config.density))
    nv = max(8, int(base_nv * config.density))

    grid: List[List[Tuple[int, int, float]]] = []
    for i in range(nu):
        u = 2 * math.pi * (i / nu)
        row = []
        for j in range(nv):
            v = 2 * math.pi * (j / nv)

            if 0 <= u < math.pi:
                x = (2.5 - 1.5 * math.cos(u)) * math.cos(v)
                z = (2.5 - 1.5 * math.cos(u)) * math.sin(v)
            else:
                x = (2.5 - 1.5 * math.cos(u)) * math.cos(v + math.pi)
                z = (2.5 - 1.5 * math.cos(u)) * math.sin(v + math.pi)

            y = -1.5 * math.sin(u)
            p = Vector3D(x * 0.4, y * 0.4, z * 0.4).rotateX(ax).rotateY(ay)
            row.append((*p.project(),))
        grid.append(row)

    if ACTIVE_STYLE == "points":
        for row in grid:
            for x, y, z in row:
                print_point(x, y, KLEIN_CHAR, z)
    else:
        for i in range(nu):
            for j in range(nv):
                p = grid[i][j]
                p_right = grid[i][(j + 1) % nv]
                print_line(p, p_right, KLEIN_CHAR)
                p_down = grid[(i + 1) % nu][j]
                print_line(p, p_down, KLEIN_CHAR)


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
        "[space]=pause  m=menu  q=quit  1-6=shape  "
        "+/-=scale  [ / ]=speed  f/F=FOV  "
        "d/D=density  w=render  g/G=shading  b=bright  c/C=color"
    )


def render_mode_name() -> str:
    return ["auto", "wire", "points"][config.render_mode]


def menu_screen():
    os.system(CLEAR_CMD)
    print("ASCII 3D Shapes – Menu (v4.4)")
    print("────────────────────────────")
    print(f"Current shape:  {config.shape_index+1} – {SHAPES[config.shape_index][0]}")
    print(f"Scale:          {config.scale:.3f}")
    print(f"FOV:            {config.fov:.3f}")
    print(f"Rot speed X:    {config.rot_speed_x:.3f}")
    print(f"Rot speed Y:    {config.rot_speed_y:.3f}")
    print(f"Density:        {config.density:.2f}")
    print(f"Render mode:    {render_mode_name()}")
    ramp = BRIGHTNESS_RAMPS[config.brightness_ramp_index]
    print(f"Brightness:     {'ON' if config.brightness_enabled else 'OFF'}")
    print(f"Shading ramp:   {config.brightness_ramp_index} – {repr(ramp)}")
    print(f"Color:          {'ON' if config.color_enabled else 'OFF'}")
    print(f"Color rotate:   {'ON' if config.color_rotate else 'OFF'}")
    print(f"Auto switch:    {config.auto_switch_seconds:.1f} s")
    print()
    print("Controls in menu:")
    print("  1-6 : select shape")
    print("  + / - : scale up/down")
    print("  f / F : FOV down/up")
    print("  [ / ] : rotation speed slower/faster")
    print("  d / D : density down/up")
    print("  w     : cycle render mode (auto → wire → points)")
    print("  b     : toggle brightness")
    print("  g / G : previous/next shading ramp")
    print("  c     : toggle color on/off")
    print("  C     : toggle color rotation")
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
            config.fov = max(0.5, config.fov - 0.2)
        elif ch == "F":
            config.fov = min(20.0, config.fov + 0.2)

        elif ch == "[":
            config.rot_speed_x *= 0.9
            config.rot_speed_y *= 0.9
        elif ch == "]":
            config.rot_speed_x *= 1.1
            config.rot_speed_y *= 1.1

        elif ch == "d":
            config.density = max(0.3, config.density - 0.1)
        elif ch == "D":
            config.density = min(3.0, config.density + 0.1)

        elif ch == "w":
            config.render_mode = (config.render_mode + 1) % 3

        elif ch == "b":
            config.brightness_enabled = not config.brightness_enabled

        elif ch == "g":
            config.brightness_ramp_index = (
                config.brightness_ramp_index - 1
            ) % len(BRIGHTNESS_RAMPS)
        elif ch == "G":
            config.brightness_ramp_index = (
                config.brightness_ramp_index + 1
            ) % len(BRIGHTNESS_RAMPS)

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
            return None

        elif ch == "q":
            return "quit"


# ─────────────────────────────────────────────────────
# Main Animation Loop
# ─────────────────────────────────────────────────────

def main():
    global WIDTH, HEIGHT, ACTIVE_STYLE

    # Initial interactive scale prompt
    try:
        val = input("Enter scale factor (0.001–2.0) [default 1.0]: ").strip()
        if val:
            scale = float(val)
        else:
            scale = 1.0
    except Exception:
        scale = 1.0

    scale = clamp(scale, 0.001, 2.0)
    config.scale = scale

    # Basic FOV prompt (optional)
    try:
        val = input("Enter FOV (0.5–20.0) [default 4.0]: ").strip()
        if val:
            fov = float(val)
        else:
            fov = 4.0
    except Exception:
        fov = 4.0
    fov = clamp(fov, 0.5, 20.0)
    config.fov = fov

    # Compute drawing size
    WIDTH = max(40, int(BASE_WIDTH * config.scale * 1.5))
    HEIGHT = max(20, int(BASE_HEIGHT * config.scale * 1.5))

    angle_x = 0.0
    angle_y = 0.0
    last_switch = time.time()
    color_phase = 0.0

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
                WIDTH = max(40, int(BASE_WIDTH * config.scale * 1.5))
                HEIGHT = max(20, int(BASE_HEIGHT * config.scale * 1.5))
            elif ch == "-":
                config.scale = max(0.05, config.scale / 1.1)
                WIDTH = max(40, int(BASE_WIDTH * config.scale * 1.5))
                HEIGHT = max(20, int(BASE_HEIGHT * config.scale * 1.5))
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
            elif ch == "C":
                config.color_rotate = not config.color_rotate
            elif ch == "d":
                config.density = max(0.3, config.density - 0.1)
            elif ch == "D":
                config.density = min(3.0, config.density + 0.1)
            elif ch == "w":
                config.render_mode = (config.render_mode + 1) % 3
            elif ch == "g":
                config.brightness_ramp_index = (
                    config.brightness_ramp_index - 1
                ) % len(BRIGHTNESS_RAMPS)
            elif ch == "G":
                config.brightness_ramp_index = (
                    config.brightness_ramp_index + 1
                ) % len(BRIGHTNESS_RAMPS)

        # Auto shape switching
        now = time.time()
        if now - last_switch > config.auto_switch_seconds:
            config.shape_index = random.randrange(len(SHAPES))
            last_switch = now

        # Determine active render style for this frame
        if config.render_mode == 1:
            ACTIVE_STYLE = "wire"
        elif config.render_mode == 2:
            ACTIVE_STYLE = "points"
        else:  # auto
            ACTIVE_STYLE = "wire" if config.shape_index in (0, 1) else "points"

        # Color rotation phase
        if config.color_rotate:
            color_phase += 0.2

        # Draw frame
        os.system(CLEAR_CMD)
        sys.stdout.write("\033[0;0H")
        show_help_overlay()

        name, draw_func = SHAPES[config.shape_index]

        if config.color_enabled:
            if config.color_rotate:
                color_idx = int(color_phase) % len(SHAPE_COLORS)
            else:
                color_idx = config.shape_index % len(SHAPE_COLORS)
            color = SHAPE_COLORS[color_idx]
            sys.stdout.write(color)

        # Draw the current shape at current angles
        draw_func(angle_x, angle_y)

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
