"""Tests for penpath.cli.config module."""

import tempfile
from pathlib import Path

import pytest

from penpath.cli.config import (
    DEFAULT_CONFIG,
    Config,
    PaperConfig,
    PenConfig,
    get_config_path,
    load_config,
    save_config,
)


class TestPenConfig:
    def test_pen_config_creation(self) -> None:
        pen = PenConfig(name="test", width=0.5, color="red", opacity=0.8)
        assert pen.name == "test"
        assert pen.width == 0.5
        assert pen.color == "red"
        assert pen.opacity == 0.8

    def test_pen_config_defaults(self) -> None:
        pen = PenConfig(name="test", width=0.5)
        assert pen.color == "black"
        assert pen.opacity == 1.0


class TestPaperConfig:
    def test_paper_config_creation(self) -> None:
        paper = PaperConfig(name="test", width=100.0, height=200.0, margin=5.0)
        assert paper.name == "test"
        assert paper.width == 100.0
        assert paper.height == 200.0
        assert paper.margin == 5.0

    def test_paper_config_default_margin(self) -> None:
        paper = PaperConfig(name="test", width=100.0, height=200.0)
        assert paper.margin == 0.0


class TestConfig:
    def test_default_config(self) -> None:
        config = Config()
        assert config.default_pen == "fine"
        assert config.default_paper == "a4"
        assert config.output_dir == "output"
        assert "fine" in config.pens
        assert "medium" in config.pens
        assert "bold" in config.pens
        assert "a4" in config.papers
        assert "a3" in config.papers
        assert "letter" in config.papers

    def test_get_pen(self) -> None:
        config = Config()
        pen = config.get_pen("fine")
        assert pen.name == "fine"
        assert pen.width == 0.3

    def test_get_pen_default(self) -> None:
        config = Config()
        pen = config.get_pen()
        assert pen.name == "fine"

    def test_get_pen_not_found(self) -> None:
        config = Config()
        with pytest.raises(ValueError, match="Pen 'unknown' not found"):
            config.get_pen("unknown")

    def test_get_paper(self) -> None:
        config = Config()
        paper = config.get_paper("a4")
        assert paper.name == "a4"
        assert paper.width == 210.0

    def test_get_paper_default(self) -> None:
        config = Config()
        paper = config.get_paper()
        assert paper.name == "a4"

    def test_get_paper_not_found(self) -> None:
        config = Config()
        with pytest.raises(ValueError, match="Paper 'unknown' not found"):
            config.get_paper("unknown")


class TestGetConfigPath:
    def test_get_config_path_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        path = get_config_path()
        assert path == Path.home() / ".config" / "penpath" / "config.toml"

    def test_get_config_path_xdg(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", "/custom/config")
        path = get_config_path()
        assert path == Path("/custom/config") / "penpath" / "config.toml"


class TestLoadConfig:
    def test_load_config_no_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "nonexistent.toml"
            config = load_config(config_path)
            assert config.default_pen == DEFAULT_CONFIG.default_pen
            assert config.default_paper == DEFAULT_CONFIG.default_paper

    def test_load_config_with_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text("""
default_pen = "bold"
default_paper = "a3"
output_dir = "custom_output"

[pens.custom]
width = 1.0
color = "blue"
opacity = 0.5

[papers.custom]
width = 300.0
height = 300.0
margin = 20.0
""")
            config = load_config(config_path)
            assert config.default_pen == "bold"
            assert config.default_paper == "a3"
            assert config.output_dir == "custom_output"
            assert "custom" in config.pens
            assert config.pens["custom"].width == 1.0
            assert config.pens["custom"].color == "blue"
            assert config.pens["custom"].opacity == 0.5
            assert "custom" in config.papers
            assert config.papers["custom"].width == 300.0
            assert config.papers["custom"].height == 300.0
            assert config.papers["custom"].margin == 20.0

    def test_load_config_preserves_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text("""
default_pen = "medium"
""")
            config = load_config(config_path)
            assert config.default_pen == "medium"
            assert config.default_paper == "a4"
            assert "fine" in config.pens
            assert "bold" in config.pens

    def test_load_config_invalid_toml(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text("invalid toml [[[")
            with pytest.raises(RuntimeError, match="Failed to parse config file"):
                load_config(config_path)


class TestSaveConfig:
    def test_save_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            config = Config(
                default_pen="bold",
                default_paper="a3",
                output_dir="test_output",
            )
            save_config(config, config_path)

            loaded = load_config(config_path)
            assert loaded.default_pen == "bold"
            assert loaded.default_paper == "a3"
            assert loaded.output_dir == "test_output"

    def test_save_config_creates_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "subdir" / "config.toml"
            config = Config()
            save_config(config, config_path)
            assert config_path.exists()
