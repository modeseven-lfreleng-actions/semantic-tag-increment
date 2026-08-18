# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 The Linux Foundation

"""
Unit tests for GitHub Actions job-log output.

Covers the escaping applied to text interpolated into workflow
commands, which reaches these helpers from tag names and exception
strings and must not be able to terminate or forge a command.
"""

import pytest

from semantic_tag_increment import workflow_output


class TestEcho:
    """Plain job-log lines."""

    def test_echo_writes_line_verbatim(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that echo does not alter the text it is given."""
        workflow_output.echo("Original version: 1.2.3")
        assert capsys.readouterr().out == "Original version: 1.2.3\n"

    def test_echo_defaults_to_blank_separator(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that echo with no argument writes a blank line."""
        workflow_output.echo()
        assert capsys.readouterr().out == "\n"


class TestGroups:
    """Collapsible job-log groups."""

    def test_group_start_emits_command(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that group_start emits the group workflow command."""
        workflow_output.group_start("Results")
        assert capsys.readouterr().out == "::group::Results\n"

    def test_group_end_emits_command(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that group_end closes the current group."""
        workflow_output.group_end()
        assert capsys.readouterr().out == "::endgroup::\n"

    def test_group_title_newline_cannot_end_command(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that a newline in a group title stays inside the command."""
        workflow_output.group_start("Results\n::error::forged")
        out = capsys.readouterr().out
        assert out == "::group::Results%0A::error::forged\n"
        assert out.count("\n") == 1


class TestError:
    """Workflow error annotations."""

    def test_error_emits_command(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that error emits the error workflow command."""
        workflow_output.error("Validation Error: bad tag")
        assert capsys.readouterr().out == "::error::Validation Error: bad tag\n"

    def test_error_escapes_carriage_return_and_newline(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that line breaks in an error message are escaped."""
        workflow_output.error("first\r\nsecond")
        assert capsys.readouterr().out == "::error::first%0D%0Asecond\n"

    def test_error_escapes_percent_before_other_sequences(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that a literal percent is not confused with an escape."""
        workflow_output.error("100%\nnext")
        # The literal '%' becomes '%25', and only the newline becomes '%0A';
        # escaping in the other order would yield '%250A' for the newline.
        assert capsys.readouterr().out == "::error::100%25%0Anext\n"


class TestNotice:
    """Workflow notice annotations."""

    def test_notice_emits_command(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that notice emits a titled notice workflow command."""
        workflow_output.notice("Version Increment Complete", "1.0.0 -> 1.0.1")
        assert (
            capsys.readouterr().out
            == "::notice title=Version Increment Complete::1.0.0 -> 1.0.1\n"
        )

    def test_notice_escapes_property_delimiters_in_title(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that ':' and ',' in a title cannot close the property list."""
        workflow_output.notice("a:b,c", "body")
        assert capsys.readouterr().out == "::notice title=a%3Ab%2Cc::body\n"

    def test_notice_leaves_delimiters_in_message(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that ':' and ',' are legal in the message body."""
        workflow_output.notice("Title", "Original: 1.0.0, New: 1.0.1")
        assert (
            capsys.readouterr().out
            == "::notice title=Title::Original: 1.0.0, New: 1.0.1\n"
        )
