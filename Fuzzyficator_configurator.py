"""Dependency-free desktop configurator for Fuzzyficator."""

from __future__ import annotations

import base64
import os
import sys
from dataclasses import replace
from pathlib import Path

from tools.configurator import (
    FEATURE_SIZES,
    INTENSITIES,
    TEXTURE_TYPES,
    ConfiguratorSettings,
    match_intensity,
)
from tools.preview_surfaces import render_corner_preview, render_hilbert_surface
from tools.preview_textures import rgb_png_bytes


REPOSITORY_ROOT = Path(__file__).resolve().parent
PROCESSOR_PATH = REPOSITORY_ROOT / "Fuzzyficator.py"
PREVIEW_PIXELS = 88
PREVIEW_MILLIMETRES = 25.0


def build_slicer_command(settings: ConfiguratorSettings) -> str:
    if getattr(sys, "frozen", False):
        return settings.application_command(sys.executable)
    return settings.slicer_command(sys.executable, PROCESSOR_PATH)


def main() -> int:
    try:
        import tkinter as tk
        from tkinter import messagebox, ttk
    except ImportError:
        print("Tkinter is required for the configurator. Reinstall Python with the Tcl/Tk option enabled.")
        return 2

    class ConfiguratorApp:
        def __init__(self, root: tk.Tk) -> None:
            self.root = root
            self.settings = ConfiguratorSettings()
            self.preview_images: dict[tuple[str, float], tk.PhotoImage] = {}
            self.preview_buttons: dict[tuple[str, float | None], tk.Button] = {}
            self.corner_images: dict[tuple[object, ...], tk.PhotoImage] = {}
            self.intensity_var = tk.StringVar(value="Standard")
            self.intensity_note_var = tk.StringVar()
            self.loading_controls = False
            self.height_var = tk.DoubleVar(value=self.settings.height)
            self.speed_var = tk.DoubleVar(value=self.settings.speed)
            self.top_var = tk.BooleanVar(value=self.settings.top_surface)
            self.lower_var = tk.BooleanVar(value=self.settings.lower_surface)
            self.resolution_var = tk.DoubleVar(value=self.settings.resolution)
            self.octaves_var = tk.IntVar(value=self.settings.octaves)
            self.persistence_var = tk.DoubleVar(value=self.settings.persistence)
            self.seed_var = tk.IntVar(value=self.settings.seed)
            self.connect_var = tk.BooleanVar(value=self.settings.connect_walls)
            self.compensate_var = tk.BooleanVar(value=self.settings.compensate_extrusion)
            self.command_var = tk.StringVar()
            self.summary_var = tk.StringVar()
            self.advanced_visible = False

            root.title("Fuzzyficator Configurator")
            root.minsize(990, 750)
            root.option_add("*Font", ("Segoe UI", 9))
            self._build()
            self._refresh()

        def _build(self) -> None:
            outer = ttk.Frame(self.root, padding=14)
            outer.pack(fill="both", expand=True)

            ttk.Label(outer, text="Fuzzyficator", font=("Segoe UI Semibold", 19)).pack(anchor="w")
            ttk.Label(
                outer,
                text="Choose the look, set its physical height, then copy the slicer command.",
            ).pack(anchor="w", pady=(0, 12))

            content = ttk.Frame(outer)
            content.pack(fill="both", expand=True)
            preview_panel = ttk.LabelFrame(content, text="1  Texture and feature size", padding=10)
            preview_panel.pack(side="left", fill="both", expand=True, padx=(0, 12))
            controls = ttk.Frame(content, width=300)
            controls.pack(side="right", fill="y")

            ttk.Label(preview_panel, text="Texture", font=("Segoe UI Semibold", 9)).grid(row=0, column=0, sticky="w")
            for column, feature_size in enumerate(FEATURE_SIZES, start=1):
                ttk.Label(
                    preview_panel,
                    text=f"{feature_size.name}\n{feature_size.millimetres:g} mm",
                    anchor="center",
                ).grid(row=0, column=column, padx=3, pady=(0, 5))

            for row, texture in enumerate(TEXTURE_TYPES, start=1):
                ttk.Label(preview_panel, text=texture.title(), font=("Segoe UI Semibold", 9)).grid(
                    row=row, column=0, sticky="nw", padx=(0, 7), pady=3
                )
                if texture == "random":
                    button = self._preview_button(preview_panel, texture, FEATURE_SIZES[1].millimetres)
                    button.grid(row=row, column=1, padx=3, pady=3)
                    self.preview_buttons[(texture, None)] = button
                    ttk.Label(preview_panel, text="Size is not used for Random", foreground="#666666").grid(
                        row=row, column=2, columnspan=3, sticky="w", padx=8
                    )
                    continue
                for column, feature_size in enumerate(FEATURE_SIZES, start=1):
                    button = self._preview_button(preview_panel, texture, feature_size.millimetres)
                    button.grid(row=row, column=column, padx=3, pady=3)
                    self.preview_buttons[(texture, feature_size.millimetres)] = button

            ttk.Label(
                preview_panel,
                text="Simulated 0.4 mm Hilbert top-surface toolpath. Final sheen varies by filament and lighting.",
                foreground="#666666",
                wraplength=500,
            ).grid(row=6, column=0, columnspan=5, sticky="w", pady=(8, 0))

            object_frame = ttk.LabelFrame(controls, text="Selected object preview", padding=6)
            object_frame.pack(fill="x", pady=(0, 10))
            self.corner_label = ttk.Label(object_frame)
            self.corner_label.pack(anchor="center")
            ttk.Label(
                object_frame,
                text="Top: selected Hilbert texture    Wall: smooth",
                foreground="#555555",
            ).pack(anchor="w", padx=4, pady=(4, 0))
            ttk.Label(
                object_frame,
                text="Fuzzyficator does not currently texture vertical walls.",
                foreground="#777777",
            ).pack(anchor="w", padx=4)

            intensity_frame = ttk.LabelFrame(controls, text="2  Texture intensity", padding=10)
            intensity_frame.pack(fill="x", pady=(0, 10))
            intensity_buttons = ttk.Frame(intensity_frame)
            intensity_buttons.pack(fill="x")
            for column, intensity_name in enumerate(INTENSITIES):
                ttk.Radiobutton(
                    intensity_buttons,
                    text=intensity_name,
                    value=intensity_name,
                    variable=self.intensity_var,
                    command=self._apply_intensity,
                ).grid(row=0, column=column, sticky="w", padx=(0, 12))
            ttk.Label(
                intensity_frame,
                textvariable=self.intensity_note_var,
                foreground="#666666",
                wraplength=290,
            ).pack(anchor="w", pady=(6, 0))

            basic = ttk.LabelFrame(controls, text="3  Fine tuning", padding=10)
            basic.pack(fill="x", pady=(0, 10))
            self._spinbox_row(basic, "Texture height", self.height_var, 0.05, 1.0, 0.05, "mm", 0)
            self._spinbox_row(basic, "Texture speed", self.speed_var, 1, 100, 1, "mm/s", 1)
            ttk.Checkbutton(basic, text="Top surfaces", variable=self.top_var, command=self._refresh).grid(
                row=2, column=0, columnspan=3, sticky="w", pady=(7, 0)
            )
            ttk.Checkbutton(basic, text="Supported lower surfaces", variable=self.lower_var, command=self._refresh).grid(
                row=3, column=0, columnspan=3, sticky="w"
            )

            self.advanced_toggle = ttk.Button(controls, text="Show advanced settings", command=self._toggle_advanced)
            self.advanced_toggle.pack(fill="x", pady=(0, 6))
            self.advanced = ttk.LabelFrame(controls, text="Advanced", padding=10)
            self._spinbox_row(self.advanced, "G-code resolution", self.resolution_var, 0.05, 2.0, 0.05, "mm", 0)
            self._spinbox_row(self.advanced, "Octaves", self.octaves_var, 1, 12, 1, "", 1)
            self._spinbox_row(self.advanced, "Roughness", self.persistence_var, 0.1, 1.0, 0.05, "", 2)
            self._spinbox_row(self.advanced, "Seed", self.seed_var, -999999, 999999, 1, "", 3)
            ttk.Checkbutton(self.advanced, text="Reconnect paths at nominal Z", variable=self.connect_var, command=self._refresh).grid(
                row=4, column=0, columnspan=3, sticky="w", pady=(7, 0)
            )
            ttk.Checkbutton(self.advanced, text="Compensate extrusion", variable=self.compensate_var, command=self._refresh).grid(
                row=5, column=0, columnspan=3, sticky="w"
            )

            setup = ttk.LabelFrame(controls, text="4  Slicer checks", padding=10)
            setup.pack(fill="x", pady=(4, 10))
            ttk.Label(setup, text="Top pattern: Hilbert Curve").pack(anchor="w")
            ttk.Label(setup, text="Native fuzzy skin: Disabled").pack(anchor="w")
            ttk.Label(setup, text="Extrusion mode: Relative (M83)").pack(anchor="w")

            ttk.Label(controls, textvariable=self.summary_var, wraplength=300).pack(fill="x", pady=(0, 7))
            ttk.Button(controls, text="Copy Bambu / Orca command", command=self._copy_command).pack(fill="x")
            ttk.Entry(controls, textvariable=self.command_var, state="readonly").pack(fill="x", pady=(6, 0))

            for variable in (self.height_var, self.speed_var, self.resolution_var):
                variable.trace_add("write", self._on_intensity_control_change)
            for variable in (self.octaves_var, self.persistence_var, self.seed_var):
                variable.trace_add("write", self._on_control_change)
            self._update_intensity_note()

        def _preview_button(self, parent: ttk.Frame, texture: str, size: float) -> tk.Button:
            key = (texture, size)
            rows = render_hilbert_surface(
                texture,
                output_size=PREVIEW_PIXELS,
                millimetres=PREVIEW_MILLIMETRES,
                height=0.30,
                seed=42,
                scale=size,
                octaves=4,
                persistence=0.5,
            )
            encoded = base64.b64encode(rgb_png_bytes(rows))
            image = tk.PhotoImage(data=encoded)
            self.preview_images[key] = image
            selection_size = None if texture == "random" else size
            return tk.Button(
                parent,
                image=image,
                command=lambda: self._select_preview(texture, selection_size),
                relief="raised",
                borderwidth=2,
                padx=1,
                pady=1,
                cursor="hand2",
            )

        def _spinbox_row(
            self,
            parent: ttk.Frame,
            label: str,
            variable: tk.Variable,
            minimum: float,
            maximum: float,
            increment: float,
            unit: str,
            row: int,
        ) -> None:
            ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=2)
            spinbox = ttk.Spinbox(
                parent,
                textvariable=variable,
                from_=minimum,
                to=maximum,
                increment=increment,
                width=8,
                command=self._refresh,
            )
            spinbox.grid(row=row, column=1, sticky="e", padx=(8, 4), pady=2)
            ttk.Label(parent, text=unit).grid(row=row, column=2, sticky="w")

        def _select_preview(self, texture: str, size: float | None) -> None:
            changes: dict[str, object] = {"texture": texture}
            if size is not None:
                changes["size"] = size
            self.settings = replace(self.settings, **changes)
            self._refresh()

        def _apply_intensity(self) -> None:
            intensity = INTENSITIES[self.intensity_var.get()]
            self.settings = replace(
                self.settings,
                height=intensity.height,
                speed=intensity.speed,
                resolution=intensity.resolution,
            )
            self.loading_controls = True
            try:
                self.height_var.set(intensity.height)
                self.speed_var.set(intensity.speed)
                self.resolution_var.set(intensity.resolution)
            finally:
                self.loading_controls = False
            self._update_intensity_note()
            self._refresh()

        def _load_variables(self) -> None:
            self.loading_controls = True
            try:
                self.height_var.set(self.settings.height)
                self.speed_var.set(self.settings.speed)
                self.top_var.set(self.settings.top_surface)
                self.lower_var.set(self.settings.lower_surface)
                self.resolution_var.set(self.settings.resolution)
                self.octaves_var.set(self.settings.octaves)
                self.persistence_var.set(self.settings.persistence)
                self.seed_var.set(self.settings.seed)
                self.connect_var.set(self.settings.connect_walls)
                self.compensate_var.set(self.settings.compensate_extrusion)
            finally:
                self.loading_controls = False

        def _on_control_change(self, *_args: object) -> None:
            if self.loading_controls:
                return
            self.root.after_idle(self._refresh)

        def _on_intensity_control_change(self, *_args: object) -> None:
            if self.loading_controls:
                return
            try:
                values = (
                    float(self.height_var.get()),
                    float(self.speed_var.get()),
                    float(self.resolution_var.get()),
                )
            except (ValueError, tk.TclError):
                self.intensity_var.set("Custom")
            else:
                self.intensity_var.set(match_intensity(*values))
            self._update_intensity_note()
            self.root.after_idle(self._refresh)

        def _update_intensity_note(self) -> None:
            intensity_name = self.intensity_var.get()
            if intensity_name in INTENSITIES:
                intensity = INTENSITIES[intensity_name]
                self.intensity_note_var.set(
                    f"{intensity.height:g} mm high · {intensity.speed:g} mm/s · "
                    f"{intensity.resolution:g} mm sampling"
                )
            else:
                self.intensity_note_var.set("Custom values from the fine-tuning controls")

        def _read_settings(self) -> ConfiguratorSettings:
            return replace(
                self.settings,
                height=float(self.height_var.get()),
                speed=float(self.speed_var.get()),
                top_surface=bool(self.top_var.get()),
                lower_surface=bool(self.lower_var.get()),
                resolution=float(self.resolution_var.get()),
                octaves=int(self.octaves_var.get()),
                persistence=float(self.persistence_var.get()),
                seed=int(self.seed_var.get()),
                connect_walls=bool(self.connect_var.get()),
                compensate_extrusion=bool(self.compensate_var.get()),
            ).validated()

        def _refresh(self, *_args: object) -> None:
            try:
                self.settings = self._read_settings()
                command = build_slicer_command(self.settings)
                self.command_var.set(command)
                self.summary_var.set(
                    f"Selected: {self.settings.texture.title()} · {self.settings.size_name} · "
                    f"{self.settings.height:g} mm high · {self.settings.speed:g} mm/s"
                )
                self._update_corner_preview()
            except (ValueError, tk.TclError):
                self.summary_var.set("Enter valid values to generate the command.")
                self.command_var.set("")
            selected_key = (
                self.settings.texture,
                None if self.settings.texture == "random" else self.settings.size,
            )
            for key, button in self.preview_buttons.items():
                button.configure(relief="sunken" if key == selected_key else "raised")

        def _update_corner_preview(self) -> None:
            preview_scale = 1.4 if self.settings.texture == "random" else self.settings.size
            key = (
                self.settings.texture,
                round(preview_scale, 4),
                round(self.settings.height, 4),
                self.settings.seed,
                self.settings.octaves,
                round(self.settings.persistence, 4),
            )
            image = self.corner_images.get(key)
            if image is None:
                rows = render_corner_preview(
                    self.settings.texture,
                    texture_height=self.settings.height,
                    seed=self.settings.seed,
                    scale=preview_scale,
                    octaves=self.settings.octaves,
                    persistence=self.settings.persistence,
                )
                image = tk.PhotoImage(data=base64.b64encode(rgb_png_bytes(rows)))
                self.corner_images[key] = image
            self.corner_label.configure(image=image)

        def _copy_command(self) -> None:
            self._refresh()
            command = self.command_var.get()
            if not command:
                messagebox.showerror("Invalid settings", "Fix the highlighted settings before copying.")
                return
            self.root.clipboard_clear()
            self.root.clipboard_append(command)
            self.root.update_idletasks()
            self.summary_var.set("Command copied. Paste it into the slicer's post-processing scripts field.")

        def _toggle_advanced(self) -> None:
            self.advanced_visible = not self.advanced_visible
            if self.advanced_visible:
                self.advanced.pack(fill="x", pady=(0, 10), after=self.advanced_toggle)
                self.advanced_toggle.configure(text="Hide advanced settings")
            else:
                self.advanced.pack_forget()
                self.advanced_toggle.configure(text="Show advanced settings")

    root = tk.Tk()
    ConfiguratorApp(root)
    if os.environ.get("FUZZYFICATOR_GUI_SMOKE_TEST") == "1":
        root.after(250, root.destroy)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
