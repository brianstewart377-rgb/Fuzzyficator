"""Pure configuration helpers shared by the desktop configurator and tests."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable


TEXTURE_TYPES = ("random", "perlin", "billow", "ridged", "voronoi")


@dataclass(frozen=True)
class FeatureSize:
    name: str
    millimetres: float


FEATURE_SIZES = (
    FeatureSize("Fine", 0.7),
    FeatureSize("Medium", 1.4),
    FeatureSize("Coarse", 2.8),
    FeatureSize("Extra coarse", 5.6),
)


@dataclass(frozen=True)
class TextureIntensity:
    name: str
    height: float
    speed: float
    resolution: float


INTENSITIES = {
    "Subtle": TextureIntensity("Subtle", height=0.15, speed=25.0, resolution=0.35),
    "Standard": TextureIntensity("Standard", height=0.30, speed=25.0, resolution=0.35),
    "Bold": TextureIntensity("Bold", height=0.40, speed=20.0, resolution=0.30),
}


def match_intensity(height: float, speed: float, resolution: float) -> str:
    values = (height, speed, resolution)
    for intensity_name, intensity in INTENSITIES.items():
        expected = (intensity.height, intensity.speed, intensity.resolution)
        if all(abs(actual - target) < 1e-9 for actual, target in zip(values, expected)):
            return intensity_name
    return "Custom"


@dataclass(frozen=True)
class ConfiguratorSettings:
    texture: str = "ridged"
    size: float = 1.4
    height: float = 0.30
    speed: float = 25.0
    resolution: float = 0.35
    top_surface: bool = True
    lower_surface: bool = False
    connect_walls: bool = True
    compensate_extrusion: bool = True
    octaves: int = 4
    persistence: float = 0.5
    seed: int = 42

    def validated(self) -> "ConfiguratorSettings":
        if self.texture not in TEXTURE_TYPES:
            raise ValueError(f"Unknown texture: {self.texture}")
        if self.size <= 0:
            raise ValueError("Feature size must be greater than zero")
        if self.height < 0:
            raise ValueError("Texture height cannot be negative")
        if self.speed <= 0:
            raise ValueError("Speed must be greater than zero")
        if self.resolution <= 0:
            raise ValueError("Resolution must be greater than zero")
        if not self.top_surface and not self.lower_surface:
            raise ValueError("Select at least one surface")
        if not 1 <= self.octaves <= 12:
            raise ValueError("Octaves must be between 1 and 12")
        if not 0 < self.persistence <= 1:
            raise ValueError("Persistence must be greater than zero and at most one")
        return self

    def with_values(self, **changes: object) -> "ConfiguratorSettings":
        return replace(self, **changes).validated()

    def processor_arguments(self) -> list[str]:
        self.validated()
        arguments = [
            "--run",
            "1",
            "--texture",
            self.texture,
            "--height",
            _number(self.height),
            "--resolution",
            _number(self.resolution),
            "--connect-walls",
            _toggle(self.connect_walls),
            "--compensate-extrusion",
            _toggle(self.compensate_extrusion),
            "--top-surface",
            _toggle(self.top_surface),
            "--lower-surface",
            _toggle(self.lower_surface),
            "--speed",
            _number(self.speed),
            "--seed",
            str(self.seed),
        ]
        if self.texture != "random":
            arguments.extend(
                [
                    "--size",
                    _number(self.size),
                    "--noise-octaves",
                    str(self.octaves),
                    "--noise-persistence",
                    _number(self.persistence),
                ]
            )
        return arguments

    def slicer_command(self, python_path: Path | str, script_path: Path | str) -> str:
        tokens = [str(python_path), str(script_path), *self.processor_arguments()]
        return subprocess.list2cmdline(tokens)

    def application_command(self, application_path: Path | str) -> str:
        """Build a slicer command for the bundled single-file application."""
        return subprocess.list2cmdline([str(application_path), *self.processor_arguments()])

    @property
    def size_name(self) -> str:
        if self.texture == "random":
            return "Scale-independent"
        closest = min(FEATURE_SIZES, key=lambda item: abs(item.millimetres - self.size))
        if abs(closest.millimetres - self.size) < 1e-9:
            return closest.name
        return f"Custom {self.size:g} mm"


def preview_choices() -> Iterable[tuple[str, FeatureSize | None]]:
    """Yield every selectable preview; Random intentionally has no size."""
    yield "random", None
    for texture in TEXTURE_TYPES[1:]:
        for feature_size in FEATURE_SIZES:
            yield texture, feature_size


def _number(value: float) -> str:
    return f"{value:.6g}"


def _toggle(value: bool) -> str:
    return "1" if value else "0"
