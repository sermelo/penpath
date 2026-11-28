"""Unit tests for the core image-to-drawing conversion."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console
from shapely import LineString

from penpath.cli.progress import StageReporter
from penpath.core import Drawing, Reporter, draw_project
from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings
from penpath.core.image.pipeline import FilterPipeline
from penpath.core.models import ImageRef, Paper, Pen, Project, make_pfm_settings

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
CIRCLE = FIXTURES / "images" / "reference" / "circle.png"


class RecordingReporter:
    """Capture the progress calls made by the conversion pipeline."""

    def __init__(self) -> None:
        self.starts: list[str] = []
        self.finishes = 0
        self.messages: list[str] = []
        self.totals: list[int] = []

    def start(self, name: str) -> None:
        """Record a stage start."""
        self.starts.append(name)

    def finish(self) -> None:
        """Record a stage finish."""
        self.finishes += 1

    def message(self, text: str, *, markup: bool = True, style: str | None = None) -> None:
        """Record a message."""
        self.messages.append(text)

    def set_total_stages(self, total: int) -> None:
        """Record the stage count."""
        self.totals.append(total)


def _project(output_path: Path) -> Project:
    """A small, deterministic single-pen project on a fixture image."""
    filters = FilterPipeline()
    filters.add_step("grayscale", method="luminance")
    return Project(
        image=ImageRef(path=CIRCLE, filters=filters),
        paper=Paper(name="A4", width_mm=210, height_mm=297),
        pen=Pen(name="fine", width_mm=0.3, color="#000000"),
        pfm=make_pfm_settings("sketch_lines", SketchLinesSettings(seed=42)),
        output_path=output_path,
    )


def test_draw_project_returns_drawing_with_planned_geometry(tmp_path: Path) -> None:
    """draw_project reports stages and returns the strokes and placement."""
    reporter = RecordingReporter()
    drawing = draw_project(_project(tmp_path / "out.svg"), max_resolution_px=64, reporter=reporter)

    assert isinstance(drawing, Drawing)
    assert drawing.paper.name == "A4"
    assert [pen.name for pen in drawing.pens] == ["fine"]
    assert len(drawing.strokes_by_pen) == 1
    assert drawing.strokes_by_pen[0]
    assert all(isinstance(line, LineString) for line in drawing.strokes_by_pen[0])
    assert drawing.image_placement.width > 0
    assert drawing.fit_mode == "fit"
    assert drawing.clip_rect is None
    assert drawing.source_size_px == (400, 400)
    assert drawing.working_size_px == (64, 64)
    assert drawing.resolution.target_size_px == (64, 64)
    assert reporter.starts == [
        "Loading image",
        "Downscaling image",
        "Applying filters",
        "Generating lines (PFM)",
        "Optimizing geometry",
    ]
    assert reporter.finishes == 5
    assert reporter.totals == [6]
    assert any("Working resolution: 64x64 px" in text for text in reporter.messages)


def test_drawing_to_svg_writes_direct_export_without_a_reporter(tmp_path: Path) -> None:
    """to_svg writes the same layers without any progress reporter."""
    output = tmp_path / "out.svg"
    drawing = draw_project(_project(output), max_resolution_px=64)
    written = drawing.to_svg(output, use_vpype=False)

    assert written == output
    assert output.exists()
    text = output.read_text(encoding="utf-8")
    assert 'id="layer1"' in text
    assert 'inkscape:label="fine"' in text
    assert 'image-width="64"' in text
    assert 'source-width="400"' in text


def test_to_svg_reports_export_and_falls_back_when_vpype_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing vpype falls back to direct export and says so on the reporter."""

    def missing_vpype(*args: object, **kwargs: object) -> object:
        raise FileNotFoundError("vpype")

    import penpath.core.convert as convert_module

    monkeypatch.setattr(convert_module, "optimize_with_vpype", missing_vpype)
    reporter = RecordingReporter()
    output = tmp_path / "fallback.svg"
    drawing = draw_project(_project(output), max_resolution_px=64, reporter=reporter)

    drawing.to_svg(output, use_vpype=True, reporter=reporter)

    assert output.exists()
    assert reporter.starts[-1] == "Exporting SVG"
    assert reporter.finishes >= 1
    assert any(
        "vpype not found, falling back to direct SVG export" in text for text in reporter.messages
    )


def test_empty_drawing_writes_no_svg(tmp_path: Path) -> None:
    """A drawing with no strokes leaves the output path untouched."""
    output = tmp_path / "empty.svg"
    drawing = draw_project(_project(output), max_resolution_px=64, reporter=RecordingReporter())
    empty = Drawing(
        paper=drawing.paper,
        pens=drawing.pens,
        strokes_by_pen=[[] for _ in drawing.pens],
        image_placement=drawing.image_placement,
        resolution=drawing.resolution,
        fit_mode=drawing.fit_mode,
        clip_rect=drawing.clip_rect,
        source_size_px=drawing.source_size_px,
        working_size_px=drawing.working_size_px,
    )
    reporter = RecordingReporter()

    assert empty.to_svg(output, reporter=reporter) == output
    assert not output.exists()
    assert reporter.starts == []


def test_cli_stage_reporter_satisfies_core_protocol() -> None:
    """The CLI reporter can be passed to core without an import in core."""

    def use_reporter(reporter: Reporter) -> None:
        reporter.start("Stage")
        reporter.finish()
        reporter.message("done", style="yellow", markup=False)
        reporter.set_total_stages(3)

    reporter = StageReporter(Console(file=StringIO()))
    use_reporter(reporter)
