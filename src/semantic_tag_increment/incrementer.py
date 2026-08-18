# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 The Linux Foundation

"""
Version Incrementer.

This module provides intelligent version incrementing logic for semantic versions,
including smart pre-release handling and various increment strategies.
"""

import logging
from enum import Enum

from .parser import SemanticVersion
from .prerelease_increment import PrereleaseIncrementer

logger = logging.getLogger(__name__)


class IncrementType(Enum):
    """Supported version increment types."""

    MAJOR = "major"
    MINOR = "minor"
    PATCH = "patch"
    PRERELEASE = "prerelease"
    DEV = "dev"  # Alias for prerelease for backwards compatibility


class VersionIncrementer(PrereleaseIncrementer):
    """
    Handles intelligent incrementing of semantic versions.

    Supports major, minor, patch, and intelligent pre-release incrementing
    with preservation of metadata and smart handling of complex pre-release
    patterns.
    """

    def increment(
        self,
        version: SemanticVersion,
        increment_type: IncrementType,
        prerelease_type: str | None = None,
    ) -> SemanticVersion:
        """
        Increment a semantic version based on the specified increment type.

        Args:
            version: The version to increment
            increment_type: The type of increment to perform
            prerelease_type: Optional prerelease identifier for new prereleases

        Returns:
            New incremented SemanticVersion
        """
        if increment_type == IncrementType.MAJOR:
            return self._increment_major(version)
        elif increment_type == IncrementType.MINOR:
            return self._increment_minor(version)
        elif increment_type == IncrementType.PATCH:
            return self._increment_patch(version, prerelease_type or "dev")
        elif increment_type in (IncrementType.PRERELEASE, IncrementType.DEV):
            return self._increment_prerelease(version, prerelease_type)
        else:
            raise ValueError(  # pyright: ignore[reportUnreachable]
                f"Unsupported increment type: {increment_type}"
            )

    def _increment_major(self, version: SemanticVersion) -> SemanticVersion:
        """Increment the major version and reset minor and patch."""
        candidate = SemanticVersion(
            major=version.major + 1,
            minor=0,
            patch=0,
            prerelease=None,
            metadata=version.metadata if self.preserve_metadata else None,
            prefix=version.prefix,
        )

        if self._version_exists(candidate):
            # If a conflict exists, try incrementing the patch version
            for patch in range(1, self.MAX_PATCH_ATTEMPTS):
                next_candidate = SemanticVersion(
                    major=candidate.major,
                    minor=candidate.minor,
                    patch=patch,
                    prerelease=None,
                    metadata=version.metadata
                    if self.preserve_metadata
                    else None,
                    prefix=version.prefix,
                )
                if not self._version_exists(next_candidate):
                    return next_candidate

            # If no available version found, try prerelease versions
            return self._find_next_available_prerelease_for_conflict(
                candidate, "dev"
            )

        return candidate

    def _increment_minor(self, version: SemanticVersion) -> SemanticVersion:
        """Increment the minor version and reset patch."""
        candidate = SemanticVersion(
            major=version.major,
            minor=version.minor + 1,
            patch=0,
            prerelease=None,
            metadata=version.metadata if self.preserve_metadata else None,
            prefix=version.prefix,
        )

        if self._version_exists(candidate):
            # If a conflict exists, try incrementing the patch version
            for patch in range(1, self.MAX_PATCH_ATTEMPTS):
                next_candidate = SemanticVersion(
                    major=candidate.major,
                    minor=candidate.minor,
                    patch=patch,
                    prerelease=None,
                    metadata=version.metadata
                    if self.preserve_metadata
                    else None,
                    prefix=version.prefix,
                )
                if not self._version_exists(next_candidate):
                    return next_candidate

            # If no available version found, try prerelease versions
            return self._find_next_available_prerelease_for_conflict(
                candidate, "dev"
            )

        return candidate

    def _increment_patch(
        self, version: SemanticVersion, prerelease_type: str = "dev"
    ) -> SemanticVersion:
        """Increment the patch version and reset prerelease."""
        candidate = self._create_patch_candidate(version)

        if not self._version_exists(candidate):
            return candidate

        return self._resolve_patch_conflict(version, prerelease_type)

    def _create_patch_candidate(
        self, version: SemanticVersion
    ) -> SemanticVersion:
        """Create a candidate patch version."""
        return SemanticVersion(
            major=version.major,
            minor=version.minor,
            patch=version.patch + 1,
            prerelease=None,
            metadata=version.metadata if self.preserve_metadata else None,
            prefix=version.prefix,
        )

    def _resolve_patch_conflict(
        self, version: SemanticVersion, prerelease_type: str
    ) -> SemanticVersion:
        """Resolve conflicts when incrementing patch version."""
        # Try finding next available patch number
        next_patch = self._find_next_available_patch(version)
        if next_patch:
            return next_patch

        # Fall back to prerelease version
        return self._create_conflict_prerelease(version, prerelease_type)

    def _find_next_available_patch(
        self, version: SemanticVersion
    ) -> SemanticVersion | None:
        """Find the next available patch version using optimized search."""
        existing_patches = self._get_existing_patches(
            version.major, version.minor
        )

        # Find first gap in sequence starting from patch + 1
        patch = version.patch + 1
        max_patch = version.patch + self.MAX_PATCH_ATTEMPTS

        while patch <= max_patch:
            if patch not in existing_patches:
                candidate = SemanticVersion(
                    major=version.major,
                    minor=version.minor,
                    patch=patch,
                    prerelease=None,
                    metadata=version.metadata
                    if self.preserve_metadata
                    else None,
                    prefix=version.prefix,
                )
                # Double-check with full version string matching
                if not self._version_exists(candidate):
                    return candidate
            patch += 1

        return None

    @classmethod
    def determine_increment_type(cls, increment_str: str) -> IncrementType:
        """
        Determine the increment type from a string.

        Args:
            increment_str: String representation of increment type

        Returns:
            IncrementType enum value

        Raises:
            ValueError: If increment type is not recognized
        """
        increment_str = increment_str.lower().strip()

        for increment_type in IncrementType:
            if increment_type.value == increment_str:
                return increment_type

        aliases = {
            "dev": IncrementType.DEV,
            "pre": IncrementType.PRERELEASE,
            "prerel": IncrementType.PRERELEASE,
        }

        if increment_str in aliases:
            return aliases[increment_str]

        raise ValueError(
            f"Invalid increment type: {increment_str}."
            + f" Valid types: {[t.value for t in IncrementType]}"
        )

    def suggest_next_version(
        self, current_version: SemanticVersion, increment_type: IncrementType
    ) -> list[SemanticVersion]:
        """
        Suggest multiple possible next versions.

        Useful for interactive scenarios or when multiple strategies are valid.

        Args:
            current_version: The current version
            increment_type: The type of increment desired

        Returns:
            List of suggested next versions in order of preference
        """
        suggestions: list[SemanticVersion] = []

        if increment_type == IncrementType.PRERELEASE:
            # If current version is already a prerelease, suggest the next logical prerelease type
            if current_version.is_prerelease():
                identifiers = current_version.get_prerelease_identifiers()
                current_type = identifiers[0].lower() if identifiers else "dev"

                # Standard prerelease progression: dev → alpha → beta → rc → release
                next_type = None
                if "alpha" in current_type or "dev" in current_type:
                    next_type = "beta"
                elif "beta" in current_type:
                    next_type = "rc"

                if next_type:
                    try:
                        # Maintain same patch version when changing prerelease type
                        suggestion = SemanticVersion(
                            major=current_version.major,
                            minor=current_version.minor,
                            patch=current_version.patch,
                            prerelease=f"{next_type}.1",
                            metadata=current_version.metadata,
                            prefix=current_version.prefix,
                        )
                        suggestions.append(suggestion)
                    except Exception as e:
                        logger.debug(
                            f"Failed to create suggestion with prerelease type {next_type}: {e}"
                        )

            # Offer multiple prerelease strategies
            for prerelease_type in ["dev", "alpha", "beta", "rc"]:
                try:
                    suggestion = self._create_first_prerelease(
                        current_version, prerelease_type
                    )
                    if suggestion not in suggestions:
                        suggestions.append(suggestion)
                except Exception as e:
                    logger.debug(
                        f"Failed to create suggestion with prerelease type {prerelease_type}: {e}"
                    )
                    continue
        else:
            # For other increment types, just return the single increment
            suggestions.append(self.increment(current_version, increment_type))

        return suggestions
