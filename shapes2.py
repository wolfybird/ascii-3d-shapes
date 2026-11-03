import os
import time
import math
import random





class Vector3D:
    def __init__(self, x, y, z):
        self.x = x
        self.y = y
        self.z = z

    def rotateX(self, angle):
        cosAngle = math.cos(angle)
        sinAngle = math.sin(angle)
        y = self.y * cosAngle - self.z * sinAngle
        z = self.y * sinAngle + self.z * cosAngle
        return Vector3D(self.x, y, z)

    def rotateY(self, angle):
        cosAngle = math.cos(angle)
        sinAngle = math.sin(angle)
        z = self.z * cosAngle - self.x * sinAngle
        x = self.z * sinAngle + self.x * cosAngle
        return Vector3D(x, self.y, z)

    def project(self, width, height, fov, distance):
        factor = fov / (self.z + distance)
        x = self.x * factor + width / 2
        y = -self.y * factor + height / 2
        return Vector3D(x, y, self.z)

def print_line(start, end):
    steps = max(int(abs(start.x - end.x)), int(abs(start.y - end.y)))

    if steps == 0:
        x = int(start.x)
        y = int(start.y)
        print("\033[%d;%dH+" % (y, x))
        return

    for step in range(steps + 1):
        t = step / steps
        x = int(start.x * (1 - t) + end.x * t)
        y = int(start.y * (1 - t) + end.y * t)
        print("\033[%d;%dH+" % (y, x))

def draw_cube(angleX, angleY, width, height, distance):
    os.system('cls' if os.name == 'nt' else 'clear')

...

def get_cube_vertices(size):
    """Generate vertices for a cube."""
    d = size / 2
    return [
        Vector3D(-d, -d, -d),
        Vector3D(d, -d, -d),
        Vector3D(d, d, -d),
        Vector3D(-d, d, -d),
        Vector3D(-d, -d, d),
        Vector3D(d, -d, d),
        Vector3D(d, d, d),
        Vector3D(-d, d, d)
    ]

def draw_cube(angleX, angleY, width, height, distance):
    os.system('cls' if os.name == 'nt' else 'clear')

    cube_vertices = get_cube_vertices(2)  # Cube size (2 in this case)

    projected_vertices = []
    for v in cube_vertices:
        rotated = v.rotateX(angleX).rotateY(angleY)
        projected = rotated.project(width, height, 8, distance)
        projected_vertices.append(projected)

    # Draw cube edges
    edges = [
        (0, 1), (1, 2), (2, 3), (3, 0),  # Bottom edges
        (4, 5), (5, 6), (6, 7), (7, 4),  # Top edges
        (0, 4), (1, 5), (2, 6), (3, 7)  # Side edges
    ]

    for edge in edges:
        start = projected_vertices[edge[0]]
        end = projected_vertices[edge[1]]
        print_line(start, end)



def get_sphere_vertices(radius, segments):
    """Generate vertices for a sphere."""
    vertices = []

    for i in range(segments):
        lat = (math.pi / segments) * i
        for j in range(segments):
            lon = (2 * math.pi / segments) * j
            x = radius * math.sin(lat) * math.cos(lon)
            y = radius * math.sin(lat) * math.sin(lon)
            z = radius * math.cos(lat)
            vertices.append(Vector3D(x, y, z))
    return vertices


def draw_sphere(angleX, angleY, width, height, distance):
    os.system('cls' if os.name == 'nt' else 'clear')

    sphere_vertices = get_sphere_vertices(2, 16)  # Radius and segments

    projected_vertices = []
    for v in sphere_vertices:
        rotated = v.rotateX(angleX).rotateY(angleY)
        projected = rotated.project(width, height, 8, distance)
        projected_vertices.append(projected)

    for v in projected_vertices:
        print("\033[%d;%dH." % (int(v.y), int(v.x)))



def get_pyramid_vertices(base_size, height):
    half_base = base_size / 2
    vertices = [
        Vector3D(0, height, 0),  # Top vertex
        Vector3D(-half_base, 0, half_base),  # Base vertices
        Vector3D(half_base, 0, half_base),
        Vector3D(half_base, 0, -half_base),
        Vector3D(-half_base, 0, -half_base)
    ]
    return vertices

def print_pyramid_line(start, end):
    steps = max(int(abs(start.x - end.x)), int(abs(start.y - end.y)))

    if steps == 0:
        x = int(start.x)
        y = int(start.y)
        print("\033[%d;%dH^" % (y, x))
        return

    for step in range(steps + 1):
        t = step / steps
        x = int(start.x * (1 - t) + end.x * t)
        y = int(start.y * (1 - t) + end.y * t)
        print("\033[%d;%dH`~" % (y, x))

def draw_pyramid(angleX, angleY, width, height, distance):
    os.system('cls' if os.name == 'nt' else 'clear')
    pyramid_vertices = get_pyramid_vertices(3, 3)  # Base size and height

    projected_vertices = []
    for v in pyramid_vertices:
        rotated = v.rotateX(angleX).rotateY(angleY)
        projected = rotated.project(width, height, 8, distance)
        projected_vertices.append(projected)

        # Draw the base
    for i in range(1, 5):
        print_pyramid_line(projected_vertices[i], projected_vertices[(i % 4) + 1])

        # Draw sides
    for i in range(1, 5):
        print_pyramid_line(projected_vertices[0], projected_vertices[i])


def main():
    angleX, angleY = 0, 0
    distance = 2.5  # Initial distance
    zoom_speed = .1 # Adjust this to make zooming faster or slower

    start_time = time.time()
    shape_duration = 3
    shapes = [0, 1, 2]  # 0 for cube, 1 for pyramid, 2 for sphere
    current_shape = random.choice(shapes)  # Start with a random shape

    while True:
        elapsed_time = time.time() - start_time

        if elapsed_time > shape_duration:
            start_time = time.time()
            current_shape = random.choice(shapes)

        if current_shape == 0:
            draw_cube(angleX, angleY, 80, 40, distance)
        elif current_shape == 1:
            draw_pyramid(angleX, angleY, 80, 40, distance)
        elif current_shape == 2:
            draw_sphere(angleX, angleY, 80, 40, distance)

        time.sleep(0)
        angleX += 0.10
        angleY += 0.10

        distance += zoom_speed
        if distance > 6 or distance < 3:
            zoom_speed = -zoom_speed

if __name__ == "__main__":
    main()

