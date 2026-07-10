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


def test_table_header_and_row():
    out = render([_session()], "table")
    lines = out.splitlines()
    assert lines[0].split()[0] == "PROVIDER"
    assert "my_session" in lines[1]
    assert "11111111"[:8] in lines[1]  # short id


def test_table_no_header():
    out = render([_session()], "table", header=False)
    assert "PROVIDER" not in out
    assert len(out.splitlines()) == 1


def test_table_long_includes_path_and_full_id():
    out = render([_session()], "table", long=True)
    assert "/tmp/x.jsonl" in out
    assert "11111111-1111-1111-1111-111111111111" in out


def test_table_missing_fields_render_as_dash():
    out = render([_session(name=None, cwd=None)], "table")
    row = out.splitlines()[1]
    assert " - " in row or row.rstrip().endswith("-")


def test_empty_sessions_table_is_header_only():
    out = render([], "table")
    assert out.splitlines() == ["PROVIDER  UPDATED  NAME  WORKSPACE  ID"]


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
        out = render([self._coordinator(), self._subagent()], "table")
        lines = out.splitlines()
        assert lines[1].split()[0] == "claude"
        assert "sdk_112" in lines[1]
        assert "└─ explorer:Nash" in lines[2]  # "└─ explorer:Nash"

    def test_same_workspace_as_parent_is_blanked_on_the_nested_row(self):
        out = render([self._coordinator(), self._subagent()], "table")
        child_line = out.splitlines()[2]
        assert "/home/ubuntu/work/proj-a" not in child_line

    def test_different_workspace_is_still_shown_on_the_nested_row(self):
        out = render(
            [self._coordinator(), self._subagent(cwd="/home/ubuntu/work/other")], "table"
        )
        child_line = out.splitlines()[2]
        assert "/home/ubuntu/work/other" in child_line

    def test_orphaned_subagent_renders_as_a_standalone_row(self):
        # parent_id points at an id that isn't in the current (e.g.
        # filtered) result set -- must not vanish or crash, just render
        # like any other top-level row.
        out = render([self._subagent(parent_id="does-not-exist")], "table")
        lines = out.splitlines()
        assert len(lines) == 2
        assert "└─" not in lines[1]
        assert "explorer:Nash" in lines[1]

    def test_multi_level_nesting_indents_by_depth(self):
        coordinator = self._coordinator()
        child = self._subagent()
        grandchild = self._subagent(id="grandchild", role="reviewer:Otto", parent_id="child")
        out = render([coordinator, child, grandchild], "table")
        lines = out.splitlines()
        assert "└─ explorer:Nash" in lines[2]
        assert "└─ reviewer:Otto" in lines[3]
        # the grandchild's branch glyph sits further right than its parent's,
        # i.e. one deeper level of indent inside the NAME column
        assert lines[3].index("└─") > lines[2].index("└─")

    def test_flat_disables_nesting_and_keeps_original_order(self):
        out = render([self._coordinator(), self._subagent()], "table", tree=False)
        lines = out.splitlines()
        assert "└─" not in lines[2]
        assert lines[2].split()[0] == "claude"

    def test_cyclic_parent_id_does_not_infinite_loop(self):
        # A genuine mutual cycle can't happen with real tool output (ids
        # are generated by the tool, not user-editable), but corrupt data
        # must not hang agent-sessions -- it's fine for a fully cyclic
        # pair to have no valid root and render as just a header.
        a = self._subagent(id="a", parent_id="b", role="a-role")
        b = self._subagent(id="b", parent_id="a", role="b-role")
        out = render([a, b], "table")  # must return promptly, not hang
        assert out.splitlines()[0].startswith("PROVIDER")
