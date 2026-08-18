# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 The Linux Foundation

"""
GitHub Actions job-log output.

Every function here writes to stdout because stdout *is* the runner's
documented channel for the job log and for workflow commands such as
``::group::``, ``::error::`` and ``::notice::``. That output is part of
the action's contract with the runner, not diagnostic logging, so it
deliberately bypasses the ``logging`` module: a logger would send it to
stderr, reorder it relative to the workflow commands, and let a log
level silence it.

Keeping the writes behind these named helpers puts the whole protocol in
one reviewed place and keeps bare ``print`` calls out of the rest of the
package, where they really would be debug leftovers.

The helpers that emit a workflow command escape the text they
interpolate, because tag names and exception strings reach them from
outside the process and an unescaped newline would end the command and
let the remainder of the string start a new one.
"""

from __future__ import annotations

import sys

__all__ = [
    "echo",
    "error",
    "group_end",
    "group_start",
    "notice",
]


def _escape_data(value: str) -> str:
    """
    Escape text interpolated into a workflow command's message.

    The runner decodes these sequences again before displaying the
    message, so escaping is invisible in the rendered job log.

    Args:
        value: Raw text to place after the command's ``::`` separator.

    Returns:
        The text with the runner's message escapes applied.
    """
    # Percent first: it is the escape introducer, so reordering these
    # would re-escape the percent signs the later replacements emit.
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_property(value: str) -> str:
    """
    Escape text interpolated into a workflow command property value.

    Args:
        value: Raw text to place in a ``key=value`` property.

    Returns:
        The text with the runner's property escapes applied.
    """
    # Properties are delimited by ':' and ',' on top of the message rules.
    return _escape_data(value).replace(":", "%3A").replace(",", "%2C")


def echo(line: str = "") -> None:
    """
    Write a single line verbatim to the GitHub Actions job log.

    Callers that build a workflow command are responsible for escaping
    the data they interpolate; this function must not escape, or it
    would mangle the ``::`` markers of the commands passed to it.

    Args:
        line: Text to write; defaults to a blank separator line.
    """
    # Discard the byte count: the job log is fire-and-forget.
    _ = sys.stdout.write(f"{line}\n")


def group_start(title: str) -> None:
    """
    Open a collapsible job-log group.

    Args:
        title: Heading shown on the collapsed group.
    """
    echo(f"::group::{_escape_data(title)}")


def group_end() -> None:
    """Close the most recently opened job-log group."""
    echo("::endgroup::")


def error(message: str) -> None:
    """
    Emit a workflow error annotation.

    Args:
        message: Text shown on the annotation.
    """
    echo(f"::error::{_escape_data(message)}")


def notice(title: str, message: str) -> None:
    """
    Emit a workflow notice annotation.

    Args:
        title: Annotation title shown in the run summary.
        message: Annotation body.
    """
    echo(f"::notice title={_escape_property(title)}::{_escape_data(message)}")
