# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 The Linux Foundation

"""
Pre-release increment strategy.

Covers the pre-release half of version incrementing: creating a first
pre-release, advancing an existing one, and searching forward for an
identifier that no published tag already claims.
"""

import logging
import re

from .incrementer_base import VersionIncrementerBase
from .parser import SemanticVersion

logger = logging.getLogger(__name__)


class PrereleaseIncrementer(VersionIncrementerBase):
    """Pre-release creation, incrementing, and conflict resolution."""

    def _create_conflict_prerelease(
        self, version: SemanticVersion, prerelease_type: str
    ) -> SemanticVersion:
        """Create a prerelease version to resolve conflicts."""
        base_version = SemanticVersion(
            major=version.major,
            minor=version.minor,
            patch=version.patch + 1,
            prerelease=None,
            metadata=version.metadata if self.preserve_metadata else None,
            prefix=version.prefix,
        )

        prerelease_candidate = SemanticVersion(
            major=base_version.major,
            minor=base_version.minor,
            patch=base_version.patch,
            prerelease=f"{prerelease_type}.1",
            metadata=base_version.metadata if self.preserve_metadata else None,
            prefix=base_version.prefix,
        )

        if not self._version_exists(prerelease_candidate):
            return prerelease_candidate

        return self._find_next_available_prerelease_for_conflict(
            base_version, prerelease_type
        )

    def _find_next_available_prerelease_for_conflict(
        self, base_version: SemanticVersion, prerelease_type: str
    ) -> SemanticVersion:
        """
        Find the next available prerelease version when a regular version has conflicts.

        Args:
            base_version: The base version to use
            prerelease_type: The prerelease identifier type (dev, alpha, beta, etc.)

        Returns:
            The next available prerelease version
        """
        # Try different prerelease numbers using the shared helper
        available_version = self._find_available_prerelease_version(
            major=base_version.major,
            minor=base_version.minor,
            patch=base_version.patch,
            prerelease_type=prerelease_type,
            metadata=base_version.metadata,
            prefix=base_version.prefix,
        )

        if available_version:
            return available_version

        # If still no available version, increment patch and try again
        fallback = SemanticVersion(
            major=base_version.major,
            minor=base_version.minor,
            patch=base_version.patch + 1,
            prerelease=f"{prerelease_type}.1",
            metadata=base_version.metadata,
            prefix=base_version.prefix,
        )

        if not self._version_exists(fallback):
            return fallback

        # Last resort - use find_next_available_version
        return self._find_next_available_version(fallback)

    def _increment_prerelease(
        self, version: SemanticVersion, prerelease_type: str | None = None
    ) -> SemanticVersion:
        """
        Intelligently increment the pre-release version.

        For existing pre-releases, finds and increments numeric components.
        For non-pre-releases, creates a new pre-release version.
        """
        if not version.is_prerelease():
            # Not a prerelease - create first prerelease
            return self._create_first_prerelease(version, prerelease_type)

        # Check if we're changing prerelease types (e.g., alpha → beta → rc)
        if prerelease_type:
            identifiers = version.get_prerelease_identifiers()
            current_type = identifiers[0].lower() if identifiers else ""
            # If we're switching from one prerelease type to another
            if current_type and current_type != prerelease_type.lower():
                return SemanticVersion(
                    major=version.major,
                    minor=version.minor,
                    patch=version.patch,
                    prerelease=f"{prerelease_type}.1",
                    metadata=version.metadata
                    if self.preserve_metadata
                    else None,
                    prefix=version.prefix,
                )
        # Existing prerelease - increment it
        return self._increment_existing_prerelease(version)

    def _create_first_prerelease(
        self, version: SemanticVersion, prerelease_type: str | None = None
    ) -> SemanticVersion:
        """
        Create the first pre-release version for a given base version.

        Searches forward from ``patch + 1`` for an identifier that no
        existing tag claims. If that search is exhausted, falls back to
        the unincremented patch with counter 1.
        """
        # Handle transitions between prerelease types (alpha → beta → rc)
        # We only need to handle the case when we're creating a prerelease
        # from a non-prerelease version. The case for switching between
        # prerelease types is now handled in _increment_prerelease
        prerelease_id = prerelease_type or "dev"
        # Determine first available prerelease by checking for conflicts
        # Start with patch + 1 as default
        patch = version.patch + 1

        # Try incremented patch with different prerelease numbers using the shared helper
        for p in range(patch, patch + 5):
            available_version = self._find_available_prerelease_version(
                major=version.major,
                minor=version.minor,
                patch=p,
                prerelease_type=prerelease_id,
                metadata=version.metadata,
                prefix=version.prefix,
                max_attempts=min(
                    self.MAX_PRERELEASE_ATTEMPTS, self.MAX_PATCH_ATTEMPTS
                ),
            )
            if available_version:
                return available_version

        # If we couldn't find an available version, create a fallback
        return SemanticVersion(
            major=version.major,
            minor=version.minor,
            patch=version.patch,
            prerelease=f"{prerelease_id}.1",
            metadata=version.metadata if self.preserve_metadata else None,
            prefix=version.prefix,
        )

    def _increment_existing_prerelease(
        self, version: SemanticVersion
    ) -> SemanticVersion:
        """
        Increment an existing pre-release version.

        Uses smart logic to find and increment numeric components.
        """
        numeric_components = version.find_numeric_prerelease_components()

        if not numeric_components:
            # No numeric components found - add .1 to the end
            new_prerelease = f"{version.prerelease}.1"
        else:
            identifiers = version.get_prerelease_identifiers()
            last_numeric = numeric_components[-1]
            index, original_id, numeric_value = last_numeric

            if original_id.isdigit():
                # Pure numeric identifier
                new_id = str(numeric_value + 1)
            else:
                # Alphanumeric identifier with trailing number
                new_id = re.sub(r"\d+$", str(numeric_value + 1), original_id)

            # Replace the identifier at the found index
            new_identifiers = identifiers.copy()
            new_identifiers[index] = new_id
            new_prerelease = ".".join(new_identifiers)

        candidate = SemanticVersion(
            major=version.major,
            minor=version.minor,
            patch=version.patch,
            prerelease=new_prerelease,
            metadata=version.metadata if self.preserve_metadata else None,
            prefix=version.prefix,
        )

        # The bumped counter is taken, so numbering restarts under the
        # next patch rather than probing further counters on this one.
        if self._version_exists(candidate):
            prerelease_base = (
                new_prerelease.split(".")[0]
                if "." in new_prerelease
                else new_prerelease
            )
            patch = version.patch + 1

            available_version = self._find_available_prerelease_version(
                major=version.major,
                minor=version.minor,
                patch=patch,
                prerelease_type=prerelease_base,
                metadata=version.metadata,
                prefix=version.prefix,
            )

            if available_version:
                return available_version

            raise RuntimeError("Could not find available prerelease version")
        return candidate

    def _find_next_available_prerelease(
        self,
        major: int,
        minor: int,
        patch: int,
        prerelease_base: str,
        metadata: str | None,
        prefix: str,
    ) -> SemanticVersion:
        """Find the next available prerelease version by incrementing numbers."""
        available_version = self._find_available_prerelease_version(
            major=major,
            minor=minor,
            patch=patch,
            prerelease_type=prerelease_base,
            metadata=metadata,
            prefix=prefix,
        )

        if available_version:
            return available_version

        raise RuntimeError("Could not find available prerelease version")

    def _find_next_available_version(
        self, base_version: SemanticVersion
    ) -> SemanticVersion:
        """
        Find the next available version by incrementing prerelease numbers.
        """
        if not base_version.is_prerelease():
            raise ValueError("Base version must be a prerelease")

        numeric_components = base_version.find_numeric_prerelease_components()
        if not numeric_components:
            # Add a numeric component
            new_prerelease = f"{base_version.prerelease}.1"
            return SemanticVersion(
                major=base_version.major,
                minor=base_version.minor,
                patch=base_version.patch,
                prerelease=new_prerelease,
                metadata=base_version.metadata
                if self.preserve_metadata
                else None,
                prefix=base_version.prefix,
            )

        # Only the rightmost numeric identifier advances; the loop below
        # walks it upward until no existing tag claims the candidate.
        identifiers = base_version.get_prerelease_identifiers()
        last_numeric = numeric_components[-1]
        index, original_id, numeric_value = last_numeric

        counter = numeric_value + 1
        while True:
            new_identifiers = identifiers.copy()

            if original_id.isdigit():
                new_identifiers[index] = str(counter)
            else:
                new_identifiers[index] = re.sub(
                    r"\d+$", str(counter), original_id
                )

            candidate = SemanticVersion(
                major=base_version.major,
                minor=base_version.minor,
                patch=base_version.patch,
                prerelease=".".join(new_identifiers),
                metadata=base_version.metadata,
                prefix=base_version.prefix,
            )

            if not self._version_exists(candidate):
                return candidate

            counter += 1

            # Safety break
            if counter > self.MAX_PRERELEASE_ATTEMPTS:
                raise RuntimeError("Could not find available version")

    def _find_available_prerelease_version(
        self,
        major: int,
        minor: int,
        patch: int,
        prerelease_type: str,
        start_counter: int = 1,
        max_attempts: int | None = None,
        metadata: str | None = None,
        prefix: str = "",
    ) -> SemanticVersion | None:
        """
        Find the next available prerelease version with the given parameters.

        Args:
            major: Major version component
            minor: Minor version component
            patch: Patch version component
            prerelease_type: The prerelease identifier (dev, alpha, beta, etc.)
            start_counter: Starting counter value for prerelease numbers
            max_attempts: Maximum number of attempts (defaults to MAX_PRERELEASE_ATTEMPTS)
            metadata: Version metadata
            prefix: Version prefix

        Returns:
            Available SemanticVersion or None if no version found within max_attempts
        """
        max_attempts = max_attempts or self.MAX_PRERELEASE_ATTEMPTS

        for counter in range(start_counter, start_counter + max_attempts):
            candidate = SemanticVersion(
                major=major,
                minor=minor,
                patch=patch,
                prerelease=f"{prerelease_type}.{counter}",
                metadata=metadata,
                prefix=prefix,
            )
            if not self._version_exists(candidate):
                return candidate

        return None
