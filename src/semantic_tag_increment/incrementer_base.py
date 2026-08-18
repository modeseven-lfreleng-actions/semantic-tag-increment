# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 The Linux Foundation

"""
Shared state for the version increment strategies.

Holds the set of tags already published and the lookups that ask
questions of it. The increment strategies in
:mod:`prerelease_increment` and :mod:`incrementer` build on this base so
that every strategy sees one normalized view of the existing tags.
"""

import logging
from typing import ClassVar

from .parser import SemanticVersion

logger = logging.getLogger(__name__)


class VersionIncrementerBase:
    """
    Known-tag state shared by every increment strategy.

    Normalizing a tag is not free, so the normalized form of
    ``existing_tags`` is cached on first use and rebuilt only when the
    caller supplies a new tag set.
    """

    # Safety limits to prevent infinite loops and excessive search attempts
    MAX_PATCH_ATTEMPTS: ClassVar[int] = 100
    MAX_PRERELEASE_ATTEMPTS: ClassVar[int] = 1000

    def __init__(
        self,
        existing_tags: set[str] | None = None,
        preserve_metadata: bool = False,
    ):
        """
        Initialize the version incrementer.

        Args:
            existing_tags: Set of existing version tags to avoid conflicts
            preserve_metadata: Whether to preserve build metadata during
                increments
        """
        self.existing_tags: set[str] = existing_tags or set()
        self.preserve_metadata: bool = preserve_metadata
        # Cache normalized tags for performance optimization
        self._normalized_tags_cache: set[str] | None = None

    def _version_exists(self, version: SemanticVersion) -> bool:
        """Check if a version already exists in the known tags."""
        if not self.existing_tags:
            return False

        # Build normalized tags cache if not already built
        if self._normalized_tags_cache is None:
            self._normalized_tags_cache = {
                self._normalize_version_string(tag)
                for tag in self.existing_tags
            }

        # Compare against the pre-normalized cache built above: re-normalizing
        # every existing tag on each lookup dominated the search cost.
        normalized_version = self._normalize_version_string(
            version.to_string(include_prefix=False)
        )

        return normalized_version in self._normalized_tags_cache

    def _normalize_version_string(self, version_str: str) -> str:
        """
        Normalize a version string for consistent comparison.

        Optimized for performance with minimal string operations.
        """
        # Fast path for common cases
        if not version_str:
            return ""

        # Index arithmetic avoids allocating a new string just to drop 'v'.
        start_idx = (
            1
            if version_str and (version_str[0] == "v" or version_str[0] == "V")
            else 0
        )

        # Find build metadata separator if present
        plus_idx = version_str.find("+", start_idx)

        if plus_idx != -1:
            return version_str[start_idx:plus_idx].lower()
        else:
            return version_str[start_idx:].lower()

    def update_existing_tags(self, new_tags: set[str]) -> None:
        """
        Update the set of existing tags and invalidate the cache.

        Args:
            new_tags: New set of existing version tags
        """
        self.existing_tags = new_tags
        # Invalidate cache to force rebuild on next access
        self._normalized_tags_cache = None

    def _get_existing_patches(self, major: int, minor: int) -> set[int]:
        """
        Get existing patch numbers for a given major.minor version.

        Returns:
            Set of existing patch numbers
        """
        patches: set[int] = set()
        prefix_pattern = f"{major}.{minor}."

        for tag in self.existing_tags:
            normalized = self._normalize_version_string(tag)
            if normalized.startswith(prefix_pattern):
                try:
                    # Extract patch number (before any prerelease or metadata)
                    remainder = normalized[len(prefix_pattern) :]
                    patch_str = remainder.split("-")[0].split("+")[0]
                    if patch_str.isdigit():
                        patches.add(int(patch_str))
                except (ValueError, IndexError):
                    continue

        return patches

    def _get_existing_prerelease_numbers(
        self, major: int, minor: int, patch: int, prerelease_type: str
    ) -> set[int]:
        """
        Get existing prerelease numbers for a given version and prerelease type.

        Returns:
            Set of existing prerelease numbers
        """
        numbers: set[int] = set()
        version_prefix = f"{major}.{minor}.{patch}-{prerelease_type}."

        for tag in self.existing_tags:
            normalized = self._normalize_version_string(tag)
            if normalized.startswith(version_prefix):
                try:
                    remainder = normalized[len(version_prefix) :]
                    # Get everything before any additional dots, plus, or end of string
                    num_str = remainder.split(".")[0].split("+")[0]
                    if num_str.isdigit():
                        numbers.add(int(num_str))
                except (ValueError, IndexError):
                    continue

        return numbers
