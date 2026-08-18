# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 The Linux Foundation

"""
CLI interface module.

This module provides the clean command-line interface using Typer,
focused solely on semantic tag incrementing without project detection.
"""

import logging
from typing import Annotated

import typer

from .exceptions import ErrorReporter, handle_cli_errors
from .git_operations import GitOperations
from .increment_command import increment_version
from .incrementer import VersionIncrementer
from .logging_config import LoggingConfig
from .parser import SemanticVersion

logger = logging.getLogger(__name__)

app = typer.Typer(
    help="A Python tool to increment semantic version tags.",
    context_settings={"help_option_names": ["-h", "--help"]},
)


@app.callback(invoke_without_command=True)
@handle_cli_errors
def main_callback(
    ctx: typer.Context,
    debug: Annotated[
        bool,
        typer.Option("--debug", help="Enable debug logging output to terminal"),
    ] = False,
    tag: Annotated[
        str | None,
        typer.Option(
            "--tag", "-t", help="The existing semantic tag to be incremented"
        ),
    ] = None,
    increment: Annotated[
        str | None,
        typer.Option(
            "--increment",
            "-i",
            help="Increment type: major, minor, patch, prerelease/dev (defaults: dev for increment, prerelease for --suggest, not required with --validate)",
        ),
    ] = None,
    prerelease_type: Annotated[
        str | None,
        typer.Option(
            "--prerelease-type",
            "-p",
            help="Type of prerelease identifier (dev, alpha, beta, rc, etc.)",
        ),
    ] = None,
    check_conflicts: Annotated[
        bool,
        typer.Option(
            "--check-conflicts/--no-check-conflicts",
            help="Check for conflicts with existing git tags",
        ),
    ] = True,
    preserve_metadata: Annotated[
        bool,
        typer.Option(
            "--preserve-metadata/--no-preserve-metadata",
            help="Preserve build metadata during version increments",
        ),
    ] = False,
    output_format: Annotated[
        str,
        typer.Option(
            "--output-format",
            "-f",
            help="Output format: full (with prefix), numeric (without prefix), both",
        ),
    ] = "full",
    suppress_cli_logging: Annotated[
        bool,
        typer.Option(
            "--suppress-cli-logging/--no-suppress-cli-logging",
            help="Suppress CLI logging when running in GitHub Actions mode",
        ),
    ] = False,
    validate_only: Annotated[
        bool,
        typer.Option(
            "--validate",
            help="Validate the semantic version tag format without incrementing",
            show_default=False,
        ),
    ] = False,
    suggest: Annotated[
        bool,
        typer.Option(
            "--suggest",
            help="Show multiple possible next versions for the given increment type",
            show_default=False,
        ),
    ] = False,
    path: Annotated[
        str,
        typer.Option(
            "--path",
            help="Directory location for git operations",
        ),
    ] = ".",
    fetch_timeout: Annotated[
        int,
        typer.Option(
            "--fetch-timeout",
            help="Timeout in seconds for git remote fetch operations",
        ),
    ] = 120,
) -> None:
    """
    Semantic Tag Increment Tool

    A tool for incrementing semantic version tags with support
    for complex pre-release patterns and GitHub Actions integration.

    By default, increments a semantic version tag when --tag is provided.
    Use --validate to validate tag format without incrementing.
    Use --suggest to see multiple possible next versions.

    Examples:
        semantic-tag-increment --tag "v1.2.3" --increment "patch"
        semantic-tag-increment --tag "1.0.0" --increment "major"
        semantic-tag-increment --tag "v2.1.0" --increment "prerelease" --prerelease-type "alpha"
        semantic-tag-increment --tag "v1.2.3" --validate
        semantic-tag-increment --tag "v1.2.3" --increment "prerelease" --suggest
        semantic-tag-increment --tag "v1.2.3" --increment "patch" --fetch-timeout 60
    """
    LoggingConfig.setup_logging(debug, suppress_console=False)

    # If a subcommand is being invoked, don't run main logic
    if ctx.invoked_subcommand is not None:
        return

    # Handle validation-only mode
    if validate_only:
        if tag is None:
            ErrorReporter.log_and_raise_validation_error(
                "Tag parameter is required for validation"
            )
        validate_version_inline(tag)
        return

    if suggest:
        if tag is None:
            ErrorReporter.log_and_raise_validation_error(
                "Tag parameter is required for suggestions"
            )
        if increment is None:
            increment = "prerelease"  # Default for suggestions
        suggest_versions_inline(tag, increment, path, fetch_timeout)
        return

    # If no tag is provided and not validating or suggesting, show help
    if tag is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()

    # For increment mode, increment parameter is required
    if increment is None:
        increment = "dev"  # Default value

    increment_version(
        tag=tag,
        increment=increment,
        prerelease_type=prerelease_type,
        check_conflicts=check_conflicts,
        output_format=output_format,
        suppress_cli_logging=suppress_cli_logging,
        path=path,
        preserve_metadata=preserve_metadata,
        fetch_timeout=fetch_timeout,
    )


def validate_version_inline(tag: str) -> None:
    """
    Validate a semantic version tag and display results.

    Args:
        tag: The semantic version tag to validate
    """
    logger.info(f"Validating version: {tag}")
    version = SemanticVersion.parse(tag)

    typer.echo(f"✅ Valid semantic version: {version}")
    typer.echo(f"   Major:      {version.major}")
    typer.echo(f"   Minor:      {version.minor}")
    typer.echo(f"   Patch:      {version.patch}")

    if version.is_prerelease():
        typer.echo(f"   Pre-release: {version.prerelease}")
        identifiers = version.get_prerelease_identifiers()
        typer.echo(f"   Pre-release identifiers:   {identifiers}")

        numeric_components = version.find_numeric_prerelease_components()
        if numeric_components:
            typer.echo(f"   Numeric components:      {numeric_components}")

    if version.has_metadata():
        typer.echo(f"   Metadata:   {version.metadata}")

    if version.prefix:
        typer.echo(f"   Prefix:     {version.prefix}")

    logger.info("Version validation completed successfully")


def suggest_versions_inline(
    tag: str, increment: str, path: str = ".", fetch_timeout: int = 120
) -> None:
    """
    Suggest multiple possible next versions and display results.

    Args:
        tag: The current semantic tag
        increment: Increment type for suggestions
        path: Directory location for git operations
        fetch_timeout: Timeout in seconds for git remote fetch operations
    """
    logger.info(f"Generating suggestions for: {tag}")
    version = SemanticVersion.parse(tag)
    increment_type = VersionIncrementer.determine_increment_type(increment)

    existing_tags = GitOperations.get_existing_tags(path, timeout=fetch_timeout)
    incrementer = VersionIncrementer(existing_tags)

    suggestions = incrementer.suggest_next_version(version, increment_type)

    typer.echo(
        f"Suggestions for {increment_type.value} increment of {version}:"
    )
    for i, suggestion in enumerate(suggestions, 1):
        typer.echo(f"  {i}. {suggestion}")

    logger.info(f"Generated {len(suggestions)} suggestions")
