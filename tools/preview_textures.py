"""Generate dependency-free grayscale PNG previews of Fuzzyficator noise fields."""

from __future__ import annotations

import argparse
import os
import struct
import sys
import zlib
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from Fuzzyficator import TextureNoise  # noqa: E402


NOISE_TYPES = ("random", "perlin", "billow", "ridged", "voronoi")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(chunk_type)
    checksum = zlib.crc32(payload, checksum)
    return struct.pack(">I", len(payload)) + chunk_type + payload + struct.pack(">I", checksum & 0xFFFFFFFF)


def write_grayscale_png(path: os.PathLike[str] | str, rows: list[bytes]) -> None:
    if not rows or not rows[0]:
        raise ValueError("Preview rows cannot be empty")
    width = len(rows[0])
    if any(len(row) != width for row in rows):
        raise ValueError("Every preview row must have the same width")
    height = len(rows)
    raw_scanlines = b"".join(b"\x00" + row for row in rows)
    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    content = (
        PNG_SIGNATURE
        + png_chunk(b"IHDR", header)
        + png_chunk(b"IDAT", zlib.compress(raw_scanlines, level=9))
        + png_chunk(b"IEND", b"")
    )
    with open(path, "wb") as handle:
        handle.write(content)


def render_texture(
    noise_type: str,
    *,
    size: int,
    millimetres: float,
    seed: int,
    scale: float,
    octaves: int,
    persistence: float,
) -> list[bytes]:
    texture = TextureNoise(
        noise_type,
        seed=seed,
        scale=scale,
        octaves=octaves,
        persistence=persistence,
    )
    pixel_size = millimetres / max(1, size - 1)
    return [
        bytes(
            round(255 * texture.sample(column * pixel_size, row * pixel_size))
            for column in range(size)
        )
        for row in range(size)
    ]


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Fuzzyficator texture height fields as PNG files")
    parser.add_argument("--output-dir", default="texture-previews")
    parser.add_argument("--size", type=int, default=256, help="Preview width and height in pixels")
    parser.add_argument("--millimetres", type=float, default=25.0, help="Physical area represented by each preview")
    parser.add_argument("--scale", type=float, default=1.4)
    parser.add_argument("--octaves", type=int, default=4)
    parser.add_argument("--persistence", type=float, default=0.5)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def main() -> int:
    args = parse_arguments()
    if args.size < 8:
        raise SystemExit("--size must be at least 8")
    if args.millimetres <= 0:
        raise SystemExit("--millimetres must be greater than zero")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for noise_type in NOISE_TYPES:
        rows = render_texture(
            noise_type,
            size=args.size,
            millimetres=args.millimetres,
            seed=args.seed,
            scale=args.scale,
            octaves=args.octaves,
            persistence=args.persistence,
        )
        destination = output_dir / f"{noise_type}-scale-{args.scale:g}-seed-{args.seed}.png"
        write_grayscale_png(destination, rows)
        print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
