"""CLI commands package for penpath."""

from penpath.cli.commands.compare import compare_cmd
from penpath.cli.commands.config_cmd import config_group
from penpath.cli.commands.convert import convert_cmd
from penpath.cli.commands.evaluate import evaluate_cmd
from penpath.cli.commands.info import info_group
from penpath.cli.commands.preview import preview_cmd

__all__ = [
    "compare_cmd",
    "config_group",
    "convert_cmd",
    "evaluate_cmd",
    "info_group",
    "preview_cmd",
]
