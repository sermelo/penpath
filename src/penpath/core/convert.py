"""Image-to-plot-geometry conversion in core, independent of the CLI.

``draw_project`` runs the same pipeline as ``penpath convert`` and returns a
``Drawing`` that holds the pens, the optimised strokes and everything needed
to place them on the paper. ``Drawing.to_svg`` writes penpath's SVG, through
vpype when available or directly otherwise, so both export paths produce the
same bytes as before this module was extracted.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from shapely import LineString

from penpath.core.drawing.key_layer import key_layer_strokes
from penpath.core.drawing.pfm_engraving import EngravingSettings
from penpath.core.drawing.pfm_hatch import (
    PALETTE_ANGLE_STEP_DEG,
    HatchSettings,
    with_angle_offset,
)
from penpath.core.drawing.pfm_patch_hatch import PatchHatchSettings, with_layer_angle_offset
from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings
from penpath.core.drawing.pfm_squiggle import SquiggleSettings
from penpath.core.drawing.pfm_tsp import TSPSettings
from penpath.core.drawing.registry import get_pfm
from penpath.core.drawing.tone_targets import pfm_tone_targets
from penpath.core.geometry.pipeline import optimize
from penpath.core.image.background import mask_background
from penpath.core.image.filters import auto_equalize
from penpath.core.image.load import load_image
from penpath.core.image.palette_order import is_near_black_pen, order_pens_for_drawing
from penpath.core.image.resolution import (
    WorkingResolution,
    apply_working_resolution,
    plan_working_resolution,
)
from penpath.core.image.saturation import NO_BOOST_FACTOR, adapt_saturation, boost_saturation
from penpath.core.image.separate import separate_palette
from penpath.core.image.tone_levels import apply_tone_levels
from penpath.core.models import FitMode, Paper, Pen, Project
from penpath.core.output.svg import (
    ImagePlacement,
    export_pen_layers,
    fit_image_placement,
    write_penpath_svg,
)
from penpath.core.output.vpype import optimize_with_vpype
from penpath.core.styles import draw_styled_lines


class Reporter(Protocol):
    """Progress reporting methods used by the conversion pipeline.

    The CLI's ``StageReporter`` satisfies this protocol structurally, so core
    never imports from ``penpath.cli``. A caller that wants no progress at all
    can pass ``None`` to :func:`draw_project` or :meth:`Drawing.to_svg`.
    """

    def start(self, name: str) -> None:
        """Begin a named stage."""
        ...

    def finish(self) -> None:
        """Report the current stage as finished."""
        ...

    def message(self, text: str, *, markup: bool = True, style: str | None = None) -> None:
        """Write one non-error message."""
        ...

    def set_total_stages(self, total: int) -> None:
        """Update the number of stages once optional stages are known."""
        ...


class _NullReporter:
    """Reporter that discards every message."""

    def start(self, name: str) -> None:
        """Begin a named stage without reporting it."""

    def finish(self) -> None:
        """Finish the current stage without reporting it."""

    def message(self, text: str, *, markup: bool = True, style: str | None = None) -> None:
        """Discard a message."""

    def set_total_stages(self, total: int) -> None:
        """Discard a stage count."""


_NULL_REPORTER = _NullReporter()


@dataclass
class Drawing:
    """Everything needed to reproduce a project's SVG.

    Attributes
    ----------
    paper : Paper
        Paper the drawing is placed on.
    pens : list[Pen]
        Pens in drawing order, including any appended key pen.
    strokes_by_pen : list[list[LineString]]
        Optimised strokes per pen, in drawing order, in working-image pixels.
    image_placement : ImagePlacement
        Rectangle occupied by the source image on the page, in millimetres.
    resolution : WorkingResolution
        Working resolution used by the drawing algorithms.
    fit_mode : FitMode
        Placement mode used for the image: ``fit``, ``fill`` or ``none``.
    clip_rect : ImagePlacement | None
        Rectangle the ink is clipped to for ``fill`` mode, else ``None``.
    source_size_px : tuple[int, int]
        Source image size in pixels.
    working_size_px : tuple[int, int]
        Working image size in pixels, matching ``strokes_by_pen`` coordinates.
    """

    paper: Paper
    pens: list[Pen]
    strokes_by_pen: list[list[LineString]]
    image_placement: ImagePlacement
    resolution: WorkingResolution
    fit_mode: FitMode
    clip_rect: ImagePlacement | None
    source_size_px: tuple[int, int]
    working_size_px: tuple[int, int]

    def to_svg(
        self,
        path: str | Path,
        *,
        use_vpype: bool = True,
        vpype_path: str = "vpype",
        reporter: Reporter | None = None,
    ) -> Path:
        """Write this drawing to an SVG and return the path written.

        vpype optimises geometry one pen at a time when available; penpath
        writes the final SVG on both paths, so the millimetre layout and the
        metadata are identical. A drawing with no strokes writes no file, as
        the CLI did before this logic moved into core.

        Parameters
        ----------
        path : str | Path
            Output SVG file path.
        use_vpype : bool, optional
            Ask vpype to optimise each pen's geometry. Defaults to True.
        vpype_path : str, optional
            Path to the vpype executable. Defaults to ``"vpype"``.
        reporter : Reporter | None, optional
            Progress reporter. ``None`` discards progress messages.

        Returns
        -------
        Path
            The output path written.
        """
        output_path = Path(path)
        if not any(self.strokes_by_pen):
            return output_path

        report = reporter if reporter is not None else _NULL_REPORTER
        report.start("Exporting SVG")
        if use_vpype:
            try:
                strokes_mm_by_pen = optimize_with_vpype(
                    self.strokes_by_pen,
                    self.paper,
                    self.pens,
                    vpype_path,
                    self.image_placement,
                    self.working_size_px,
                    self.clip_rect,
                )
                write_penpath_svg(
                    [
                        [LineString(stroke.polyline) for stroke in strokes]
                        for strokes in strokes_mm_by_pen
                    ],
                    self.paper,
                    self.pens,
                    output_path,
                    self.image_placement,
                    self.resolution,
                    self.fit_mode,
                    self.clip_rect,
                )
            except FileNotFoundError:
                report.message(
                    "vpype not found, falling back to direct SVG export "
                    '(install it with: pip install "penpath[vpype]")',
                    style="yellow",
                    markup=False,
                )
                export_pen_layers(
                    self.strokes_by_pen,
                    self.paper,
                    self.pens,
                    output_path,
                    self.image_placement,
                    self.working_size_px,
                    self.resolution,
                    self.fit_mode,
                    self.clip_rect,
                )
        else:
            export_pen_layers(
                self.strokes_by_pen,
                self.paper,
                self.pens,
                output_path,
                self.image_placement,
                self.working_size_px,
                self.resolution,
                self.fit_mode,
                self.clip_rect,
            )
        report.finish()
        return output_path


def draw_project(
    project: Project,
    *,
    max_resolution_px: int | None = None,
    no_downscale: bool = False,
    reporter: Reporter | None = None,
) -> Drawing:
    """Run the image-to-geometry pipeline for a project.

    The steps are the ones ``penpath convert`` has always run: load the image
    and plan the working resolution, downscale, auto-equalize, mask the paper
    background, boost saturation, trace the key edges, split by pen, apply the
    filters, run the PFM once per pen, order pens for drawing and optimise the
    geometry per pen. No SVG is written here; call :meth:`Drawing.to_svg`.

    Parameters
    ----------
    project : Project
        Fully resolved project: image, paper, pens, PFM and output path.
    max_resolution_px : int | None, optional
        Longest side of the working image, overriding the derived value.
    no_downscale : bool, optional
        Keep the source pixels instead of downscaling. Defaults to False.
    reporter : Reporter | None, optional
        Progress reporter. ``None`` discards progress messages.

    Returns
    -------
    Drawing
        The optimised strokes, pens and placement needed to write the SVG.
    """
    report = reporter if reporter is not None else _NULL_REPORTER
    pens = project.palette
    use_palette = len(pens) > 1
    use_background = (
        project.image.background if project.image.background is not None else use_palette
    )
    saturation_active = use_palette and (
        project.image.saturation != NO_BOOST_FACTOR or project.image.palette_adapt
    )
    use_key_layer = project.image.key_layer if project.image.key_layer is not None else use_palette

    # Step 1: Load image and plan the working resolution. Placement is derived
    # from the source size so the drawing rectangle does not move when the
    # working image is downscaled.
    report.start("Loading image")
    image = load_image(project.image.path, auto_orient=project.image.auto_orient)
    source_size_px = image.size
    origin_x_mm, origin_y_mm = project.paper.drawable_origin_mm
    fit_mode = project.paper.fit
    image_placement = fit_image_placement(
        image_size_px=source_size_px,
        area_width_mm=project.paper.drawable_width_mm,
        area_height_mm=project.paper.drawable_height_mm,
        image_dpi=project.image.dpi,
        offset_x_mm=origin_x_mm,
        offset_y_mm=origin_y_mm,
        mode=fit_mode,
    )
    clip_rect = (
        ImagePlacement(
            origin_x_mm,
            origin_y_mm,
            project.paper.drawable_width_mm,
            project.paper.drawable_height_mm,
        )
        if fit_mode == "fill"
        else None
    )
    resolution = plan_working_resolution(
        source_size_px,
        project.paper,
        pens[0].width_mm,
        max_longest_px=max_resolution_px,
    )
    if no_downscale:
        resolution = replace(resolution, target_size_px=source_size_px, scale=1.0)
    downscaling = resolution.target_size_px != source_size_px
    report.set_total_stages(
        5 + int(downscaling) + int(use_background) + int(saturation_active) + int(use_key_layer)
    )
    report.finish()

    working_width, working_height = resolution.target_size_px
    report.message(
        f"Working resolution: {working_width}x{working_height} px "
        f"(source {source_size_px[0]}x{source_size_px[1]} px, scale {resolution.scale:.3f})"
    )

    # Step 2: Downscale to the working resolution, only when it changes the image.
    if downscaling:
        report.start("Downscaling image")
    working_image = apply_working_resolution(image, resolution)
    if downscaling:
        report.finish()
    working_size_px = working_image.size

    # Auto levels run once on the whole working image, before separation, so
    # every palette channel shares one luminance range and explicit -f filters
    # keep their current meaning.
    if project.image.auto_equalize:
        working_image = auto_equalize(working_image)

    if use_background:
        report.start("Masking paper background")
        masked = mask_background(
            working_image,
            threshold=project.image.background_threshold,
            method=project.image.background_method,
        )
        working_image = masked.image
        report.finish()
        report.message(
            f"Paper colour: {masked.paper_color} ({project.image.background_method} method); "
            f"masked {masked.masked_percent:.1f}% of pixels as no ink"
        )

    # Chroma boost runs on the masked working image. A single pen has no colour
    # decision to make, so both paths are silent no-ops there.
    if saturation_active:
        if project.image.saturation != NO_BOOST_FACTOR:
            factor = project.image.saturation
            report.start("Boosting saturation")
            working_image = boost_saturation(working_image, factor)
            report.finish()
            mode = "manual"
        else:
            report.start("Adapting saturation to palette")
            factor = adapt_saturation(working_image, pens)
            report.finish()
            if factor != NO_BOOST_FACTOR:
                working_image = boost_saturation(working_image, factor)
            mode = "palette-adapted"
        report.message(f"Saturation factor: {factor:.2f} ({mode})")

    # The key pass traces the working colour image once, before separation, so
    # it sees the same masking and chroma boost as the palette channels.
    key_lines: list[LineString] = []
    if use_key_layer:
        report.start("Tracing key edges")
        key_lines = key_layer_strokes(working_image)
        report.finish()

    # Step 3: Split before filtering, so the default grayscale filter cannot
    # throw away the colour needed to choose a pen.
    report.start("Applying filters")
    pen_images = separate_palette(working_image, pens)
    filtered_by_pen = [project.image.filters.apply(img) for _, img in pen_images]
    report.finish()

    # Step 4: Run the PFM once per pen, with settings in working-image pixels.
    report.start("Generating lines (PFM)")
    pfm_fn, _ = get_pfm(project.pfm.pfm_type)
    pfm_settings = project.pfm.to_typed_settings()
    if use_palette and isinstance(pfm_settings, SketchLinesSettings):
        legacy = {
            "max_fill": 80.0,
            "line_density": 0.75,
            "tone_coverage": 1.0,
            "tone_exponent": 1.0,
            "texture_limit": 0.0,
        }
        updates = {
            key: value for key, value in legacy.items() if key not in pfm_settings.model_fields_set
        }
        if updates:
            pfm_settings = pfm_settings.model_copy(update=updates)
    # Hatch, Patch Hatch, TSP, Squiggle and Engraving need the physical scale,
    # which the serialisable settings do not carry. A palette rotates the angle
    # set per pen so colour layers do not sit exactly on top of one another; a
    # single pen keeps the original angles.
    pixels_per_mm = working_width / image_placement.width
    lines_by_pen: list[list[LineString]] = []
    for index, img in enumerate(filtered_by_pen):
        pen_settings = pfm_settings
        pfm_kwargs: dict[str, object] = {}
        if isinstance(
            pen_settings,
            (HatchSettings, PatchHatchSettings, TSPSettings, SquiggleSettings, EngravingSettings),
        ):
            if use_palette and isinstance(pen_settings, HatchSettings):
                pen_settings = with_angle_offset(pen_settings, index * PALETTE_ANGLE_STEP_DEG)
            elif use_palette and isinstance(pen_settings, PatchHatchSettings):
                pen_settings = with_layer_angle_offset(pen_settings, index * PALETTE_ANGLE_STEP_DEG)
            pfm_kwargs = {
                "pixels_per_mm": pixels_per_mm,
                "pen_width_mm": pens[index].width_mm,
            }
        if project.image.equalize_levels:
            img = apply_tone_levels(img, pfm_tone_targets(pen_settings, pens[index].width_mm))
        lines_by_pen.append(draw_styled_lines(img, pfm_fn, pen_settings, project.style, pfm_kwargs))
    report.finish()

    drawing_pens = order_pens_for_drawing(pens)
    position_by_id = {id(pen): index for index, pen in enumerate(pens)}
    lines_by_pen = [lines_by_pen[position_by_id[id(pen)]] for pen in drawing_pens]
    pens = drawing_pens

    # In palette mode the key strokes share the near-black pen, which drawing
    # order puts last. A single pen or a palette without black gets its own
    # appended "key" pen so the edges land in a separate final layer.
    if use_key_layer:
        if use_palette and pens and is_near_black_pen(pens[-1]):
            lines_by_pen[-1] = [*lines_by_pen[-1], *key_lines]
        else:
            key_pen = Pen(
                name="key",
                width_mm=min(pen.width_mm for pen in pens),
                color="#000000",
            )
            pens = [*pens, key_pen]
            lines_by_pen = [*lines_by_pen, key_lines]

    def _drawing(strokes: list[list[LineString]], drawing_pens: list[Pen]) -> Drawing:
        return Drawing(
            paper=project.paper,
            pens=drawing_pens,
            strokes_by_pen=strokes,
            image_placement=image_placement,
            resolution=resolution,
            fit_mode=fit_mode,
            clip_rect=clip_rect,
            source_size_px=source_size_px,
            working_size_px=working_size_px,
        )

    if not any(lines_by_pen):
        report.message("Warning: No lines generated", style="yellow")
        return _drawing([[] for _ in pens], pens)

    # Step 5: Optimize geometry per pen; never merge or sort across pens.
    report.start("Optimizing geometry")
    strokes_by_pen = [
        optimize(
            lines,
            project.paper,
            simplify_tol_mm=0.1,
            merge_angle_deg=5.0,
            merge_dist_mm=0.5,
        )
        for lines in lines_by_pen
    ]
    report.finish()

    return _drawing(strokes_by_pen, pens)


__all__ = ["Drawing", "Reporter", "draw_project"]
