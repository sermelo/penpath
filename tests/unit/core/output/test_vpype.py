"""Unit tests for the vpype wrapper."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from shapely import LineString

from penpath.core.models import Paper, Pen
from penpath.core.output.vpype import optimize_with_vpype

if TYPE_CHECKING:
    from collections.abc import Sequence

    from penpath.core.simulation import PenStroke


pytest.importorskip("vpype", reason="vpype not installed, skipping vpype tests")


_FAKE_SVG = b"""<svg xmlns="http://www.w3.org/2000/svg"
 xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
 width="100mm" height="100mm" viewBox="0 0 100 100">
 <g fill="none" inkscape:groupmode="layer" inkscape:label="1">
  <line x1="10" y1="10" x2="20" y2="20"/>
 </g>
</svg>"""


class TestOptimizeWithVpype:
    """Tests for optimise-with-vpype, which returns geometry in millimetres."""

    def test_optimize_with_vpype_basic(self):
        """A vpype run returns strokes in paper millimetres."""
        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)
        pen = Pen(name="fine", width_mm=0.3)
        lines = [LineString([(100, 100), (200, 200), (300, 100)])]

        strokes_by_pen = optimize_with_vpype([lines], paper, [pen])

        assert len(strokes_by_pen) == 1
        strokes = strokes_by_pen[0]
        assert strokes
        assert all(stroke.pen_up is False for stroke in strokes)
        assert all(
            point[0] <= 210 and point[1] <= 297 for stroke in strokes for point in stroke.polyline
        )

    def test_optimize_with_vpype_multiple_lines(self):
        """Multiple lines all appear in the returned geometry."""
        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)
        pen = Pen(name="fine", width_mm=0.3)
        lines = [
            LineString([(100, 100), (200, 200)]),
            LineString([(300, 300), (400, 400)]),
            LineString([(500, 100), (600, 200)]),
        ]

        strokes = optimize_with_vpype([lines], paper, [pen])[0]

        assert len(strokes) >= 1

    def test_optimize_with_vpype_empty_geometries_raises(self):
        """No valid geometry is rejected."""
        paper = Paper(name="A4", width_mm=210, height_mm=297)
        pen = Pen(name="fine", width_mm=0.3)

        with pytest.raises(ValueError, match="No valid geometries"):
            optimize_with_vpype([[]], paper, [pen])

    def test_optimize_with_vpype_no_pens_raises(self):
        """At least one pen is required."""
        paper = Paper(name="A4", width_mm=210, height_mm=297)
        lines = [LineString([(100, 100), (200, 200)])]

        with pytest.raises(ValueError, match="At least one pen must be provided"):
            optimize_with_vpype([lines], paper, [])

    def test_optimize_with_vpype_pen_count_must_match(self):
        """One geometry entry is required per pen."""
        paper = Paper(name="A4", width_mm=210, height_mm=297)
        pens = [Pen(name="fine", width_mm=0.3), Pen(name="bold", width_mm=0.5)]
        lines = [LineString([(100, 100), (200, 200)])]

        with pytest.raises(ValueError, match="one entry per pen"):
            optimize_with_vpype([lines], paper, pens)

    def test_optimize_with_vpype_vpype_not_found(self):
        """A missing executable raises a helpful error."""
        paper = Paper(name="A4", width_mm=210, height_mm=297)
        pen = Pen(name="fine", width_mm=0.3)
        lines = [LineString([(100, 100), (200, 200)])]

        with pytest.raises(FileNotFoundError, match="vpype executable not found"):
            optimize_with_vpype([lines], paper, [pen], vpype_path="/nonexistent/vpype")

    def test_optimize_with_vpype_placement_without_image_size_raises(self):
        """A placement requires the image size in pixels."""
        paper = Paper(name="A4", width_mm=210, height_mm=297)
        pen = Pen(name="fine", width_mm=0.3)
        lines = [LineString([(100, 100), (200, 200)])]

        with pytest.raises(ValueError, match="image_size_px is required"):
            optimize_with_vpype([lines], paper, [pen], image_placement=(10.0, 20.0, 50.0, 50.0))

    def test_optimize_with_vpype_placement_scales_geometry_and_drops_center(self):
        """With a placement, strokes land in the rectangle without recentering."""
        paper = Paper(name="square", width_mm=100, height_mm=100)
        pen = Pen(name="fine", width_mm=0.3)
        lines = [LineString([(0, 0), (100, 50)])]
        placement = (10.0, 10.0, 50.0, 25.0)

        strokes = optimize_with_vpype(
            [lines], paper, [pen], image_placement=placement, image_size_px=(100, 50)
        )[0]

        assert strokes
        points = [point for stroke in strokes for point in stroke.polyline]
        assert min(point[0] for point in points) == pytest.approx(10.0, abs=0.1)
        assert min(point[1] for point in points) == pytest.approx(10.0, abs=0.1)
        assert max(point[0] for point in points) == pytest.approx(60.0, abs=0.1)
        assert max(point[1] for point in points) == pytest.approx(35.0, abs=0.1)

    def test_optimize_with_vpype_without_placement_centers(self, monkeypatch):
        """Without a placement, vpype is allowed to centre the output."""
        paper = Paper(name="square", width_mm=100, height_mm=100)
        pen = Pen(name="fine", width_mm=0.3)
        lines = [LineString([(0, 0), (100, 50)])]
        commands: list[list[str]] = []

        def fake_run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
            commands.append(cmd)
            return SimpleNamespace(stdout=_FAKE_SVG, stderr=b"")

        monkeypatch.setattr(subprocess, "run", fake_run)
        optimize_with_vpype([lines], paper, [pen])

        assert commands
        assert "--center" in commands[0]

    def test_optimize_with_vpype_one_call_and_one_layer_per_pen(self, monkeypatch):
        """Each pen gets exactly one vpype call with one layer and no sorting across pens."""
        paper = Paper(name="square", width_mm=100, height_mm=100)
        pens = [
            Pen(name="red", width_mm=0.3, color="#FF0000"),
            Pen(name="blue", width_mm=0.4, color="#0000FF"),
        ]
        batches: Sequence[Sequence[LineString]] = [
            [LineString([(0, 0), (10, 10)])],
            [LineString([(20, 20), (30, 30)])],
        ]
        commands: list[list[str]] = []

        def fake_run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
            commands.append(cmd)
            return SimpleNamespace(stdout=_FAKE_SVG, stderr=b"")

        monkeypatch.setattr(subprocess, "run", fake_run)
        strokes_by_pen = optimize_with_vpype(batches, paper, pens, vpype_path="vpype-stub")

        assert len(commands) == 2
        for command in commands:
            assert command.count("--layer") == 1
            assert "--layer" in command
            assert "script" in command
            assert "linesort" in command
            assert "color" not in command
            assert "name" not in command
        assert len(strokes_by_pen) == 2
        assert all(len(strokes) == 1 for strokes in strokes_by_pen)
        assert all(
            stroke.polyline == [(10.0, 10.0), (20.0, 20.0)]
            for strokes in strokes_by_pen
            for stroke in strokes
        )

    def test_optimize_with_vpype_failed_call_raises_runtime_error(self, monkeypatch):
        """A vpype failure is reported with its stderr."""
        paper = Paper(name="square", width_mm=100, height_mm=100)
        pen = Pen(name="fine", width_mm=0.3)
        lines = [LineString([(0, 0), (10, 10)])]

        def fake_run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
            raise subprocess.CalledProcessError(1, cmd, stderr=b"broken pipeline")

        monkeypatch.setattr(subprocess, "run", fake_run)
        with pytest.raises(RuntimeError, match="broken pipeline"):
            optimize_with_vpype([lines], paper, [pen], vpype_path="vpype-stub")

    def test_optimize_with_vpype_reads_back_millimetres_from_viewbox(self):
        """The parser derives millimetres from the root width/viewBox ratio."""
        paper = Paper(name="square", width_mm=100, height_mm=100)
        pen = Pen(name="fine", width_mm=0.3)
        lines = [LineString([(0, 0), (100, 50)])]

        strokes: list[PenStroke] = optimize_with_vpype(
            [lines],
            paper,
            [pen],
            image_placement=(0.0, 0.0, 100.0, 100.0),
            image_size_px=(100, 100),
        )[0]

        assert strokes
        assert max(point[0] for stroke in strokes for point in stroke.polyline) == pytest.approx(
            100.0, abs=0.1
        )


if __name__ == "__main__":
    pytest.main([__file__, "-xvs"])
