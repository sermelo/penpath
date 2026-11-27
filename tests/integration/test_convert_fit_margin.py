"""End-to-end bounding-box tests for convert --fit and --margin (LUC-163)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner
from PIL import Image

from penpath.cli.main import main
from penpath.core.image.pipeline import FilterPipeline
from penpath.core.models import FitMode, ImageRef, Paper, Pen, Project, SketchLinesPFM
from penpath.core.output.svg import ImagePlacement, fit_image_placement
from penpath.core.project import load_yaml, save_yaml
from penpath.core.svg_parse import get_image_placement, parse_svg_strokes

SHAPES = {
    "portrait": (90, 150),
    "landscape": (150, 90),
    "square": (120, 120),
}
PAPERS = {"square190": ("190x190", 190.0, 190.0), "a4": ("a4", 210.0, 297.0)}
MARGINS = {"default": None, "uniform": "5", "per_side": "20,5,20,5"}
DPI = 300
EPS = 0.05


def _make_checkerboard(path: Path, size: tuple[int, int]) -> None:
    image = Image.new("L", size, 255)
    pixels = image.load()
    for y in range(size[1]):
        for x in range(size[0]):
            pixels[x, y] = 0 if (x // 10 + y // 10) % 2 == 0 else 255
    image.save(path)


def _margins(spec: str | None) -> tuple[float, float, float, float]:
    if spec is None:
        return (10.0, 10.0, 10.0, 10.0)
    values = [float(value) for value in spec.split(",")]
    if len(values) == 1:
        return (values[0], values[0], values[0], values[0])
    return (values[0], values[1], values[2], values[3])


def _convert(
    runner: CliRunner,
    image_path: Path,
    output: Path,
    *,
    paper: str,
    mode: FitMode,
    margin: str | None = None,
    extra: list[str] | None = None,
) -> None:
    args = [
        "convert",
        str(image_path),
        "-o",
        str(output),
        "--paper",
        paper,
        "--fit",
        mode,
        "--no-vpype",
        "--quiet",
        "-s",
        "seed=42",
        "-s",
        "line_density=2.0",
    ]
    if margin is not None:
        args.extend(["--margin", margin])
    if extra:
        args.extend(extra)
    result = runner.invoke(main, args)
    assert result.exit_code == 0, result.output


def _bbox(path: Path) -> tuple[float, float, float, float]:
    points = [point for stroke in parse_svg_strokes(path) for point in stroke.polyline]
    assert points
    return (
        min(x for x, _ in points),
        min(y for _, y in points),
        max(x for x, _ in points),
        max(y for _, y in points),
    )


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.mark.parametrize("shape", list(SHAPES))
@pytest.mark.parametrize("paper_name", list(PAPERS))
@pytest.mark.parametrize("mode", ["fit", "fill", "none"])
@pytest.mark.parametrize("margin_name", list(MARGINS))
def test_convert_ink_bounding_box_matrix(
    runner: CliRunner,
    tmp_path: Path,
    shape: str,
    paper_name: str,
    mode: FitMode,
    margin_name: str,
) -> None:
    """Placement and ink follow the paper, margins and mode on every combination."""
    image_size = SHAPES[shape]
    paper_spec, paper_width, paper_height = PAPERS[paper_name]
    margin = MARGINS[margin_name]
    top, right, bottom, left = _margins(margin)
    image_path = tmp_path / f"{shape}.png"
    output = tmp_path / f"{shape}_{paper_name}_{mode}_{margin_name}.svg"
    _make_checkerboard(image_path, image_size)
    _convert(runner, image_path, output, paper=paper_spec, mode=mode, margin=margin)

    drawable_width = paper_width - left - right
    drawable_height = paper_height - top - bottom
    expected = fit_image_placement(
        image_size,
        drawable_width,
        drawable_height,
        image_dpi=DPI,
        offset_x_mm=left,
        offset_y_mm=top,
        mode=mode,
    )
    assert tuple(get_image_placement(output, image_size)) == pytest.approx(
        tuple(expected), abs=0.001
    )

    min_x, min_y, max_x, max_y = _bbox(output)
    assert left - EPS <= min_x <= max_x <= paper_width - right + EPS
    assert top - EPS <= min_y <= max_y <= paper_height - bottom + EPS

    if mode == "fit":
        assert expected.width <= drawable_width + EPS
        assert expected.height <= drawable_height + EPS
        assert expected.width == pytest.approx(drawable_width) or expected.height == pytest.approx(
            drawable_height
        )
    elif mode == "fill":
        assert expected.width >= drawable_width - EPS
        assert expected.height >= drawable_height - EPS
    else:
        assert expected.width == pytest.approx(image_size[0] * 25.4 / DPI)
        assert expected.height == pytest.approx(image_size[1] * 25.4 / DPI)

    if mode in ("fit", "fill"):
        assert max_x - min_x >= 0.6 * min(expected.width, drawable_width)
        assert max_y - min_y >= 0.6 * min(expected.height, drawable_height)


def test_default_fit_fills_190x190_minus_the_default_margin(
    runner: CliRunner, tmp_path: Path
) -> None:
    """The exact acceptance command fills 170x170 mm on a 190x190 page."""
    image_path = tmp_path / "img.png"
    output = tmp_path / "out.svg"
    _make_checkerboard(image_path, (120, 120))
    result = runner.invoke(
        main,
        [
            "convert",
            str(image_path),
            "-o",
            str(output),
            "--paper",
            "190x190",
            "--no-vpype",
            "--quiet",
            "-s",
            "seed=42",
            "-s",
            "line_density=2.0",
        ],
    )
    assert result.exit_code == 0, result.output

    assert get_image_placement(output, (120, 120)) == ImagePlacement(10.0, 10.0, 170.0, 170.0)
    min_x, min_y, max_x, max_y = _bbox(output)
    assert min_x == pytest.approx(10.0, abs=EPS)
    assert min_y == pytest.approx(10.0, abs=EPS)
    assert max_x >= 168.0
    assert max_y >= 168.0


def test_dpi_only_changes_size_with_fit_none(runner: CliRunner, tmp_path: Path) -> None:
    image_path = tmp_path / "square.png"
    _make_checkerboard(image_path, SHAPES["square"])
    for mode in ("fit", "fill"):
        placements = []
        for dpi in (72, 300):
            output = tmp_path / f"{mode}_{dpi}.svg"
            _convert(
                runner,
                image_path,
                output,
                paper="190x190",
                mode=mode,
                extra=["--dpi", str(dpi)],
            )
            placements.append(get_image_placement(output, SHAPES["square"]))
        assert placements[0] == pytest.approx(placements[1])

    placements = []
    for dpi in (72, 300):
        output = tmp_path / f"none_{dpi}.svg"
        _convert(
            runner,
            image_path,
            output,
            paper="190x190",
            mode="none",
            extra=["--dpi", str(dpi)],
        )
        placements.append(get_image_placement(output, SHAPES["square"]))
    assert placements[1].width == pytest.approx(placements[0].width * 72 / 300)
    assert placements[1].height == pytest.approx(placements[0].height * 72 / 300)


def test_margin_wins_over_inline_paper_margins(runner: CliRunner, tmp_path: Path) -> None:
    image_path = tmp_path / "square.png"
    output = tmp_path / "override.svg"
    _make_checkerboard(image_path, SHAPES["square"])
    _convert(
        runner,
        image_path,
        output,
        paper="190x190,20,5,20,5",
        mode="fit",
        margin="8",
    )
    assert get_image_placement(output, SHAPES["square"]) == ImagePlacement(8.0, 8.0, 174.0, 174.0)


def test_fit_and_margin_through_vpype_match_the_direct_path(
    runner: CliRunner, tmp_path: Path
) -> None:
    pytest.importorskip("vpype")
    if shutil.which("vpype") is None:
        pytest.skip("vpype executable not found")
    image_path = tmp_path / "landscape.png"
    _make_checkerboard(image_path, SHAPES["landscape"])
    args = [
        "convert",
        str(image_path),
        "--paper",
        "190x190",
        "--margin",
        "5",
        "--fit",
        "fill",
        "--quiet",
        "-s",
        "seed=42",
        "-s",
        "line_density=2.0",
    ]
    direct = tmp_path / "direct.svg"
    vpype = tmp_path / "vpype.svg"
    result = runner.invoke(main, [*args, "-o", str(direct), "--no-vpype"])
    assert result.exit_code == 0, result.output
    result = runner.invoke(main, [*args, "-o", str(vpype)])
    assert result.exit_code == 0, result.output

    assert get_image_placement(vpype, SHAPES["landscape"]) == pytest.approx(
        get_image_placement(direct, SHAPES["landscape"])
    )
    for output in (direct, vpype):
        min_x, min_y, max_x, max_y = _bbox(output)
        assert 5.0 - EPS <= min_x <= max_x <= 185.0 + EPS
        assert 5.0 - EPS <= min_y <= max_y <= 185.0 + EPS


def test_inline_paper_keeps_four_per_side_margins(runner: CliRunner, tmp_path: Path) -> None:
    image_path = tmp_path / "square.png"
    output = tmp_path / "inline.svg"
    _make_checkerboard(image_path, SHAPES["square"])
    _convert(
        runner,
        image_path,
        output,
        paper="190x190,20,5,20,5",
        mode="fit",
    )
    assert get_image_placement(output, SHAPES["square"]) == ImagePlacement(20.0, 20.0, 150.0, 150.0)


@pytest.mark.parametrize("spec", ["-1", "1,2", "1,2,3,4,5", "nan", "abc"])
def test_invalid_margin_is_a_usage_error(runner: CliRunner, tmp_path: Path, spec: str) -> None:
    image_path = tmp_path / "square.png"
    _make_checkerboard(image_path, SHAPES["square"])
    result = runner.invoke(
        main,
        [
            "convert",
            str(image_path),
            "-o",
            str(tmp_path / "invalid.svg"),
            "--paper",
            "190x190",
            "--margin",
            spec,
            "--no-vpype",
        ],
    )
    assert result.exit_code == 2
    assert "--margin" in result.output


@pytest.mark.parametrize(
    ("paper", "margin"),
    [("190x190", "100,100,100,100"), ("20x20", None), ("190x190,100,100,100,100", None)],
)
def test_no_drawable_area_is_a_usage_error(
    runner: CliRunner, tmp_path: Path, paper: str, margin: str | None
) -> None:
    image_path = tmp_path / "square.png"
    _make_checkerboard(image_path, SHAPES["square"])
    args = [
        "convert",
        str(image_path),
        "-o",
        str(tmp_path / "invalid.svg"),
        "--paper",
        paper,
        "--no-vpype",
    ]
    if margin is not None:
        args.extend(["--margin", margin])
    result = runner.invoke(main, args)
    assert result.exit_code == 2
    assert "no drawable area" in result.output
    assert "reduce the margin or use a larger paper" in result.output


def test_project_paper_roundtrip_and_cli_overrides(runner: CliRunner, tmp_path: Path) -> None:
    image_path = tmp_path / "square.png"
    output = tmp_path / "project.svg"
    override_output = tmp_path / "override.svg"
    project_path = tmp_path / "project.yaml"
    _make_checkerboard(image_path, SHAPES["square"])
    project = Project(
        image=ImageRef(path=image_path, filters=FilterPipeline(), dpi=DPI),
        paper=Paper(
            name="square190", width_mm=190, height_mm=190, margin_mm=(20, 5, 20, 5), fit="fill"
        ),
        pen=Pen(name="fine", width_mm=0.3),
        pfm=SketchLinesPFM(),
        output_path=output,
    )
    save_yaml(project, project_path)
    loaded = load_yaml(project_path)
    assert loaded.paper.margin_mm == (20.0, 5.0, 20.0, 5.0)
    assert loaded.paper.fit == "fill"

    result = runner.invoke(
        main,
        [
            "convert",
            str(image_path),
            "-o",
            str(output),
            "--project",
            str(project_path),
            "--no-vpype",
            "--quiet",
            "-s",
            "seed=42",
        ],
    )
    assert result.exit_code == 0, result.output
    assert get_image_placement(output, SHAPES["square"]) == ImagePlacement(5.0, 5.0, 180.0, 180.0)
    assert 'fit="fill"' in output.read_text(encoding="utf-8")

    result = runner.invoke(
        main,
        [
            "convert",
            str(image_path),
            "-o",
            str(override_output),
            "--project",
            str(project_path),
            "--fit",
            "fit",
            "--margin",
            "12",
            "--no-vpype",
            "--quiet",
            "-s",
            "seed=42",
        ],
    )
    assert result.exit_code == 0, result.output
    assert get_image_placement(override_output, SHAPES["square"]) == ImagePlacement(
        12.0, 12.0, 166.0, 166.0
    )
    assert 'fit="fill"' not in override_output.read_text(encoding="utf-8")


def test_help_documents_fit_margin_and_dpi_rule(runner: CliRunner) -> None:
    result = runner.invoke(main, ["convert", "--help"])
    assert result.exit_code == 0, result.output
    assert "--fit [fit|fill|none]" in result.output
    assert "--margin TEXT" in result.output
    assert "top,right,bottom,left" in result.output
    assert "drawn size only with --fit none" in " ".join(result.output.split())
