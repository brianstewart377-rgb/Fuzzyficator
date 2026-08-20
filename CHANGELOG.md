# Changelog

## 2.0.0-dev

### Correctness

- Conserved relative extrusion and removed duplicate start-point extrusion.
- Changed interpolation to ceiling-based maximum segment length.
- Based extrusion compensation on adjacent 3D segment lengths.
- Preserved Z continuity across connected short moves, including Hilbert paths.
- Restored nominal Z and the prior feed rate after textured features.
- Corrected slicer-setting inheritance and current Bambu point-distance parsing.

### Safety

- Added atomic output replacement, optional backups, and separate output paths.
- Rejected unsafe extrusion/positioning modes before modifying input.
- Added a processed marker to prevent accidental double processing.
- Added deterministic seeds and explicit validation for all numeric settings.

### Textures and tooling

- Added Perlin, Billow, Ridged multifractal, and Voronoi spatial noise.
- Separated G-code interpolation resolution from spatial noise feature scale.
- Added dependency-free grayscale PNG texture previews.
- Added a standard-library regression suite and multi-version GitHub Actions workflow.
