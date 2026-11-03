import os
import time
import math
import random
import sys

# ==========================
#  USER SETTINGS (GLOBAL)
# ==========================

# Terminal-safe clear command
CLEAR_CMD = "cls" if os.name == "nt" else "clear"

# Ask user for scale factor
try:
    SCALE = float(input("Enter scale factor (0.001 to 2.0): "))
    SCALE = max(0.001, min(SCALE, 2.0))
except:
    SCALE = 1.0

# Global appearance settings
FOV = 4.0
CUBE_CHAR = "+"
SPHERE_CHAR = "."
PYRAMID_CHAR = "^"
PYRAMID_LINE_CHAR = "^"

# Output area
WIDTH = int(80 * SCALE * 2)
HEIGHT = int(40 * SCALE * 2)


# ==========================
#  VECTOR CLASS
# ==========================
class Vector3D:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z

    def rotateX(self, angle):
        c = math.cos(angle)
        s = math.sin(angle)
        y = self.y * c - self.z * s
        z = self.y * s + self.z * c
        return Vector3D(self.x, y, z)

    def rotateY(self, angle):
        c = math.cos(angle)
        s = math.sin(angle)
        z = self.z * c - self.x * s
        x = self.z * s + self.x * c
        return Vector3D(x, self.y, z)

    def project(self):
        factor = FOV / (self.z + 5.0)
        x = int(self.x * factor * SCALE + WIDTH // 2)
        y = int(-self.y * factor * SCALE + HEIGHT // 2)
        return x, y


# ==========================
#  DRAWING UTILITY
# ==========================
def print_line(p1, p2, char):
    x1, y1 = p1
    x2, y2 = p2

    dx = abs(x2 - x1)
    dy = abs(y2 - y1)
    steps = max(dx, dy)

    if steps == 0:
        print(f"\033[{y1};{x1}H{char}")
        return

    for i in range(steps + 1):
        t = i / steps
        x = int(x1 * (1 - t) + x2 * t)
        y = int(y1 * (1 - t) + y2 * t)
        print(f"\033[{y};{x}H{char}")


# ==========================
#  CUBE
# ==========================
def get_cube_vertices():
    s = 1.0 * SCALE
    return [
        Vector3D(-s, -s, -s),
        Vector3D(s, -s, -s),
        Vector3D(s, s, -s),
        Vector3D(-s, s, -s),
        Vector3D(-s, -s, s),
        Vector3D(s, -s, s),
        Vector3D(s, s, s),
        Vector3D(-s, s, s)
    ]


def draw_cube(ax, ay):
    verts = [v.rotateX(ax).rotateY(ay).project() for v in get_cube_vertices()]

    edges = [
        (0,1),(1,2),(2,3),(3,0),
        (4,5),(5,6),(6,7),(7,4),
        (0,4),(1,5),(2,6),(3,7)
    ]

    for a,b in edges:
        print_line(verts[a], verts[b], CUBE_CHAR)


# ==========================
#  SPHERE
# ==========================
def get_sphere_vertices(segments=22):
    verts = []
    r = 1.0 * SCALE
    for i in range(segments):
        lat = math.pi * (i / segments)
        for j in range(segments):
            lon = 2 * math.pi * (j / segments)
            x = r * math.sin(lat) * math.cos(lon)
            y = r * math.sin(lat) * math.sin(lon)
            z = r * math.cos(lat)
            verts.append(Vector3D(x, y, z))
    return verts


def draw_sphere(ax, ay):
    verts = [v.rotateX(ax).rotateY(ay).project() for v in get_sphere_vertices()]
    for x,y in verts:
        print(f"\033[{y};{x}H{SPHERE_CHAR}")


# ==========================
#  PYRAMID
# ==========================
def get_pyramid_vertices():
    s = 1.5 * SCALE
    return [
        Vector3D(0, s, 0),
        Vector3D(-s, -s, s),
        Vector3D(s, -s, s),
        Vector3D(s, -s, -s),
        Vector3D(-s, -s, -s)
    ]


def draw_pyramid(ax, ay):
    pv = [v.rotateX(ax).rotateY(ay).project() for v in get_pyramid_vertices()]

    # Base
    for i in range(1,5):
        print_line(pv[i], pv[(i%4)+1], PYRAMID_CHAR)

    # Sides
    for i in range(1,5):
        print_line(pv[0], pv[i], PYRAMID_LINE_CHAR)


# ==========================
#  MAIN LOOP
# ==========================
def main():
    ax = ay = 0
    distance = 5

    shapes = [draw_cube, draw_pyramid, draw_sphere]
    current = random.choice(shapes)
    last_switch = time.time()

    while True:
        os.system(CLEAR_CMD)
        print("\033[0;0H", end="")

        now = time.time()
        if now - last_switch > 5:
            current = random.choice(shapes)
            last_switch = now

        current(ax, ay)

        ax += 0.06
        ay += 0.05

        time.sleep(0.02)


if __name__ == "__main__":
    main()
