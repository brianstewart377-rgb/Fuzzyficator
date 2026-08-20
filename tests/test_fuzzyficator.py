import math
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import Fuzzyficator as fuzzy
import FuzzyficatorApp as fuzzy_app
import Fuzzyficator_configurator as configurator_app
from tools import preview_textures
from tools import preview_surfaces
from tools.configurator import ConfiguratorSettings, FEATURE_SIZES, INTENSITIES, match_intensity, preview_choices


def make_args(**overrides):
    values = {
        "input_gcode": "input.gcode",
        "resolution": None,
        "zMin": 0.0,
        "zMax": None,
        "connectWalls": 1,
        "fuzzySpeed": None,
        "run": None,
        "compensateExtrusion": 1,
        "lowerSurface": 0,
        "topSurface": 1,
        "bridgeCompensationMultiplier": 3.0,
        "minSupportDistance": 0.1,
        "noiseType": "random",
        "noiseScale": 1.4,
        "noiseOctaves": 4,
        "noisePersistence": 0.5,
        "seed": 0,
        "output": None,
        "backup": False,
        "force": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class ConfigurationTests(unittest.TestCase):
    def test_legacy_command_flags_and_new_ridged_flags_parse_together(self):
        args = fuzzy.parse_arguments(
            [
                "-run",
                "1",
                "-resolution",
                "0.35",
                "-zMax",
                "0.3",
                "-ConnectWalls",
                "1",
                "-noiseType",
                "ridged",
                "-noiseScale",
                "1.4",
                "input.gcode",
            ]
        )

        self.assertEqual(args.input_gcode, "input.gcode")
        self.assertEqual(args.noiseType, "ridged")
        self.assertEqual(args.noiseScale, 1.4)
        self.assertEqual(args.resolution, 0.35)

    def test_friendly_command_flags_parse_and_convert_speed(self):
        args = fuzzy.parse_arguments(
            [
                "--run",
                "1",
                "--texture",
                "ridged",
                "--size",
                "1.4",
                "--height",
                "0.3",
                "--speed",
                "25",
                "input.gcode",
            ]
        )
        config = fuzzy.FuzzySkinConfig(args)

        self.assertEqual(args.noiseType, "ridged")
        self.assertEqual(args.noiseScale, 1.4)
        self.assertEqual(args.zMax, 0.3)
        self.assertEqual(config.fuzzy_speed, 1500.0)

    def test_configurator_command_is_accepted_by_processor_parser(self):
        settings = ConfiguratorSettings()
        args = fuzzy.parse_arguments([*settings.processor_arguments(), "input.gcode"])
        config = fuzzy.FuzzySkinConfig(args)

        self.assertEqual(config.noise_type, settings.texture)
        self.assertEqual(config.noise_scale, settings.size)
        self.assertEqual(config.z_max, settings.height)
        self.assertEqual(config.fuzzy_speed, settings.speed * 60)

    def test_bundled_application_command_needs_no_python_or_script_path(self):
        settings = ConfiguratorSettings()
        command = settings.application_command(r"C:\Program Files\Fuzzyficator\Fuzzyficator.exe")

        self.assertTrue(command.startswith(r'"C:\Program Files\Fuzzyficator\Fuzzyficator.exe"'))
        self.assertIn("--texture ridged", command)
        self.assertNotIn(".py", command)

    def test_single_app_routes_no_arguments_to_configurator(self):
        with mock.patch.object(fuzzy_app.Fuzzyficator_configurator, "main", return_value=7) as gui_main:
            result = fuzzy_app.main([])

        self.assertEqual(result, 7)
        gui_main.assert_called_once_with()

    def test_single_app_routes_arguments_to_processor(self):
        with mock.patch.object(fuzzy_app.Fuzzyficator, "main", return_value=8) as processor_main:
            result = fuzzy_app.main(["--version"])

        self.assertEqual(result, 8)
        processor_main.assert_called_once_with(["--version"])

    def test_source_configurator_command_uses_running_python_and_processor_path(self):
        settings = ConfiguratorSettings()
        command = configurator_app.build_slicer_command(settings)

        self.assertIn("Fuzzyficator.py", command)
        self.assertIn("--texture ridged", command)

    def test_frozen_configurator_command_uses_only_application_path(self):
        settings = ConfiguratorSettings()
        with mock.patch.object(configurator_app.sys, "frozen", True, create=True), mock.patch.object(
            configurator_app.sys, "executable", r"C:\Apps\Fuzzyficator.exe"
        ):
            command = configurator_app.build_slicer_command(settings)

        self.assertTrue(command.startswith(r"C:\Apps\Fuzzyficator.exe"))
        self.assertNotIn("python", command.lower())
        self.assertNotIn(".py", command)

    def test_preview_grid_has_one_random_and_four_sizes_for_spatial_textures(self):
        choices = list(preview_choices())

        self.assertEqual(choices[0], ("random", None))
        self.assertEqual(len(choices), 1 + 4 * len(FEATURE_SIZES))

    def test_texture_intensities_change_only_postprocessor_strength_values(self):
        standard = INTENSITIES["Standard"]
        settings = ConfiguratorSettings()

        self.assertEqual((standard.height, standard.speed, standard.resolution), (0.30, 25.0, 0.35))
        self.assertEqual(
            match_intensity(settings.height, settings.speed, settings.resolution),
            "Standard",
        )
        self.assertEqual(match_intensity(0.22, settings.speed, settings.resolution), "Custom")

    def test_slicer_settings_are_inherited_when_cli_values_are_omitted(self):
        config = fuzzy.FuzzySkinConfig(make_args())
        config.apply_gcode_settings(
            fuzzy_enabled=True,
            point_dist=0.72,
            thickness=0.28,
            support_contact_dist=0.2,
        )

        self.assertEqual(config.resolution, 0.72)
        self.assertEqual(config.z_max, 0.28)
        self.assertEqual(config.run, 1)

    def test_current_bambu_point_distance_key_is_recognised(self):
        processor = fuzzy.GCodeProcessor(fuzzy.FuzzySkinConfig(make_args()))
        processor.lookup = fuzzy.LOOKUP_TABLES["bambustudio"]
        settings = processor.process_fuzzy_skin_settings(
            [
                "; fuzzy_skin = external\n",
                "; fuzzy_skin_point_distance = 1.4\n",
                "; fuzzy_skin_thickness = 0.3\n",
            ]
        )

        self.assertEqual(settings[:3], (True, 1.4, 0.3))


class InterpolationTests(unittest.TestCase):
    def make_processor(self, **overrides):
        values = {
            "resolution": 0.4,
            "zMin": 0.0,
            "zMax": 0.0,
            "run": 1,
            "compensateExtrusion": 0,
            "connectWalls": 0,
        }
        values.update(overrides)
        args = make_args(**values)
        config = fuzzy.FuzzySkinConfig(args)
        config.apply_gcode_settings(False, None, None, None)
        processor = fuzzy.GCodeProcessor(config)
        processor.current_layer_height = 0.2
        return processor

    def test_interpolation_uses_ceiling_and_does_not_repeat_start_point(self):
        processor = self.make_processor()
        points = processor.interpolate_with_constant_resolution(
            (0.0, 0.0, 0.2),
            (1.0, 0.0, 0.2),
            0.4,
            0.3,
        )

        self.assertEqual(len(points), 3)
        self.assertGreater(points[0][0], 0.0)
        self.assertEqual(points[-1][0], 1.0)

    def test_extrusion_is_conserved_when_compensation_is_disabled(self):
        processor = self.make_processor()
        points = processor.interpolate_with_constant_resolution(
            (0.0, 0.0, 0.2),
            (1.0, 0.0, 0.2),
            0.4,
            0.3,
        )

        self.assertTrue(math.isclose(sum(point[3] for point in points), 0.3))

    def test_compensation_uses_change_in_height_not_absolute_displacement(self):
        processor = self.make_processor(
            zMin=0.2,
            zMax=0.2,
            compensateExtrusion=1,
        )
        first = processor.interpolate_with_constant_resolution(
            (0.0, 0.0, 0.2),
            (1.0, 0.0, 0.2),
            1.0,
            0.1,
        )
        processor.physical_point = first[-1][:3]
        second = processor.interpolate_with_constant_resolution(
            (1.0, 0.0, 0.2),
            (2.0, 0.0, 0.2),
            1.0,
            0.1,
        )

        self.assertTrue(math.isclose(first[0][3], 0.1 * math.sqrt(1.04)))
        self.assertTrue(math.isclose(second[0][3], 0.1))


class EndToEndTests(unittest.TestCase):
    BAMBU_HILBERT = """; generated by BambuStudio 2.0\n; gcode_flavor = marlin\nM83\n; fuzzy_skin = none\n; fuzzy_skin_point_dist = 0.8\n; fuzzy_skin_thickness = 0.3\n; CHANGE_LAYER\nG1 Z0.200\nG1 F3000\n; FEATURE: Top surface\nG1 X0.000 Y0.000 F9000\nG1 X0.400 Y0.000 E0.040\nG1 X0.400 Y0.400 E0.040\n; FEATURE: Outer wall\nG1 X1.000 Y1.000 F9000\n"""

    def test_short_connected_moves_keep_texture_and_restore_speed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "hilbert.gcode")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(self.BAMBU_HILBERT)

            config = fuzzy.FuzzySkinConfig(
                make_args(
                    input_gcode=path,
                    resolution=0.5,
                    zMin=0.2,
                    zMax=0.2,
                    run=1,
                    connectWalls=1,
                    compensateExtrusion=0,
                    fuzzySpeed=1500,
                )
            )
            fuzzy.GCodeProcessor(config).process_file()

            with open(path, "r", encoding="utf-8") as handle:
                output = handle.read()

        self.assertIn("Z0.4000", output)
        self.assertIn("G1 F1500", output)
        self.assertIn("G1 F3000", output)
        self.assertTrue(math.isclose(sum(fuzzy.extract_extrusion_values(output)), 0.08))

    def test_absolute_extrusion_fails_without_modifying_input(self):
        original = self.BAMBU_HILBERT.replace("M83", "M82")
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "absolute.gcode")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(original)

            config = fuzzy.FuzzySkinConfig(make_args(input_gcode=path, run=1))
            with self.assertRaises(fuzzy.UnsupportedGCodeError):
                fuzzy.GCodeProcessor(config).process_file()

            with open(path, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), original)

    def test_missing_m83_fails_before_first_positive_extrusion(self):
        original = self.BAMBU_HILBERT.replace("M83\n", "")
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "unknown-extrusion-mode.gcode")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(original)

            config = fuzzy.FuzzySkinConfig(make_args(input_gcode=path, run=1))
            with self.assertRaises(fuzzy.UnsupportedGCodeError):
                fuzzy.GCodeProcessor(config).process_file()

            with open(path, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), original)

    def test_relative_xyz_mode_is_rejected_for_a_textured_feature(self):
        original = self.BAMBU_HILBERT.replace("; FEATURE: Top surface", "G91\n; FEATURE: Top surface")
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "relative-positioning.gcode")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(original)

            config = fuzzy.FuzzySkinConfig(make_args(input_gcode=path, run=1))
            with self.assertRaises(fuzzy.UnsupportedGCodeError):
                fuzzy.GCodeProcessor(config).process_file()

            with open(path, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), original)

    def test_formatted_segments_preserve_source_extrusion(self):
        original = self.BAMBU_HILBERT.replace("X0.400 Y0.000 E0.040", "X1.000 Y0.000 E0.100")
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "rounding.gcode")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(original)

            config = fuzzy.FuzzySkinConfig(
                make_args(
                    input_gcode=path,
                    resolution=0.3,
                    zMax=0.0,
                    run=1,
                    compensateExtrusion=0,
                )
            )
            fuzzy.GCodeProcessor(config).process_file()
            with open(path, "r", encoding="utf-8") as handle:
                output_total = sum(fuzzy.extract_extrusion_values(handle.read()))

        self.assertTrue(math.isclose(output_total, 0.14, abs_tol=1e-9))

    def test_processed_marker_prevents_accidental_second_pass(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "twice.gcode")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(self.BAMBU_HILBERT)
            args = make_args(input_gcode=path, resolution=0.5, zMax=0.3, run=1)
            fuzzy.GCodeProcessor(fuzzy.FuzzySkinConfig(args)).process_file()
            with open(path, "r", encoding="utf-8") as handle:
                first_pass = handle.read()

            stats = fuzzy.GCodeProcessor(fuzzy.FuzzySkinConfig(args)).process_file()
            with open(path, "r", encoding="utf-8") as handle:
                second_pass = handle.read()

        self.assertTrue(stats.skipped)
        self.assertEqual(first_pass, second_pass)

    def test_output_option_leaves_input_unchanged(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = os.path.join(temp_dir, "source.gcode")
            output_path = os.path.join(temp_dir, "textured.gcode")
            with open(input_path, "w", encoding="utf-8") as handle:
                handle.write(self.BAMBU_HILBERT)

            args = make_args(
                input_gcode=input_path,
                output=output_path,
                resolution=0.5,
                zMax=0.3,
                run=1,
            )
            fuzzy.GCodeProcessor(fuzzy.FuzzySkinConfig(args)).process_file()

            with open(input_path, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), self.BAMBU_HILBERT)
            with open(output_path, "r", encoding="utf-8") as handle:
                self.assertIn(fuzzy.PROCESSED_MARKER, handle.read())


class NoiseTests(unittest.TestCase):
    def test_ridged_noise_is_deterministic_and_bounded(self):
        texture_a = fuzzy.TextureNoise("ridged", seed=42, scale=1.4, octaves=4, persistence=0.5)
        texture_b = fuzzy.TextureNoise("ridged", seed=42, scale=1.4, octaves=4, persistence=0.5)

        values_a = [texture_a.sample(x * 0.2, 0.7) for x in range(20)]
        values_b = [texture_b.sample(x * 0.2, 0.7) for x in range(20)]

        self.assertEqual(values_a, values_b)
        self.assertTrue(all(0.0 <= value <= 1.0 for value in values_a))
        self.assertGreater(max(values_a) - min(values_a), 0.05)

    def test_preview_writer_creates_a_valid_png(self):
        rows = preview_textures.render_texture(
            "ridged",
            size=16,
            millimetres=10.0,
            seed=42,
            scale=1.4,
            octaves=4,
            persistence=0.5,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "ridged.png")
            preview_textures.write_grayscale_png(path, rows)
            with open(path, "rb") as handle:
                content = handle.read()

        self.assertTrue(content.startswith(preview_textures.PNG_SIGNATURE))
        self.assertIn(b"IHDR", content)
        self.assertTrue(content.endswith(b"IEND\xaeB`\x82"))

    def test_preview_encoder_matches_file_writer(self):
        rows = preview_textures.render_texture(
            "voronoi",
            size=16,
            millimetres=10.0,
            seed=42,
            scale=2.8,
            octaves=4,
            persistence=0.5,
        )
        encoded = preview_textures.grayscale_png_bytes(rows)

        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "voronoi.png")
            preview_textures.write_grayscale_png(path, rows)
            with open(path, "rb") as handle:
                written = handle.read()

        self.assertEqual(encoded, written)

    def test_hilbert_path_visits_every_grid_point_with_orthogonal_steps(self):
        path = preview_surfaces.hilbert_path(4)

        self.assertEqual(len(path), 16 * 16)
        self.assertEqual(len(set(path)), len(path))
        self.assertTrue(
            all(
                abs(end[0] - start[0]) + abs(end[1] - start[1]) == 1
                for start, end in zip(path, path[1:])
            )
        )

    def test_hilbert_surface_preview_is_deterministic_rgb(self):
        first = preview_surfaces.render_hilbert_surface(
            "voronoi",
            output_size=32,
            height=0.3,
            seed=42,
            scale=1.4,
            octaves=4,
            persistence=0.5,
            hilbert_order=4,
        )
        second = preview_surfaces.render_hilbert_surface(
            "voronoi",
            output_size=32,
            height=0.3,
            seed=42,
            scale=1.4,
            octaves=4,
            persistence=0.5,
            hilbert_order=4,
        )

        self.assertEqual(first, second)
        self.assertEqual(len(first), 32)
        self.assertTrue(all(len(row) == 32 * 3 for row in first))
        self.assertGreater(len(set(first[16])), 12)

    def test_corner_preview_contains_textured_top_and_layered_smooth_wall(self):
        rows = preview_surfaces.render_corner_preview(
            "ridged",
            width=200,
            height_pixels=130,
            texture_height=0.3,
            seed=42,
            scale=1.4,
            octaves=4,
            persistence=0.5,
        )

        self.assertEqual(len(rows), 130)
        self.assertTrue(all(len(row) == 200 * 3 for row in rows))
        self.assertGreater(len(set(rows[50])), 20)
        self.assertGreater(len(set(rows[105])), 8)

    def test_rgb_preview_encoder_creates_truecolour_png(self):
        rows = [bytes((255, 0, 0, 0, 255, 0)), bytes((0, 0, 255, 255, 255, 255))]
        content = preview_textures.rgb_png_bytes(rows)

        self.assertTrue(content.startswith(preview_textures.PNG_SIGNATURE))
        self.assertIn(b"IHDR", content)
        self.assertTrue(content.endswith(b"IEND\xaeB`\x82"))


if __name__ == "__main__":
    unittest.main()
