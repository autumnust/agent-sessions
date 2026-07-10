"""Tests for agent_sessions.discovery."""

from __future__ import annotations

from agent_sessions.discovery import discover, iter_claude_sessions, iter_codex_sessions

from .helpers import (
    claude_project_dir,
    make_claude_session,
    make_codex_session,
    write_codex_index,
    write_jsonl,
)


class TestClaudeDiscovery:
    def test_basic_fields(self, tmp_path):
        claude_dir = tmp_path / "claude"
        make_claude_session(
            claude_dir, "/home/ubuntu/work/proj-a", "11111111-1111-1111-1111-111111111111"
        )
        sessions = list(iter_claude_sessions(claude_dir))
        assert len(sessions) == 1
        s = sessions[0]
        assert s.provider == "claude"
        assert s.id == "11111111-1111-1111-1111-111111111111"
        assert s.cwd == "/home/ubuntu/work/proj-a"
        assert s.name is None
        assert s.started_at is not None
        assert s.updated_at is not None

    def test_rename_is_picked_up_and_last_one_wins(self, tmp_path):
        claude_dir = tmp_path / "claude"
        project_dir = claude_project_dir(claude_dir, "/home/ubuntu/work/proj-a")
        records = [
            {
                "type": "user",
                "message": {},
                "cwd": "/home/ubuntu/work/proj-a",
                "timestamp": "2026-07-01T10:00:00.000Z",
                "sessionId": "s1",
            },
            {
                "type": "system",
                "subtype": "local_command",
                "content": "<local-command-stdout>Session renamed to: first_name</local-command-stdout>",
            },
            {
                "type": "system",
                "subtype": "local_command",
                "content": "<local-command-stdout>Session renamed to: second_name</local-command-stdout>",
            },
        ]
        write_jsonl(project_dir / "s1.jsonl", records)
        sessions = list(iter_claude_sessions(claude_dir))
        assert len(sessions) == 1
        assert sessions[0].name == "second_name"

    def test_rename_text_inside_unrelated_tool_payload_is_not_a_false_positive(self, tmp_path):
        # A session that writes a file (or test fixture) containing this
        # exact rename-confirmation text as *data* must not be mistaken for
        # an actual rename. Regression test for a real false positive hit
        # while smoke-testing this tool against its own live session, whose
        # transcript logged its own source files being written.
        claude_dir = tmp_path / "claude"
        project_dir = claude_project_dir(claude_dir, "/home/ubuntu/work/proj-a")
        records = [
            {
                "type": "user",
                "message": {},
                "cwd": "/home/ubuntu/work/proj-a",
                "timestamp": "2026-07-01T10:00:00.000Z",
                "sessionId": "s1",
            },
            {
                "type": "system",
                "subtype": "local_command",
                "content": "<local-command-stdout>Session renamed to: real_name</local-command-stdout>",
            },
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Write",
                            "input": {
                                "file_path": "/tmp/example.py",
                                "content": (
                                    "Session renamed to: not_a_real_rename"
                                    "</local-command-stdout>"
                                ),
                            },
                        }
                    ],
                },
            },
        ]
        write_jsonl(project_dir / "s1.jsonl", records)
        sessions = list(iter_claude_sessions(claude_dir))
        assert len(sessions) == 1
        assert sessions[0].name == "real_name"

    def test_malformed_line_does_not_crash(self, tmp_path):
        claude_dir = tmp_path / "claude"
        project_dir = claude_project_dir(claude_dir, "/home/ubuntu/work/proj-a")
        project_dir.mkdir(parents=True)
        path = project_dir / "s1.jsonl"
        path.write_text(
            '{"cwd": "/home/ubuntu/work/proj-a", "timestamp": "2026-07-01T10:00:00.000Z"}\n'
            "not json at all\n"
        )
        sessions = list(iter_claude_sessions(claude_dir))
        assert len(sessions) == 1
        assert sessions[0].cwd == "/home/ubuntu/work/proj-a"
        assert sessions[0].started_at is not None

    def test_empty_file_yields_session_with_no_metadata(self, tmp_path):
        claude_dir = tmp_path / "claude"
        project_dir = claude_project_dir(claude_dir, "/home/ubuntu/work/proj-a")
        project_dir.mkdir(parents=True)
        (project_dir / "s1.jsonl").write_text("")
        sessions = list(iter_claude_sessions(claude_dir))
        assert len(sessions) == 1
        assert sessions[0].cwd is None
        assert sessions[0].name is None

    def test_missing_projects_dir_yields_nothing(self, tmp_path):
        assert list(iter_claude_sessions(tmp_path / "nope")) == []

    def test_ignores_non_jsonl_entries(self, tmp_path):
        claude_dir = tmp_path / "claude"
        project_dir = claude_project_dir(claude_dir, "/home/ubuntu/work/proj-a")
        project_dir.mkdir(parents=True)
        (project_dir / "not-a-session").mkdir()
        (project_dir / "notes.txt").write_text("irrelevant")
        make_claude_session(
            claude_dir, "/home/ubuntu/work/proj-a", "11111111-1111-1111-1111-111111111111"
        )
        sessions = list(iter_claude_sessions(claude_dir))
        assert len(sessions) == 1


class TestCodexDiscovery:
    def test_basic_fields(self, tmp_path):
        codex_dir = tmp_path / "codex"
        make_codex_session(
            codex_dir, "/home/ubuntu/work/proj-b", "22222222-2222-2222-2222-222222222222"
        )
        sessions = list(iter_codex_sessions(codex_dir))
        assert len(sessions) == 1
        s = sessions[0]
        assert s.provider == "codex"
        assert s.id == "22222222-2222-2222-2222-222222222222"
        assert s.cwd == "/home/ubuntu/work/proj-b"
        assert s.name is None
        assert s.started_at is not None

    def test_name_resolved_from_index_latest_by_updated_at_wins(self, tmp_path):
        codex_dir = tmp_path / "codex"
        sid = "33333333-3333-3333-3333-333333333333"
        make_codex_session(codex_dir, "/home/ubuntu/work/proj-c", sid)
        # Written out of chronological order on purpose: the index must be
        # sorted by updated_at, not trusted to be in file order.
        write_codex_index(
            codex_dir,
            [
                (sid, "new_name", "2026-07-05T00:00:00Z"),
                (sid, "old_name", "2026-07-01T00:00:00Z"),
            ],
        )
        sessions = list(iter_codex_sessions(codex_dir))
        assert sessions[0].name == "new_name"

    def test_name_resolved_via_session_id_fallback(self, tmp_path):
        codex_dir = tmp_path / "codex"
        thread_id = "44444444-4444-4444-4444-444444444444"
        rollout_id = "55555555-5555-5555-5555-555555555555"
        make_codex_session(
            codex_dir,
            "/home/ubuntu/work/proj-d",
            thread_id,
            rollout_id=rollout_id,
            session_id_field=thread_id,
            day="2026/07/03",
        )
        write_codex_index(codex_dir, [(thread_id, "resumed_thread", "2026-07-03T09:00:00Z")])
        sessions = list(iter_codex_sessions(codex_dir))
        assert len(sessions) == 1
        assert sessions[0].id == rollout_id
        assert sessions[0].name == "resumed_thread"

    def test_name_resolved_via_parent_thread_id_fallback(self, tmp_path):
        codex_dir = tmp_path / "codex"
        parent_id = "66666666-6666-6666-6666-666666666666"
        rollout_id = "77777777-7777-7777-7777-777777777777"
        make_codex_session(
            codex_dir,
            "/home/ubuntu/work/proj-e",
            parent_id,
            rollout_id=rollout_id,
            parent_thread_id=parent_id,
            day="2026/07/04",
        )
        write_codex_index(codex_dir, [(parent_id, "spawned_from", "2026-07-04T09:00:00Z")])
        sessions = list(iter_codex_sessions(codex_dir))
        assert sessions[0].name == "spawned_from"

    def test_malformed_first_line_falls_back_to_filename_id(self, tmp_path):
        codex_dir = tmp_path / "codex"
        rollout_dir = codex_dir / "sessions" / "2026" / "07" / "04"
        rollout_dir.mkdir(parents=True)
        rid = "88888888-8888-8888-8888-888888888888"
        path = rollout_dir / f"rollout-2026-07-04T11-00-00-{rid}.jsonl"
        path.write_text("not json\n")
        sessions = list(iter_codex_sessions(codex_dir))
        assert len(sessions) == 1
        assert sessions[0].id == rid
        assert sessions[0].cwd is None
        assert sessions[0].started_at is None

    def test_missing_session_index_does_not_crash(self, tmp_path):
        codex_dir = tmp_path / "codex"
        make_codex_session(
            codex_dir, "/home/ubuntu/work/proj-f", "99999999-9999-9999-9999-999999999999"
        )
        sessions = list(iter_codex_sessions(codex_dir))
        assert sessions[0].name is None

    def test_missing_sessions_dir_yields_nothing(self, tmp_path):
        assert list(iter_codex_sessions(tmp_path / "nope")) == []


def test_discover_combines_both_providers(tmp_path):
    claude_dir = tmp_path / "claude"
    codex_dir = tmp_path / "codex"
    make_claude_session(
        claude_dir, "/home/ubuntu/work/proj-a", "11111111-1111-1111-1111-111111111111"
    )
    make_codex_session(
        codex_dir, "/home/ubuntu/work/proj-b", "22222222-2222-2222-2222-222222222222"
    )
    sessions = list(discover(["claude", "codex"], claude_dir, codex_dir))
    assert {s.provider for s in sessions} == {"claude", "codex"}


def test_discover_respects_provider_selection(tmp_path):
    claude_dir = tmp_path / "claude"
    codex_dir = tmp_path / "codex"
    make_claude_session(
        claude_dir, "/home/ubuntu/work/proj-a", "11111111-1111-1111-1111-111111111111"
    )
    make_codex_session(
        codex_dir, "/home/ubuntu/work/proj-b", "22222222-2222-2222-2222-222222222222"
    )
    sessions = list(discover(["codex"], claude_dir, codex_dir))
    assert len(sessions) == 1
    assert sessions[0].provider == "codex"
