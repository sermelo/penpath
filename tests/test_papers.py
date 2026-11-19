"""Tests for penpath.presets.papers module."""

import pytest

from penpath.cli.config import PaperConfig
from penpath.presets.papers import (
    DEFAULT_PAPER,
    PAPER_PRESETS,
    get_paper,
    list_papers,
)


class TestPapersPresets:
    def test_default_paper_exists(self) -> None:
        assert DEFAULT_PAPER in PAPER_PRESETS

    def test_paper_presets_structure(self) -> None:
        for name, paper in PAPER_PRESETS.items():
            assert isinstance(paper, PaperConfig)
            assert paper.name == name
            assert paper.width > 0
            assert paper.height > 0
            assert paper.margin >= 0

    def test_expected_papers_present(self) -> None:
        expected = {"a4", "a3", "a5", "letter", "legal", "tabloid", "square_200", "square_300"}
        assert expected.issubset(set(PAPER_PRESETS.keys()))

    def test_a4_dimensions(self) -> None:
        paper = PAPER_PRESETS["a4"]
        assert paper.width == 210.0
        assert paper.height == 297.0

    def test_a3_dimensions(self) -> None:
        paper = PAPER_PRESETS["a3"]
        assert paper.width == 297.0
        assert paper.height == 420.0


class TestGetPaper:
    def test_get_existing_paper(self) -> None:
        paper = get_paper("a4")
        assert paper.name == "a4"
        assert paper.width == 210.0
        assert paper.height == 297.0

    def test_get_unknown_paper_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown paper preset: unknown"):
            get_paper("unknown")


class TestListPapers:
    def test_list_papers_sorted(self) -> None:
        papers = list_papers()
        assert papers == sorted(papers)
        assert "a4" in papers
        assert "a3" in papers
