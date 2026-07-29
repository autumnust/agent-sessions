"""Tests for agent_sessions.render."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from agent_sessions.models import Session
from agent_sessions.render import render


def _session(**overrides) -> Session:
    defaults = dict(
        provider="claude",
        id="11111111-1111-1111-1111-111111111111",
        name="my_session",
        cwd="/home/ubuntu/work/proj-a",
        started_at=dt.datetime(2026, 7, 1, 10, 0, tzinfo=dt.timezone.utc),
        updated_at=dt.datetime(2026, 7, 1, 11, 0, tzinfo=dt.timezone.utc),
        path=Path("/tmp/x.jsonl"),
    )
    defaults.update(overrides)
    return Session(**defaults)


def test_json_round_trip():
    sessions = [_session()]
    out = json.loads(render(sessions, "json"))
    assert out[0]["name"] == "my_session"
    assert out[0]["id"] == sessions[0].id
    assert out[0]["started_at"].startswith("2026-07-01")


def test_json_serializes_none_fields():
    sessions = [_session(name=None, cwd=None, started_at=None)]
    out = json.loads(render(sessions, "json"))
    assert out[0]["name"] is None
    assert out[0]["cwd"] is None
    assert out[0]["started_at"] is None


def test_jsonl_one_compact_line_per_session():
    sessions = [
        _session(),
        _session(id="22222222-2222-2222-2222-222222222222", name=None),
    ]
    lines = render(sessions, "jsonl").splitlines()
    assert len(lines) == 2
    assert "\n" not in lines[0]
    assert json.loads(lines[1])["name"] is None


def _session_lines(out: str) -> list:
    """The session rows of a grouped table: no header, headings, or blanks."""
    lines = out.splitlines()
    if lines and lines[0].startswith("PROVIDER"):
        lines = lines[1:]
    return [ln for ln in lines if ln.strip() and not ln.startswith(("/", "~", "("))]


def test_table_header_and_row():
    out = render([_session()], "table")
    assert out.splitlines()[0].split() == ["PROVIDER", "UPDATED", "ID", "NAME"]
    row = _session_lines(out)[0]
    assert "my_session" in row
    assert "11111111"[:8] in row  # short id


def test_table_groups_rows_under_a_workspace_heading():
    out = render([_session()], "table")
    assert "/home/ubuntu/work/proj-a" in out.splitlines()
    # the workspace is the heading, so it is not repeated as a column
    assert out.splitlines()[0].split() == ["PROVIDER", "UPDATED", "ID", "NAME"]
    assert _session_lines(out)[0].count("/home/ubuntu/work/proj-a") == 0


def test_table_heading_abbreviates_the_home_directory(monkeypatch):
    monkeypatch.setenv("HOME", "/home/ubuntu")
    out = render([_session(cwd="/home/ubuntu/work/proj-a")], "table")
    assert "~/work/proj-a" in out.splitlines()


def test_table_no_header_starts_at_the_first_heading():
    out = render([_session()], "table", header=False)
    assert "PROVIDER" not in out
    assert out.splitlines()[0] == "/home/ubuntu/work/proj-a"


def test_table_long_includes_path_and_full_id():
    out = render([_session()], "table", long=True)
    assert "/tmp/x.jsonl" in out
    assert "11111111-1111-1111-1111-111111111111" in out


def test_table_missing_name_renders_as_dash():
    out = render([_session(name=None)], "table")
    assert _session_lines(out)[0].rstrip().endswith("-")


def test_table_missing_cwd_gets_its_own_heading():
    out = render([_session(cwd=None)], "table")
    assert "(unknown workspace)" in out.splitlines()


def test_empty_sessions_table_is_header_only():
    out = render([], "table")
    assert out.splitlines() == ["PROVIDER  UPDATED  ID  NAME"]


def test_empty_sessions_json_is_empty_array():
    assert render([], "json") == "[]"


def test_empty_sessions_jsonl_is_empty_string():
    assert render([], "jsonl") == ""


def test_unknown_format_raises():
    with pytest.raises(ValueError):
        render([_session()], "xml")


def test_json_and_jsonl_stay_flat_and_include_parent_and_role():
    coordinator = _session(id="coord", name="sdk_112")
    subagent = _session(
        id="child", name=None, role="explorer:Nash", cwd="/home/ubuntu/work/proj-a",
        parent_id="coord",
    )
    out = json.loads(render([coordinator, subagent], "json"))
    assert [row["id"] for row in out] == ["coord", "child"]
    assert out[1]["parent_id"] == "coord"
    assert out[1]["role"] == "explorer:Nash"

    lines = render([coordinator, subagent], "jsonl").splitlines()
    assert json.loads(lines[1])["parent_id"] == "coord"


class TestTree:
    def _coordinator(self, **overrides):
        return _session(id="coord", name="sdk_112", cwd="/home/ubuntu/work/proj-a", **overrides)

    def _subagent(self, **overrides):
        defaults = dict(
            id="child", name=None, role="explorer:Nash",
            cwd="/home/ubuntu/work/proj-a", parent_id="coord",
        )
        defaults.update(overrides)
        return _session(**defaults)

    def test_subagent_is_indented_under_its_coordinator(self):
        rows = _session_lines(render([self._coordinator(), self._subagent()], "table"))
        assert rows[0].split()[0] == "claude"
        assert rows[0].endswith("sdk_112")
        assert rows[1].endswith("└─ explorer:Nash")  # "└─ explorer:Nash"

    def test_same_workspace_as_parent_is_not_repeated_on_the_nested_row(self):
        rows = _session_lines(render([self._coordinator(), self._subagent()], "table"))
        assert "/home/ubuntu/work/proj-a" not in rows[1]

    def test_different_workspace_is_called_out_on_the_nested_row(self):
        rows = _session_lines(
            render([self._coordinator(), self._subagent(cwd="/home/ubuntu/work/other")], "table")
        )
        assert rows[1].endswith("└─ explorer:Nash  (in /home/ubuntu/work/other)")

    def test_only_one_child_uses_the_last_glyph(self):
        rows = _session_lines(
            render(
                [
                    self._coordinator(),
                    self._subagent(id="c1", role="explorer:Nash"),
                    self._subagent(id="c2", role="explorer:Bohr"),
                ],
                "table",
            )
        )
        assert rows[1].endswith("├─ explorer:Nash")  # "├─ explorer:Nash"
        assert rows[2].endswith("└─ explorer:Bohr")

    def test_orphaned_subagent_renders_as_a_standalone_row(self):
        # parent_id points at an id that isn't in the current (e.g.
        # filtered) result set -- must not vanish or crash, just render
        # like any other top-level row.
        rows = _session_lines(render([self._subagent(parent_id="does-not-exist")], "table"))
        assert len(rows) == 1
        assert "└─" not in rows[0]
        assert "explorer:Nash" in rows[0]

    def test_multi_level_nesting_indents_by_depth(self):
        coordinator = self._coordinator()
        child = self._subagent()
        grandchild = self._subagent(id="grandchild", role="reviewer:Otto", parent_id="child")
        rows = _session_lines(render([coordinator, child, grandchild], "table"))
        assert rows[1].endswith("└─ explorer:Nash")
        assert rows[2].endswith("└─ reviewer:Otto")
        # the grandchild's branch glyph sits further right than its parent's,
        # i.e. one deeper level of indent inside the NAME column
        assert rows[2].index("└─") > rows[1].index("└─")

    def test_a_deeper_branch_draws_a_continuation_bar_past_an_open_parent(self):
        # child c1 has a sibling below it, so the column under c1's branch
        # has to stay drawn while c1's own child is printed.
        rows = _session_lines(
            render(
                [
                    self._coordinator(),
                    self._subagent(id="c1", role="explorer:Nash"),
                    self._subagent(id="g1", role="reviewer:Otto", parent_id="c1"),
                    self._subagent(id="c2", role="explorer:Bohr"),
                ],
                "table",
            )
        )
        assert rows[1].endswith("├─ explorer:Nash")
        assert rows[2].endswith("│  └─ reviewer:Otto")  # "│  └─ reviewer:Otto"
        assert rows[3].endswith("└─ explorer:Bohr")


class TestGrouping:
    def _at(self, **overrides):
        defaults = dict(name=None, role=None, parent_id=None)
        defaults.update(overrides)
        return _session(**defaults)

    def test_each_workspace_gets_one_heading_in_first_appearance_order(self):
        out = render(
            [
                self._at(id="a", cwd="/w/one"),
                self._at(id="b", cwd="/w/two"),
                self._at(id="c", cwd="/w/one"),
            ],
            "table",
        )
        headings = [ln for ln in out.splitlines() if ln.startswith("/w/")]
        assert headings == ["/w/one", "/w/two"]

    def test_a_blank_line_separates_consecutive_workspaces(self):
        out = render([self._at(id="a", cwd="/w/one"), self._at(id="b", cwd="/w/two")], "table")
        lines = out.splitlines()
        assert lines[lines.index("/w/two") - 1] == ""

    def test_single_row_sessions_in_one_workspace_stay_packed(self):
        out = render(
            [self._at(id="a", cwd="/w/one"), self._at(id="b", cwd="/w/one")], "table"
        )
        body = out.splitlines()[out.splitlines().index("/w/one") + 1 :]
        assert "" not in body  # no gap inserted between two plain rows

    def test_a_coordinator_block_is_set_apart_from_its_neighbours(self):
        out = render(
            [
                self._at(id="plain-before", cwd="/w/one"),
                self._at(id="coord", name="sdk_112", cwd="/w/one"),
                self._at(id="child", role="explorer:Nash", cwd="/w/one", parent_id="coord"),
                self._at(id="plain-after", cwd="/w/one"),
            ],
            "table",
        )
        lines = out.splitlines()
        coord_at = next(i for i, ln in enumerate(lines) if ln.endswith("sdk_112"))
        child_at = next(i for i, ln in enumerate(lines) if ln.endswith("└─ explorer:Nash"))
        assert lines[coord_at - 1] == ""  # gap opened above the block
        assert child_at == coord_at + 1  # but the block itself is contiguous
        assert lines[child_at + 1] == ""  # and closed below it


class TestFlat:
    """--flat: one plain row per session, no headings, no gaps, no glyphs."""

    def _coordinator(self, **overrides):
        return _session(id="coord", name="sdk_112", cwd="/home/ubuntu/work/proj-a", **overrides)

    def _subagent(self, **overrides):
        defaults = dict(
            id="child", name=None, role="explorer:Nash",
            cwd="/home/ubuntu/work/proj-a", parent_id="coord",
        )
        defaults.update(overrides)
        return _session(**defaults)

    def test_flat_disables_nesting_and_keeps_original_order(self):
        out = render([self._coordinator(), self._subagent()], "table", tree=False)
        lines = out.splitlines()
        assert "└─" not in lines[2]
        assert lines[2].split()[0] == "claude"

    def test_flat_keeps_the_workspace_column_and_repeats_it_per_row(self):
        out = render([self._coordinator(), self._subagent()], "table", tree=False)
        lines = out.splitlines()
        assert "WORKSPACE" in lines[0]
        assert all("/home/ubuntu/work/proj-a" in ln for ln in lines[1:])

    def test_flat_inserts_no_blank_lines(self):
        out = render(
            [self._coordinator(), self._subagent(), _session(id="other", cwd="/w/two")],
            "table",
            tree=False,
        )
        assert "" not in out.splitlines()

    def test_cyclic_parent_id_does_not_infinite_loop(self):
        # A genuine mutual cycle can't happen with real tool output (ids
        # are generated by the tool, not user-editable), but corrupt data
        # must not hang agent-sessions -- it's fine for a fully cyclic
        # pair to have no valid root and render as just a header.
        a = self._subagent(id="a", parent_id="b", role="a-role")
        b = self._subagent(id="b", parent_id="a", role="b-role")
        out = render([a, b], "table")  # must return promptly, not hang
        assert out.splitlines()[0].startswith("PROVIDER")
