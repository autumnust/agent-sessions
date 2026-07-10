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
