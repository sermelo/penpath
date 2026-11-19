"""Config command group for penpath."""

from pathlib import Path

import click

from penpath.cli.config import Config, get_config_path, load_config, save_config


@click.group(name="config")
def config_group() -> None:
    """Manage penpath configuration."""


@config_group.command(name="show")
@click.option("--path", type=click.Path(path_type=str), help="Path to config file")
def config_show(path: str | None) -> None:
    """Show the current configuration."""
    config_path = path or str(get_config_path())
    config = load_config(Path(config_path) if path else None)

    click.echo(f"Config file: {config_path}")
    click.echo(f"Exists: {Path(config_path).exists()}")
    click.echo("")
    click.echo(f"Default pen: {config.default_pen}")
    click.echo(f"Default paper: {config.default_paper}")
    click.echo(f"Output dir: {config.output_dir}")
    click.echo("")
    click.echo("Pens:")
    for name, pen in config.pens.items():
        click.echo(f"  {name}: width={pen.width}mm, color={pen.color}, opacity={pen.opacity}")
    click.echo("")
    click.echo("Papers:")
    for name, paper in config.papers.items():
        click.echo(f"  {name}: {paper.width}x{paper.height}mm, margin={paper.margin}mm")


@config_group.command(name="init")
@click.option("--force", "-f", is_flag=True, help="Overwrite existing config file")
@click.option("--path", type=click.Path(path_type=str), help="Path to config file")
def config_init(force: bool, path: str | None) -> None:
    """Initialize a new configuration file with defaults."""
    config_path = Path(path) if path else get_config_path()

    if config_path.exists() and not force:
        click.confirm(f"Config file {config_path} exists. Overwrite?", abort=True)

    config_path.parent.mkdir(parents=True, exist_ok=True)
    save_config(Config(), config_path)
    click.echo(f"Created config file at {config_path}")


@config_group.command(name="edit")
@click.option("--path", type=click.Path(path_type=str), help="Path to config file")
def config_edit(path: str | None) -> None:
    """Open the configuration file in the default editor."""
    import os
    import subprocess

    config_path = Path(path) if path else get_config_path()

    if not config_path.exists():
        click.confirm(f"Config file {config_path} does not exist. Create it?", abort=True)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        save_config(Config(), config_path)

    editor = os.environ.get("EDITOR", "vi")
    try:
        subprocess.run([editor, str(config_path)], check=True)
    except subprocess.CalledProcessError as e:
        click.echo(f"Editor exited with code {e.returncode}", err=True)
        raise click.Abort() from e
    except FileNotFoundError:
        click.echo(f"Editor '{editor}' not found. Set EDITOR environment variable.", err=True)
        raise click.Abort() from None

    click.echo(f"Edited config file at {config_path}")


@config_group.command(name="path")
def config_path() -> None:
    """Show the path to the configuration file."""
    click.echo(str(get_config_path()))


__all__ = ["config_group"]
