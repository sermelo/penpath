"""End-to-end tests for penpath CLI."""

import tempfile
from pathlib import Path

import click
import pytest
from click.testing import CliRunner
from PIL import Image

from penpath.cli.main import main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def temp_config_dir(monkeypatch: pytest.MonkeyPatch) -> Path:
    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir) / "penpath"
        config_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(config_dir.parent))
        yield config_dir


@pytest.fixture
def test_image(tmp_path: Path) -> Path:
    """Create a simple test image."""
    img_path = tmp_path / "test_input.png"
    img = Image.new("RGB", (100, 100), "white")
    pixels = img.load()
    for y in range(100):
        for x in range(100):
            val = int(255 * (1 - (x + y) / 200))
            if 25 < x < 75 and 25 < y < 75:
                val = int(val * 0.3)
            pixels[x, y] = (val, val, val)
    img.save(img_path)
    return img_path


_USER_PROFILE = (
    "  bed:\n"
    "    size_mm: [300.0, 210.0]\n"
    "  feed:\n"
    "    travel_mm_s: 80.0\n"
    "    draw_mm_s: 30.0\n"
    "    z_mm_s: 12.0\n"
    "  pen:\n"
    "    z_up: 6.0\n"
    "    z_down: 0.5\n"
)


class TestCLI:
    def test_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "penpath" in result.output
        assert "config" in result.output

    def test_version(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "penpath" in result.output
        assert "0.1.0" in result.output

    def test_no_args_shows_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, [])
        assert result.exit_code == 0
        assert "Usage:" in result.output

    def test_config_show(self, runner: CliRunner, temp_config_dir: Path) -> None:
        result = runner.invoke(main, ["config", "show"])
        assert result.exit_code == 0
        assert "Config file:" in result.output
        assert "Default pen: fine" in result.output
        assert "Default paper: a4" in result.output
        assert "Pens:" in result.output
        assert "Papers:" in result.output

    def test_config_show_with_custom_path(self, runner: CliRunner, temp_config_dir: Path) -> None:
        config_path = temp_config_dir / "custom.toml"
        config_path.write_text("""
default_pen = "bold"
default_paper = "a3"
""")
        result = runner.invoke(main, ["config", "show", "--path", str(config_path)])
        assert result.exit_code == 0
        assert "Default pen: bold" in result.output
        assert "Default paper: a3" in result.output

    def test_config_init(self, runner: CliRunner, temp_config_dir: Path) -> None:
        config_path = temp_config_dir / "config.toml"
        result = runner.invoke(main, ["config", "init", "--path", str(config_path)])
        assert result.exit_code == 0
        assert config_path.exists()
        assert "Created config file" in result.output

    def test_config_init_existing_without_force(
        self, runner: CliRunner, temp_config_dir: Path
    ) -> None:
        config_path = temp_config_dir / "config.toml"
        config_path.write_text("default_pen = 'fine'")
        result = runner.invoke(main, ["config", "init", "--path", str(config_path)], input="n\n")
        assert result.exit_code == 1
        assert "Overwrite" in result.output

    def test_config_init_existing_with_force(
        self, runner: CliRunner, temp_config_dir: Path
    ) -> None:
        config_path = temp_config_dir / "config.toml"
        config_path.write_text("default_pen = 'fine'")
        result = runner.invoke(main, ["config", "init", "--path", str(config_path), "--force"])
        assert result.exit_code == 0
        assert "Created config file" in result.output

    def test_config_path(self, runner: CliRunner, temp_config_dir: Path) -> None:
        result = runner.invoke(main, ["config", "path"])
        assert result.exit_code == 0
        assert str(temp_config_dir / "config.toml") in result.output

    def test_config_edit_creates_if_missing(
        self, runner: CliRunner, temp_config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_path = temp_config_dir / "config.toml"
        monkeypatch.setenv("EDITOR", "touch")
        result = runner.invoke(main, ["config", "edit", "--path", str(config_path)], input="y\n")
        assert result.exit_code == 0
        assert config_path.exists()

    def test_config_edit_existing(
        self, runner: CliRunner, temp_config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_path = temp_config_dir / "config.toml"
        config_path.write_text("default_pen = 'fine'")
        monkeypatch.setenv("EDITOR", "touch")
        result = runner.invoke(main, ["config", "edit", "--path", str(config_path)])
        assert result.exit_code == 0


class TestConvertCommand:
    """Tests for the convert command."""

    def test_convert_basic(self, runner: CliRunner, test_image: Path, tmp_path: Path) -> None:
        """Test basic convert command with --no-vpype."""
        output_path = tmp_path / "output.svg"
        args = ["convert", str(test_image), "-o", str(output_path), "--no-vpype"]
        result = runner.invoke(main, args)
        assert result.exit_code == 0
        assert output_path.exists()
        assert "SVG saved to:" in result.output

        # Verify SVG content
        svg_content = output_path.read_text()
        assert "<svg" in svg_content
        assert "</svg>" in svg_content
        assert 'viewBox="0 0 210 297"' in svg_content
        assert 'id="layer1"' in svg_content  # Layer for the used pen

    def test_convert_positional_output(
        self, runner: CliRunner, test_image: Path, tmp_path: Path
    ) -> None:
        """The optional positional OUTPUT_PATH writes the SVG at the given path."""
        output_path = tmp_path / "positional.svg"
        result = runner.invoke(main, ["convert", str(test_image), str(output_path), "--no-vpype"])
        assert result.exit_code == 0
        assert output_path.exists()
        svg_content = output_path.read_text()
        assert "<svg" in svg_content
        assert "</svg>" in svg_content

    def test_convert_positional_and_option_land_on_same_file(
        self, runner: CliRunner, test_image: Path, tmp_path: Path
    ) -> None:
        """The positional form and -o/--output both write the requested file."""
        shared_path = tmp_path / "shared.svg"
        positional = runner.invoke(
            main, ["convert", str(test_image), str(shared_path), "--no-vpype"]
        )
        assert positional.exit_code == 0
        assert shared_path.exists()
        option = runner.invoke(
            main, ["convert", str(test_image), "-o", str(shared_path), "--no-vpype"]
        )
        assert option.exit_code == 0
        assert "<svg" in shared_path.read_text()

    def test_convert_conflicting_output_paths(
        self, runner: CliRunner, test_image: Path, tmp_path: Path
    ) -> None:
        """Different positional and -o paths are a usage error naming both."""
        positional_path = tmp_path / "a.svg"
        option_path = tmp_path / "b.svg"
        result = runner.invoke(
            main,
            [
                "convert",
                str(test_image),
                str(positional_path),
                "-o",
                str(option_path),
                "--no-vpype",
            ],
        )
        assert result.exit_code == 2
        assert "Conflicting output paths" in result.output
        assert str(positional_path) in result.output
        assert str(option_path) in result.output
        assert not positional_path.exists()
        assert not option_path.exists()

    def test_convert_same_output_path_from_both_forms(
        self, runner: CliRunner, test_image: Path, tmp_path: Path
    ) -> None:
        """Giving the same path both ways is accepted."""
        output_path = tmp_path / "same.svg"
        result = runner.invoke(
            main,
            ["convert", str(test_image), str(output_path), "-o", str(output_path), "--no-vpype"],
        )
        assert result.exit_code == 0
        assert output_path.exists()

    def test_convert_help_shows_optional_positional_output(self, runner: CliRunner) -> None:
        """--help documents INPUT_PATH [OUTPUT_PATH]."""
        result = runner.invoke(main, ["convert", "--help"])
        assert result.exit_code == 0
        assert "INPUT_PATH [OUTPUT_PATH]" in result.output

    def test_convert_with_filters(
        self, runner: CliRunner, test_image: Path, tmp_path: Path
    ) -> None:
        """Test convert with explicit filters."""
        output_path = tmp_path / "output.svg"
        args = [
            "convert",
            str(test_image),
            "-o",
            str(output_path),
            "--no-vpype",
            "-f",
            "grayscale",
            "-f",
            "threshold:level=128",
        ]
        result = runner.invoke(main, args)
        assert result.exit_code == 0
        assert output_path.exists()

    def test_convert_with_pen_paper(
        self, runner: CliRunner, test_image: Path, tmp_path: Path
    ) -> None:
        """Test convert with custom pen and paper."""
        output_path = tmp_path / "output.svg"
        args = [
            "convert",
            str(test_image),
            "-o",
            str(output_path),
            "--no-vpype",
            "--pen",
            "bold",
            "--paper",
            "a3",
        ]
        result = runner.invoke(main, args)
        assert result.exit_code == 0
        assert output_path.exists()

    def test_convert_with_builtin_palette_draws_the_nearest_pen(
        self, runner: CliRunner, test_image: Path, tmp_path: Path
    ) -> None:
        """A palette splits by colour; this greyscale image's dark pixels pick black."""
        output_path = tmp_path / "palette.svg"
        result = runner.invoke(
            main,
            [
                "convert",
                str(test_image),
                "-o",
                str(output_path),
                "--no-vpype",
                "-s",
                "seed=42",
                "--palette",
                "stabilo_88",
            ],
        )
        assert result.exit_code == 0, result.output
        svg = output_path.read_text()
        assert 'inkscape:label="stabilo_88_black"' in svg
        assert 'stroke="#000000"' in svg
        assert "stabilo_88_yellow" not in svg
        assert svg.count('inkscape:groupmode="layer"') >= 1  # unused pens get no layer
        assert 'id="layer1"' in svg

    def test_convert_with_inline_palette_keeps_user_order(
        self, runner: CliRunner, test_image: Path, tmp_path: Path
    ) -> None:
        output_path = tmp_path / "inline.svg"
        result = runner.invoke(
            main,
            [
                "convert",
                str(test_image),
                "-o",
                str(output_path),
                "--no-vpype",
                "-s",
                "seed=42",
                "--palette",
                "red=0.5,#FF0000;blue=0.4,#0000FF",
            ],
        )
        assert result.exit_code == 0, result.output
        svg = output_path.read_text()
        assert 'inkscape:label="red"' in svg
        assert 'stroke="#FF0000"' in svg
        assert "blue" not in svg

    def test_convert_pen_and_palette_is_a_clear_error(
        self, runner: CliRunner, test_image: Path, tmp_path: Path
    ) -> None:
        output_path = tmp_path / "conflict.svg"
        result = runner.invoke(
            main,
            [
                "convert",
                str(test_image),
                "-o",
                str(output_path),
                "--pen",
                "fine",
                "--palette",
                "stabilo_88",
            ],
        )
        assert result.exit_code == 2
        assert "mutually exclusive" in result.output
        assert not output_path.exists()

    def test_convert_invalid_input(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test convert with non-existent input file."""
        output_path = tmp_path / "output.svg"
        result = runner.invoke(main, ["convert", "nonexistent.png", "-o", str(output_path)])
        assert result.exit_code != 0
        assert "not found" in result.output.lower() or "error" in result.output.lower()

    def test_convert_invalid_pen(self, runner: CliRunner, test_image: Path, tmp_path: Path) -> None:
        """Test convert with invalid pen preset."""
        output_path = tmp_path / "output.svg"
        args = [
            "convert",
            str(test_image),
            "-o",
            str(output_path),
            "--no-vpype",
            "--pen",
            "nonexistent",
        ]
        result = runner.invoke(main, args)
        assert result.exit_code != 0
        assert "unknown pen" in result.output.lower()


class TestPaletteResolution:
    def test_inline_palette_resolves_to_ordered_pens(self) -> None:
        from penpath.cli.commands.convert import _resolve_palette

        palette = _resolve_palette("first=0.5,#FF0000;second=0.4,#0000FF")
        assert palette.name == "inline"
        assert [pen.name for pen in palette.pens] == ["first", "second"]
        assert [pen.width_mm for pen in palette.pens] == [0.5, 0.4]
        assert [pen.color for pen in palette.pens] == ["#FF0000", "#0000FF"]

    def test_bad_inline_palette_is_a_clear_error(self) -> None:
        from penpath.cli.commands.convert import _resolve_palette

        with pytest.raises(click.BadParameter, match="NAME=WIDTH,#HEX"):
            _resolve_palette("first")


class TestInfoCommand:
    """Tests for the info command."""

    def test_info_pens(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["info", "pens"])
        assert result.exit_code == 0
        assert "fine" in result.output
        assert "bold" in result.output
        assert "builtin" in result.output
        assert "config" in result.output

    def test_info_pens_json(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["info", "pens", "--format", "json"])
        assert result.exit_code == 0
        import json

        data = json.loads(result.output)
        assert "builtin_pens" in data
        assert "config_pens" in data

    def test_info_papers(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["info", "papers"])
        assert result.exit_code == 0
        assert "a4" in result.output
        assert "a3" in result.output

    def test_info_palettes_lists_pens_in_drawing_order(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["info", "palettes", "--format", "json"])
        assert result.exit_code == 0, result.output
        import json

        data = json.loads(result.output)
        assert [p["name"] for p in data["builtin_palettes"]] == ["stabilo_88"]
        rows = data["palette_pens"]
        assert len(rows) == 12
        assert [row["order"] for row in rows] == list(range(1, 13))
        assert [row["name"] for row in rows][:3] == [
            "stabilo_88_yellow",
            "stabilo_88_cyan",
            "stabilo_88_light_blue",
        ]
        assert [row["name"] for row in rows][-1] == "stabilo_88_green"
        assert all(row["width_mm"] == 0.4 for row in rows)

    def test_info_palettes_table(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["info", "palettes", "--format", "table"])
        assert result.exit_code == 0, result.output
        assert "stabilo_88" in result.output
        assert "stabilo_88_yellow" in result.output
        assert "stabilo_88_green" in result.output

    def test_info_palettes_yaml(self, runner: CliRunner) -> None:
        import yaml

        result = runner.invoke(main, ["info", "palettes", "--format", "yaml"])
        assert result.exit_code == 0, result.output
        data = yaml.safe_load(result.output)
        assert [p["name"] for p in data["builtin_palettes"]] == ["stabilo_88"]
        assert [row["name"] for row in data["palette_pens"]][:3] == [
            "stabilo_88_yellow",
            "stabilo_88_cyan",
            "stabilo_88_light_blue",
        ]

    def test_info_pfms(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["info", "pfms"])
        assert result.exit_code == 0
        assert "sketch_lines" in result.output

    def test_info_profiles_marks_builtin_and_user_sources(
        self, runner: CliRunner, temp_config_dir: Path
    ) -> None:
        (temp_config_dir / "profiles.yaml").write_text(
            "shop_plotter:\n  description: The small plotter in the shop\n" + _USER_PROFILE,
            encoding="utf-8",
        )

        result = runner.invoke(main, ["info", "profiles"])
        assert result.exit_code == 0, result.output
        assert "generic" in result.output
        assert "built-in" in result.output
        assert "shop_plotter" in result.output
        assert "user" in result.output
        assert "small" in result.output

    def test_info_profiles_json_reports_bed_feeds_and_user_override(
        self, runner: CliRunner, temp_config_dir: Path
    ) -> None:
        (temp_config_dir / "profiles.yaml").write_text(
            "generic:\n"
            "  description: My own generic machine\n"
            "  bed:\n    size_mm: [300.0, 200.0]\n"
            "  feed:\n    travel_mm_s: 120.0\n    draw_mm_s: 40.0\n"
            "  pen:\n    z_up: 7.0\n    z_down: 1.0\n"
            + "shop_plotter:\n  description: The small plotter\n"
            + _USER_PROFILE,
            encoding="utf-8",
        )

        result = runner.invoke(main, ["info", "profiles", "--format", "json"])
        assert result.exit_code == 0, result.output
        import json

        data = json.loads(result.output)
        rows = {row["name"]: row for row in data["profiles"]}
        assert list(rows) == ["generic", "shop_plotter"]
        assert rows["generic"]["source"] == "user"
        assert rows["generic"]["description"] == "My own generic machine"
        assert rows["generic"]["bed_width_mm"] == 300.0
        assert rows["generic"]["bed_height_mm"] == 200.0
        assert rows["generic"]["travel_mm_s"] == 120.0
        assert rows["shop_plotter"]["source"] == "user"
        assert rows["shop_plotter"]["bed_height_mm"] == 210.0
        assert rows["shop_plotter"]["z_mm_s"] == 12.0

    def test_info_profiles_broken_user_file_reports_error(
        self, runner: CliRunner, temp_config_dir: Path
    ) -> None:
        (temp_config_dir / "profiles.yaml").write_text(
            "shop_plotter:\n  bed: [\n", encoding="utf-8"
        )

        result = runner.invoke(main, ["info", "profiles"])
        assert result.exit_code != 0
        assert "Invalid YAML" in result.output
        assert "Traceback" not in result.output

    def test_info_filters(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["info", "filters"])
        assert result.exit_code == 0
        assert "grayscale" in result.output
        assert "threshold" in result.output

    def test_info_config(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["info", "config"])
        assert result.exit_code == 0
        assert "default_pen" in result.output
        assert "default_paper" in result.output

    def test_info_image(self, runner: CliRunner, test_image: Path) -> None:
        result = runner.invoke(main, ["info", "image", str(test_image)])
        assert result.exit_code == 0
        assert "100" in result.output  # Image dimensions
        assert "RGB" in result.output or "L" in result.output


class TestMainModule:
    CWD = (
        "/home/paperclip/.paperclip/instances/default/projects/"
        "f76284ac-2a49-40a6-b858-fb4e88a04f17/8629db6d-47e6-45d0-965d-2befba253fd7/penpath"
    )

    def test_main_module_execution(self) -> None:
        import subprocess

        result = subprocess.run(
            ["python", "-m", "penpath", "--help"],
            capture_output=True,
            text=True,
            cwd=self.CWD,
        )
        assert result.returncode == 0
        assert "penpath" in result.stdout

    def test_penpath_command(self) -> None:
        import subprocess

        result = subprocess.run(
            ["penpath", "--help"],
            capture_output=True,
            text=True,
            cwd=self.CWD,
        )
        assert result.returncode == 0
        assert "penpath" in result.stdout
