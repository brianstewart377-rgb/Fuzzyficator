"""Render print-like previews from Fuzzyficator's actual texture sampler."""

from __future__ import annotations

import math
from typing import Optional

from Fuzzyficator import TextureNoise, clamp


RGBRows = list[bytes]


def hilbert_xy(order: int, index: int) -> tuple[int, int]:
    """Return the grid coordinate visited at *index* by a Hilbert curve."""
    if order < 1:
        raise ValueError("Hilbert order must be at least one")
    side = 1 << order
    if index < 0 or index >= side * side:
        raise ValueError("Hilbert index is outside the curve")
    x_value = 0
    y_value = 0
    remaining = index
    scale = 1
    while scale < side:
        rotate_x = 1 & (remaining // 2)
        rotate_y = 1 & (remaining ^ rotate_x)
        if rotate_y == 0:
            if rotate_x == 1:
                x_value = scale - 1 - x_value
                y_value = scale - 1 - y_value
            x_value, y_value = y_value, x_value
        x_value += scale * rotate_x
        y_value += scale * rotate_y
        remaining //= 4
        scale *= 2
    return x_value, y_value


def hilbert_path(order: int) -> list[tuple[int, int]]:
    side = 1 << order
    return [hilbert_xy(order, index) for index in range(side * side)]


def render_hilbert_surface(
    noise_type: str,
    *,
    output_size: int = 88,
    millimetres: float = 25.0,
    line_width: float = 0.45,
    height: float = 0.30,
    seed: int = 42,
    scale: float = 1.4,
    octaves: int = 4,
    persistence: float = 0.5,
    hilbert_order: int = 6,
) -> RGBRows:
    """Render raised filament following a realistic Hilbert top-surface path."""
    if output_size < 16:
        raise ValueError("Preview size must be at least 16 pixels")
    if millimetres <= 0 or line_width <= 0:
        raise ValueError("Preview dimensions must be greater than zero")
    if height < 0:
        raise ValueError("Texture height cannot be negative")

    texture = TextureNoise(
        noise_type,
        seed=seed,
        scale=scale,
        octaves=octaves,
        persistence=persistence,
    )
    path = hilbert_path(hilbert_order)
    grid_side = 1 << hilbert_order
    physical_step = millimetres / (grid_side - 1)
    pixel_step = (output_size - 1) / (grid_side - 1)
    heights = [
        height * texture.sample(grid_x * physical_step, grid_y * physical_step)
        for grid_x, grid_y in path
    ]

    surface: list[list[Optional[float]]] = [
        [None for _ in range(output_size)] for _ in range(output_size)
    ]
    millimetres_per_pixel = millimetres / (output_size - 1)
    radius_pixels = max(0.55, 0.5 * line_width / millimetres_per_pixel)
    bead_height = min(0.06, max(0.018, line_width * 0.10))
    for index in range(1, len(path)):
        start_x, start_y = path[index - 1]
        end_x, end_y = path[index]
        _paint_segment(
            surface,
            start_x * pixel_step,
            start_y * pixel_step,
            heights[index - 1],
            end_x * pixel_step,
            end_y * pixel_step,
            heights[index],
            radius_pixels,
            bead_height,
        )

    filled = _fill_surface_gaps(surface)
    return _shade_height_surface(filled, millimetres_per_pixel, max(height + bead_height, 0.01))


def render_corner_preview(
    noise_type: str,
    *,
    width: int = 292,
    height_pixels: int = 176,
    texture_height: float = 0.30,
    seed: int = 42,
    scale: float = 1.4,
    octaves: int = 4,
    persistence: float = 0.5,
) -> RGBRows:
    """Render the selected Hilbert top meeting the processor's smooth wall."""
    if width < 180 or height_pixels < 120:
        raise ValueError("Corner preview is too small")
    top_source = render_hilbert_surface(
        noise_type,
        output_size=144,
        height=texture_height,
        seed=seed,
        scale=scale,
        octaves=octaves,
        persistence=persistence,
    )
    canvas = [[(238, 239, 241) for _ in range(width)] for _ in range(height_pixels)]

    top_left = (18.0, 14.0)
    top_vector = (width - 72.0, 0.0)
    depth_vector = (36.0, 88.0)
    front_left = (top_left[0] + depth_vector[0], top_left[1] + depth_vector[1])
    front_right = (front_left[0] + top_vector[0], front_left[1])
    wall_bottom = min(height_pixels - 15, int(front_left[1] + 56))

    for y_value in range(height_pixels):
        depth = (y_value - top_left[1]) / depth_vector[1]
        if not 0.0 <= depth <= 1.0:
            continue
        for x_value in range(width):
            across = (x_value - top_left[0] - depth * depth_vector[0]) / top_vector[0]
            if 0.0 <= across <= 1.0:
                source_x = min(143, max(0, round(across * 143)))
                source_y = min(143, max(0, round(depth * 143)))
                row = top_source[source_y]
                source_index = source_x * 3
                canvas[y_value][x_value] = (
                    row[source_index],
                    row[source_index + 1],
                    row[source_index + 2],
                )

    wall_top = round(front_left[1])
    wall_left = round(front_left[0])
    wall_right = round(front_right[0])
    for y_value in range(wall_top, wall_bottom + 1):
        layer_phase = (y_value - wall_top) % 4
        layer_adjustment = -15 if layer_phase == 0 else (5 if layer_phase == 1 else 0)
        vertical_shade = round(10 * (y_value - wall_top) / max(1, wall_bottom - wall_top))
        for x_value in range(wall_left, min(width, wall_right + 1)):
            side_shade = round(9 * (x_value - wall_left) / max(1, wall_right - wall_left))
            base = 184 + layer_adjustment - vertical_shade + side_shade
            canvas[y_value][x_value] = (
                _byte(base + 5),
                _byte(base + 7),
                _byte(base + 9),
            )

    _draw_line(canvas, round(front_left[0]), wall_top, round(front_right[0]), wall_top, (91, 94, 99))
    _draw_line(canvas, wall_left, wall_bottom, wall_right, wall_bottom, (111, 114, 119))
    _draw_line(canvas, round(top_left[0]), round(top_left[1]), round(top_left[0] + top_vector[0]), round(top_left[1]), (145, 147, 151))
    return [bytes(channel for pixel in row for channel in pixel) for row in canvas]


def _paint_segment(
    surface: list[list[Optional[float]]],
    start_x: float,
    start_y: float,
    start_z: float,
    end_x: float,
    end_y: float,
    end_z: float,
    radius: float,
    bead_height: float,
) -> None:
    size = len(surface)
    distance = math.hypot(end_x - start_x, end_y - start_y)
    steps = max(1, math.ceil(distance * 2.0))
    for step in range(steps + 1):
        amount = step / steps
        centre_x = start_x + amount * (end_x - start_x)
        centre_y = start_y + amount * (end_y - start_y)
        centre_z = start_z + amount * (end_z - start_z)
        minimum_x = max(0, math.floor(centre_x - radius))
        maximum_x = min(size - 1, math.ceil(centre_x + radius))
        minimum_y = max(0, math.floor(centre_y - radius))
        maximum_y = min(size - 1, math.ceil(centre_y + radius))
        for pixel_y in range(minimum_y, maximum_y + 1):
            for pixel_x in range(minimum_x, maximum_x + 1):
                radial_distance = math.hypot(pixel_x - centre_x, pixel_y - centre_y)
                if radial_distance > radius:
                    continue
                cap = bead_height * math.sqrt(max(0.0, 1.0 - (radial_distance / radius) ** 2))
                candidate = centre_z + cap
                current = surface[pixel_y][pixel_x]
                if current is None or candidate > current:
                    surface[pixel_y][pixel_x] = candidate


def _fill_surface_gaps(surface: list[list[Optional[float]]]) -> list[list[float]]:
    size = len(surface)
    working = [row[:] for row in surface]
    for _ in range(3):
        updated = [row[:] for row in working]
        for y_value in range(size):
            for x_value in range(size):
                if working[y_value][x_value] is not None:
                    continue
                neighbours = []
                for offset_x, offset_y in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    neighbour_x = x_value + offset_x
                    neighbour_y = y_value + offset_y
                    if 0 <= neighbour_x < size and 0 <= neighbour_y < size:
                        neighbour = working[neighbour_y][neighbour_x]
                        if neighbour is not None:
                            neighbours.append(neighbour)
                if neighbours:
                    updated[y_value][x_value] = sum(neighbours) / len(neighbours)
        working = updated
    return [[0.0 if value is None else value for value in row] for row in working]


def _shade_height_surface(
    surface: list[list[float]],
    millimetres_per_pixel: float,
    maximum_height: float,
) -> RGBRows:
    size = len(surface)
    light = (-0.48, -0.64, 0.60)
    rows: RGBRows = []
    for y_value in range(size):
        channels = bytearray()
        for x_value in range(size):
            left = surface[y_value][max(0, x_value - 1)]
            right = surface[y_value][min(size - 1, x_value + 1)]
            above = surface[max(0, y_value - 1)][x_value]
            below = surface[min(size - 1, y_value + 1)][x_value]
            # Small FDM relief catches directional light more strongly than a
            # literal height-map render suggests. Exaggerating the normals
            # makes the printed character legible in an 88 px selector card.
            gradient_x = 3.6 * (right - left) / max(2 * millimetres_per_pixel, 1e-9)
            gradient_y = 3.6 * (below - above) / max(2 * millimetres_per_pixel, 1e-9)
            normal_length = math.sqrt(gradient_x * gradient_x + gradient_y * gradient_y + 1.0)
            normal = (-gradient_x / normal_length, -gradient_y / normal_length, 1.0 / normal_length)
            illumination = max(0.0, sum(component * direction for component, direction in zip(normal, light)))
            elevation = clamp(surface[y_value][x_value] / maximum_height)
            neighbour_average = 0.25 * (left + right + above + below)
            relief = clamp(
                0.5 + 2.5 * (surface[y_value][x_value] - neighbour_average) / maximum_height
            ) - 0.5
            brightness = 0.34 + 0.50 * illumination + 0.24 * elevation + 0.18 * relief
            channels.extend(
                (
                    _byte(205 * brightness + 24),
                    _byte(209 * brightness + 25),
                    _byte(214 * brightness + 27),
                )
            )
        rows.append(bytes(channels))
    return rows


def _draw_line(
    canvas: list[list[tuple[int, int, int]]],
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    colour: tuple[int, int, int],
) -> None:
    steps = max(abs(end_x - start_x), abs(end_y - start_y), 1)
    for index in range(steps + 1):
        amount = index / steps
        x_value = round(start_x + amount * (end_x - start_x))
        y_value = round(start_y + amount * (end_y - start_y))
        if 0 <= y_value < len(canvas) and 0 <= x_value < len(canvas[0]):
            canvas[y_value][x_value] = colour


def _byte(value: float) -> int:
    return max(0, min(255, round(value)))
