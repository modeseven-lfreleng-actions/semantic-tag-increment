# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 The Linux Foundation

"""
Increment command implementation.

Holds the increment pipeline behind the CLI's default command:
input validation, the increment itself, and result reporting.
Separated from :mod:`cli_interface` so the Typer option surface and
the operation it drives can be read (and tested) independently.
"""

import logging
import os
import re
from dataclasses import dataclass

import typer

from .exceptions import ErrorReporter
from .git_operations import GitOperations
from .incrementer import VersionIncrementer
from .io_operations import IOOperations
from .logging_config import LoggingConfig
from .modes import ModeHelper, ModeValidator, OperationMode
from .parser import SemanticVersion

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IncrementRequest:
    """Bundle of parameters describing a single increment operation."""

    mode: OperationMode
    tag: str
    increment: str
    prerelease_type: str | None
    check_conflicts: bool
    output_format: str
    path: str
    preserve_metadata: bool
    fetch_timeout: int


def increment_version(
    tag: str,
    increment: str = "dev",
    prerelease_type: str | None = None,
    check_conflicts: bool = True,
    output_format: str = "full",
    suppress_cli_logging: bool = False,
    path: str = ".",
    preserve_metadata: bool = False,
    fetch_timeout: int = 120,
) -> None:
    """
    Increment a semantic version tag.

    This function takes an explicit semantic version tag and increments it
    according to the specified increment type.
    """
    request = IncrementRequest(
        mode=OperationMode.STRING,  # Force string mode (only supported mode)
        tag=tag,
        increment=increment,
        prerelease_type=prerelease_type,
        check_conflicts=check_conflicts,
        output_format=output_format,
        path=path,
        preserve_metadata=preserve_metadata,
        fetch_timeout=fetch_timeout,
    )

    _validate_increment_inputs(request)
    _configure_increment_logging(suppress_cli_logging)
    result = _process_version_increment(request)
    _output_increment_results(result, request.output_format)

    logger.info("Version increment completed successfully")


def _validate_increment_inputs(request: IncrementRequest) -> None:
    """Validate all inputs for the increment command."""
    ModeValidator.validate_mode_inputs(
        request.mode, request.tag, request.path, request.check_conflicts
    )

    # Basic input validation
    if not request.increment or not request.increment.strip():
        ErrorReporter.log_and_raise_validation_error(
            "Increment type cannot be empty"
        )

    valid_formats = ["full", "numeric", "both"]
    if request.output_format not in valid_formats:
        ErrorReporter.log_and_raise_validation_error(
            f"Invalid output format: {request.output_format}. Valid formats: {', '.join(valid_formats)}"
        )

    # Validate prerelease type if provided
    if (
        request.prerelease_type is not None
        and not request.prerelease_type.strip()
    ):
        ErrorReporter.log_and_raise_validation_error(
            "Prerelease type cannot be empty if provided"
        )

    if request.prerelease_type and not re.fullmatch(
        r"[a-zA-Z0-9.-]+", request.prerelease_type
    ):
        ErrorReporter.log_and_raise_validation_error(
            "Prerelease type must contain only alphanumeric characters, hyphens, and dots"
        )

    effective_path = ModeHelper.get_effective_path(request.mode, request.path)
    if not os.path.exists(effective_path):
        ErrorReporter.log_and_raise_validation_error(
            f"Path directory does not exist: {effective_path}"
        )

    if not os.path.isdir(effective_path):
        ErrorReporter.log_and_raise_validation_error(
            f"Path is not a directory: {effective_path}"
        )


def _configure_increment_logging(suppress_cli_logging: bool) -> None:
    """Configure logging for the increment operation."""
    if suppress_cli_logging and IOOperations.is_github_actions():
        LoggingConfig.set_module_level(
            "semantic_tag_increment", logging.WARNING
        )


def _process_version_increment(
    request: IncrementRequest,
) -> dict[str, SemanticVersion]:
    """Process the version increment operation."""
    ModeHelper.log_mode_operation(request.mode, request.tag, request.path)

    effective_path = ModeHelper.get_effective_path(request.mode, request.path)

    original_version = SemanticVersion.parse(request.tag)
    logger.info(f"Using version: {original_version} from input tag")

    increment_type = VersionIncrementer.determine_increment_type(
        request.increment
    )
    logger.info(f"Increment type: {increment_type.value}")

    # Get existing tags if conflict checking is enabled
    should_check_tags = ModeHelper.should_check_git_tags(
        request.mode, request.check_conflicts
    )
    existing_tags: set[str] = (
        GitOperations.get_existing_tags(
            effective_path, timeout=request.fetch_timeout
        )
        if should_check_tags
        else set()
    )

    incrementer = VersionIncrementer(
        existing_tags, preserve_metadata=request.preserve_metadata
    )
    incremented_version = incrementer.increment(
        original_version, increment_type, request.prerelease_type
    )

    _log_operation_details(original_version, incremented_version, existing_tags)

    return {
        "original_version": original_version,
        "incremented_version": incremented_version,
    }


def _output_increment_results(
    result: dict[str, SemanticVersion], output_format: str
) -> None:
    """Output results in the specified format."""
    incremented_version = result["incremented_version"]

    # Generate output versions
    full_version = incremented_version.to_string(include_prefix=True)
    numeric_version = incremented_version.numeric_version()

    # Output based on format
    if output_format == "full":
        typer.echo(full_version)
    elif output_format == "numeric":
        typer.echo(numeric_version)
    elif output_format == "both":
        typer.echo(f"Full version:    {full_version}")
        typer.echo(f"Numeric version: {numeric_version}")

    # Write GitHub Actions outputs if in GitHub Actions context
    if IOOperations.is_github_actions():
        IOOperations.write_outputs_to_github(full_version, numeric_version)


def _log_operation_details(
    original: SemanticVersion,
    incremented: SemanticVersion,
    existing_tags: set[str],
) -> None:
    """Log detailed information about the increment operation."""
    logger.info(f"Original version: {original}")
    logger.info(f"Next version: {incremented}")

    # Only log conflict check if there were actually tags to check
    if existing_tags:
        logger.info(f"Checked {len(existing_tags)} existing tags for conflicts")

    if original.is_prerelease():
        logger.debug(
            f"Original prerelease identifiers: {original.get_prerelease_identifiers()}"
        )
        numeric_components = original.find_numeric_prerelease_components()
        if numeric_components:
            logger.debug(
                f"Found numeric prerelease components: {numeric_components}"
            )

    if incremented.is_prerelease():
        logger.debug(
            f"New prerelease identifiers: {incremented.get_prerelease_identifiers()}"
        )
