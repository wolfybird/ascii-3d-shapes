#!/usr/bin/env python3
"""
shapes_v8.py – ASCII 3D Shape Renderer

v8.0 (2026-07)
    - Resolution presets: Small/Medium/Large/Auto, cycle with 'R'
    - Audio device picker: detect input & output devices, select input
      via sub-menu ('A' in menu or main view)
    - Auto-switch OFF: press 's' below 1s to disable; shows "OFF"
    - HUD overlay toggle: '.' hides/shows all on-screen text
    - Z-buffer, geometry caching, delta-time animation (from v7)
    - Audio reactivity with onset/BPM detection (from v7)
    - 6 shapes, 5 depth palettes, wireframe/points, brightness ramps
"""

import math
import os
import random
import shutil
import sys
import time
import threading
from collections import deque
from typing import List, Tuple, Callable, Optional

HAS_AUDIO = False
try:
    import numpy as np
    import sounddevice as sd
    HAS_AUDIO = True
except ImportError:
    pass

CLEAR_CMD = "cls" if os.name == "nt" else "clear"
COLOR_RESET = "\033[0m"

SHAPE_COLORS = [
    "\033[38;5;45m",
    "\033[38;5;214m",
    "\033[38;5;82m",
    "\033[38;5;201m",
    "\033[38;5;189m",
    "\033[38;5;160m",
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

RESOLUTION_PRESETS = [
    ("Auto",   None, None),
    ("Small",  80,   24),
    ("Medium", 120,  40),
    ("Large",  160,  50),
    ("XL",     200,  55),
]

CUBE_CHAR = "+"
PYRAMID_CHAR = "^"
SPHERE_CHAR = "."
TORUS_CHAR = "."
MOBIUS_CHAR = "."
KLEIN_CHAR = "."

WIDTH = 120
HEIGHT = 40


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def terminal_size():
    size = shutil.get_terminal_size(fallback=(120, 40))
    return max(40, size.columns), max(10, size.lines - 1)


def fov_for_size(w, h):
    eff_w = w * 0.8
    eff_h = (h - 3) * 2.2
    return clamp(min(eff_w, eff_h) * 0.35, 2.0, 100.0)


def apply_resolution(preset_idx):
    global WIDTH, HEIGHT
    term_w, term_h = terminal_size()
    label, pw, ph = RESOLUTION_PRESETS[preset_idx]
    if pw is None:
        WIDTH, HEIGHT = term_w, term_h
    else:
        WIDTH = min(pw, term_w)
        HEIGHT = min(ph, term_h)
    config.fov.value = fov_for_size(WIDTH, HEIGHT)


# ── Param system ──────────────────────────────────────

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

    def increase(self):
        if self.multiplicative:
            self.value = min(self.hi, self.value * self.step)
        else:
            self.value = min(self.hi, self.value + self.step)

    def decrease(self):
        if self.multiplicative:
            self.value = max(self.lo, self.value / self.step)
        else:
            self.value = max(self.lo, self.value - self.step)

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

    def display(self):
        if self.value == 0 and self.lo == 0:
            return f"{self.name}:OFF"
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
        self.auto_switch = Param("Auto", 6.0, 0.0, 60.0, 1.0, ".0f", "s", "S")

        self.shape_index = 0
        self.paused = False
        self.render_mode = "wire"
        self.brightness_enabled = True
        self.brightness_ramp_idx = 0
        self.color_mode_idx = 1
        self.depth_palette_idx = 0
        self.audio_reactive = False
        self.hud_visible = True
        self.resolution_idx = 0

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


# ── Vector & Projection ──────────────────────────────

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


# ── Non-blocking input ───────────────────────────────

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


# ── Audio Analyzer ───────────────────────────────────

class AudioAnalyzer:
    def __init__(self, sample_rate=22050, block_size=1024):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.running = False
        self.device_index = None
        self.device_name = "Default"
        self._stream = None
        self._lock = threading.Lock()
        self._rms = 0.0
        self._onset = False
        self._bpm = 120.0
        self._rms_slow = 0.0
        self._last_onset = 0.0
        self._onset_times: deque = deque(maxlen=32)
        self._cooldown = 0.12

    def start(self, device=None):
        if not HAS_AUDIO:
            return False
        self.stop()
        if device is not None:
            self.device_index = device
        try:
            self._stream = sd.InputStream(
                device=self.device_index,
                samplerate=self.sample_rate,
                blocksize=self.block_size,
                channels=1,
                dtype="float32",
                callback=self._callback,
            )
            self._stream.start()
            self.running = True
            return True
        except Exception:
            self.running = False
            return False

    def stop(self):
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
        self.running = False
        self._stream = None
        self._rms_slow = 0.0
        self._onset_times.clear()

    def _callback(self, indata, frames, time_info, status):
        rms = float(np.sqrt(np.mean(indata ** 2)))
        self._rms_slow = self._rms_slow * 0.93 + rms * 0.07

        now = time.time()
        onset = False
        threshold = max(self._rms_slow * 3.0, 0.008)
        if rms > threshold and (now - self._last_onset) > self._cooldown:
            onset = True
            self._last_onset = now
            self._onset_times.append(now)

        bpm = self._bpm
        if len(self._onset_times) >= 3:
            times = list(self._onset_times)
            intervals = [
                times[i] - times[i - 1]
                for i in range(1, len(times))
                if 0.25 < times[i] - times[i - 1] < 2.0
            ]
            if len(intervals) >= 2:
                bpm = clamp(
                    60.0 / sorted(intervals)[len(intervals) // 2], 60, 240
                )

        with self._lock:
            self._rms = rms
            if onset:
                self._onset = True
            self._bpm = bpm

    def get_features(self):
        with self._lock:
            rms = self._rms
            onset = self._onset
            bpm = self._bpm
            self._onset = False
            return rms, onset, bpm


audio = AudioAnalyzer()


# ── Audio device listing ─────────────────────────────

def list_audio_devices():
    if not HAS_AUDIO:
        return [], []
    try:
        devices = sd.query_devices()
    except Exception:
        return [], []
    inputs = []
    outputs = []
    default_in, default_out = sd.default.device
    for i, dev in enumerate(devices):
        name = dev["name"]
        is_default = False
        if dev["max_input_channels"] > 0:
            is_default = (i == default_in)
            inputs.append((i, name, is_default))
        if dev["max_output_channels"] > 0:
            is_default = (i == default_out)
            outputs.append((i, name, is_default))
    return inputs, outputs


def run_audio_menu():
    while True:
        os.system(CLEAR_CMD)
        print("Audio Device Setup")
        print("=" * 50)
        print()

        if not HAS_AUDIO:
            print("  Audio libraries not installed.")
            print("  Run: pip install sounddevice numpy")
            print()
            print("  x = back")
            ch = get_key()
            if ch is None:
                time.sleep(0.05)
                continue
            if ch == "x":
                return
            continue

        inputs, outputs = list_audio_devices()

        print("  INPUT DEVICES:")
        if not inputs:
            print("    (none detected)")
        for list_idx, (dev_idx, name, is_def) in enumerate(inputs):
            sel = ">" if dev_idx == audio.device_index else " "
            if audio.device_index is None and is_def:
                sel = ">"
            def_tag = " [DEFAULT]" if is_def else ""
            print(f"  {sel} {list_idx}: {name}{def_tag}")

        print()
        print("  OUTPUT DEVICES (reference):")
        if not outputs:
            print("    (none detected)")
        for list_idx, (dev_idx, name, is_def) in enumerate(outputs):
            def_tag = " [DEFAULT]" if is_def else ""
            print(f"    {list_idx}: {name}{def_tag}")

        print()
        cur = audio.device_name
        if audio.running:
            cur += " (active)"
        print(f"  Selected input: {cur}")
        print()
        print("  0-9 = select input device")
        print("  d   = reset to default")
        print("  x   = back")

        ch = get_key()
        if ch is None:
            time.sleep(0.05)
            continue
        if ch == "x":
            return
        elif ch == "d":
            was_running = audio.running
            audio.stop()
            audio.device_index = None
            audio.device_name = "Default"
            if was_running or config.audio_reactive:
                audio.start()
        elif ch in "0123456789":
            pick = int(ch)
            if pick < len(inputs):
                dev_idx, name, _ = inputs[pick]
                was_running = audio.running
                audio.stop()
                audio.device_index = dev_idx
                audio.device_name = name
                if was_running or config.audio_reactive:
                    if not audio.start():
                        audio.device_index = None
                        audio.device_name = "Default"
                        audio.start()


# ── Per-cell color ───────────────────────────────────

def depth_color_code(z):
    _, palette = DEPTH_PALETTES[config.depth_palette_idx % len(DEPTH_PALETTES)]
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


# ── Screen buffer with z-buffer ──────────────────────

def shade_char(base_char, z):
    if not config.brightness_enabled:
        return base_char
    ramp = BRIGHTNESS_RAMPS[config.brightness_ramp_idx % len(BRIGHTNESS_RAMPS)]
    z_norm = clamp((z + 3.0) / 6.0, 0.0, 1.0)
    z_norm = 1.0 - z_norm
    idx = int(z_norm * (len(ramp) - 1))
    ch = ramp[idx]
    return ch if ch != " " else base_char


class ScreenBuffer:
    def __init__(self, w, h):
        self.w = w
        self.h = h
        self.chars = [[" "] * w for _ in range(h)]
        self.colors = [[""] * w for _ in range(h)]
        self.zbuf = [[float("inf")] * w for _ in range(h)]

    def clear(self):
        for r in range(self.h):
            cr = self.chars[r]
            co = self.colors[r]
            zr = self.zbuf[r]
            for c in range(self.w):
                cr[c] = " "
                co[c] = ""
                zr[c] = float("inf")

    def put(self, x, y, ch, color="", z=float("inf")):
        if 0 <= x < self.w and 0 <= y < self.h and z <= self.zbuf[y][x]:
            self.chars[y][x] = ch
            self.colors[y][x] = color
            self.zbuf[y][x] = z

    def put_line(self, x1, y1, z1, x2, y2, z2, base_char, color_fn):
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        steps = max(dx, dy)
        if steps == 0:
            z = (z1 + z2) * 0.5
            self.put(x1, y1, shade_char(base_char, z), color_fn(z), z)
            return
        for i in range(steps + 1):
            t = i / steps
            x = int(x1 + (x2 - x1) * t)
            y = int(y1 + (y2 - y1) * t)
            z = z1 + (z2 - z1) * t
            self.put(x, y, shade_char(base_char, z), color_fn(z), z)

    def put_text(self, x, y, text):
        for i, ch in enumerate(text):
            xi = x + i
            if 0 <= xi < self.w and 0 <= y < self.h:
                self.chars[y][xi] = ch
                self.colors[y][xi] = ""
                self.zbuf[y][xi] = float("-inf")

    def render(self):
        parts = []
        prev_color = ""
        for r in range(self.h):
            row_chars = self.chars[r]
            row_colors = self.colors[r]
            for c in range(self.w):
                col = row_colors[c]
                if col != prev_color:
                    parts.append(col if col else COLOR_RESET)
                    prev_color = col
                parts.append(row_chars[c])
            if r < self.h - 1:
                parts.append("\n")
        if prev_color:
            parts.append(COLOR_RESET)
        return "".join(parts)


# ── Geometry cache ───────────────────────────────────

_geo_cache = {}
_geo_cache_density = -1.0


def get_cached(name, gen_fn, *args):
    global _geo_cache, _geo_cache_density
    d = config.density.value
    if d != _geo_cache_density:
        _geo_cache.clear()
        _geo_cache_density = d
    if name not in _geo_cache:
        _geo_cache[name] = gen_fn(*args)
    return _geo_cache[name]


# ── Shapes ───────────────────────────────────────────

def _gen_cube():
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
    verts = get_cached("cube", _gen_cube)
    vs = [v.rotate_x(ax).rotate_y(ay) for v in verts]
    ps = [v.project() for v in vs]
    if config.render_mode == "points":
        for x, y, z in ps:
            scr.put(x, y, shade_char(CUBE_CHAR, z), color_fn(z), z)
    else:
        for a, b in CUBE_EDGES:
            scr.put_line(*ps[a], *ps[b], CUBE_CHAR, color_fn)


def _gen_pyramid():
    s = 1.3
    return [
        Vector3D(0, s, 0),
        Vector3D(-s, -s, s), Vector3D(s, -s, s),
        Vector3D(s, -s, -s), Vector3D(-s, -s, -s),
    ]

PYRAMID_EDGES = [
    (1, 2), (2, 3), (3, 4), (4, 1),
    (0, 1), (0, 2), (0, 3), (0, 4),
]


def draw_pyramid(ax, ay, scr, color_fn):
    verts = get_cached("pyramid", _gen_pyramid)
    vs = [v.rotate_x(ax).rotate_y(ay) for v in verts]
    ps = [v.project() for v in vs]
    if config.render_mode == "points":
        for x, y, z in ps:
            scr.put(x, y, shade_char(PYRAMID_CHAR, z), color_fn(z), z)
    else:
        for a, b in PYRAMID_EDGES:
            scr.put_line(*ps[a], *ps[b], PYRAMID_CHAR, color_fn)


def _gen_sphere(detail):
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
    pts, nrows, ncols = get_cached("sphere", _gen_sphere, detail)
    vs = [v.rotate_x(ax).rotate_y(ay) for v in pts]
    ps = [v.project() for v in vs]

    if config.render_mode == "points":
        for x, y, z in ps:
            scr.put(x, y, shade_char(SPHERE_CHAR, z), color_fn(z), z)
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


def _gen_torus(nu, nv):
    R, r = 1.5, 0.6
    pts = []
    for i in range(nu):
        u = 2 * math.pi * (i / nu)
        cu, su = math.cos(u), math.sin(u)
        for j in range(nv):
            v = 2 * math.pi * (j / nv)
            cv, sv = math.cos(v), math.sin(v)
            pts.append(Vector3D(
                (R + r * cv) * cu, (R + r * cv) * su, r * sv
            ))
    return pts, nu, nv


def draw_torus(ax, ay, scr, color_fn):
    nu = max(10, int(24 * config.density.value))
    nv = max(6, int(12 * config.density.value))
    pts, nu, nv = get_cached("torus", _gen_torus, nu, nv)
    vs = [v.rotate_x(ax).rotate_y(ay) for v in pts]
    ps = [v.project() for v in vs]

    def idx(i, j):
        return (i % nu) * nv + (j % nv)

    if config.render_mode == "points":
        for x, y, z in ps:
            scr.put(x, y, shade_char(TORUS_CHAR, z), color_fn(z), z)
    else:
        for i in range(nu):
            for j in range(nv):
                scr.put_line(*ps[idx(i, j)], *ps[idx(i, j + 1)],
                             TORUS_CHAR, color_fn)
        for j in range(nv):
            for i in range(nu):
                scr.put_line(*ps[idx(i, j)], *ps[idx(i + 1, j)],
                             TORUS_CHAR, color_fn)


def _gen_mobius(nu, nv):
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
    return pts, nu, nv


def draw_mobius(ax, ay, scr, color_fn):
    nu = max(20, int(60 * config.density.value))
    nv = max(4, int(8 * config.density.value))
    pts, nu, nv = get_cached("mobius", _gen_mobius, nu, nv)
    vs = [v.rotate_x(ax).rotate_y(ay) for v in pts]
    ps = [v.project() for v in vs]

    def idx(i, j):
        return (i % nu) * nv + (j % nv)

    if config.render_mode == "points":
        for x, y, z in ps:
            scr.put(x, y, shade_char(MOBIUS_CHAR, z), color_fn(z), z)
    else:
        for i in range(nu):
            for j in range(nv):
                scr.put_line(*ps[idx(i, j)], *ps[idx(i, j + 1)],
                             MOBIUS_CHAR, color_fn)
        for j in range(nv):
            for i in range(nu):
                scr.put_line(*ps[idx(i, j)], *ps[idx(i + 1, j)],
                             MOBIUS_CHAR, color_fn)


def _gen_klein(nu, nv):
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
    return pts, nu, nv


def draw_klein(ax, ay, scr, color_fn):
    nu = max(20, int(50 * config.density.value))
    nv = max(8, int(16 * config.density.value))
    pts, nu, nv = get_cached("klein", _gen_klein, nu, nv)
    vs = [v.rotate_x(ax).rotate_y(ay) for v in pts]
    ps = [v.project() for v in vs]

    def idx(i, j):
        return (i % nu) * nv + (j % nv)

    if config.render_mode == "points":
        for x, y, z in ps:
            scr.put(x, y, shade_char(KLEIN_CHAR, z), color_fn(z), z)
    else:
        for i in range(nu):
            for j in range(nv):
                scr.put_line(*ps[idx(i, j)], *ps[idx(i, j + 1)],
                             KLEIN_CHAR, color_fn)
        for j in range(nv):
            for i in range(nu):
                scr.put_line(*ps[idx(i, j)], *ps[idx(i + 1, j)],
                             KLEIN_CHAR, color_fn)


SHAPES: List[Tuple[str, Callable]] = [
    ("Cube", draw_cube),
    ("Pyramid", draw_pyramid),
    ("Sphere", draw_sphere),
    ("Torus", draw_torus),
    ("Mobius Strip", draw_mobius),
    ("Klein Bottle", draw_klein),
]


# ── HUD ──────────────────────────────────────────────

def build_hud_line1(bpm_str=""):
    si = config.shape_index
    name = SHAPES[si][0]
    mode = config.color_mode
    pal = ""
    if mode == "depth":
        pal_name = DEPTH_PALETTES[
            config.depth_palette_idx % len(DEPTH_PALETTES)
        ][0]
        pal = f"({pal_name})"
    res_label = RESOLUTION_PRESETS[config.resolution_idx][0]
    parts = [
        f"[{si + 1}] {name}",
        config.render_mode.upper(),
        f"color:{mode}{pal}",
        f"{WIDTH}x{HEIGHT}({res_label})",
    ]
    if config.audio_reactive:
        status = bpm_str if bpm_str else "waiting..."
        parts.append(f"AUDIO:{status}")
    if config.paused:
        parts.append("PAUSED")
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
        "a=audio A=devices R=res s/S=auto .=hud r=reset m=menu q=quit"
    )


# ── Menu ──────────────────────────────────────────────

def menu_screen():
    os.system(CLEAR_CMD)
    pal_name = DEPTH_PALETTES[
        config.depth_palette_idx % len(DEPTH_PALETTES)
    ][0]
    res_label = RESOLUTION_PRESETS[config.resolution_idx][0]
    print("ASCII 3D Shapes v8 - Menu")
    print("=" * 50)
    print(f"  Shape:         {config.shape_index + 1}"
          f" - {SHAPES[config.shape_index][0]}")
    print(f"  Render:        {config.render_mode}")
    for p in config.all_params:
        tag = ""
        if p.value == 0 and p.lo == 0:
            tag = "  (disabled)"
        elif p.at_min:
            tag = "  << MIN"
        elif p.at_max:
            tag = "  >> MAX"
        fmt_lo = f"{p.lo:{p.fmt}}" if p.lo != 0 else "OFF"
        print(f"  {p.name + ':':<14} {p.display().split(':')[1]}{tag}"
              f"  ({fmt_lo} .. {p.hi:{p.fmt}})")
    print(f"  SpeedY:        {config.speed_y.value:{config.speed_y.fmt}}"
          f"  (linked to Speed)")
    print(f"  Brightness:    {'ON' if config.brightness_enabled else 'OFF'}")
    ramp_str = repr(
        BRIGHTNESS_RAMPS[config.brightness_ramp_idx % len(BRIGHTNESS_RAMPS)]
    )
    print(f"  Ramp:          {config.brightness_ramp_idx} - {ramp_str}")
    print(f"  Color mode:    {config.color_mode}")
    print(f"  Depth palette: {pal_name}")
    print(f"  Resolution:    {WIDTH}x{HEIGHT} ({res_label})")
    print(f"  HUD overlay:   {'ON' if config.hud_visible else 'OFF'}")
    audio_str = "OFF"
    if config.audio_reactive:
        audio_str = "ON" if audio.running else "ON (no signal)"
    if not HAS_AUDIO:
        audio_str = "N/A (pip install sounddevice numpy)"
    print(f"  Audio react:   {audio_str}")
    print(f"  Audio device:  {audio.device_name}")
    print(f"  Terminal:      {terminal_size()[0]}x{terminal_size()[1] + 1}")
    print()
    print("  Same hotkeys as render view, plus:")
    print("  A = audio device setup")
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
        if ch == "A":
            run_audio_menu()
            continue
        if ch == "R":
            return "cycle_resolution"
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
        config.render_mode = (
            "points" if config.render_mode == "wire" else "wire"
        )
        return True
    elif ch == "b":
        config.brightness_enabled = not config.brightness_enabled
        return True
    elif ch == "B":
        config.brightness_ramp_idx = (
            (config.brightness_ramp_idx + 1) % len(BRIGHTNESS_RAMPS)
        )
        return True
    elif ch == "c":
        config.color_mode_idx = (
            (config.color_mode_idx + 1) % len(COLOR_MODES)
        )
        return True
    elif ch == "C":
        config.depth_palette_idx = (
            (config.depth_palette_idx + 1) % len(DEPTH_PALETTES)
        )
        return True
    elif ch == "a":
        config.audio_reactive = not config.audio_reactive
        if config.audio_reactive:
            if not audio.running:
                if not audio.start():
                    config.audio_reactive = False
        else:
            audio.stop()
        return True
    elif ch == ".":
        config.hud_visible = not config.hud_visible
        return True
    return False


# ── Main loop ─────────────────────────────────────────

def main():
    global WIDTH, HEIGHT, config

    tw, th = terminal_size()
    WIDTH, HEIGHT = tw, th
    config = Config(auto_fov=fov_for_size(WIDTH, HEIGHT))

    scr = ScreenBuffer(WIDTH, HEIGHT)
    angle_x = 0.0
    angle_y = 0.0
    last_switch = time.time()
    last_frame = time.time()
    frame_count = 0
    audio_punch = 0.0
    audio_bpm = 120.0
    need_resize = False

    sys.stdout.write("\033[?25l")
    sys.stdout.flush()
    os.system(CLEAR_CMD)

    try:
        while True:
            now = time.time()
            dt = now - last_frame
            last_frame = now
            dt_scale = dt / 0.03 if dt > 0 else 1.0

            # Resize buffer if resolution changed
            if need_resize:
                scr = ScreenBuffer(WIDTH, HEIGHT)
                os.system(CLEAR_CMD)
                need_resize = False

            # Input
            ch = get_key()
            if ch:
                if ch == " ":
                    config.paused = not config.paused
                elif ch == "q":
                    return
                elif ch == "R":
                    config.resolution_idx = (
                        (config.resolution_idx + 1) % len(RESOLUTION_PRESETS)
                    )
                    apply_resolution(config.resolution_idx)
                    need_resize = True
                elif ch == "A":
                    sys.stdout.write("\033[?25h")
                    sys.stdout.flush()
                    run_audio_menu()
                    sys.stdout.write("\033[?25l")
                    sys.stdout.flush()
                    os.system(CLEAR_CMD)
                    last_frame = time.time()
                elif ch == "m":
                    sys.stdout.write("\033[?25h")
                    sys.stdout.flush()
                    result = run_menu()
                    sys.stdout.write("\033[?25l")
                    sys.stdout.flush()
                    os.system(CLEAR_CMD)
                    last_frame = time.time()
                    if result == "quit":
                        return
                    elif result == "reset_angles":
                        angle_x = angle_y = 0.0
                    elif result == "cycle_resolution":
                        config.resolution_idx = (
                            (config.resolution_idx + 1)
                            % len(RESOLUTION_PRESETS)
                        )
                        apply_resolution(config.resolution_idx)
                        need_resize = True
                elif ch == "r":
                    angle_x = angle_y = 0.0
                else:
                    handle_common_key(ch)

            # Auto shape switching
            if (not config.audio_reactive
                    and config.auto_switch.value > 0
                    and now - last_switch > config.auto_switch.value):
                config.shape_index = random.randrange(len(SHAPES))
                last_switch = now

            # Audio processing
            audio_rms = 0.0
            bpm_str = ""
            if config.audio_reactive and audio.running:
                rms, onset, bpm = audio.get_features()
                audio_rms = rms
                audio_bpm = bpm
                bpm_str = f"{bpm:.0f}bpm"

                if onset:
                    audio_punch = 1.0
                    config.shape_index = random.randrange(len(SHAPES))
                    config.depth_palette_idx = (
                        (config.depth_palette_idx + 1) % len(DEPTH_PALETTES)
                    )
                    last_switch = now

                audio_punch *= 0.85 ** dt_scale

            elif config.audio_reactive and not audio.running:
                bpm_str = "waiting..."

            # Temporarily apply audio scale boost
            saved_scale = config.scale.value
            if config.audio_reactive and audio.running:
                config.scale.value *= (
                    1.0 + audio_punch * 0.5 + audio_rms * 2.0
                )

            # Render
            scr.clear()

            si = config.shape_index
            _, draw_func = SHAPES[si]

            def color_fn(z, _si=si, _fc=frame_count):
                return get_cell_color(z, _si, _fc)

            draw_func(angle_x, angle_y, scr, color_fn)

            if config.hud_visible:
                scr.put_text(0, 0, build_hud_line1(bpm_str)[:WIDTH])
                scr.put_text(0, 1, build_hud_line2()[:WIDTH])
                scr.put_text(0, HEIGHT - 1, build_hud_line3()[:WIDTH])

            sys.stdout.write("\033[H")
            sys.stdout.write(scr.render())
            sys.stdout.flush()

            # Restore scale
            config.scale.value = saved_scale

            # Update angles (delta-time compensated)
            if not config.paused:
                if config.audio_reactive and audio.running:
                    bps = audio_bpm / 60.0
                    angle_x += bps * 1.0 * dt
                    angle_y += bps * 0.83 * dt
                else:
                    angle_x += config.speed_x.value * dt_scale
                    angle_y += config.speed_y.value * dt_scale

            frame_count += 1
            time.sleep(0.03)

    finally:
        audio.stop()
        sys.stdout.write("\033[?25h")
        sys.stdout.write(COLOR_RESET)
        sys.stdout.flush()
        os.system(CLEAR_CMD)
        print("Goodbye.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        audio.stop()
        sys.stdout.write("\033[?25h")
        sys.stdout.write(COLOR_RESET)
        sys.stdout.flush()
        os.system(CLEAR_CMD)
        print("Interrupted.")
