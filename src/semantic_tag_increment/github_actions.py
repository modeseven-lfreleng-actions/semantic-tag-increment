# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 The Linux Foundation

"""
GitHub Actions integration module.

This module handles GitHub Actions specific logic and execution flow
for string-mode tag incrementing only.
"""

import logging
import time
from dataclasses import dataclass
from typing import TypedDict

from .app_context import GitHubActionsConfig
from .exceptions import handle_github_actions_errors
from .git_operations import GitOperations
from .incrementer import IncrementType, VersionIncrementer
from .io_operations import IOOperations
from .logging_config import LoggingConfig, SemanticLogger
from .modes import ModeValidator, OperationMode
from .parser import SemanticVersion
from .workflow_output import echo, group_end, group_start, notice

logger = logging.getLogger(__name__)


class IncrementResult(TypedDict):
    """Structured result returned by ``_execute_increment``."""

    original_version: SemanticVersion
    incremented_version: SemanticVersion
    increment_type: IncrementType
    existing_tags: set[str]


@dataclass(frozen=True)
class IncrementSettings:
    """Typed view of the GitHub Actions inputs that govern the increment."""

    check_tags: bool
    path: str
    preserve_metadata: bool
    fetch_timeout: int


class GitHubActionsRunner:
    """Handles GitHub Actions execution mode for string-based tag incrementing."""

    def __init__(self, debug_mode: bool = False):
        """
        Initialize GitHub Actions runner.

        Args:
            debug_mode: Enable debug mode
        """
        self.debug_mode: bool = debug_mode
        self._setup_logging()

    def _setup_logging(self) -> None:
        """Configure logging for GitHub Actions mode."""
        LoggingConfig.setup_logging(
            debug=self.debug_mode, suppress_console=not self.debug_mode
        )

        if not self.debug_mode:
            # Suppress excessive logging in non-debug mode
            LoggingConfig.set_module_level(
                "semantic_tag_increment", logging.WARNING
            )

    @handle_github_actions_errors
    def run(self) -> None:
        """Run in GitHub Actions mode."""
        start_time = time.time()
        SemanticLogger.operation_start(
            "github_actions_execution", {"debug_mode": self.debug_mode}
        )

        logger.info("Running in GitHub Actions mode")

        config = GitHubActionsConfig.get_inputs()
        self._validate_github_actions_inputs(config)

        self._print_startup_banner(config)

        SemanticLogger.operation_start(
            "version_increment",
            {
                "tag": config.get("tag"),
                "increment": config.get("increment", "dev"),
            },
        )

        result = self._execute_increment(config)

        SemanticLogger.operation_success(
            "version_increment",
            {
                "original": str(result["original_version"]),
                "incremented": str(result["incremented_version"]),
            },
        )

        # Output results and exit successfully
        self._output_results(result)
        self._print_success_banner()

        total_time = time.time() - start_time
        SemanticLogger.operation_success(
            "github_actions_execution",
            {"total_time_seconds": f"{total_time:.3f}"},
        )
        SemanticLogger.performance_metric(
            "github_actions_total_time", total_time * 1000, "ms"
        )

    def _validate_github_actions_inputs(
        self, config: dict[str, str | None]
    ) -> None:
        """Validate GitHub Actions inputs for string mode."""
        # Only string mode is supported
        operation_mode = OperationMode.STRING

        tag = config.get("tag")
        if not tag or not tag.strip():
            raise ValueError("String mode requires a non-empty 'tag' input")

        ModeValidator.validate_mode_inputs(
            operation_mode,
            tag,
            config.get("path"),
            True,  # check_tags parameter (not used in string mode)
        )

    def _print_startup_banner(self, config: dict[str, str | None]) -> None:
        """Print startup banner and configuration."""
        group_start("Semantic Tag Increment Configuration")
        echo("Semantic Tag Increment")
        echo("=" * 50)
        echo("Configuration:")
        echo("   Mode: string")
        echo(f"   Tag: {config.get('tag', 'Not specified')}")
        echo(f"   Increment: {config.get('increment', 'dev')}")
        if config.get("prerelease_type"):
            echo(f"   Prerelease Type: {config['prerelease_type']}")
        echo(f"   Path: {config.get('path', '.')}")
        echo(f"   Check Tags: {config.get('check_tags', 'true')}")
        echo(
            f"   Preserve Metadata: {config.get('preserve_metadata', 'false')}"
        )
        echo(f"   Fetch Timeout: {config.get('fetch_timeout', '120')} seconds")
        echo("=" * 50)
        group_end()
        echo()

    def _resolve_version_source(
        self, config: dict[str, str | None]
    ) -> tuple[SemanticVersion, IncrementType]:
        """
        Parse the source tag and the requested increment type.

        Args:
            config: Configuration dictionary

        Returns:
            The parsed source version and the increment type to apply.

        Raises:
            ValueError: If the 'tag' input is missing.
        """
        group_start("Version Source")
        tag = config.get("tag")
        if not tag:
            raise ValueError("Tag is required for string mode")

        original_version = SemanticVersion.parse(tag)
        echo("Version source: input tag")
        echo(f"Version: {original_version}")

        increment_str = config.get("increment", "dev")
        if increment_str is None:
            increment_str = "dev"
        increment_type = VersionIncrementer.determine_increment_type(
            increment_str
        )
        echo(f"Increment type: {increment_type.value}")
        group_end()

        return original_version, increment_type

    @staticmethod
    def _read_settings(config: dict[str, str | None]) -> IncrementSettings:
        """
        Coerce the raw string inputs into typed increment settings.

        Args:
            config: Configuration dictionary

        Returns:
            The resolved settings, with defaults applied.
        """
        check_tags_str = config.get("check_tags", "true")
        preserve_metadata_str = config.get("preserve_metadata", "false")

        fetch_timeout_str = config.get("fetch_timeout", "120")
        try:
            fetch_timeout = int(fetch_timeout_str) if fetch_timeout_str else 120
        except ValueError:
            logger.warning(
                f"Invalid fetch_timeout value: {fetch_timeout_str}, using default 120"
            )
            fetch_timeout = 120

        return IncrementSettings(
            check_tags=(
                check_tags_str is not None and check_tags_str.lower() == "true"
            ),
            path=config.get("path", ".") or ".",
            preserve_metadata=(
                preserve_metadata_str is not None
                and preserve_metadata_str.lower() == "true"
            ),
            fetch_timeout=fetch_timeout,
        )

    @staticmethod
    def _collect_existing_tags(settings: IncrementSettings) -> set[str]:
        """
        Read the existing git tags used for conflict checking.

        A git failure is not fatal: the increment still runs, just
        without conflict checking, so a shallow or tagless checkout
        degrades gracefully instead of failing the workflow.

        Args:
            settings: Resolved increment settings

        Returns:
            Existing tag names, or an empty set when checking is
            disabled or the git lookup fails.
        """
        if not settings.check_tags:
            echo("Tag checking disabled - proceeding without conflict checking")
            return set()

        try:
            tag_start_time = time.time()
            existing_tags = GitOperations.get_existing_tags(
                settings.path, timeout=settings.fetch_timeout
            )
            tag_time = time.time() - tag_start_time
        except Exception as e:
            logger.warning(f"Error with git operations: {e}")
            echo(f"Git operation failed: {e}")
            echo("Proceeding without conflict checking")
            return set()

        echo(f"Retrieved {len(existing_tags)} existing git tags")
        SemanticLogger.performance_metric(
            "git_tag_retrieval", tag_time * 1000, "ms"
        )
        return existing_tags

    @staticmethod
    def _apply_increment(
        incrementer: VersionIncrementer,
        original_version: SemanticVersion,
        increment_type: IncrementType,
        prerelease_type: str | None,
    ) -> SemanticVersion:
        """
        Run the increment and record its timing.

        Args:
            incrementer: Incrementer primed with the existing tags
            original_version: Version parsed from the input tag
            increment_type: Increment to apply
            prerelease_type: Optional pre-release identifier to use

        Returns:
            The incremented version.
        """
        increment_start_time = time.time()
        incremented_version = incrementer.increment(
            original_version, increment_type, prerelease_type
        )
        increment_time = time.time() - increment_start_time

        echo("Incremented version successfully")
        SemanticLogger.performance_metric(
            "version_increment", increment_time * 1000, "ms"
        )
        SemanticLogger.version_operation(
            "increment", str(original_version), str(incremented_version)
        )
        return incremented_version

    def _execute_increment(
        self, config: dict[str, str | None]
    ) -> IncrementResult:
        """
        Execute the version increment operation.

        Args:
            config: Configuration dictionary

        Returns:
            Dictionary containing the increment results
        """
        original_version, increment_type = self._resolve_version_source(config)
        settings = self._read_settings(config)

        group_start("Git Operations")
        existing_tags = self._collect_existing_tags(settings)
        group_end()

        incrementer = VersionIncrementer(
            existing_tags, preserve_metadata=settings.preserve_metadata
        )

        group_start("Version Increment")
        incremented_version = self._apply_increment(
            incrementer,
            original_version,
            increment_type,
            config.get("prerelease_type"),
        )
        group_end()

        self._log_operation_details(
            original_version, incremented_version, existing_tags
        )

        return {
            "original_version": original_version,
            "incremented_version": incremented_version,
            "increment_type": increment_type,
            "existing_tags": existing_tags,
        }

    def _output_results(
        self,
        result: IncrementResult,
    ) -> None:
        """Output results to GitHub Actions."""
        group_start("Results")
        incremented_version = result["incremented_version"]

        # Prepare outputs
        full_version = incremented_version.to_string(include_prefix=True)
        numeric_version = incremented_version.numeric_version()

        IOOperations.write_outputs_to_github(full_version, numeric_version)

        echo(f"Original version: {result['original_version']}")
        echo(f"Next version:     {full_version}")
        echo(f"Numeric version:  {numeric_version}")

        # Add GitHub Actions notice for visibility
        notice(
            "Version Increment Complete",
            f"Original: {result['original_version']} -> New: {full_version}",
        )
        group_end()

    def _print_success_banner(self) -> None:
        """Print success banner."""
        echo()
        group_start("Success")
        echo("Semantic Tag Increment")
        echo("=" * 50)
        echo("Version increment completed successfully!")
        group_end()
        logger.info("GitHub Actions execution completed successfully")

    def _log_operation_details(
        self,
        original: SemanticVersion,
        incremented: SemanticVersion,
        existing_tags: set[str],
    ) -> None:
        """Log detailed information about the increment operation."""
        logger.info(f"Original version: {original}")
        logger.info(f"Next version: {incremented}")

        # Only log conflict check if there were actually tags to check
        if existing_tags:
            logger.info(
                f"Checked {len(existing_tags)} existing tags for conflicts"
            )

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
