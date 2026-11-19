"""End-to-end tests for penpath CLI."""

import tempfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from penpath.cli.main import main


class TestCLI:
    @pytest.fixture
    def runner(self) -> CliRunner:
        return CliRunner()

    @pytest.fixture
    def temp_config_dir(self, monkeypatch: pytest.MonkeyPatch) -> Path:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "penpath"
            config_dir.mkdir(parents=True, exist_ok=True)
            monkeypatch.setenv("XDG_CONFIG_HOME", str(config_dir.parent))
            yield config_dir

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


class TestMainModule:
    def test_main_module_execution(self) -> None:
        import subprocess

        result = subprocess.run(
            ["python", "-m", "penpath", "--help"],
            capture_output=True,
            text=True,
            cwd="/home/paperclip/.paperclip/instances/default/projects/f76284ac-2a49-40a6-b858-fb4e88a04f17/8629db6d-47e6-45d0-965d-2befba253fd7/penpath",
        )
        assert result.returncode == 0
        assert "penpath" in result.stdout

    def test_penpath_command(self) -> None:
        import subprocess

        result = subprocess.run(
            ["penpath", "--help"],
            capture_output=True,
            text=True,
            cwd="/home/paperclip/.paperclip/instances/default/projects/f76284ac-2a49-40a6-b858-fb4e88a04f17/8629db6d-47e6-45d0-965d-2befba253fd7/penpath",
        )
        assert result.returncode == 0
        assert "penpath" in result.stdout
