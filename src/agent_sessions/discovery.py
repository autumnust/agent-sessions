"""Scan Claude Code and Codex CLI on-disk session stores.

Neither tool exposes a public API or subcommand for listing sessions, so
this module reads their transcript files directly:

  Claude Code: ``$CLAUDE_CONFIG_DIR/projects/<escaped-cwd>/<session-id>.jsonl``
      One file per top-level session; it grows in place across resumes.
      Some lines carry a ``cwd`` and ``timestamp`` field directly. A
      ``/rename`` in the session shows up as a
      ``{"type": "system", "subtype": "local_command", "content":
      "<local-command-stdout>Session renamed to: <name>..."}`` record; the
      file is scanned for the last one, so the most recent rename wins.

      A coordinator session that spawns subagents (the Agent tool) writes
      each one to its own file at
      ``<same project dir>/<coordinator-session-id>/subagents/agent-<hash>.jsonl``,
      with a companion ``agent-<hash>.meta.json`` carrying ``agentType``
      and ``description``. Subagents are never independently renamed.

  Codex CLI: ``$CODEX_HOME/sessions/YYYY/MM/DD/rollout-<ts>-<id>.jsonl``
      One file per session *or per resume* -- resuming a session can
      start a new rollout file that references the original thread via
      ``session_id`` / ``parent_thread_id`` in its first record. The
      first line is always a ``session_meta`` record carrying ``id``,
      ``cwd``, and ``timestamp``. Renames are logged separately, as an
      append-only ``id`` -> ``thread_name`` history in
      ``$CODEX_HOME/session_index.jsonl``; the entry with the latest
      ``updated_at`` per id wins.

      A coordinator spawning a subagent also produces a new rollout file
      referencing the parent via ``parent_thread_id``, distinguished from
      a plain resume by ``thread_source == "subagent"`` (a resume's is
      ``"user"``). Only that case is treated as a fold-worthy subagent: a
      resume legitimately continues the same named thread and keeps
      inheriting its name; a subagent is a distinct, usually-unnamed
      child and should not silently borrow the coordinator's name.

Both formats are undocumented internals observed by inspection, not a
specified contract -- see the CAVEATS section of the man page.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

from .models import Session

_RENAME_RE = re.compile(r"Session renamed to:\s*(.+?)\s*</local-command-stdout>")
_ROLLOUT_FILENAME_RE = re.compile(
    r"rollout-\d{4}-\d{2}-\d{2}T[\d-]+-(?P<id>[0-9a-fA-F-]{36})\.jsonl$"
)


def _parse_timestamp(value: object) -> Optional[dt.datetime]:
    """Parse the ISO-8601-with-trailing-Z timestamps both tools use."""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return dt.datetime.fromisoformat(text)
    except ValueError:
        return None


def _file_mtime(path: Path) -> Optional[dt.datetime]:
    try:
        return dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.timezone.utc)
    except OSError:
        return None


def _read_json(path: Path) -> Optional[dict]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    try:
        record = json.loads(text)
    except json.JSONDecodeError:
        return None
    return record if isinstance(record, dict) else None


# --------------------------------------------------------------------------
# Claude Code
# --------------------------------------------------------------------------


def iter_claude_sessions(claude_dir: Path) -> Iterator[Session]:
    """Yield one Session per Claude Code transcript under *claude_dir*.

    Covers both top-level (coordinator) sessions and their subagents.
    """
    projects_dir = claude_dir / "projects"
    if not projects_dir.is_dir():
        return
    for project_dir in sorted(p for p in projects_dir.iterdir() if p.is_dir()):
        for jsonl_path in sorted(project_dir.glob("*.jsonl")):
            session = _parse_claude_transcript(jsonl_path)
            if session is not None:
                yield session
            coordinator_id = jsonl_path.stem
            subagents_dir = project_dir / coordinator_id / "subagents"
            if not subagents_dir.is_dir():
                continue
            for agent_path in sorted(subagents_dir.glob("agent-*.jsonl")):
                subagent = _parse_claude_subagent(agent_path, coordinator_id)
                if subagent is not None:
                    yield subagent


def _parse_claude_transcript(path: Path) -> Optional[Session]:
    updated_at = _file_mtime(path)
    if updated_at is None:
        return None

    cwd, started_at, name = _scan_claude_lines(path)

    return Session(
        provider="claude",
        id=path.stem,
        name=name,
        cwd=cwd,
        started_at=started_at,
        updated_at=updated_at,
        path=path,
    )


def _parse_claude_subagent(path: Path, coordinator_id: str) -> Optional[Session]:
    updated_at = _file_mtime(path)
    if updated_at is None:
        return None

    cwd, started_at, _name = _scan_claude_lines(path)

    meta = _read_json(path.with_suffix("").with_suffix(".meta.json")) or {}
    agent_type = meta.get("agentType")
    description = meta.get("description")
    if agent_type and description:
        role = f"{agent_type}: {description}"
    else:
        role = agent_type or description

    return Session(
        provider="claude",
        id=path.stem,
        name=None,
        cwd=cwd,
        started_at=started_at,
        updated_at=updated_at,
        path=path,
        parent_id=coordinator_id,
        role=role,
    )


def _scan_claude_lines(path: Path) -> Tuple[Optional[str], Optional[dt.datetime], Optional[str]]:
    """Return (cwd, started_at, name) found by scanning a transcript's lines."""
    cwd: Optional[str] = None
    started_at: Optional[dt.datetime] = None
    name: Optional[str] = None

    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue

                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue

                if cwd is None:
                    value = record.get("cwd")
                    if isinstance(value, str):
                        cwd = value
                if started_at is None:
                    started_at = _parse_timestamp(record.get("timestamp"))

                # Only trust the session's own generated rename confirmation
                # (type=system/subtype=local_command). A raw substring search
                # across the whole line would also match this exact text
                # sitting inside unrelated tool payloads -- e.g. a file this
                # very tool writes that happens to *contain* this docstring
                # or a test fixture string, which then gets logged verbatim
                # into the session transcript that wrote it.
                if record.get("type") == "system" and record.get("subtype") == "local_command":
                    content = record.get("content")
                    if isinstance(content, str):
                        match = _RENAME_RE.search(content)
                        if match:
                            name = match.group(1)
    except OSError:
        pass

    return cwd, started_at, name


# --------------------------------------------------------------------------
# Codex CLI
# --------------------------------------------------------------------------


def iter_codex_sessions(codex_dir: Path) -> Iterator[Session]:
    """Yield one Session per Codex CLI rollout file under *codex_dir*."""
    sessions_root = codex_dir / "sessions"
    if not sessions_root.is_dir():
        return
    name_index = _load_codex_name_index(codex_dir / "session_index.jsonl")
    for jsonl_path in sorted(sessions_root.rglob("*.jsonl")):
        session = _parse_codex_rollout(jsonl_path, name_index)
        if session is not None:
            yield session


def _load_codex_name_index(index_path: Path) -> Dict[str, str]:
    """Build {thread id: current name} from the rename history log.

    The log is append-only and (per observation) chronologically ordered,
    but entries are re-sorted by ``updated_at`` here rather than trusting
    file order, so the latest rename always wins even if that changes.
    """
    if not index_path.is_file():
        return {}

    entries: List[Tuple[dt.datetime, str, str]] = []
    try:
        with index_path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                sid = record.get("id")
                name = record.get("thread_name")
                if not sid or not name:
                    continue
                updated = _parse_timestamp(record.get("updated_at"))
                if updated is None:
                    updated = dt.datetime.min.replace(tzinfo=dt.timezone.utc)
                entries.append((updated, sid, name))
    except OSError:
        return {}

    entries.sort(key=lambda item: item[0])
    index: Dict[str, str] = {}
    for _, sid, name in entries:
        index[sid] = name
    return index


def _parse_codex_rollout(path: Path, name_index: Dict[str, str]) -> Optional[Session]:
    updated_at = _file_mtime(path)
    if updated_at is None:
        return None

    session_id: Optional[str] = None
    alt_id: Optional[str] = None
    thread_parent_id: Optional[str] = None
    cwd: Optional[str] = None
    started_at: Optional[dt.datetime] = None
    is_subagent = False
    agent_role: Optional[str] = None
    agent_nickname: Optional[str] = None

    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            first_line = fh.readline()
    except OSError:
        return None

    record = None
    if first_line.strip():
        try:
            record = json.loads(first_line)
        except json.JSONDecodeError:
            record = None

    if isinstance(record, dict) and record.get("type") == "session_meta":
        payload = record.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        session_id = payload.get("id")
        alt_id = payload.get("session_id")
        thread_parent_id = payload.get("parent_thread_id")
        cwd_value = payload.get("cwd")
        if isinstance(cwd_value, str):
            cwd = cwd_value
        started_at = _parse_timestamp(record.get("timestamp") or payload.get("timestamp"))

        is_subagent = payload.get("thread_source") == "subagent"
        agent_role = payload.get("agent_role")
        agent_nickname = payload.get("agent_nickname")
        if not (agent_role or agent_nickname):
            # payload["source"] is a plain string ("cli") on an ordinary
            # session and only a dict for a subagent spawn -- so every
            # step here has to tolerate the wrong shape, not just a
            # missing key.
            source = payload.get("source")
            subagent_block = source.get("subagent") if isinstance(source, dict) else None
            spawn = subagent_block.get("thread_spawn") if isinstance(subagent_block, dict) else None
            if not isinstance(spawn, dict):
                spawn = {}
            agent_role = agent_role or spawn.get("agent_role")
            agent_nickname = agent_nickname or spawn.get("agent_nickname")
            if not thread_parent_id:
                thread_parent_id = spawn.get("parent_thread_id")

    if not session_id:
        session_id = _fallback_id_from_filename(path)

    parent_id: Optional[str] = None
    role: Optional[str] = None
    name: Optional[str] = None

    if is_subagent:
        # A subagent is a distinct child of its coordinator, not a
        # continuation of it -- fold it under the coordinator instead of
        # inheriting the coordinator's name onto an unrelated row.
        parent_id = thread_parent_id or alt_id
        if agent_role and agent_nickname:
            role = f"{agent_role}:{agent_nickname}"
        else:
            role = agent_role or agent_nickname
    else:
        # A plain resume of a named thread should keep showing that name.
        for candidate in (session_id, alt_id, thread_parent_id):
            if candidate and candidate in name_index:
                name = name_index[candidate]
                break

    return Session(
        provider="codex",
        id=session_id,
        name=name,
        cwd=cwd,
        started_at=started_at,
        updated_at=updated_at,
        path=path,
        parent_id=parent_id,
        role=role,
    )


def _fallback_id_from_filename(path: Path) -> str:
    match = _ROLLOUT_FILENAME_RE.search(path.name)
    if match:
        return match.group("id")
    return path.stem


# --------------------------------------------------------------------------
# Combined
# --------------------------------------------------------------------------


def discover(providers: Iterable[str], claude_dir: Path, codex_dir: Path) -> Iterator[Session]:
    """Yield sessions from the requested providers ("claude", "codex")."""
    wanted = set(providers)
    if "claude" in wanted:
        yield from iter_claude_sessions(claude_dir)
    if "codex" in wanted:
        yield from iter_codex_sessions(codex_dir)
