"""Main CLI entry point for penpath."""

import click

from penpath import __version__
from penpath.cli.commands.config_cmd import config_group


@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    invoke_without_command=True,
)
@click.version_option(version=__version__, prog_name="penpath")
@click.pass_context
def main(ctx: click.Context) -> None:
    """penpath - A CLI tool for generating pen plotter paths."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


main.add_command(config_group)


if __name__ == "__main__":
    main()
