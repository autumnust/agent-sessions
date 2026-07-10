"""Render a list of Session objects as table, json, or jsonl output."""

from __future__ import annotations

import json
from typing import Dict, List, Optional, Set

from .models import Session

_TABLE_COLUMNS = ("PROVIDER", "UPDATED", "NAME", "WORKSPACE", "ID")
_LONG_COLUMNS = ("PROVIDER", "UPDATED", "STARTED", "NAME", "WORKSPACE", "ID", "PATH")
_SHORT_ID_LEN = 8
_BRANCH = "└─ "  # "└─ "


def render(
    sessions: List[Session],
    fmt: str,
    *,
    long: bool = False,
    header: bool = True,
    tree: bool = True,
) -> str:
    if fmt == "json":
        return json.dumps([s.to_dict() for s in sessions], indent=2)
    if fmt == "jsonl":
        return "\n".join(json.dumps(s.to_dict()) for s in sessions)
    if fmt == "table":
        return _render_table(sessions, long=long, header=header, tree=tree)
    raise ValueError(f"unknown format: {fmt!r}")


def _fmt_time(value) -> str:
    if value is None:
        return "-"
    return value.astimezone().strftime("%Y-%m-%d %H:%M")


def _short_id(session_id: str) -> str:
    return session_id[:_SHORT_ID_LEN] if len(session_id) > _SHORT_ID_LEN else session_id


def _row_for(
    session: Session, long: bool, *, depth: int = 0, parent: Optional[Session] = None
) -> List[str]:
    display_name = session.name or session.role or "-"
    if depth > 0:
        display_name = ("  " * (depth - 1)) + _BRANCH + display_name

    display_cwd = session.cwd or "-"
    if depth > 0 and parent is not None and session.cwd == parent.cwd:
        display_cwd = ""  # same workspace as the parent row directly above; avoid repeating it

    if long:
        return [
            session.provider,
            _fmt_time(session.updated_at),
            _fmt_time(session.started_at),
            display_name,
            display_cwd,
            session.id,
            str(session.path),
        ]
    return [
        session.provider,
        _fmt_time(session.updated_at),
        display_name,
        display_cwd,
        _short_id(session.id),
    ]


def _tree_rows(sessions: List[Session], long: bool) -> List[List[str]]:
    """Flatten *sessions* into display rows, nesting subagents under their
    coordinator (in the order the coordinator appears) instead of listing
    every id as an unrelated flat row.

    A session whose parent_id doesn't resolve within the current, already
    filtered/sorted *sessions* list (parent excluded by a filter, or the
    link is simply unknown) is rendered as a standalone top-level row
    rather than silently dropped or mis-nested.
    """
    by_id: Dict[str, Session] = {s.id: s for s in sessions}
    children: Dict[str, List[Session]] = {}
    nested_ids: Set[str] = set()
    for s in sessions:
        if s.parent_id and s.parent_id in by_id and s.parent_id != s.id:
            children.setdefault(s.parent_id, []).append(s)
            nested_ids.add(s.id)

    rows: List[List[str]] = []
    visited: Set[str] = set()

    def emit(session: Session, depth: int) -> None:
        if session.id in visited:
            return  # defends against a cyclic parent_id in corrupt/adversarial data
        visited.add(session.id)
        parent = by_id.get(session.parent_id) if depth > 0 else None
        rows.append(_row_for(session, long, depth=depth, parent=parent))
        for child in children.get(session.id, []):
            emit(child, depth + 1)

    for s in sessions:
        if s.id not in nested_ids:
            emit(s, 0)

    return rows


def _render_table(sessions: List[Session], *, long: bool, header: bool, tree: bool) -> str:
    columns = _LONG_COLUMNS if long else _TABLE_COLUMNS
    rows = _tree_rows(sessions, long) if tree else [_row_for(s, long) for s in sessions]

    widths = [len(c) for c in columns]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    lines = []
    if header:
        lines.append("  ".join(c.ljust(widths[i]) for i, c in enumerate(columns)).rstrip())
    for row in rows:
        lines.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
    return "\n".join(lines)
