"""Builders for synthetic Claude Code / Codex CLI session stores, used by tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


def write_jsonl(path: Path, records: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record) + "\n")


def claude_project_dir(claude_dir: Path, cwd: str) -> Path:
    return claude_dir / "projects" / cwd.replace("/", "-")


def make_claude_session(
    claude_dir: Path,
    cwd: str,
    session_id: str,
    *,
    renamed_to: Optional[str] = None,
    timestamp: str = "2026-07-01T10:00:00.000Z",
) -> Path:
    """Write a minimal but representative Claude Code transcript file."""
    project_dir = claude_project_dir(claude_dir, cwd)
    records: List[dict] = [
        {"type": "mode", "mode": "normal", "sessionId": session_id},
        {
            "type": "user",
            "message": {"role": "user", "content": "hello"},
            "cwd": cwd,
            "timestamp": timestamp,
            "sessionId": session_id,
        },
    ]
    if renamed_to:
        records.append(
            {
                "type": "system",
                "subtype": "local_command",
                "content": (
                    f"<local-command-stdout>Session renamed to: "
                    f"{renamed_to}</local-command-stdout>"
                ),
                "cwd": cwd,
                "sessionId": session_id,
            }
        )
    path = project_dir / f"{session_id}.jsonl"
    write_jsonl(path, records)
    return path


def make_codex_session(
    codex_dir: Path,
    cwd: str,
    session_id: str,
    *,
    timestamp: str = "2026-07-02T10:00:00.000Z",
    day: str = "2026/07/02",
    session_id_field: Optional[str] = None,
    parent_thread_id: Optional[str] = None,
    rollout_id: Optional[str] = None,
    thread_source: Optional[str] = None,
    agent_role: Optional[str] = None,
    agent_nickname: Optional[str] = None,
) -> Path:
    """Write a minimal but representative Codex CLI rollout file."""
    file_id = rollout_id or session_id
    ts_for_name = timestamp.replace(":", "-").split(".")[0]
    rollout_dir = codex_dir / "sessions" / day
    path = rollout_dir / f"rollout-{ts_for_name}-{file_id}.jsonl"
    payload = {"id": file_id, "cwd": cwd, "timestamp": timestamp}
    if session_id_field:
        payload["session_id"] = session_id_field
    if parent_thread_id:
        payload["parent_thread_id"] = parent_thread_id
    if thread_source:
        payload["thread_source"] = thread_source
    if agent_role:
        payload["agent_role"] = agent_role
    if agent_nickname:
        payload["agent_nickname"] = agent_nickname
    records = [
        {"timestamp": timestamp, "type": "session_meta", "payload": payload},
        {
            "timestamp": timestamp,
            "type": "event_msg",
            "payload": {"type": "user_message", "message": "hi"},
        },
    ]
    write_jsonl(path, records)
    return path


def make_claude_subagent(
    claude_dir: Path,
    cwd: str,
    coordinator_id: str,
    agent_hash: str,
    *,
    agent_type: Optional[str] = "general-purpose",
    description: Optional[str] = "Investigate the sampler",
    timestamp: str = "2026-07-01T10:05:00.000Z",
) -> Path:
    """Write a minimal Claude Code subagent transcript + its .meta.json sidecar."""
    project_dir = claude_project_dir(claude_dir, cwd)
    subagents_dir = project_dir / coordinator_id / "subagents"
    agent_id = f"agent-{agent_hash}"
    records = [
        {
            "type": "user",
            "message": {"role": "user", "content": "go"},
            "cwd": cwd,
            "timestamp": timestamp,
            "agentId": agent_hash,
        },
    ]
    write_jsonl(subagents_dir / f"{agent_id}.jsonl", records)
    meta = {}
    if agent_type:
        meta["agentType"] = agent_type
    if description:
        meta["description"] = description
    (subagents_dir / f"{agent_id}.meta.json").write_text(json.dumps(meta))
    return subagents_dir / f"{agent_id}.jsonl"


def write_codex_index(codex_dir: Path, entries: Iterable[Tuple[str, str, str]]) -> Path:
    """entries: iterable of (id, thread_name, updated_at)."""
    path = codex_dir / "session_index.jsonl"
    records = [{"id": i, "thread_name": n, "updated_at": u} for i, n, u in entries]
    write_jsonl(path, records)
    return path
