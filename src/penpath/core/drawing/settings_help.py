"""Help text for PFM settings, read from their existing docstrings."""

from __future__ import annotations

import inspect

from pydantic import BaseModel


def _parameters_section(docstring: str) -> list[str]:
    """Return the lines of a numpydoc ``Parameters`` section, without its header."""
    lines = inspect.cleandoc(docstring).splitlines()
    for index in range(len(lines) - 1):
        if lines[index].strip() == "Parameters" and set(lines[index + 1].strip()) == {"-"}:
            return lines[index + 2 :]
    return []


def field_help(model: type[BaseModel]) -> dict[str, str]:
    """Read a settings model's numpydoc ``Parameters`` section into field help.

    Each documented field maps to its description with multi-line text joined
    by spaces. Fields without a doc entry are simply absent from the result,
    so a model with incomplete documentation never raises.

    Parameters
    ----------
    model : type[BaseModel]
        A Pydantic settings model whose class docstring uses numpydoc sections.

    Returns
    -------
    dict[str, str]
        Mapping of field name to its one-paragraph help text.
    """
    help_by_name: dict[str, str] = {}
    current_name: str | None = None
    description: list[str] = []

    def store_current() -> None:
        if current_name is not None:
            help_by_name[current_name] = " ".join(description)

    for line in _parameters_section(model.__doc__ or ""):
        stripped = line.strip()
        if not stripped:
            continue
        if not line.startswith((" ", "\t")):
            name, separator, _type = stripped.partition(" : ")
            if not separator:
                break
            store_current()
            current_name = name
            description = []
        elif current_name is not None:
            description.append(stripped)

    store_current()
    return help_by_name


__all__ = ["field_help"]
