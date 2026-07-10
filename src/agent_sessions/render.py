"""Render a list of Session objects as table, json, or jsonl output."""

from __future__ import annotations

import json
from typing import List

from .models import Session

_TABLE_COLUMNS = ("PROVIDER", "UPDATED", "NAME", "WORKSPACE", "ID")
_LONG_COLUMNS = ("PROVIDER", "UPDATED", "STARTED", "NAME", "WORKSPACE", "ID", "PATH")
_SHORT_ID_LEN = 8


def render(sessions: List[Session], fmt: str, *, long: bool = False, header: bool = True) -> str:
    if fmt == "json":
        return json.dumps([s.to_dict() for s in sessions], indent=2)
    if fmt == "jsonl":
        return "\n".join(json.dumps(s.to_dict()) for s in sessions)
    if fmt == "table":
        return _render_table(sessions, long=long, header=header)
    raise ValueError(f"unknown format: {fmt!r}")


def _fmt_time(value) -> str:
    if value is None:
        return "-"
    return value.astimezone().strftime("%Y-%m-%d %H:%M")


def _short_id(session_id: str) -> str:
    return session_id[:_SHORT_ID_LEN] if len(session_id) > _SHORT_ID_LEN else session_id


def _row_for(session: Session, long: bool) -> List[str]:
    if long:
        return [
            session.provider,
            _fmt_time(session.updated_at),
            _fmt_time(session.started_at),
            session.name or "-",
            session.cwd or "-",
            session.id,
            str(session.path),
        ]
    return [
        session.provider,
        _fmt_time(session.updated_at),
        session.name or "-",
        session.cwd or "-",
        _short_id(session.id),
    ]


def _render_table(sessions: List[Session], *, long: bool, header: bool) -> str:
    columns = _LONG_COLUMNS if long else _TABLE_COLUMNS
    rows = [_row_for(s, long) for s in sessions]

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
