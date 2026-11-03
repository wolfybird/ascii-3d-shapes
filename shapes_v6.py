#!/usr/bin/env python3
"""
shapes_v6.py - ASCII 3D Shape Renderer

v6.0 (Claude, 2026-05)
    - Flicker-free rendering via screen buffer (no cls per frame)
    - Live HUD with current param values and [MIN]/[MAX] indicators
    - Unified parameter system (no duplicated key handling)
    - Terminal size auto-detection
    - 6 shapes: Cube, Pyramid, Sphere, Torus, Mobius Strip, Klein Bottle
    - Wire / point-cloud render modes
    - Depth-based brightness with selectable ramps
    - Per-shape ANSI color with optional color rotation
    - Density, FOV, scale, speed all hotkey-adjustable
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
DIM = "\033[2m"
BOLD = "\033[1m"

SHAPE_COLORS = [
    "\033[38;5;45m",   # cube - cyan
    "\033[38;5;214m",  # pyramid - orange
    "\033[38;5;82m",   # sphere - green
    "\033[38;5;201m",  # torus - magenta
    "\033[38;5;189m",  # mobius - light purple
    "\033[38;5;160m",  # klein - red
]

BRIGHTNESS_RAMPS = [
    " .:-=+*#%@",
    " .oO@",
    " .:+*#",
]

CUBE_CHAR = "+"
PYRAMID_CHAR = "^"
SPHERE_CHAR = "."
TORUS_CHAR = "."
MOBIUS_CHAR = "."
KLEIN_CHAR = "."

WIDTH = 120
HEIGHT = 40


class Param:
    def __init__(self, name, value, lo, hi, step, fmt=".2f", key_down=None, key_up=None, multiplicative=False):
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
            tag = " [MIN]"
        elif self.at_max:
            tag = " [MAX]"
        return f"{self.name}:{val_str}{tag}"


class Config:
    def __init__(self):
        self.scale = Param("Scale", 1.0, 0.05, 5.0, 1.1, ".2f", "-", "+", multiplicative=True)
        self.fov = Param("FOV", 4.0, 0.5, 100.0, 0.5, ".1f", "f", "F")
        self.speed_x = Param("SpdX", 0.06, 0.001, 0.5, 1.15, ".3f", "[", "]", multiplicative=True)
        self.speed_y = Param("SpdY", 0.05, 0.001, 0.5, 1.15, ".3f", None, None, multiplicative=True)
        self.density = Param("Density", 1.0, 0.25, 4.0, 1.2, ".2f", "d", "D", multiplicative=True)
        self.auto_switch = Param("AutoSwitch", 6.0, 1.0, 60.0, 1.0, ".0f", "s", "S")

        self.shape_index = 0
        self.paused = False
        self.render_mode = "wire"
        self.brightness_enabled = True
        self.brightness_ramp_idx = 0
        self.color_enabled = True
        self.color_rotate = False

        self.all_params = [self.scale, self.fov, self.speed_x, self.density, self.auto_switch]

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


# ---- Screen buffer ----

class ScreenBuffer:
    def __init__(self, w, h):
        self.w = w
        self.h = h
        self.buf = [[" "] * w for _ in range(h)]

    def clear(self):
        for row in self.buf:
            for i in range(len(row)):
                row[i] = " "

    def put(self, x, y, ch):
        if 0 <= x < self.w and 0 <= y < self.h:
            self.buf[y][x] = ch

    def put_line(self, x1, y1, z1, x2, y2, z2, base_char):
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        steps = max(dx, dy)
        if steps == 0:
            self.put(x1, y1, shade_char(base_char, (z1 + z2) * 0.5))
            return
        for i in range(steps + 1):
            t = i / steps
            x = int(x1 + (x2 - x1) * t)
            y = int(y1 + (y2 - y1) * t)
            z = z1 + (z2 - z1) * t
            self.put(x, y, shade_char(base_char, z))

    def put_text(self, x, y, text):
        for i, ch in enumerate(text):
            self.put(x + i, y, ch)

    def render(self):
        lines = []
        for row in self.buf:
            lines.append("".join(row))
        return "\n".join(lines)


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

def draw_cube(ax, ay, scr):
    vs = [v.rotate_x(ax).rotate_y(ay) for v in cube_verts()]
    ps = [v.project() for v in vs]
    if config.render_mode == "points":
        for x, y, z in ps:
            scr.put(x, y, shade_char(CUBE_CHAR, z))
    else:
        for a, b in CUBE_EDGES:
            x1, y1, z1 = ps[a]
            x2, y2, z2 = ps[b]
            scr.put_line(x1, y1, z1, x2, y2, z2, CUBE_CHAR)


def pyramid_verts():
    s = 1.3
    return [
        Vector3D(0, s, 0),
        Vector3D(-s, -s, s), Vector3D(s, -s, s),
        Vector3D(s, -s, -s), Vector3D(-s, -s, -s),
    ]

PYRAMID_BASE = [(1, 2), (2, 3), (3, 4), (4, 1)]
PYRAMID_SIDES = [(0, 1), (0, 2), (0, 3), (0, 4)]

def draw_pyramid(ax, ay, scr):
    vs = [v.rotate_x(ax).rotate_y(ay) for v in pyramid_verts()]
    ps = [v.project() for v in vs]
    if config.render_mode == "points":
        for x, y, z in ps:
            scr.put(x, y, shade_char(PYRAMID_CHAR, z))
    else:
        for a, b in PYRAMID_BASE + PYRAMID_SIDES:
            x1, y1, z1 = ps[a]
            x2, y2, z2 = ps[b]
            scr.put_line(x1, y1, z1, x2, y2, z2, PYRAMID_CHAR)


def sphere_points(detail):
    pts = []
    r = 1.3
    for i in range(detail):
        theta = math.pi * (i / max(detail - 1, 1))
        ncols = detail * 2
        for j in range(ncols):
            phi = 2 * math.pi * (j / ncols)
            pts.append(Vector3D(
                r * math.sin(theta) * math.cos(phi),
                r * math.sin(theta) * math.sin(phi),
                r * math.cos(theta),
            ))
    return pts, detail, detail * 2

def draw_sphere(ax, ay, scr):
    detail = max(6, int(14 * config.density.value))
    pts, nrows, ncols = sphere_points(detail)
    vs = [v.rotate_x(ax).rotate_y(ay) for v in pts]
    ps = [v.project() for v in vs]

    if config.render_mode == "points":
        for x, y, z in ps:
            scr.put(x, y, shade_char(SPHERE_CHAR, z))
    else:
        lat_step = max(1, nrows // 8)
        lon_step = max(1, ncols // 12)
        for i in range(0, nrows, lat_step):
            for j in range(0, ncols - lon_step, lon_step):
                a = i * ncols + j
                b = i * ncols + j + lon_step
                if b < len(ps):
                    x1, y1, z1 = ps[a]
                    x2, y2, z2 = ps[b]
                    scr.put_line(x1, y1, z1, x2, y2, z2, SPHERE_CHAR)
        for j in range(0, ncols, lon_step):
            for i in range(0, nrows - lat_step, lat_step):
                a = i * ncols + j
                b = (i + lat_step) * ncols + j
                if b < len(ps):
                    x1, y1, z1 = ps[a]
                    x2, y2, z2 = ps[b]
                    scr.put_line(x1, y1, z1, x2, y2, z2, SPHERE_CHAR)


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

def draw_torus(ax, ay, scr):
    nu = max(10, int(24 * config.density.value))
    nv = max(6, int(12 * config.density.value))
    pts = torus_points(nu, nv)
    vs = [v.rotate_x(ax).rotate_y(ay) for v in pts]
    ps = [v.project() for v in vs]

    if config.render_mode == "points":
        for x, y, z in ps:
            scr.put(x, y, shade_char(TORUS_CHAR, z))
    else:
        def idx(i, j):
            return (i % nu) * nv + (j % nv)
        for i in range(nu):
            for j in range(nv):
                a, b = idx(i, j), idx(i, (j + 1))
                x1, y1, z1 = ps[a]
                x2, y2, z2 = ps[b]
                scr.put_line(x1, y1, z1, x2, y2, z2, TORUS_CHAR)
        for j in range(nv):
            for i in range(nu):
                a, b = idx(i, j), idx((i + 1), j)
                x1, y1, z1 = ps[a]
                x2, y2, z2 = ps[b]
                scr.put_line(x1, y1, z1, x2, y2, z2, TORUS_CHAR)


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

def draw_mobius(ax, ay, scr):
    nu = max(20, int(60 * config.density.value))
    nv = max(4, int(8 * config.density.value))
    pts = mobius_points(nu, nv)
    vs = [v.rotate_x(ax).rotate_y(ay) for v in pts]
    ps = [v.project() for v in vs]

    if config.render_mode == "points":
        for x, y, z in ps:
            scr.put(x, y, shade_char(MOBIUS_CHAR, z))
    else:
        def idx(i, j):
            return (i % nu) * nv + (j % nv)
        for i in range(nu):
            for j in range(nv):
                a, b = idx(i, j), idx(i, (j + 1))
                x1, y1, z1 = ps[a]
                x2, y2, z2 = ps[b]
                scr.put_line(x1, y1, z1, x2, y2, z2, MOBIUS_CHAR)
        for j in range(nv):
            for i in range(nu):
                a, b = idx(i, j), idx((i + 1), j)
                x1, y1, z1 = ps[a]
                x2, y2, z2 = ps[b]
                scr.put_line(x1, y1, z1, x2, y2, z2, MOBIUS_CHAR)


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

def draw_klein(ax, ay, scr):
    nu = max(20, int(50 * config.density.value))
    nv = max(8, int(16 * config.density.value))
    pts = klein_points(nu, nv)
    vs = [v.rotate_x(ax).rotate_y(ay) for v in pts]
    ps = [v.project() for v in vs]

    if config.render_mode == "points":
        for x, y, z in ps:
            scr.put(x, y, shade_char(KLEIN_CHAR, z))
    else:
        def idx(i, j):
            return (i % nu) * nv + (j % nv)
        for i in range(nu):
            for j in range(nv):
                a, b = idx(i, j), idx(i, (j + 1))
                x1, y1, z1 = ps[a]
                x2, y2, z2 = ps[b]
                scr.put_line(x1, y1, z1, x2, y2, z2, KLEIN_CHAR)
        for j in range(nv):
            for i in range(nu):
                a, b = idx(i, j), idx((i + 1), j)
                x1, y1, z1 = ps[a]
                x2, y2, z2 = ps[b]
                scr.put_line(x1, y1, z1, x2, y2, z2, KLEIN_CHAR)


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
    parts = [
        f"[{si+1}] {name}",
        config.render_mode.upper(),
        "PAUSED" if config.paused else "",
    ]
    return "  ".join(p for p in parts if p)


def build_hud_line2():
    parts = []
    for p in config.all_params:
        parts.append(p.display())

    ramp_name = repr(BRIGHTNESS_RAMPS[config.brightness_ramp_idx % len(BRIGHTNESS_RAMPS)])
    parts.append(f"Bright:{'ON' if config.brightness_enabled else 'OFF'}")
    parts.append(f"Ramp:{config.brightness_ramp_idx}")
    parts.append(f"Color:{'ON' if config.color_enabled else 'OFF'}")
    if config.color_rotate:
        parts.append("ColRot:ON")
    return "  ".join(parts)


def build_hud_line3():
    return (
        "Space=pause  1-6=shape  p=wire/pts  +/-=scale  f/F=fov  "
        "[/]=speed  d/D=density  b=bright  B=ramp  c=color  C=col-rot  "
        "s/S=auto  r=reset  m=menu  q=quit"
    )


# ---- Menu ----

def menu_screen():
    os.system(CLEAR_CMD)
    print(f"ASCII 3D Shapes v6 - Menu")
    print(f"{'=' * 40}")
    print(f"  Shape:        {config.shape_index+1} - {SHAPES[config.shape_index][0]}")
    for p in config.all_params:
        tag = ""
        if p.at_min:
            tag = "  << MIN"
        elif p.at_max:
            tag = "  >> MAX"
        print(f"  {p.name + ':':<14} {p.value:{p.fmt}}{tag}  (range {p.lo:{p.fmt}} - {p.hi:{p.fmt}})")
    print(f"  SpeedY:       {config.speed_y.value:{config.speed_y.fmt}}  (linked to SpeedX)")
    print(f"  Render:       {config.render_mode}")
    print(f"  Brightness:   {'ON' if config.brightness_enabled else 'OFF'}")
    print(f"  Ramp:         {config.brightness_ramp_idx} - {repr(BRIGHTNESS_RAMPS[config.brightness_ramp_idx % len(BRIGHTNESS_RAMPS)])}")
    print(f"  Color:        {'ON' if config.color_enabled else 'OFF'}")
    print(f"  Color rotate: {'ON' if config.color_rotate else 'OFF'}")
    print()
    print("  Keys work the same as in render view.")
    print("  x = exit menu   q = quit program   r = reset angles")
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
        config.color_enabled = not config.color_enabled
        return True
    elif ch == "C":
        config.color_rotate = not config.color_rotate
        return True
    return False


# ---- Main loop ----

def main():
    global WIDTH, HEIGHT

    size = shutil.get_terminal_size(fallback=(120, 40))
    WIDTH = max(40, size.columns)
    HEIGHT = max(10, size.lines - 1)

    try:
        val = input(f"Scale factor (0.05-5.0) [1.0]: ").strip()
        if val:
            config.scale.value = clamp(float(val), config.scale.lo, config.scale.hi)
    except Exception:
        pass

    try:
        val = input(f"FOV (0.5-100) [4.0]: ").strip()
        if val:
            config.fov.value = clamp(float(val), config.fov.lo, config.fov.hi)
    except Exception:
        pass

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

            name, draw_func = SHAPES[config.shape_index]

            draw_func(angle_x, angle_y, scr)

            hud1 = build_hud_line1()
            hud2 = build_hud_line2()
            hud3 = build_hud_line3()
            scr.put_text(0, 0, hud1[:WIDTH])
            scr.put_text(0, 1, hud2[:WIDTH])
            scr.put_text(0, HEIGHT - 1, hud3[:WIDTH])

            frame_text = scr.render()

            sys.stdout.write("\033[H")
            if config.color_enabled:
                color_idx = config.shape_index
                if config.color_rotate:
                    color_idx = (config.shape_index + frame_count // 10) % len(SHAPE_COLORS)
                sys.stdout.write(SHAPE_COLORS[color_idx % len(SHAPE_COLORS)])

            sys.stdout.write(frame_text)

            if config.color_enabled:
                sys.stdout.write(COLOR_RESET)

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
