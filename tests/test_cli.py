"""End-to-end tests for the agent-sessions CLI."""

from __future__ import annotations

import json

import pytest

from agent_sessions.cli import main

from .helpers import make_claude_session, make_codex_session


@pytest.fixture
def stores(tmp_path, monkeypatch):
    """Isolated, empty Claude/Codex stores; env vars point at them by default."""
    claude_dir = tmp_path / ".claude"
    codex_dir = tmp_path / ".codex"
    monkeypatch.delenv("AGENT_SESSIONS_WORKSPACE_ROOT", raising=False)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_dir))
    monkeypatch.setenv("CODEX_HOME", str(codex_dir))
    return claude_dir, codex_dir


def _run_jsonl(argv):
    """Run main() with --format jsonl and return the parsed rows."""
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        code = main([*argv, "--format", "jsonl"])
    text = buf.getvalue().strip()
    rows = [json.loads(line) for line in text.splitlines()] if text else []
    return code, rows


def test_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "usage" in capsys.readouterr().out.lower()


def test_version_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "agent-sessions" in capsys.readouterr().out


def test_bad_format_is_usage_error():
    with pytest.raises(SystemExit) as exc:
        main(["--format", "xml"])
    assert exc.value.code == 2


def test_bad_provider_is_usage_error():
    with pytest.raises(SystemExit) as exc:
        main(["--provider", "gemini"])
    assert exc.value.code == 2


def test_bad_since_is_usage_error():
    with pytest.raises(SystemExit) as exc:
        main(["--since", "not-a-date"])
    assert exc.value.code == 2


def test_no_sessions_found_is_not_an_error(stores):
    code, rows = _run_jsonl([])
    assert code == 0
    assert rows == []


def test_workspace_filter_default_uses_env_var(stores):
    claude_dir, codex_dir = stores
    make_claude_session(claude_dir, "/home/ubuntu/work/inside", "11111111-1111-1111-1111-111111111111")
    make_claude_session(claude_dir, "/somewhere/else", "22222222-2222-2222-2222-222222222222")
    code, rows = _run_jsonl(["--workspace-root", "/home/ubuntu/work"])
    assert code == 0
    assert len(rows) == 1
    assert rows[0]["cwd"] == "/home/ubuntu/work/inside"


def test_all_workspaces_includes_everything(stores):
    claude_dir, codex_dir = stores
    make_claude_session(claude_dir, "/home/ubuntu/work/inside", "11111111-1111-1111-1111-111111111111")
    make_claude_session(claude_dir, "/somewhere/else", "22222222-2222-2222-2222-222222222222")
    code, rows = _run_jsonl(["--all-workspaces"])
    assert code == 0
    assert len(rows) == 2


def test_unknown_cwd_excluded_when_filter_active(stores):
    claude_dir, codex_dir = stores
    rollout_dir = codex_dir / "sessions" / "2026" / "07" / "05"
    rollout_dir.mkdir(parents=True)
    (rollout_dir / "rollout-2026-07-05T00-00-00-99999999-9999-9999-9999-999999999999.jsonl").write_text(
        "not json\n"
    )
    code, rows = _run_jsonl(["--workspace-root", "/home/ubuntu/work"])
    assert code == 0
    assert rows == []
    code, rows = _run_jsonl(["--all-workspaces"])
    assert code == 0
    assert len(rows) == 1


def test_named_only(stores):
    claude_dir, codex_dir = stores
    make_claude_session(
        claude_dir, "/home/ubuntu/work/a", "11111111-1111-1111-1111-111111111111", renamed_to="alpha"
    )
    make_claude_session(claude_dir, "/home/ubuntu/work/b", "22222222-2222-2222-2222-222222222222")
    code, rows = _run_jsonl(["--workspace-root", "/home/ubuntu/work", "--named-only"])
    assert code == 0
    assert len(rows) == 1
    assert rows[0]["name"] == "alpha"


def test_query_filters_by_name_case_insensitively(stores):
    claude_dir, codex_dir = stores
    make_claude_session(
        claude_dir,
        "/home/ubuntu/work/a",
        "11111111-1111-1111-1111-111111111111",
        renamed_to="Sampler_Investigation",
    )
    make_claude_session(
        claude_dir,
        "/home/ubuntu/work/b",
        "22222222-2222-2222-2222-222222222222",
        renamed_to="unrelated_task",
    )
    code, rows = _run_jsonl(["--workspace-root", "/home/ubuntu/work", "-q", "sampler"])
    assert code == 0
    assert len(rows) == 1
    assert rows[0]["name"] == "Sampler_Investigation"


def test_provider_filter(stores):
    claude_dir, codex_dir = stores
    make_claude_session(claude_dir, "/home/ubuntu/work/a", "11111111-1111-1111-1111-111111111111")
    make_codex_session(codex_dir, "/home/ubuntu/work/b", "22222222-2222-2222-2222-222222222222")
    code, rows = _run_jsonl(["--workspace-root", "/home/ubuntu/work", "-p", "codex"])
    assert code == 0
    assert len(rows) == 1
    assert rows[0]["provider"] == "codex"


def test_limit(stores):
    claude_dir, codex_dir = stores
    for i in range(5):
        make_claude_session(
            claude_dir, "/home/ubuntu/work/a", f"1111111{i}-1111-1111-1111-11111111111{i}"
        )
    code, rows = _run_jsonl(["--workspace-root", "/home/ubuntu/work", "--limit", "2"])
    assert code == 0
    assert len(rows) == 2


def test_sort_updated_defaults_to_newest_first(stores):
    claude_dir, codex_dir = stores
    make_claude_session(
        claude_dir,
        "/home/ubuntu/work/a",
        "11111111-1111-1111-1111-111111111111",
        timestamp="2026-07-01T10:00:00.000Z",
    )
    make_claude_session(
        claude_dir,
        "/home/ubuntu/work/b",
        "22222222-2222-2222-2222-222222222222",
        timestamp="2026-07-05T10:00:00.000Z",
    )
    import os
    import time

    # Force distinguishable mtimes regardless of how fast the two writes ran.
    a_path = claude_dir / "projects" / "-home-ubuntu-work-a" / "11111111-1111-1111-1111-111111111111.jsonl"
    b_path = claude_dir / "projects" / "-home-ubuntu-work-b" / "22222222-2222-2222-2222-222222222222.jsonl"
    now = time.time()
    os.utime(a_path, (now - 100, now - 100))
    os.utime(b_path, (now, now))

    code, rows = _run_jsonl(["--workspace-root", "/home/ubuntu/work"])
    assert code == 0
    assert [r["id"] for r in rows] == [
        "22222222-2222-2222-2222-222222222222",
        "11111111-1111-1111-1111-111111111111",
    ]

    code, rows = _run_jsonl(["--workspace-root", "/home/ubuntu/work", "--reverse"])
    assert [r["id"] for r in rows] == [
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    ]


def test_sort_by_name_defaults_ascending(stores):
    claude_dir, codex_dir = stores
    make_claude_session(
        claude_dir, "/home/ubuntu/work/a", "11111111-1111-1111-1111-111111111111", renamed_to="zeta"
    )
    make_claude_session(
        claude_dir, "/home/ubuntu/work/b", "22222222-2222-2222-2222-222222222222", renamed_to="alpha"
    )
    code, rows = _run_jsonl(["--workspace-root", "/home/ubuntu/work", "--sort", "name"])
    assert [r["name"] for r in rows] == ["alpha", "zeta"]


def test_since_and_until_filter_on_updated_at(stores):
    claude_dir, codex_dir = stores
    make_claude_session(claude_dir, "/home/ubuntu/work/a", "11111111-1111-1111-1111-111111111111")
    import datetime as dt

    far_future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=3650)).date().isoformat()
    far_past = "1990-01-01"

    code, rows = _run_jsonl(["--workspace-root", "/home/ubuntu/work", "--since", far_future])
    assert code == 0
    assert rows == []

    code, rows = _run_jsonl(["--workspace-root", "/home/ubuntu/work", "--since", far_past])
    assert len(rows) == 1

    code, rows = _run_jsonl(["--workspace-root", "/home/ubuntu/work", "--until", far_past])
    assert rows == []

    code, rows = _run_jsonl(["--workspace-root", "/home/ubuntu/work", "--until", far_future])
    assert len(rows) == 1


def test_table_format_default_is_table(stores, capsys):
    claude_dir, codex_dir = stores
    make_claude_session(
        claude_dir, "/home/ubuntu/work/a", "11111111-1111-1111-1111-111111111111", renamed_to="alpha"
    )
    code = main(["--workspace-root", "/home/ubuntu/work"])
    assert code == 0
    out = capsys.readouterr().out
    assert "PROVIDER" in out
    assert "alpha" in out


def test_json_format_is_a_single_array(stores, capsys):
    claude_dir, codex_dir = stores
    make_claude_session(claude_dir, "/home/ubuntu/work/a", "11111111-1111-1111-1111-111111111111")
    code = main(["--workspace-root", "/home/ubuntu/work", "--format", "json"])
    assert code == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert isinstance(parsed, list)
    assert len(parsed) == 1


def test_claude_dir_and_codex_dir_flags_override_env(tmp_path, monkeypatch):
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.delenv("AGENT_SESSIONS_WORKSPACE_ROOT", raising=False)
    claude_dir = tmp_path / "explicit-claude"
    codex_dir = tmp_path / "explicit-codex"
    make_claude_session(claude_dir, "/home/ubuntu/work/a", "11111111-1111-1111-1111-111111111111")
    code, rows = _run_jsonl(
        [
            "--claude-dir", str(claude_dir),
            "--codex-dir", str(codex_dir),
            "--workspace-root", "/home/ubuntu/work",
        ]
    )
    assert code == 0
    assert len(rows) == 1
