"""Guard: every ``penpath`` command in README.md must still run.

The README is read from the repository root. Only top-level commands in fenced
``bash`` blocks are extracted; indented lines belong to shell examples such as
the ``for`` loop and are out of scope, as are the pip/uv/git install lines and
``bash scripts/nightly.sh`` (they are not ``penpath`` commands). Commands piped
to ``jq`` are the one explicit skip: jq is an external tool we do not install.

vpype is deliberately left on PATH so the small synthetic photo exercises the
default export path too. The fixture is 120x90 px, so every convert stays fast
and the whole guard fits inside the existing CI budget.
"""

from __future__ import annotations

import re
import shlex
import shutil
from pathlib import Path
from typing import NamedTuple

import pytest
from click.testing import CliRunner
from PIL import Image

from penpath.cli.main import main
from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings
from penpath.core.image.pipeline import FilterPipeline
from penpath.core.models import ImageRef, Paper, Pen, Project, SketchLinesPFM
from penpath.core.project import save_yaml

_README = Path(__file__).resolve().parents[2] / "README.md"

# Only commands that need an external tool are skipped. The keys are normalised
# shlex output, so prose edits and trailing comments do not create drift. Any
# other new ``penpath`` command is run and must exit 0.
_SKIPPED: dict[str, str] = {
    "penpath evaluate photo.jpg plot.svg --json | jq {likeness, masked_likeness}": (
        "jq is an external tool"
    ),
    "penpath evaluate photo.jpg plot.svg --json | jq "
    "{likeness, masked_likeness, total: .machine_cost.total}": "jq is an external tool",
}

_REDIRECT = re.compile(r"^(?P<fd>2)?(?P<op>>>|>)(?P<target>.*)$")
_VALUE_OPTIONS = frozenset(
    {
        "-o",
        "--output",
        "-p",
        "--project",
        "-f",
        "--filter",
        "-s",
        "--pfm-setting",
        "--pen",
        "--palette",
        "--paper",
        "--pfm",
        "--style",
        "--max-resolution",
        "--background-threshold",
        "--background-method",
        "--saturation",
        "--dpi",
        "--config",
        "-c",
        "--vpype-path",
        "--profile",
        "--profiles",
        "--place",
        "--at",
        "--format",
    }
)


class ParsedCommand(NamedTuple):
    """One README command split into CLI arguments and shell redirections."""

    text: str
    argv: list[str]
    stdout_to: str | None
    stderr_to: str | None


def _bash_commands(text: str) -> list[str]:
    """Return top-level ``penpath`` commands from fenced bash blocks.

    Backslash continuations are joined. Leading whitespace is significant: an
    indented command is part of a shell example, not a standalone command.
    """
    commands: list[str] = []
    in_bash = False
    pending: list[str] = []
    for line in text.splitlines():
        if not in_bash:
            if line.strip() == "```bash":
                in_bash = True
            continue
        if line.strip() == "```":
            if pending:
                commands.append(" ".join(pending))
                pending = []
            in_bash = False
            continue
        if not line.strip() or (not line.startswith("penpath") and not pending):
            continue
        piece = line.strip()
        if piece.endswith("\\"):
            pending.append(piece[:-1].rstrip())
            continue
        pending.append(piece)
        commands.append(" ".join(pending))
        pending = []
    return commands


def _normalize(command: str) -> str:
    """Join shlex tokens so whitespace and trailing comments do not affect keys."""
    return " ".join(shlex.split(command, comments=True))


def _parse(command: str) -> ParsedCommand:
    """Strip the leading ``penpath`` and any shell redirections from a command."""
    tokens = shlex.split(command, comments=True)
    assert tokens and tokens[0] == "penpath", command
    argv: list[str] = []
    stdout_to: str | None = None
    stderr_to: str | None = None
    index = 1
    while index < len(tokens):
        token = tokens[index]
        match = _REDIRECT.match(token)
        if match:
            target = match.group("target")
            if not target:
                index += 1
                target = tokens[index]
            if match.group("fd") == "2":
                stderr_to = target
            else:
                stdout_to = target
        else:
            argv.append(token)
        index += 1
    return ParsedCommand(command, argv, stdout_to, stderr_to)


def _positionals(argv: list[str]) -> list[str]:
    """Return positional arguments, skipping values consumed by options."""
    values: list[str] = []
    index = 1
    while index < len(argv):
        token = argv[index]
        if token in _VALUE_OPTIONS:
            index += 2
        elif token.startswith("-"):
            index += 1
        else:
            values.append(token)
            index += 1
    return values


def _expected_output(parsed: ParsedCommand) -> str | None:
    """Return the file a command names, or None if it names no output file."""
    if parsed.stdout_to:
        return parsed.stdout_to
    for option in ("-o", "--output"):
        if option in parsed.argv:
            return parsed.argv[parsed.argv.index(option) + 1]
    values = _positionals(parsed.argv)
    if not values:
        return None
    if parsed.argv[0] == "convert":
        if "--project" in parsed.argv or "-p" in parsed.argv:
            return None
        if len(values) > 1:
            return values[1]
        return f"{Path(values[0]).stem}_plot.svg"
    if parsed.argv[0] == "gcode":
        return str(Path(values[0]).with_suffix(".gcode"))
    return None


def _seed_workspace(work: Path) -> None:
    """Create the small fixtures the README commands refer to."""
    image = Image.new("RGB", (120, 90), "white")
    pixels = image.load()
    for y in range(90):
        for x in range(120):
            value = int(255 * (1 - (x + y) / 210))
            if 30 < x < 90 and 20 < y < 70:
                value = int(value * 0.3)
            pixels[x, y] = (value, value, value)
    source = work / "seed.jpg"
    image.save(source, format="JPEG")
    for name in ("photo.jpg", "input.jpg"):
        shutil.copyfile(source, work / name)
    reference = work / "tests" / "fixtures" / "images" / "reference"
    reference.mkdir(parents=True)
    shutil.copyfile(source, reference / "photo.jpg")
    source.unlink()

    for name, output in (
        ("my_project.yaml", "plot.svg"),
        ("portrait.yaml", "portrait.svg"),
        ("batch.yaml", "batch.svg"),
    ):
        project = Project(
            image=ImageRef(path=Path("photo.jpg"), filters=FilterPipeline(), dpi=300),
            paper=Paper(name="a4", width_mm=210.0, height_mm=297.0),
            pen=Pen(name="fine", width_mm=0.3),
            pfm=SketchLinesPFM(settings=SketchLinesSettings(seed=42)),
            output_path=Path(output),
        )
        save_yaml(project, work / name)


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An isolated working directory: no repo files or developer config are touched."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("EDITOR", "true")
    _seed_workspace(tmp_path)
    return tmp_path


def _pregenerate(runner: CliRunner) -> None:
    """Create the SVGs the README reuses before the commands that consume them."""
    for argv in (
        ["convert", "photo.jpg", "-o", "plot.svg", "--quiet"],
        ["convert", "photo.jpg", "-o", "card.svg", "--paper", "170x170", "--quiet"],
        [
            "convert",
            "photo.jpg",
            "-o",
            "palette_plot.svg",
            "--palette",
            "stabilo_88",
            "-s",
            "seed=42",
            "--quiet",
        ],
    ):
        result = runner.invoke(main, argv)
        assert result.exit_code == 0, f"fixture setup failed: {argv}\n{result.output}"


def test_readme_commands_run(workspace: Path) -> None:
    """Every non-skipped ``penpath`` command in the README must exit 0."""
    runner = CliRunner()
    _pregenerate(runner)

    commands = _bash_commands(_README.read_text(encoding="utf-8"))
    assert commands, f"No penpath commands found in {_README}"
    normalized = {_normalize(command) for command in commands}
    assert set(_SKIPPED) <= normalized, "Stale README skip entry; remove it"

    executed = 0
    for command in commands:
        if _normalize(command) in _SKIPPED:
            continue
        parsed = _parse(command)
        result = runner.invoke(main, parsed.argv)
        assert result.exit_code == 0, f"README command failed: {command}\n{result.output}"
        if parsed.stdout_to is not None:
            (workspace / parsed.stdout_to).write_text(result.stdout, encoding="utf-8")
        if parsed.stderr_to is not None:
            (workspace / parsed.stderr_to).write_text(result.stderr, encoding="utf-8")
        output = _expected_output(parsed)
        if output is not None:
            assert (workspace / output).is_file(), f"README command wrote no {output}: {command}"
        executed += 1
    assert executed > 40


class TestReadmeCommandParsing:
    """Unit checks for the extraction and redirect handling used by the guard."""

    def test_extracts_top_level_commands_joins_continuations(self) -> None:
        text = "\n".join(
            [
                "```bash",
                "pip install penpath",
                "penpath convert photo.jpg -o art.svg \\",
                '  -f grayscale --pen "0.4,#000000,fineliner"',
                "for img in photos/*.jpg; do",
                '  penpath convert "$img" -o out.svg',
                "done",
                "```",
                "```yaml",
                "penpath convert ignored.yaml",
                "```",
            ]
        )
        commands = _bash_commands(text)
        assert len(commands) == 1
        assert _parse(commands[0]).argv == [
            "convert",
            "photo.jpg",
            "-o",
            "art.svg",
            "-f",
            "grayscale",
            "--pen",
            "0.4,#000000,fineliner",
        ]

    def test_normalize_keeps_quoted_hash_and_drops_trailing_comment(self) -> None:
        command = 'penpath preview plot.svg -o preview.png --paper-color "#FFFDD0"  # cream'
        assert _normalize(command) == (
            "penpath preview plot.svg -o preview.png --paper-color #FFFDD0"
        )

    def test_parse_strips_stdout_redirect_and_comment(self) -> None:
        parsed = _parse(
            "penpath gcode plot.svg --profile generic --dry-run > plot.gcode  # write it"
        )
        assert parsed.argv == ["gcode", "plot.svg", "--profile", "generic", "--dry-run"]
        assert parsed.stdout_to == "plot.gcode"
        assert parsed.stderr_to is None

    def test_parse_strips_stderr_redirect(self) -> None:
        parsed = _parse("penpath convert photo.jpg 2>convert.log")
        assert parsed.argv == ["convert", "photo.jpg"]
        assert parsed.stderr_to == "convert.log"
        assert parsed.stdout_to is None

    def test_expected_output_covers_named_default_and_redirected_files(self) -> None:
        assert _expected_output(_parse("penpath convert input.jpg output.svg")) == "output.svg"
        assert _expected_output(_parse("penpath convert input.jpg -o output.svg")) == "output.svg"
        assert _expected_output(_parse("penpath convert input.jpg")) == "input_plot.svg"
        assert _expected_output(_parse("penpath evaluate photo.jpg plot.svg")) is None
        assert _expected_output(_parse("penpath gcode plot.svg --profile generic")) == "plot.gcode"

    def test_skip_list_is_jq_only_and_matches_the_readme(self) -> None:
        normalized = {_normalize(command) for command in _bash_commands(_README.read_text())}
        assert set(_SKIPPED) <= normalized
        assert all("jq" in key for key in _SKIPPED)
