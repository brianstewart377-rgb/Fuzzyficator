"""Fuzzyficator G-code post-processor.

This module keeps the original one-file post-processing workflow while fixing
extrusion conservation, path continuity, setting inheritance, and safe file
replacement. It also adds deterministic spatial noise suitable for continuous
top-surface paths such as Hilbert curves.
"""

# SPDX-License-Identifier: GPL-3.0-or-later
# Original work Copyright (c) 2024 Roman Tenger.
# Correctness and patterned-noise rewrite Copyright (c) 2026 Fuzzyficator contributors.

from __future__ import annotations

import argparse
import logging
import math
import os
import random
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence


VERSION = "2.0.0-dev"
PROCESSED_MARKER = "; FUZZYFICATOR: PROCESSED"
NUMBER_PATTERN = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
PARAMETER_RE = re.compile(rf"(?<![A-Za-z])([A-Za-z])({NUMBER_PATTERN})")
MOTION_RE = re.compile(r"^\s*G0?([01])(?:\s|$)", re.IGNORECASE)


LOOKUP_TABLES = {
    "prusaslicer": {
        "fuzzy_skin": ("; fuzzy_skin =",),
        "fuzzy_skin_point_dist": ("; fuzzy_skin_point_dist =", "; fuzzy_skin_point_distance ="),
        "fuzzy_skin_thickness": ("; fuzzy_skin_thickness =",),
        "top_solid_infill": ";TYPE:Top solid infill",
        "type": ";TYPE:",
        "layer": ";LAYER_CHANGE",
        "bridge": ";TYPE:Bridge infill",
        "support_contact": ("; support_material_contact_distance =",),
        "overhang": ";TYPE:Overhang perimeter",
    },
    "orcaslicer": {
        "fuzzy_skin": ("; fuzzy_skin =",),
        "fuzzy_skin_point_dist": ("; fuzzy_skin_point_distance =", "; fuzzy_skin_point_dist ="),
        "fuzzy_skin_thickness": ("; fuzzy_skin_thickness =",),
        "top_solid_infill": ";TYPE:Top surface",
        "type": ";TYPE:",
        "layer": ";LAYER_CHANGE",
        "bridge": ";TYPE:Bridge",
        "support_contact": ("; support_bottom_z_distance =",),
        "overhang": ";TYPE:Overhang wall",
    },
    "bambustudio": {
        "fuzzy_skin": ("; fuzzy_skin =",),
        "fuzzy_skin_point_dist": ("; fuzzy_skin_point_distance =", "; fuzzy_skin_point_dist ="),
        "fuzzy_skin_thickness": ("; fuzzy_skin_thickness =",),
        "top_solid_infill": "; FEATURE: Top surface",
        "type": "; FEATURE:",
        "layer": "; CHANGE_LAYER",
        "bridge": "; FEATURE: Bridge",
        "support_contact": ("; support_top_z_distance =",),
        "overhang": "; FEATURE: Overhang wall",
    },
}


class FuzzyficatorError(RuntimeError):
    """Base exception for safe, user-facing processing failures."""


class UnsupportedGCodeError(FuzzyficatorError):
    """Raised when the input uses a mode the processor cannot safely rewrite."""


class ConfigurationError(FuzzyficatorError):
    """Raised when command-line or inherited settings are invalid."""


def clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def parse_parameters(line: str) -> dict[str, float]:
    """Return numeric G-code parameters, ignoring everything after a comment."""
    code = line.split(";", 1)[0]
    return {match.group(1).upper(): float(match.group(2)) for match in PARAMETER_RE.finditer(code)}


def is_motion_line(line: str) -> bool:
    return bool(MOTION_RE.match(line.split(";", 1)[0]))


def is_extrusion_move(line: str) -> bool:
    if not is_motion_line(line):
        return False
    params = parse_parameters(line)
    return ("X" in params or "Y" in params) and params.get("E", 0.0) > 0.0


def extract_extrusion_values(gcode_text: str) -> list[float]:
    """Extract positive relative extrusion values from executable motion lines."""
    values: list[float] = []
    for line in gcode_text.splitlines():
        if not is_motion_line(line):
            continue
        extrusion = parse_parameters(line).get("E")
        if extrusion is not None and extrusion > 0.0:
            values.append(extrusion)
    return values


class TextureNoise:
    """Deterministic random and spatial texture generators returning 0..1."""

    _GRADIENTS = (
        (1.0, 0.0),
        (-1.0, 0.0),
        (0.0, 1.0),
        (0.0, -1.0),
        (0.7071067812, 0.7071067812),
        (-0.7071067812, 0.7071067812),
        (0.7071067812, -0.7071067812),
        (-0.7071067812, -0.7071067812),
    )

    def __init__(
        self,
        noise_type: str = "random",
        *,
        seed: int = 0,
        scale: float = 1.4,
        octaves: int = 4,
        persistence: float = 0.5,
    ) -> None:
        self.noise_type = noise_type.lower()
        self.seed = int(seed)
        self.scale = float(scale)
        self.octaves = int(octaves)
        self.persistence = float(persistence)
        self._random = random.Random(self.seed)
        if self.noise_type not in {"random", "perlin", "billow", "ridged", "voronoi"}:
            raise ConfigurationError(f"Unknown noise type: {noise_type}")
        if self.scale <= 0:
            raise ConfigurationError("Noise scale must be greater than zero")
        if self.octaves < 1 or self.octaves > 12:
            raise ConfigurationError("Noise octaves must be between 1 and 12")
        if not 0.0 < self.persistence <= 1.0:
            raise ConfigurationError("Noise persistence must be greater than 0 and at most 1")

    def _hash(self, x_value: int, y_value: int, salt: int = 0) -> int:
        value = (
            x_value * 0x1F123BB5
            + y_value * 0x5F356495
            + self.seed * 0x6C8E9CF5
            + salt * 0x27D4EB2D
        ) & 0xFFFFFFFF
        value ^= value >> 15
        value = (value * 0x2C1B3C6D) & 0xFFFFFFFF
        value ^= value >> 12
        value = (value * 0x297A2D39) & 0xFFFFFFFF
        value ^= value >> 15
        return value & 0xFFFFFFFF

    @staticmethod
    def _fade(value: float) -> float:
        return value * value * value * (value * (value * 6.0 - 15.0) + 10.0)

    @staticmethod
    def _lerp(start: float, end: float, amount: float) -> float:
        return start + amount * (end - start)

    def _gradient_dot(self, grid_x: int, grid_y: int, x_offset: float, y_offset: float) -> float:
        gradient = self._GRADIENTS[self._hash(grid_x, grid_y) & 7]
        return gradient[0] * x_offset + gradient[1] * y_offset

    def _perlin(self, x_value: float, y_value: float) -> float:
        x_floor = math.floor(x_value)
        y_floor = math.floor(y_value)
        x_fraction = x_value - x_floor
        y_fraction = y_value - y_floor
        fade_x = self._fade(x_fraction)
        fade_y = self._fade(y_fraction)
        bottom_left = self._gradient_dot(x_floor, y_floor, x_fraction, y_fraction)
        bottom_right = self._gradient_dot(x_floor + 1, y_floor, x_fraction - 1.0, y_fraction)
        top_left = self._gradient_dot(x_floor, y_floor + 1, x_fraction, y_fraction - 1.0)
        top_right = self._gradient_dot(x_floor + 1, y_floor + 1, x_fraction - 1.0, y_fraction - 1.0)
        bottom = self._lerp(bottom_left, bottom_right, fade_x)
        top = self._lerp(top_left, top_right, fade_x)
        return clamp(self._lerp(bottom, top, fade_y), -1.0, 1.0)

    def _octave_samples(self, x_value: float, y_value: float) -> Iterable[tuple[float, float]]:
        frequency = 1.0
        amplitude = 1.0
        for _ in range(self.octaves):
            yield self._perlin(
                x_value * frequency / self.scale,
                y_value * frequency / self.scale,
            ), amplitude
            frequency *= 2.0
            amplitude *= self.persistence

    def _fractal_perlin(self, x_value: float, y_value: float) -> float:
        total = 0.0
        amplitude_sum = 0.0
        for sample, amplitude in self._octave_samples(x_value, y_value):
            total += sample * amplitude
            amplitude_sum += amplitude
        return total / amplitude_sum if amplitude_sum else 0.0

    def _billow(self, x_value: float, y_value: float) -> float:
        total = 0.0
        amplitude_sum = 0.0
        for sample, amplitude in self._octave_samples(x_value, y_value):
            total += (2.0 * abs(sample) - 1.0) * amplitude
            amplitude_sum += amplitude
        signed = total / amplitude_sum if amplitude_sum else 0.0
        return clamp(0.5 + 0.5 * signed)

    def _ridged(self, x_value: float, y_value: float) -> float:
        total = 0.0
        amplitude_sum = 0.0
        weight = 1.0
        for sample, amplitude in self._octave_samples(x_value, y_value):
            signal = 1.0 - abs(sample)
            signal *= signal
            signal *= weight
            weight = clamp(signal * 2.0)
            total += signal * amplitude
            amplitude_sum += amplitude
        return clamp(total / amplitude_sum if amplitude_sum else 0.0)

    def _voronoi(self, x_value: float, y_value: float) -> float:
        scaled_x = x_value / self.scale
        scaled_y = y_value / self.scale
        cell_x = math.floor(scaled_x)
        cell_y = math.floor(scaled_y)
        closest = math.inf
        for offset_y in range(-1, 2):
            for offset_x in range(-1, 2):
                candidate_x = cell_x + offset_x
                candidate_y = cell_y + offset_y
                point_x = candidate_x + self._hash(candidate_x, candidate_y, 1) / 0xFFFFFFFF
                point_y = candidate_y + self._hash(candidate_x, candidate_y, 2) / 0xFFFFFFFF
                closest = min(closest, math.hypot(scaled_x - point_x, scaled_y - point_y))
        return clamp(1.0 - closest / math.sqrt(2.0))

    def sample(self, x_value: float, y_value: float) -> float:
        if self.noise_type == "random":
            return self._random.random()
        if self.noise_type == "perlin":
            return clamp(0.5 + 0.5 * self._fractal_perlin(x_value, y_value))
        if self.noise_type == "billow":
            return self._billow(x_value, y_value)
        if self.noise_type == "ridged":
            return self._ridged(x_value, y_value)
        return self._voronoi(x_value, y_value)


class FuzzySkinConfig:
    def __init__(self, args: argparse.Namespace) -> None:
        self.input_file = args.input_gcode
        self.output_file = getattr(args, "output", None)
        self.resolution = getattr(args, "resolution", None)
        self.z_min = float(getattr(args, "zMin", 0.0))
        self.z_max = getattr(args, "zMax", None)
        self.connect_walls = bool(getattr(args, "connectWalls", 1))
        self.fuzzy_speed = getattr(args, "fuzzySpeed", None)
        self.run = getattr(args, "run", None)
        self.compensate_extrusion = bool(getattr(args, "compensateExtrusion", 1))
        self.lower_surface = bool(getattr(args, "lowerSurface", 1))
        self.top_surface = bool(getattr(args, "topSurface", 1))
        self.support_contact_dist: Optional[float] = None
        self.bridge_compensation_multiplier = float(getattr(args, "bridgeCompensationMultiplier", 3.0))
        self.min_support_distance = float(getattr(args, "minSupportDistance", 0.1))
        self.noise_type = getattr(args, "noiseType", "random").lower()
        self.noise_scale = float(getattr(args, "noiseScale", 1.4))
        self.noise_octaves = int(getattr(args, "noiseOctaves", 4))
        self.noise_persistence = float(getattr(args, "noisePersistence", 0.5))
        self.seed = int(getattr(args, "seed", 0))
        self.backup = bool(getattr(args, "backup", False))
        self.force = bool(getattr(args, "force", False))

    def apply_gcode_settings(
        self,
        fuzzy_enabled: bool,
        point_dist: Optional[float],
        thickness: Optional[float],
        support_contact_dist: Optional[float],
    ) -> None:
        """Apply slicer values only when the corresponding CLI option was omitted."""
        if self.resolution is None:
            self.resolution = point_dist if point_dist is not None else 0.3
        if self.z_max is None:
            self.z_max = thickness if thickness is not None else 0.3
        if self.run is None:
            self.run = 1 if fuzzy_enabled else 0
        self.support_contact_dist = support_contact_dist
        self.validate()

    def validate(self) -> None:
        if self.resolution is None or self.resolution <= 0:
            raise ConfigurationError("Resolution must be greater than zero")
        if self.z_max is None or self.z_max < self.z_min:
            raise ConfigurationError("zMax must be greater than or equal to zMin")
        if self.fuzzy_speed is not None and self.fuzzy_speed <= 0:
            raise ConfigurationError("Fuzzy speed must be greater than zero")
        if self.bridge_compensation_multiplier <= 0:
            raise ConfigurationError("Bridge compensation multiplier must be greater than zero")
        TextureNoise(
            self.noise_type,
            seed=self.seed,
            scale=self.noise_scale,
            octaves=self.noise_octaves,
            persistence=self.noise_persistence,
        )


@dataclass
class ProcessingStats:
    slicer: str = "unknown"
    input_extrusion: float = 0.0
    output_extrusion: float = 0.0
    rewritten_moves: int = 0
    generated_segments: int = 0
    skipped: bool = False

    def summary(self) -> str:
        if self.skipped:
            return "already processed or disabled; file left unchanged"
        return (
            f"slicer={self.slicer}, rewritten_moves={self.rewritten_moves}, "
            f"generated_segments={self.generated_segments}, "
            f"extrusion={self.input_extrusion:.5f}->{self.output_extrusion:.5f}"
        )


class GCodeProcessor:
    def __init__(self, config: FuzzySkinConfig) -> None:
        self.config = config
        self.lookup = LOOKUP_TABLES["prusaslicer"]
        self.current_layer_height = 0.0
        self.nominal_point: Optional[tuple[float, float, float]] = None
        self.physical_point: Optional[tuple[float, float, float]] = None
        self.in_top_solid_infill = False
        self.in_bridge = False
        self.has_overhang_in_layer = False
        self.extrusion_path_active = False
        self.active_feedrate: Optional[float] = None
        self.feature_entry_feedrate: Optional[float] = None
        self.absolute_positioning = True
        self.texture = TextureNoise(
            self.config.noise_type,
            seed=self.config.seed,
            scale=self.config.noise_scale,
            octaves=self.config.noise_octaves,
            persistence=self.config.noise_persistence,
        )
        self.stats = ProcessingStats()
        self._warned_missing_support_distance = False

    @staticmethod
    def calculate_distance(point1: Sequence[float], point2: Sequence[float]) -> float:
        return math.sqrt(sum((point2[index] - point1[index]) ** 2 for index in range(3)))

    def _texture_displacement(self, x_value: float, y_value: float) -> float:
        texture_value = self.texture.sample(x_value, y_value)
        displacement = self.config.z_min + texture_value * (self.config.z_max - self.config.z_min)
        if self.in_bridge:
            if self.config.support_contact_dist is None:
                if not self._warned_missing_support_distance:
                    logging.warning("Skipping lower-surface displacement: no support contact distance was found")
                    self._warned_missing_support_distance = True
                return 0.0
            safe_depth = max(0.0, self.config.support_contact_dist - self.config.min_support_distance)
            return -min(displacement, safe_depth)
        return displacement

    def interpolate_with_constant_resolution(
        self,
        start_point: Sequence[float],
        end_point: Sequence[float],
        segment_length: float,
        total_extrusion: float,
        *,
        path_start: bool = False,
        path_end: bool = False,
    ) -> list[tuple[float, float, float, float]]:
        """Split one extrusion move without duplicating its start or losing E."""
        nominal_distance = self.calculate_distance(start_point, end_point)
        if nominal_distance == 0.0 or total_extrusion <= 0.0:
            return []
        num_segments = max(1, math.ceil(nominal_distance / segment_length))
        base_extrusion = total_extrusion / num_segments
        nominal_previous = tuple(float(value) for value in start_point)
        if self.physical_point is not None and math.isclose(self.physical_point[0], start_point[0], abs_tol=1e-5) and math.isclose(self.physical_point[1], start_point[1], abs_tol=1e-5):
            physical_previous = self.physical_point
        else:
            physical_previous = nominal_previous
        if path_start and self.config.connect_walls:
            physical_previous = nominal_previous
        points: list[tuple[float, float, float, float]] = []
        for index in range(1, num_segments + 1):
            amount = index / num_segments
            nominal_current = tuple(
                float(start_point[axis]) + (float(end_point[axis]) - float(start_point[axis])) * amount
                for axis in range(3)
            )
            displacement = self._texture_displacement(nominal_current[0], nominal_current[1])
            if path_end and index == num_segments and self.config.connect_walls:
                displacement = 0.0
            physical_current = (
                nominal_current[0],
                nominal_current[1],
                nominal_current[2] + displacement,
            )
            if not self.in_bridge:
                physical_current = (
                    physical_current[0],
                    physical_current[1],
                    max(self.current_layer_height, physical_current[2]),
                )
            extrusion = base_extrusion
            if self.config.compensate_extrusion:
                nominal_segment_distance = self.calculate_distance(nominal_previous, nominal_current)
                physical_segment_distance = self.calculate_distance(physical_previous, physical_current)
                if nominal_segment_distance > 0.0:
                    factor = physical_segment_distance / nominal_segment_distance
                    if self.in_bridge:
                        factor = factor ** self.config.bridge_compensation_multiplier
                    extrusion *= factor
            points.append((physical_current[0], physical_current[1], physical_current[2], extrusion))
            nominal_previous = nominal_current
            physical_previous = physical_current
        return points

    @staticmethod
    def detect_slicer(gcode_lines: Sequence[str]) -> str:
        header = "".join(gcode_lines[:200]).lower()
        if "prusaslicer" in header:
            return "prusaslicer"
        if "orcaslicer" in header:
            return "orcaslicer"
        if "bambustudio" in header:
            return "bambustudio"
        return "prusaslicer"

    @staticmethod
    def detect_gcode_flavor(gcode_lines: Sequence[str]) -> Optional[str]:
        for line in gcode_lines:
            if line.lower().startswith("; gcode_flavor ="):
                return line.split("=", 1)[-1].strip().lower()
        return None

    @staticmethod
    def _last_setting(gcode_lines: Sequence[str], prefixes: Sequence[str]) -> Optional[str]:
        lowered_prefixes = tuple(prefix.lower() for prefix in prefixes)
        for line in reversed(gcode_lines):
            lowered = line.lower()
            if lowered.startswith(lowered_prefixes):
                return line.split("=", 1)[-1].strip()
        return None

    def process_fuzzy_skin_settings(
        self,
        gcode_lines: Sequence[str],
    ) -> tuple[bool, Optional[float], Optional[float], Optional[float]]:
        fuzzy_value = self._last_setting(gcode_lines, self.lookup["fuzzy_skin"])
        fuzzy_enabled = fuzzy_value is not None and fuzzy_value.lower() not in {"none", "off", "0", "false"}

        def float_setting(key: str) -> Optional[float]:
            value = self._last_setting(gcode_lines, self.lookup[key])
            if value is None:
                return None
            try:
                return float(value)
            except ValueError:
                logging.warning("Invalid numeric slicer setting for %s: %s", key, value)
                return None

        point_dist = float_setting("fuzzy_skin_point_dist") if fuzzy_enabled else None
        thickness = float_setting("fuzzy_skin_thickness") if fuzzy_enabled else None
        support_contact_dist = float_setting("support_contact")
        return fuzzy_enabled, point_dist, thickness, support_contact_dist

    @staticmethod
    def _validate_relative_extrusion(gcode_lines: Sequence[str]) -> None:
        relative_extrusion: Optional[bool] = None
        for line in gcode_lines:
            code = line.split(";", 1)[0].strip().upper()
            command = code.split(maxsplit=1)[0] if code else ""
            if command == "M82":
                relative_extrusion = False
            elif command == "M83":
                relative_extrusion = True
            elif is_extrusion_move(line) and relative_extrusion is not True:
                raise UnsupportedGCodeError(
                    "A positive extrusion move occurs before relative extrusion mode (M83). "
                    "Configure the slicer for relative extrusion."
                )

    def _target_point(self, params: dict[str, float]) -> tuple[float, float, float]:
        current = self.nominal_point or (0.0, 0.0, self.current_layer_height)
        if not self.absolute_positioning:
            return (
                current[0] + params.get("X", 0.0),
                current[1] + params.get("Y", 0.0),
                current[2] + params.get("Z", 0.0),
            )
        return (
            params.get("X", current[0]),
            params.get("Y", current[1]),
            params.get("Z", current[2]),
        )

    def _observe_mode_command(self, line: str) -> bool:
        code = line.split(";", 1)[0].strip()
        command = code.split(maxsplit=1)[0].upper() if code else ""
        if command == "G90":
            self.absolute_positioning = True
            return True
        if command == "G91":
            if self.in_top_solid_infill or self.in_bridge:
                raise UnsupportedGCodeError(
                    "Relative XYZ positioning (G91) cannot begin inside a textured feature."
                )
            self.absolute_positioning = False
            return True
        if command != "G92":
            return False
        params = parse_parameters(line)
        if self.nominal_point is None:
            self.nominal_point = (0.0, 0.0, self.current_layer_height)
        nominal_before = self.nominal_point
        physical_before = self.physical_point or nominal_before
        nominal_after = tuple(params.get(axis, nominal_before[index]) for index, axis in enumerate("XYZ"))
        coordinate_delta = tuple(nominal_after[index] - nominal_before[index] for index in range(3))
        self.nominal_point = nominal_after
        self.physical_point = tuple(physical_before[index] + coordinate_delta[index] for index in range(3))
        if "Z" in params:
            self.current_layer_height = params["Z"]
        return True

    def _observe_unmodified_motion(self, line: str) -> None:
        if not is_motion_line(line):
            return
        params = parse_parameters(line)
        if "F" in params:
            self.active_feedrate = params["F"]
        target = self._target_point(params)
        self.nominal_point = target
        current_physical = self.physical_point or target
        if self.absolute_positioning:
            self.physical_point = (
                params.get("X", current_physical[0]),
                params.get("Y", current_physical[1]),
                params.get("Z", current_physical[2]),
            )
        else:
            self.physical_point = (
                current_physical[0] + params.get("X", 0.0),
                current_physical[1] + params.get("Y", 0.0),
                current_physical[2] + params.get("Z", 0.0),
            )
        if "Z" in params:
            self.current_layer_height = params["Z"]

    def _next_motion_continues_extrusion(self, lines: Sequence[str], start_index: int) -> bool:
        for line in lines[start_index:]:
            stripped = line.strip()
            if not stripped:
                continue
            if line.startswith(self.lookup["layer"]) or line.startswith(self.lookup["type"]):
                return False
            if not is_motion_line(line):
                continue
            params = parse_parameters(line)
            if "X" in params or "Y" in params or "Z" in params or "E" in params:
                return is_extrusion_move(line)
        return False

    def _begin_feature(self, line: str, *, bridge: bool) -> list[str]:
        if not self.absolute_positioning:
            raise UnsupportedGCodeError(
                "Textured features in relative XYZ positioning mode (G91) are not supported; restore G90 first."
            )
        result = self._end_feature()
        self.in_top_solid_infill = not bridge
        self.in_bridge = bridge
        self.extrusion_path_active = False
        self.feature_entry_feedrate = self.active_feedrate
        result.append(line)
        return result

    def _end_feature(self) -> list[str]:
        if not (self.in_top_solid_infill or self.in_bridge):
            return []
        result: list[str] = []
        if self.nominal_point is not None and self.physical_point is not None and not math.isclose(
            self.nominal_point[2], self.physical_point[2], abs_tol=1e-5
        ):
            result.append(f"G1 Z{self.nominal_point[2]:.4f} ; FUZZYFICATOR restore nominal Z\n")
            self.physical_point = (
                self.physical_point[0],
                self.physical_point[1],
                self.nominal_point[2],
            )
        if (
            self.config.fuzzy_speed is not None
            and self.feature_entry_feedrate is not None
            and not math.isclose(self.active_feedrate or -1.0, self.feature_entry_feedrate)
        ):
            result.append(f"G1 F{self.feature_entry_feedrate:g} ; FUZZYFICATOR restore feed rate\n")
            self.active_feedrate = self.feature_entry_feedrate
        self.in_top_solid_infill = False
        self.in_bridge = False
        self.extrusion_path_active = False
        self.feature_entry_feedrate = None
        return result

    def _handle_extrusion(self, line: str, *, path_end: bool) -> list[str]:
        params = parse_parameters(line)
        target = self._target_point(params)
        if self.nominal_point is None:
            self._observe_unmodified_motion(line)
            return [line]
        extrusion = params.get("E", 0.0)
        path_start = not self.extrusion_path_active
        points = self.interpolate_with_constant_resolution(
            self.nominal_point,
            target,
            self.config.resolution,
            extrusion,
            path_start=path_start,
            path_end=path_end,
        )
        if not points:
            self._observe_unmodified_motion(line)
            return [line]
        result: list[str] = []
        requested_feedrate = self.config.fuzzy_speed if self.config.fuzzy_speed is not None else params.get("F")
        if requested_feedrate is not None and (
            self.active_feedrate is None or not math.isclose(self.active_feedrate, requested_feedrate)
        ):
            result.append(f"G1 F{requested_feedrate:g} ; FUZZYFICATOR texture feed rate\n")
            self.active_feedrate = requested_feedrate
        target_extrusion = sum(point[3] for point in points)
        rounded_extrusions = [round(point[3], 8) for point in points]
        rounded_extrusions[-1] = round(target_extrusion - sum(rounded_extrusions[:-1]), 8)
        for (x_value, y_value, z_value, _), e_value in zip(points, rounded_extrusions):
            result.append(f"G1 X{x_value:.4f} Y{y_value:.4f} Z{z_value:.4f} E{e_value:.8f}\n")
        result.append(f"; FUZZYFICATOR original: {line.strip()}\n")
        self.nominal_point = target
        self.physical_point = points[-1][:3]
        self.extrusion_path_active = not path_end
        self.stats.rewritten_moves += 1
        self.stats.generated_segments += len(points)
        return result

    def process_lines(self, gcode_lines: Sequence[str]) -> list[str]:
        result: list[str] = []
        for index, line in enumerate(gcode_lines):
            if self._observe_mode_command(line):
                result.append(line)
                continue
            if line.startswith(self.lookup["layer"]):
                result.extend(self._end_feature())
                self.has_overhang_in_layer = False
                self._observe_unmodified_motion(line)
                result.append(line)
                continue
            if line.startswith(self.lookup["top_solid_infill"]) and self.config.top_surface:
                result.extend(self._begin_feature(line, bridge=False))
                continue
            if line.startswith(self.lookup["overhang"]):
                result.extend(self._end_feature())
                self.has_overhang_in_layer = True
                result.append(line)
                continue
            if (
                line.startswith(self.lookup["bridge"])
                and self.config.lower_surface
                and self.has_overhang_in_layer
            ):
                result.extend(self._begin_feature(line, bridge=True))
                continue
            if line.startswith(self.lookup["type"]):
                result.extend(self._end_feature())
                result.append(line)
                continue
            if (self.in_top_solid_infill or self.in_bridge) and is_extrusion_move(line):
                path_end = not self._next_motion_continues_extrusion(gcode_lines, index + 1)
                result.extend(self._handle_extrusion(line, path_end=path_end))
                continue
            if self.in_top_solid_infill or self.in_bridge:
                if is_motion_line(line):
                    params = parse_parameters(line)
                    if "X" in params or "Y" in params or "Z" in params or (
                        "E" in params and params.get("E", 0.0) <= 0.0
                    ):
                        self.extrusion_path_active = False
                    self._observe_unmodified_motion(line)
                result.append(line)
                continue
            self._observe_unmodified_motion(line)
            result.append(line)
        result.extend(self._end_feature())
        return result

    @staticmethod
    def _atomic_write(path: str, content: str) -> None:
        directory = os.path.dirname(os.path.abspath(path)) or "."
        descriptor, temp_path = tempfile.mkstemp(prefix=".fuzzyficator-", suffix=".tmp", dir=directory, text=True)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
                handle.write(content)
            os.replace(temp_path, path)
        except Exception:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise

    def process_file(self) -> ProcessingStats:
        with open(self.config.input_file, "r", encoding="utf-8") as handle:
            original_text = handle.read()
        if PROCESSED_MARKER in original_text and not self.config.force:
            self.stats.skipped = True
            return self.stats
        gcode_lines = original_text.splitlines(keepends=True)
        self._validate_relative_extrusion(gcode_lines)
        slicer = self.detect_slicer(gcode_lines)
        gcode_flavor = self.detect_gcode_flavor(gcode_lines)
        self.lookup = LOOKUP_TABLES[slicer]
        if slicer == "orcaslicer" and gcode_flavor == "marlin":
            self.lookup = LOOKUP_TABLES["bambustudio"]
        self.stats.slicer = slicer
        self.stats.input_extrusion = sum(extract_extrusion_values(original_text))
        fuzzy_enabled, point_dist, thickness, support_contact_dist = self.process_fuzzy_skin_settings(gcode_lines)
        self.config.apply_gcode_settings(fuzzy_enabled, point_dist, thickness, support_contact_dist)
        self.texture = TextureNoise(
            self.config.noise_type,
            seed=self.config.seed,
            scale=self.config.noise_scale,
            octaves=self.config.noise_octaves,
            persistence=self.config.noise_persistence,
        )
        if not self.config.run:
            logging.info("Fuzzy skin is disabled; file left unchanged")
            self.stats.skipped = True
            return self.stats
        transformed_lines = self.process_lines(gcode_lines)
        marker = (
            f"{PROCESSED_MARKER} v{VERSION} noise={self.config.noise_type} "
            f"seed={self.config.seed}\n"
        )
        transformed_text = marker + "".join(transformed_lines)
        self.stats.output_extrusion = sum(extract_extrusion_values(transformed_text))
        output_path = self.config.output_file or self.config.input_file
        if self.config.backup and os.path.abspath(output_path) == os.path.abspath(self.config.input_file):
            shutil.copy2(self.config.input_file, self.config.input_file + ".bak")
        self._atomic_write(output_path, transformed_text)
        return self.stats


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )


def parse_arguments(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Add deterministic non-planar texture to top surfaces and supported lower surfaces."
    )
    parser.add_argument("input_gcode", help="Path supplied automatically by the slicer's post-processing runner")
    parser.add_argument("-resolution", "--resolution", dest="resolution", type=float, help="Maximum generated G-code segment length in mm")
    parser.add_argument("-zMin", "--z-min", dest="zMin", type=float, default=0.0, help="Minimum Z displacement in mm")
    parser.add_argument("-zMax", "--z-max", dest="zMax", type=float, help="Maximum Z displacement in mm")
    parser.add_argument("-connectWalls", "-ConnectWalls", "--connect-walls", dest="connectWalls", type=int, choices=(0, 1), default=1, help="Return each disconnected extrusion path to nominal Z")
    parser.add_argument("-run", "--run", dest="run", type=int, choices=(0, 1), help="Force processing on or off; otherwise inherit native fuzzy-skin enablement")
    parser.add_argument("-compensateExtrusion", "--compensate-extrusion", dest="compensateExtrusion", type=int, choices=(0, 1), default=1, help="Compensate extrusion for the actual 3D path length")
    parser.add_argument("-topSurface", "--top-surface", dest="topSurface", type=int, choices=(0, 1), default=1)
    parser.add_argument("-lowerSurface", "--lower-surface", dest="lowerSurface", type=int, choices=(0, 1), default=1)
    parser.add_argument("-fuzzySpeed", "--fuzzy-speed", dest="fuzzySpeed", type=float, help="Texture speed in mm/min")
    parser.add_argument("-minSupportDistance", "--min-support-distance", dest="minSupportDistance", type=float, default=0.1)
    parser.add_argument("-bridgeCompensationMultiplier", "--bridge-compensation-multiplier", dest="bridgeCompensationMultiplier", type=float, default=3.0)
    parser.add_argument("-noiseType", "--noise-type", dest="noiseType", type=str.lower, choices=("random", "perlin", "billow", "ridged", "voronoi"), default="random")
    parser.add_argument("-noiseScale", "--noise-scale", dest="noiseScale", type=float, default=1.4, help="Spatial feature size in mm for patterned noise")
    parser.add_argument("-noiseOctaves", "--noise-octaves", dest="noiseOctaves", type=int, default=4)
    parser.add_argument("-noisePersistence", "--noise-persistence", dest="noisePersistence", type=float, default=0.5)
    parser.add_argument("-seed", "--seed", dest="seed", type=int, default=0, help="Deterministic texture seed")
    parser.add_argument("--output", help="Write to a different path instead of replacing the slicer-supplied file")
    parser.add_argument("--backup", action="store_true", help="Create input.gcode.bak before in-place replacement")
    parser.add_argument("--force", action="store_true", help="Allow explicitly reprocessing a marked G-code file")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--version", action="version", version=f"Fuzzyficator {VERSION}")
    parser.add_argument("--set-resolution", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--set-zMax", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--set-run", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_arguments(argv)
    setup_logging(args.verbose)
    try:
        config = FuzzySkinConfig(args)
        stats = GCodeProcessor(config).process_file()
    except (FuzzyficatorError, OSError, ValueError) as error:
        logging.error("%s", error)
        return 2
    print(f"Fuzzyficator {VERSION}: {stats.summary()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
