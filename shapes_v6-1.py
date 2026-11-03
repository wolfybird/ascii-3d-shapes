#!/usr/bin/env python3
"""
shapes_v6-1.py - ASCII 3D Shape Renderer

v6.1 (Claude, 2026-05)
    - Auto-sizing: FOV and scale derived from terminal dimensions, no prompts
    - Per-cell depth-gradient coloring: multi-color shading on a single shape
    - 4 color modes: off / shape / depth / rotate  (cycle with 'c')
    - 5 depth palettes: warm-cool, fire, ocean, neon, matrix  (cycle with 'C')
    - Flicker-free buffer with per-cell ANSI color
    - Live HUD with param values and [MIN]/[MAX] indicators
    - Unified param system, 6 shapes, wire/points, brightness ramps
"""

import math
import os
import random
import shutil
import sys
import time
from typing import List, Tuple, Callable, Optional

CLEAR_CMD = "cls" if os.name == "nt" else "clear"
COLOR_RESET = "\033[0m"

SHAPE_COLORS = [
    "\033[38;5;45m",   # cube - cyan
    "\033[38;5;214m",  # pyramid - orange
    "\033[38;5;82m",   # sphere - green
    "\033[38;5;201m",  # torus - magenta
    "\033[38;5;189m",  # mobius - light purple
    "\033[38;5;160m",  # klein - red
]

DEPTH_PALETTES = [
    ("warm-cool", [196, 202, 208, 214, 220, 226, 154, 82, 46, 49, 51, 45, 39, 33, 27, 21]),
    ("fire",      [16, 52, 88, 124, 160, 196, 202, 208, 214, 220, 226, 228]),
    ("ocean",     [16, 17, 18, 19, 20, 21, 27, 33, 39, 45, 51, 87, 123, 159]),
    ("neon",      [21, 57, 93, 129, 165, 201, 200, 199, 198, 197, 196]),
    ("matrix",    [16, 22, 28, 34, 40, 46, 82, 118, 154, 190, 226]),
]

BRIGHTNESS_RAMPS = [
    " .:-=+*#%@",
    " .oO@",
    " .:+*#",
]

COLOR_MODES = ["off", "shape", "depth", "rotate"]

CUBE_CHAR = "+"
PYRAMID_CHAR = "^"
SPHERE_CHAR = "."
TORUS_CHAR = "."
MOBIUS_CHAR = "."
KLEIN_CHAR = "."

WIDTH = 120
HEIGHT = 40


# ---- Auto-sizing ----

def auto_size():
    size = shutil.get_terminal_size(fallback=(120, 40))
    w = max(40, size.columns)
    h = max(10, size.lines - 1)
    usable_h = h - 3
    eff_w = w * 0.8
    eff_h = usable_h * 2.2
    constraining = min(eff_w, eff_h)
    fov = clamp(constraining * 0.35, 2.0, 100.0)
    return w, h, fov


# ---- Param system ----

class Param:
    def __init__(self, name, value, lo, hi, step, fmt=".2f",
                 key_down=None, key_up=None, multiplicative=False):
        self.name = name
        self.value = value
        self.lo = lo
        self.hi = hi
        self.step = step
        self.fmt = fmt
        self.key_down = key_down
        self.key_up = key_up
        self.multiplicative = multiplicative
        self._flash_until = 0.0

    def increase(self):
        old = self.value
        if self.multiplicative:
            self.value = min(self.hi, self.value * self.step)
        else:
            self.value = min(self.hi, self.value + self.step)
        if self.value != old:
            self._flash_until = time.time() + 1.0

    def decrease(self):
        old = self.value
        if self.multiplicative:
            self.value = max(self.lo, self.value / self.step)
        else:
            self.value = max(self.lo, self.value - self.step)
        if self.value != old:
            self._flash_until = time.time() + 1.0

    @property
    def at_min(self):
        if self.multiplicative:
            return self.value <= self.lo * 1.001
        return self.value <= self.lo + abs(self.step) * 0.01

    @property
    def at_max(self):
        if self.multiplicative:
            return self.value >= self.hi * 0.999
        return self.value >= self.hi - abs(self.step) * 0.01

    @property
    def flashing(self):
        return time.time() < self._flash_until

    def display(self):
        val_str = f"{self.value:{self.fmt}}"
        tag = ""
        if self.at_min:
            tag = "[MIN]"
        elif self.at_max:
            tag = "[MAX]"
        return f"{self.name}:{val_str}{tag}"


class Config:
    def __init__(self, auto_fov=4.0):
        self.scale = Param("Scl", 1.0, 0.05, 5.0, 1.1, ".2f", "-", "+",
                           multiplicative=True)
        self.fov = Param("FOV", auto_fov, 0.5, 100.0, 0.5, ".1f", "f", "F")
        self.speed_x = Param("Spd", 0.06, 0.001, 0.5, 1.15, ".3f", "[", "]",
                             multiplicative=True)
        self.speed_y = Param("SpdY", 0.05, 0.001, 0.5, 1.15, ".3f", None, None,
                             multiplicative=True)
        self.density = Param("Den", 1.0, 0.25, 4.0, 1.2, ".2f", "d", "D",
                             multiplicative=True)
        self.auto_switch = Param("Auto", 6.0, 1.0, 60.0, 1.0, ".0f", "s", "S")

        self.shape_index = 0
        self.paused = False
        self.render_mode = "wire"
        self.brightness_enabled = True
        self.brightness_ramp_idx = 0
        self.color_mode_idx = 1
        self.depth_palette_idx = 0

        self.all_params = [self.scale, self.fov, self.speed_x, self.density,
                           self.auto_switch]

    @property
    def color_mode(self):
        return COLOR_MODES[self.color_mode_idx % len(COLOR_MODES)]

    def handle_key(self, ch):
        for p in self.all_params:
            if p.key_up and ch == p.key_up:
                p.increase()
                if p is self.speed_x:
                    self.speed_y.increase()
                return True
            if p.key_down and ch == p.key_down:
                p.decrease()
                if p is self.speed_x:
                    self.speed_y.decrease()
                return True
        return False


config = Config()


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


# ---- Vector & Projection ----

class Vector3D:
    __slots__ = ("x", "y", "z")

    def __init__(self, x, y, z):
        self.x = x
        self.y = y
        self.z = z

    def rotate_x(self, a):
        c, s = math.cos(a), math.sin(a)
        return Vector3D(self.x, self.y * c - self.z * s, self.y * s + self.z * c)

    def rotate_y(self, a):
        c, s = math.cos(a), math.sin(a)
        return Vector3D(self.z * s + self.x * c, self.y, self.z * c - self.x * s)

    def project(self):
        denom = self.z + 4.0
        if denom == 0:
            denom = 1e-4
        f = config.fov.value / denom
        sc = config.scale.value
        x = int(self.x * f * sc + WIDTH // 2)
        y = int(-self.y * f * sc + HEIGHT // 2)
        return x, y, self.z


# ---- Non-blocking input ----

def get_key():
    if os.name == "nt":
        try:
            import msvcrt
        except ImportError:
            return None
        if msvcrt.kbhit():
            return msvcrt.getwch()
        return None
    else:
        import select, termios, tty
        if not sys.stdin.isatty():
            return None
        fd = sys.stdin.fileno()
        dr, _, _ = select.select([sys.stdin], [], [], 0)
        if not dr:
            return None
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            return sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


# ---- Per-cell color ----

def depth_color_code(z):
    palette_name, palette = DEPTH_PALETTES[
        config.depth_palette_idx % len(DEPTH_PALETTES)
    ]
    z_norm = clamp((z + 3.0) / 6.0, 0.0, 1.0)
    idx = int(z_norm * (len(palette) - 1))
    return f"\033[38;5;{palette[idx]}m"


def get_cell_color(z, shape_idx, frame_count):
    mode = config.color_mode
    if mode == "off":
        return ""
    elif mode == "shape":
        return SHAPE_COLORS[shape_idx % len(SHAPE_COLORS)]
    elif mode == "depth":
        return depth_color_code(z)
    elif mode == "rotate":
        cidx = (shape_idx + frame_count // 10) % len(SHAPE_COLORS)
        return SHAPE_COLORS[cidx]
    return ""


# ---- Screen buffer with per-cell color ----

class ScreenBuffer:
    def __init__(self, w, h):
        self.w = w
        self.h = h
        self.chars = None
        self.colors = None
        self._alloc()

    def _alloc(self):
        self.chars = [[" "] * self.w for _ in range(self.h)]
        self.colors = [[""] * self.w for _ in range(self.h)]

    def clear(self):
        for r in range(self.h):
            for c in range(self.w):
                self.chars[r][c] = " "
                self.colors[r][c] = ""

    def put(self, x, y, ch, color=""):
        if 0 <= x < self.w and 0 <= y < self.h:
            self.chars[y][x] = ch
            self.colors[y][x] = color

    def put_line(self, x1, y1, z1, x2, y2, z2, base_char, color_fn):
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        steps = max(dx, dy)
        if steps == 0:
            z = (z1 + z2) * 0.5
            self.put(x1, y1, shade_char(base_char, z), color_fn(z))
            return
        for i in range(steps + 1):
            t = i / steps
            x = int(x1 + (x2 - x1) * t)
            y = int(y1 + (y2 - y1) * t)
            z = z1 + (z2 - z1) * t
            self.put(x, y, shade_char(base_char, z), color_fn(z))

    def put_text(self, x, y, text):
        for i, ch in enumerate(text):
            if 0 <= x + i < self.w and 0 <= y < self.h:
                self.chars[y][x + i] = ch
                self.colors[y][x + i] = ""

    def render(self):
        parts = []
        prev_color = ""
        for r in range(self.h):
            row_chars = self.chars[r]
            row_colors = self.colors[r]
            for c in range(self.w):
                col = row_colors[c]
                ch = row_chars[c]
                if col != prev_color:
                    parts.append(col if col else COLOR_RESET)
                    prev_color = col
                parts.append(ch)
            if r < self.h - 1:
                parts.append("\n")
        if prev_color:
            parts.append(COLOR_RESET)
        return "".join(parts)


def shade_char(base_char, z):
    if not config.brightness_enabled:
        return base_char
    ramp = BRIGHTNESS_RAMPS[config.brightness_ramp_idx % len(BRIGHTNESS_RAMPS)]
    z_norm = clamp((z + 3.0) / 6.0, 0.0, 1.0)
    idx = int(z_norm * (len(ramp) - 1))
    ch = ramp[idx]
    return ch if ch != " " else base_char


# ---- Shapes ----

def cube_verts():
    s = 1.0
    return [
        Vector3D(-s, -s, -s), Vector3D(s, -s, -s),
        Vector3D(s, s, -s), Vector3D(-s, s, -s),
        Vector3D(-s, -s, s), Vector3D(s, -s, s),
        Vector3D(s, s, s), Vector3D(-s, s, s),
    ]

CUBE_EDGES = [
    (0, 1), (1, 2), (2, 3), (3, 0),
    (4, 5), (5, 6), (6, 7), (7, 4),
    (0, 4), (1, 5), (2, 6), (3, 7),
]


def draw_cube(ax, ay, scr, color_fn):
    vs = [v.rotate_x(ax).rotate_y(ay) for v in cube_verts()]
    ps = [v.project() for v in vs]
    if config.render_mode == "points":
        for x, y, z in ps:
            scr.put(x, y, shade_char(CUBE_CHAR, z), color_fn(z))
    else:
        for a, b in CUBE_EDGES:
            x1, y1, z1 = ps[a]
            x2, y2, z2 = ps[b]
            scr.put_line(x1, y1, z1, x2, y2, z2, CUBE_CHAR, color_fn)


def pyramid_verts():
    s = 1.3
    return [
        Vector3D(0, s, 0),
        Vector3D(-s, -s, s), Vector3D(s, -s, s),
        Vector3D(s, -s, -s), Vector3D(-s, -s, -s),
    ]

PYRAMID_EDGES = [(1, 2), (2, 3), (3, 4), (4, 1), (0, 1), (0, 2), (0, 3), (0, 4)]


def draw_pyramid(ax, ay, scr, color_fn):
    vs = [v.rotate_x(ax).rotate_y(ay) for v in pyramid_verts()]
    ps = [v.project() for v in vs]
    if config.render_mode == "points":
        for x, y, z in ps:
            scr.put(x, y, shade_char(PYRAMID_CHAR, z), color_fn(z))
    else:
        for a, b in PYRAMID_EDGES:
            x1, y1, z1 = ps[a]
            x2, y2, z2 = ps[b]
            scr.put_line(x1, y1, z1, x2, y2, z2, PYRAMID_CHAR, color_fn)


def sphere_points(detail):
    pts = []
    r = 1.3
    ncols = detail * 2
    for i in range(detail):
        theta = math.pi * (i / max(detail - 1, 1))
        for j in range(ncols):
            phi = 2 * math.pi * (j / ncols)
            pts.append(Vector3D(
                r * math.sin(theta) * math.cos(phi),
                r * math.sin(theta) * math.sin(phi),
                r * math.cos(theta),
            ))
    return pts, detail, ncols


def draw_sphere(ax, ay, scr, color_fn):
    detail = max(6, int(14 * config.density.value))
    pts, nrows, ncols = sphere_points(detail)
    vs = [v.rotate_x(ax).rotate_y(ay) for v in pts]
    ps = [v.project() for v in vs]

    if config.render_mode == "points":
        for x, y, z in ps:
            scr.put(x, y, shade_char(SPHERE_CHAR, z), color_fn(z))
    else:
        lat_step = max(1, nrows // 8)
        lon_step = max(1, ncols // 12)
        for i in range(0, nrows, lat_step):
            for j in range(0, ncols - lon_step, lon_step):
                a = i * ncols + j
                b = i * ncols + j + lon_step
                if b < len(ps):
                    scr.put_line(*ps[a], *ps[b], SPHERE_CHAR, color_fn)
        for j in range(0, ncols, lon_step):
            for i in range(0, nrows - lat_step, lat_step):
                a = i * ncols + j
                b = (i + lat_step) * ncols + j
                if b < len(ps):
                    scr.put_line(*ps[a], *ps[b], SPHERE_CHAR, color_fn)


def torus_points(nu, nv):
    R, r = 1.5, 0.6
    pts = []
    for i in range(nu):
        u = 2 * math.pi * (i / nu)
        cu, su = math.cos(u), math.sin(u)
        for j in range(nv):
            v = 2 * math.pi * (j / nv)
            cv, sv = math.cos(v), math.sin(v)
            pts.append(Vector3D((R + r * cv) * cu, (R + r * cv) * su, r * sv))
    return pts


def draw_torus(ax, ay, scr, color_fn):
    nu = max(10, int(24 * config.density.value))
    nv = max(6, int(12 * config.density.value))
    pts = torus_points(nu, nv)
    vs = [v.rotate_x(ax).rotate_y(ay) for v in pts]
    ps = [v.project() for v in vs]

    def idx(i, j):
        return (i % nu) * nv + (j % nv)

    if config.render_mode == "points":
        for x, y, z in ps:
            scr.put(x, y, shade_char(TORUS_CHAR, z), color_fn(z))
    else:
        for i in range(nu):
            for j in range(nv):
                a, b = idx(i, j), idx(i, j + 1)
                scr.put_line(*ps[a], *ps[b], TORUS_CHAR, color_fn)
        for j in range(nv):
            for i in range(nu):
                a, b = idx(i, j), idx(i + 1, j)
                scr.put_line(*ps[a], *ps[b], TORUS_CHAR, color_fn)


def mobius_points(nu, nv):
    R, wmax = 1.7, 0.5
    pts = []
    for i in range(nu):
        u = 2 * math.pi * (i / nu)
        cu, su = math.cos(u), math.sin(u)
        for j in range(nv):
            w = wmax * (2 * j / max(nv - 1, 1) - 1)
            pts.append(Vector3D(
                (R + w * math.cos(u / 2)) * cu,
                (R + w * math.cos(u / 2)) * su,
                w * math.sin(u / 2),
            ))
    return pts


def draw_mobius(ax, ay, scr, color_fn):
    nu = max(20, int(60 * config.density.value))
    nv = max(4, int(8 * config.density.value))
    pts = mobius_points(nu, nv)
    vs = [v.rotate_x(ax).rotate_y(ay) for v in pts]
    ps = [v.project() for v in vs]

    def idx(i, j):
        return (i % nu) * nv + (j % nv)

    if config.render_mode == "points":
        for x, y, z in ps:
            scr.put(x, y, shade_char(MOBIUS_CHAR, z), color_fn(z))
    else:
        for i in range(nu):
            for j in range(nv):
                a, b = idx(i, j), idx(i, j + 1)
                scr.put_line(*ps[a], *ps[b], MOBIUS_CHAR, color_fn)
        for j in range(nv):
            for i in range(nu):
                a, b = idx(i, j), idx(i + 1, j)
                scr.put_line(*ps[a], *ps[b], MOBIUS_CHAR, color_fn)


def klein_points(nu, nv):
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


def draw_klein(ax, ay, scr, color_fn):
    nu = max(20, int(50 * config.density.value))
    nv = max(8, int(16 * config.density.value))
    pts = klein_points(nu, nv)
    vs = [v.rotate_x(ax).rotate_y(ay) for v in pts]
    ps = [v.project() for v in vs]

    def idx(i, j):
        return (i % nu) * nv + (j % nv)

    if config.render_mode == "points":
        for x, y, z in ps:
            scr.put(x, y, shade_char(KLEIN_CHAR, z), color_fn(z))
    else:
        for i in range(nu):
            for j in range(nv):
                a, b = idx(i, j), idx(i, j + 1)
                scr.put_line(*ps[a], *ps[b], KLEIN_CHAR, color_fn)
        for j in range(nv):
            for i in range(nu):
                a, b = idx(i, j), idx(i + 1, j)
                scr.put_line(*ps[a], *ps[b], KLEIN_CHAR, color_fn)


SHAPES: List[Tuple[str, Callable]] = [
    ("Cube", draw_cube),
    ("Pyramid", draw_pyramid),
    ("Sphere", draw_sphere),
    ("Torus", draw_torus),
    ("Mobius Strip", draw_mobius),
    ("Klein Bottle", draw_klein),
]


# ---- HUD ----

def build_hud_line1():
    si = config.shape_index
    name = SHAPES[si][0]
    mode = config.color_mode
    pal = ""
    if mode == "depth":
        pal_name = DEPTH_PALETTES[config.depth_palette_idx % len(DEPTH_PALETTES)][0]
        pal = f"({pal_name})"
    parts = [
        f"[{si+1}] {name}",
        config.render_mode.upper(),
        f"color:{mode}{pal}",
        "PAUSED" if config.paused else "",
    ]
    return "  ".join(p for p in parts if p)


def build_hud_line2():
    parts = [p.display() for p in config.all_params]
    parts.append(f"Brt:{'ON' if config.brightness_enabled else 'OFF'}")
    parts.append(f"Ramp:{config.brightness_ramp_idx}")
    return "  ".join(parts)


def build_hud_line3():
    return (
        "Spc=pause 1-6=shape p=wire/pts +/-=scl f/F=fov "
        "[/]=spd d/D=den b=brt B=ramp c=color C=palette "
        "s/S=auto r=reset m=menu q=quit"
    )


# ---- Menu ----

def menu_screen():
    os.system(CLEAR_CMD)
    pal_name = DEPTH_PALETTES[config.depth_palette_idx % len(DEPTH_PALETTES)][0]
    print("ASCII 3D Shapes v6.1 - Menu")
    print("=" * 42)
    print(f"  Shape:         {config.shape_index+1} - {SHAPES[config.shape_index][0]}")
    print(f"  Render:        {config.render_mode}")
    for p in config.all_params:
        tag = ""
        if p.at_min:
            tag = "  << MIN"
        elif p.at_max:
            tag = "  >> MAX"
        print(f"  {p.name + ':':<14} {p.value:{p.fmt}}{tag}"
              f"  ({p.lo:{p.fmt}} .. {p.hi:{p.fmt}})")
    print(f"  SpeedY:        {config.speed_y.value:{config.speed_y.fmt}}"
          f"  (linked to Speed)")
    print(f"  Brightness:    {'ON' if config.brightness_enabled else 'OFF'}")
    ramp_str = repr(BRIGHTNESS_RAMPS[config.brightness_ramp_idx % len(BRIGHTNESS_RAMPS)])
    print(f"  Ramp:          {config.brightness_ramp_idx} - {ramp_str}")
    print(f"  Color mode:    {config.color_mode}")
    print(f"  Depth palette: {pal_name}")
    print(f"  Terminal:      {WIDTH}x{HEIGHT+1}")
    print(f"  Auto FOV:      {config.fov.value:.1f}"
          f"  (derived from {WIDTH}x{HEIGHT+1})")
    print()
    print("  Same hotkeys as render view, plus:")
    print("  x = exit menu   q = quit   r = reset angles")
    print()
    print("  Press keys; changes apply immediately.")


def run_menu():
    while True:
        menu_screen()
        ch = get_key()
        if ch is None:
            time.sleep(0.05)
            continue
        if ch == "x":
            return "continue"
        if ch == "q":
            return "quit"
        if ch == "r":
            return "reset_angles"
        handle_common_key(ch)


def handle_common_key(ch):
    if config.handle_key(ch):
        return True

    if ch in "123456":
        idx = int(ch) - 1
        if 0 <= idx < len(SHAPES):
            config.shape_index = idx
        return True
    elif ch == "p":
        config.render_mode = "points" if config.render_mode == "wire" else "wire"
        return True
    elif ch == "b":
        config.brightness_enabled = not config.brightness_enabled
        return True
    elif ch == "B":
        config.brightness_ramp_idx = (config.brightness_ramp_idx + 1) % len(BRIGHTNESS_RAMPS)
        return True
    elif ch == "c":
        config.color_mode_idx = (config.color_mode_idx + 1) % len(COLOR_MODES)
        return True
    elif ch == "C":
        config.depth_palette_idx = (config.depth_palette_idx + 1) % len(DEPTH_PALETTES)
        return True
    return False


# ---- Main loop ----

def main():
    global WIDTH, HEIGHT, config

    w, h, auto_fov = auto_size()
    WIDTH = w
    HEIGHT = h

    config = Config(auto_fov=auto_fov)

    scr = ScreenBuffer(WIDTH, HEIGHT)
    angle_x = 0.0
    angle_y = 0.0
    last_switch = time.time()
    frame_count = 0

    sys.stdout.write("\033[?25l")
    sys.stdout.flush()
    os.system(CLEAR_CMD)

    try:
        while True:
            ch = get_key()
            if ch:
                if ch == " ":
                    config.paused = not config.paused
                elif ch == "q":
                    return
                elif ch == "m":
                    sys.stdout.write("\033[?25h")
                    sys.stdout.flush()
                    result = run_menu()
                    sys.stdout.write("\033[?25l")
                    sys.stdout.flush()
                    os.system(CLEAR_CMD)
                    if result == "quit":
                        return
                    elif result == "reset_angles":
                        angle_x = angle_y = 0.0
                elif ch == "r":
                    angle_x = angle_y = 0.0
                else:
                    handle_common_key(ch)

            now = time.time()
            if now - last_switch > config.auto_switch.value:
                config.shape_index = random.randrange(len(SHAPES))
                last_switch = now

            scr.clear()

            si = config.shape_index
            name, draw_func = SHAPES[si]

            def color_fn(z, _si=si, _fc=frame_count):
                return get_cell_color(z, _si, _fc)

            draw_func(angle_x, angle_y, scr, color_fn)

            scr.put_text(0, 0, build_hud_line1()[:WIDTH])
            scr.put_text(0, 1, build_hud_line2()[:WIDTH])
            scr.put_text(0, HEIGHT - 1, build_hud_line3()[:WIDTH])

            sys.stdout.write("\033[H")
            sys.stdout.write(scr.render())
            sys.stdout.flush()

            if not config.paused:
                angle_x += config.speed_x.value
                angle_y += config.speed_y.value

            frame_count += 1
            time.sleep(0.03)

    finally:
        sys.stdout.write("\033[?25h")
        sys.stdout.write(COLOR_RESET)
        sys.stdout.flush()
        os.system(CLEAR_CMD)
        print("Goodbye.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.stdout.write("\033[?25h")
        sys.stdout.write(COLOR_RESET)
        sys.stdout.flush()
        os.system(CLEAR_CMD)
        print("Interrupted.")
