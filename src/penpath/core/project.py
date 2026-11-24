"""Project file persistence for penpath.

Provides YAML load/save functionality for Project models with round-trip safety
and human-readable output including comments.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from penpath.core.models import Project

PROJECT_FILE_VERSION = 1


class ProjectLoadError(Exception):
    """Raised when a project file cannot be loaded or validated."""

    pass


class ProjectSaveError(Exception):
    """Raised when a project file cannot be saved."""

    pass


def _dump_yaml_value(value: Any, indent: int = 0) -> list[str]:
    """Dump a YAML value as lines with proper indentation."""
    lines: list[str] = []
    prefix = "  " * indent

    if value is None:
        lines.append(f"{prefix}null")
    elif isinstance(value, bool):
        lines.append(f"{prefix}{str(value).lower()}")
    elif isinstance(value, (int, float)):
        lines.append(f"{prefix}{value}")
    elif isinstance(value, str):
        # Quote strings that need it
        if value.startswith("#") or ":" in value or value in ("true", "false", "null", "~"):
            lines.append(f'{prefix}"{value}"')
        else:
            lines.append(f"{prefix}{value}")
    elif isinstance(value, dict):
        for k, v in value.items():
            lines.append(f"{prefix}{k}:")
            lines.extend(_dump_yaml_value(v, indent + 1))
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                lines.append(f"{prefix}-")
                for k, v in item.items():
                    lines.append(f"{prefix}  {k}:")
                    lines.extend(_dump_yaml_value(v, indent + 2))
            else:
                item_lines = _dump_yaml_value(item, 0)
                lines.append(f"{prefix}- {item_lines[0].lstrip()}")
    else:
        # Fallback to yaml.dump for complex types
        dumped = yaml.dump(value, default_flow_style=True).strip()
        lines.append(f"{prefix}{dumped}")

    return lines


def _add_yaml_comments(data: dict[str, Any], palette_name: str | None = None) -> str:
    """Generate YAML string with comments for a project dictionary."""
    lines: list[str] = []

    def add_section(comment: str, key: str, value: Any, indent: int = 0) -> None:
        prefix = "  " * indent
        if comment:
            lines.append(f"{prefix}# {comment}")
        if isinstance(value, dict):
            if not value:
                lines.append(f"{prefix}{key}: {{}}")
            else:
                lines.append(f"{prefix}{key}:")
                for k, v in value.items():
                    add_section("", k, v, indent + 1)
        elif isinstance(value, list):
            if not value:
                lines.append(f"{prefix}{key}: []")
            else:
                lines.append(f"{prefix}{key}:")
                for item in value:
                    if isinstance(item, dict):
                        if not item:
                            lines.append(f"{prefix}  - {{}}")
                        else:
                            lines.append(f"{prefix}  -")
                            for k, v in item.items():
                                add_section("", k, v, indent + 2)
                    else:
                        dumped = _dump_yaml_value(item, 0)[0].lstrip()
                        lines.append(f"{prefix}  - {dumped}")
        else:
            dumped = _dump_yaml_value(value, 0)[0].lstrip()
            lines.append(f"{prefix}{key}: {dumped}")

    # Add header comment
    lines.append("# penpath project file")
    lines.append(f"# version: {PROJECT_FILE_VERSION}")
    lines.append("")

    # Version field
    add_section("Project file format version", "version", data.get("version", PROJECT_FILE_VERSION))

    # Metadata
    metadata = data.get("metadata", {})
    if metadata:
        lines.append("")
        add_section("Project metadata", "metadata", metadata)

    # Image
    image = data.get("image", {})
    if image:
        lines.append("")
        add_section("Input image configuration", "image", image)

    # Paper
    paper = data.get("paper", {})
    if paper:
        lines.append("")
        add_section("Paper configuration", "paper", paper)

    # Pen
    pen = data.get("pen", {})
    if pen:
        lines.append("")
        add_section("Pen configuration", "pen", pen)

    # Palette (a built-in name, or an explicit ordered pen list)
    if palette_name:
        lines.append("")
        add_section("Built-in palette (drawing order)", "palette", palette_name)
    elif data.get("pens"):
        lines.append("")
        add_section("Ordered pens (drawing order)", "pens", data["pens"])

    # PFM
    pfm = data.get("pfm", {})
    if pfm:
        lines.append("")
        add_section("Pen Follower Module (PFM) configuration", "pfm", pfm)

    # Output
    output_path = data.get("output_path")
    if output_path:
        lines.append("")
        add_section("Output SVG file path", "output_path", output_path)

    return "\n".join(lines)


def _resolve_palette_yaml(data: dict[str, Any]) -> dict[str, Any]:
    """Expand a YAML ``palette:`` name to pens and enforce pen exclusivity."""
    selected = [
        key
        for key in ("pen", "palette", "pens")
        if key in data and data[key] not in (None, "", [], {})
    ]
    if len(selected) > 1:
        raise ProjectLoadError(
            "Project sets mutually exclusive pen fields: "
            + ", ".join(selected)
            + ". Use only one of 'pen', 'palette' or 'pens'"
        )

    if not data.get("palette"):
        return data

    name = data["palette"]
    if not isinstance(name, str):
        raise ProjectLoadError("'palette' must be a built-in palette name")

    from penpath.presets.palettes import get_palette

    try:
        palette = get_palette(name)
    except ValueError as e:
        raise ProjectLoadError(f"Unknown palette: {name}") from e

    resolved = dict(data)
    resolved["pens"] = [pen.model_dump(mode="json") for pen in palette.pens]
    resolved["palette_name"] = palette.name
    del resolved["palette"]
    return resolved


def load_yaml(path: Path) -> Project:
    """Load and validate a project from a YAML file.

    Parameters
    ----------
    path : Path
        Path to the project YAML file.

    Returns
    -------
    Project
        Validated project model.

    Raises
    ------
    ProjectLoadError
        If the file cannot be read, parsed, or validated.
    """
    if not path.exists():
        raise ProjectLoadError(f"Project file not found: {path}")
    if not path.is_file():
        raise ProjectLoadError(f"Path is not a file: {path}")

    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ProjectLoadError(f"Failed to parse YAML: {e}") from e

    if data is None:
        raise ProjectLoadError("Project file is empty")

    if not isinstance(data, dict):
        raise ProjectLoadError("Project file must contain a YAML mapping")

    # Handle version migration
    version = data.get("version", 1)
    if version != PROJECT_FILE_VERSION:
        # Placeholder for future version migration logic
        data = _migrate_project(data, version)

    try:
        project = Project.model_validate(_resolve_palette_yaml(data))
    except ValidationError as e:
        raise ProjectLoadError(f"Project validation failed: {e}") from e

    return project


def save_yaml(project: Project, path: Path) -> None:
    """Save a project to a YAML file with comments.

    Parameters
    ----------
    project : Project
        Project model to save.
    path : Path
        Path to write the project YAML file.

    Raises
    ------
    ProjectSaveError
        If the file cannot be written.
    """
    # Ensure parent directory exists
    path.parent.mkdir(parents=True, exist_ok=True)

    # Dump to dict with version and metadata
    data = project.model_dump(mode="json")
    data["version"] = PROJECT_FILE_VERSION

    # Add metadata if not present
    if "metadata" not in data:
        data["metadata"] = {
            "created": datetime.now(UTC).isoformat(),
            "modified": datetime.now(UTC).isoformat(),
            "version": "0.1.0",
        }

    try:
        yaml_str = _add_yaml_comments(data, project.palette_name)
        with path.open("w", encoding="utf-8") as f:
            f.write(yaml_str)
    except OSError as e:
        raise ProjectSaveError(f"Failed to write project file: {e}") from e


def _migrate_project(data: dict[str, Any], from_version: int) -> dict[str, Any]:
    """Migrate project data from an older version to the current version.

    Parameters
    ----------
    data : dict
        Project data dictionary.
    from_version : int
        Version number of the input data.

    Returns
    -------
    dict
        Migrated project data dictionary.
    """
    # Placeholder for future version migrations
    # Each migration step should transform data from version N to N+1
    migrated = data.copy()
    migrated["version"] = PROJECT_FILE_VERSION
    return migrated


__all__ = [
    "PROJECT_FILE_VERSION",
    "ProjectLoadError",
    "ProjectSaveError",
    "load_yaml",
    "save_yaml",
]
