"""NEXUS Command Line Interface."""

import click

from nexus.logging import configure_logging, get_logger

logger = get_logger(__name__)


@click.group()
@click.version_option(package_name="nexus")
def main() -> None:
    """NEXUS — Autonomous Homelab Operations Agent."""
    configure_logging()


@main.command()
def status() -> None:
    """Show NEXUS status."""
    click.echo("NEXUS status: initializing")


if __name__ == "__main__":
    main()
