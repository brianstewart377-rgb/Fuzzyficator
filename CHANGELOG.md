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
- Added a dependency-free desktop configurator with exact clickable style/size previews, explicit Subtle/Standard/Bold intensity controls, slicer checks, and command copying.
- Replaced raw height-map selector cards with shaded Hilbert toolpath simulations and added a corner view that distinguishes the textured top from smooth vertical walls.
- Added a single Windows application entry point that bundles the GUI and G-code processor and selects its mode from the supplied arguments.
- Added human-readable `--texture`, `--size`, `--height`, and `--speed` command aliases.
- Added a standard-library regression suite and multi-version GitHub Actions workflow.
