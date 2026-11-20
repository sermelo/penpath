"""End-to-end tests for penpath CLI."""

import tempfile
from pathlib import Path

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
        assert "viewBox" in svg_content
        assert "pen-" in svg_content  # Layer for pen

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

    def test_convert_invalid_input(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test convert with non-existent input file."""
        output_path = tmp_path / "output.svg"
        result = runner.invoke(main, ["convert", "nonexistent.png", "-o", str(output_path)])
        assert result.exit_code != 0
        assert "not found" in result.output.lower() or "error" in result.output.lower()

    def test_convert_invalid_pen(
        self, runner: CliRunner, test_image: Path, tmp_path: Path
    ) -> None:
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

    def test_info_pfms(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["info", "pfms"])
        assert result.exit_code == 0
        assert "sketch_lines" in result.output

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
    CWD = ("/home/paperclip/.paperclip/instances/default/projects/"
           "f76284ac-2a49-40a6-b858-fb4e88a04f17/8629db6d-47e6-45d0-965d-2befba253fd7/penpath")

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
