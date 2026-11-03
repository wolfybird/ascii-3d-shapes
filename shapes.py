import os
import time
import math


class Vector3D:
    def __init__(self, x, y, z):
        self.x = x
        self.y = y
        self.z = z

    def rotateX(self, angle):
        """Rotate the point around the X axis"""
        cosAngle = math.cos(angle)
        sinAngle = math.sin(angle)
        y = self.y * cosAngle - self.z * sinAngle
        z = self.y * sinAngle + self.z * cosAngle
        return Vector3D(self.x, y, z)

    def rotateY(self, angle):
        """Rotate the point around the Y axis"""
        cosAngle = math.cos(angle)
        sinAngle = math.sin(angle)
        z = self.z * cosAngle - self.x * sinAngle
        x = self.z * sinAngle + self.x * cosAngle
        return Vector3D(x, self.y, z)

    def project(self, width, height, fov, distance):
        """Project the 3D point to the 2D screen"""
        factor = fov / (self.z + distance)
        x = self.x * factor + width / 2
        y = -self.y * factor + height / 2
        return Vector3D(x, y, self.z)


def print_line(start, end):
    """Print a line between two projected points"""
    steps = max(int(abs(start.x - end.x)), int(abs(start.y - end.y)))

    if steps == 0:
        x = int(start.x)
        y = int(start.y)
        print("\033[%d;%dH!" % (y, x))
        return

    for step in range(steps + 1):
        t = step / steps
        x = int(start.x * (1 - t) + end.x * t)
        y = int(start.y * (1 - t) + end.y * t)
        print("\033[%d;%dH`" % (y, x))

def draw_cube(angleX, angleY, width, height, distance):
    os.system('cls' if os.name == 'nt' else 'clear')

    halfSize = 1.5
    vertices = [
        Vector3D(-halfSize, halfSize, -halfSize),
        Vector3D(halfSize, halfSize, -halfSize),
        Vector3D(halfSize, -halfSize, -halfSize),
        Vector3D(-halfSize, -halfSize, -halfSize),
        Vector3D(-halfSize, halfSize, halfSize),
        Vector3D(halfSize, halfSize, halfSize),
        Vector3D(halfSize, -halfSize, halfSize),
        Vector3D(-halfSize, -halfSize, halfSize)
    ]

    projected_vertices = []
    for v in vertices:
        rotated = v.rotateX(angleX).rotateY(angleY)
        projected = rotated.project(width, height, 8, distance)  # use the passed distance here
        projected_vertices.append(projected)

    for i in range(4):
        start = projected_vertices[i]
        end = projected_vertices[(i + 1) % 4]
        print_line(start, end)

        start = projected_vertices[i + 4]
        end = projected_vertices[(i + 1) % 4 + 4]
        print_line(start, end)

        start = projected_vertices[i]
        end = projected_vertices[i + 4]
        print_line(start, end)


def main():
    angleX, angleY = 0, 0
    distance = 3.0  # Initial distance
    zoom_speed = .6  # Adjust this to make zooming faster or slower

    while True:
        draw_cube(angleX, angleY, 80, 40, distance)
        time.sleep(0)

        angleX += 0.10
        angleY += 0.10

        distance += zoom_speed  # Zoom ou
        if distance > 6 or distance < 3.5 :  # Reverse zoom direction when reaching a limit
            zoom_speed = -zoom_speed


if __name__ == "__main__":
    main()