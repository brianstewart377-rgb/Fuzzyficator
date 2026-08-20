# Fuzzyficator

Fuzzyficator is a G-code post-processor that adds non-planar texture to flat top surfaces and supported lower surfaces produced by Bambu Studio, OrcaSlicer, and PrusaSlicer.

This fork retains the original single-file workflow and GPL-3.0 licence while correcting the core interpolation and file-safety behaviour. It also adds deterministic spatial texture algorithms for coherent patterns across continuous paths such as Hilbert Curve.

> This software rewrites printer G-code. Test new settings on a small calibration piece before using them on a long print.

## What this fork fixes

- Conserves relative extrusion instead of re-extruding the beginning of every source move.
- Uses `ceil()` segmentation so generated moves never exceed the requested resolution.
- Compensates extrusion using the actual height change between adjacent generated points.
- Preserves texture across short connected moves and only reconnects to nominal Z at real path boundaries.
- Reads fuzzy-skin point distance and thickness from current Bambu Studio, OrcaSlicer, and PrusaSlicer G-code when CLI overrides are omitted.
- Restores nominal Z and the previous feed rate when leaving a textured feature.
- Rejects unsupported `M82` absolute extrusion without modifying the input.
- Replaces files atomically and can create an optional backup.
- Marks processed files to prevent accidental double processing.
- Uses deterministic seeds for repeatable results.

## Texture algorithms

`-noiseType` accepts:

- `random` — the original independent random-height character.
- `perlin` — smooth coherent hills.
- `billow` — rounded cloud-like islands.
- `ridged` — connected multifractal ridges.
- `voronoi` — cellular regions.

Patterned noise separates two concepts that the original script conflated:

- `-resolution` is the maximum generated G-code segment length.
- `-noiseScale` is the approximate spatial size of the texture features.

## Recommended Hilbert + Ridged preset

In the slicer select:

**Process → Strength → Top/Bottom Shells → Top Surface Pattern → Hilbert Curve**

Leave native fuzzy skin disabled and add this to the slicer's post-processing command, replacing the first two paths:

```text
"C:\pathToPython\python.exe" "C:\pathToScript\Fuzzyficator.py" -run 1 -noiseType ridged -noiseScale 1.4 -noiseOctaves 4 -noisePersistence 0.5 -resolution 0.35 -zMin 0 -zMax 0.30 -connectWalls 1 -compensateExtrusion 1 -topSurface 1 -lowerSurface 0 -fuzzySpeed 1500 -seed 42
```

`-fuzzySpeed` is expressed in millimetres per minute, so `1500` equals 25 mm/s.

### Standalone desktop app

The preferred Windows build is `dist\Fuzzyficator.exe`. Python, the processor, the exact preview engine, and the configurator are bundled into this one file:

- Double-click the executable with no arguments to open the configurator.
- Paste its generated command into Bambu Studio or OrcaSlicer.
- When the slicer supplies a G-code path, the same executable automatically runs in processor mode.

The generated command therefore refers only to `Fuzzyficator.exe`; users of the packaged app do not need to install Python or locate `Fuzzyficator.py`.

To rebuild the executable from source on Windows:

```powershell
.\Build App.ps1 -PythonPath "C:\path\to\python.exe"
```

The script creates a repository-local packaging environment, installs PyInstaller into it if necessary, and writes the application to `dist\Fuzzyficator.exe`.

### Running the configurator from source

Developers can double-click `Launch Configurator.bat`. It launches the bundled application when present; otherwise it uses a remembered Python location, checks the normal Windows commands, or opens a file picker once. You can also run:

```text
python Fuzzyficator_configurator.py
```

The configurator shows print-like previews generated from Fuzzyficator's actual texture engine sampled along a 0.4 mm Hilbert top-surface toolpath. Choose a texture and labelled physical feature size, select a Subtle, Standard, or Bold intensity, optionally fine-tune the values, then copy the complete Bambu Studio / OrcaSlicer post-processing command. Random has one preview because it has no coherent spatial feature size.

Intensity changes only texture height, texture speed, and G-code sampling resolution. It does not replace or modify the slicer's printer, filament, layer-height, wall, support, or infill profiles. Manual changes to any intensity value are clearly identified as Custom.

A larger corner preview shows the selected textured top meeting the smooth vertical wall produced by the current workflow. Fuzzyficator does not texture vertical walls; users who independently enable slicer-native fuzzy skin for walls should treat that as a separate finish with separate settings.

When running from source, the copied command contains the exact Python executable that launched the configurator and the absolute path to the adjacent `Fuzzyficator.py`, with Windows paths quoted as required. Moving the repository later only requires launching the configurator again and copying a fresh command.

The friendlier command-line aliases used by the configurator are also available directly:

```text
python Fuzzyficator.py --texture ridged --size 1.4 --height 0.30 --speed 25 input.gcode
```

`--speed` uses mm/s. The legacy `-fuzzySpeed` option remains available and uses mm/min.

Unlike the original processor, `-connectWalls 1` is suitable for Hilbert Curve: it no longer zeroes both ends of every short source move.

## Original-compatible preset

The familiar options remain supported:

```text
"C:\pathToPython\python.exe" "C:\pathToScript\Fuzzyficator.py" -run 1 -resolution 0.5 -zMin 0 -zMax 0.3 -connectWalls 1 -compensateExtrusion 1 -topSurface 1 -lowerSurface 0 -fuzzySpeed 1500
```

If `-resolution`, `-zMax`, or `-run` are omitted, the script now genuinely inherits the corresponding slicer settings. Explicit command-line values take precedence.

## Safety and file handling

The slicer supplies the input G-code path automatically. By default the script safely replaces that path after processing succeeds.

- `--backup` creates `<input>.bak` before replacement.
- `--output <path>` writes a separate file and leaves the input unchanged.
- `--force` permits deliberately processing a file that already contains the Fuzzyficator marker.
- The input must use relative extrusion (`M83`).

## Development and tests

No third-party Python packages are required.

```text
python -m compileall -q Fuzzyficator.py tests
python -m unittest discover -s tests -v
```

The regression suite covers setting inheritance, extrusion conservation, correct segmentation, height-delta compensation, connected short paths, feed-rate restoration, deterministic Ridged noise, safe `M82` rejection, separate output files, and double-processing protection.

### Preview raw texture fields without printing

The diagnostic preview utility writes five dependency-free grayscale PNG height maps. White represents maximum displacement and black represents minimum displacement. These are mathematical fields rather than simulations of the printed Hilbert surface; the desktop configurator provides the print-like previews.

```text
python tools/preview_textures.py --output-dir texture-previews --scale 1.4 --seed 42
```

It generates separate Random, Perlin, Billow, Ridged, and Voronoi images so feature scale and seed choices can be checked before slicing or printing.

## Upstream and licence

Originally created by Roman Tenger / Tenger Technologies. Upstream project: <https://github.com/TengerTechnologies/Fuzzyficator>

Distributed under the GNU General Public License v3.0; see `LICENSE`.

Development changes are recorded in `CHANGELOG.md`.
