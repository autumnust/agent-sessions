"""Scan Claude Code and Codex CLI on-disk session stores.

Neither tool exposes a public API or subcommand for listing sessions, so
this module reads their transcript files directly:

  Claude Code: ``$CLAUDE_CONFIG_DIR/projects/<escaped-cwd>/<session-id>.jsonl``
      One file per session; it grows in place across resumes. Some lines
      carry a ``cwd`` and ``timestamp`` field directly. A ``/rename`` in
      the session shows up as a line containing the literal text
      ``Session renamed to: <name></local-command-stdout>``; the file is
      scanned for the last occurrence, so the most recent rename wins.

  Codex CLI: ``$CODEX_HOME/sessions/YYYY/MM/DD/rollout-<ts>-<id>.jsonl``
      One file per session *or per resume* -- resuming a session can
      start a new rollout file that references the original thread via
      ``session_id`` / ``parent_thread_id`` in its first record. The
      first line is always a ``session_meta`` record carrying ``id``,
      ``cwd``, and ``timestamp``. Renames are logged separately, as an
      append-only ``id`` -> ``thread_name`` history in
      ``$CODEX_HOME/session_index.jsonl``; the entry with the latest
      ``updated_at`` per id wins.

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


# --------------------------------------------------------------------------
# Claude Code
# --------------------------------------------------------------------------


def iter_claude_sessions(claude_dir: Path) -> Iterator[Session]:
    """Yield one Session per Claude Code transcript under *claude_dir*."""
    projects_dir = claude_dir / "projects"
    if not projects_dir.is_dir():
        return
    for project_dir in sorted(p for p in projects_dir.iterdir() if p.is_dir()):
        for jsonl_path in sorted(project_dir.glob("*.jsonl")):
            session = _parse_claude_transcript(jsonl_path)
            if session is not None:
                yield session


def _parse_claude_transcript(path: Path) -> Optional[Session]:
    updated_at = _file_mtime(path)
    if updated_at is None:
        return None

    session_id = path.stem
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
        return None

    return Session(
        provider="claude",
        id=session_id,
        name=name,
        cwd=cwd,
        started_at=started_at,
        updated_at=updated_at,
        path=path,
    )


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
    parent_id: Optional[str] = None
    cwd: Optional[str] = None
    started_at: Optional[dt.datetime] = None

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
        parent_id = payload.get("parent_thread_id")
        cwd_value = payload.get("cwd")
        if isinstance(cwd_value, str):
            cwd = cwd_value
        started_at = _parse_timestamp(record.get("timestamp") or payload.get("timestamp"))

    if not session_id:
        session_id = _fallback_id_from_filename(path)

    name = None
    for candidate in (session_id, alt_id, parent_id):
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
