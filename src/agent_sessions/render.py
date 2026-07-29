"""Render a list of Session objects as table, json, or jsonl output.

The default table is *grouped*: sessions are collected under a heading for
the workspace directory they ran in, and a coordinator's subagents are
drawn as a tree beneath it. Blank lines separate one workspace from the
next, and set a coordinator-plus-subagents block apart from the
single-row sessions around it, so the eye can find the boundaries without
re-reading the paths.

``--flat`` (``tree=False``) turns all of that off and prints one plain row
per session with an explicit WORKSPACE column -- the shape to reach for
when piping table output through ``grep``/``awk`` rather than reading it.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .models import Session

_FLAT_COLUMNS = ("PROVIDER", "UPDATED", "NAME", "WORKSPACE", "ID")
_FLAT_LONG_COLUMNS = ("PROVIDER", "UPDATED", "STARTED", "NAME", "WORKSPACE", "ID", "PATH")
# The grouped table drops WORKSPACE: the workspace is the group heading, so
# repeating it on every row is the noise this layout exists to remove.
#
# NAME comes last on purpose. It is the only free-form cell -- most sessions
# are never named, so padding it to the width of the longest subagent
# description would strand the fixed columns behind a gutter of "-". Last
# also means its width is never padded at all, which keeps CJK and other
# double-width names from shifting the columns after them (str padding
# counts code points, the terminal draws cells).
_GROUPED_COLUMNS = ("PROVIDER", "UPDATED", "ID", "NAME")
_GROUPED_LONG_COLUMNS = ("PROVIDER", "UPDATED", "STARTED", "ID", "NAME", "PATH")

_SHORT_ID_LEN = 8
_UNKNOWN_WORKSPACE = "(unknown workspace)"

_LAST = "└─ "  # "└─ "
_MID = "├─ "  # "├─ "
_PIPE = "│  "  # "│  "
_GAP = "   "


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
        if tree:
            return _render_grouped_table(sessions, long=long, header=header)
        return _render_flat_table(sessions, long=long, header=header)
    raise ValueError(f"unknown format: {fmt!r}")


def _fmt_time(value) -> str:
    if value is None:
        return "-"
    return value.astimezone().strftime("%Y-%m-%d %H:%M")


def _short_id(session_id: str) -> str:
    return session_id[:_SHORT_ID_LEN] if len(session_id) > _SHORT_ID_LEN else session_id


def _display_path(path: Optional[str]) -> str:
    """Shorten an absolute path by collapsing the home directory to ``~``."""
    if not path:
        return _UNKNOWN_WORKSPACE
    home = os.path.expanduser("~")
    if home and home != os.sep:
        if path == home:
            return "~"
        if path.startswith(home + os.sep):
            return "~" + path[len(home) :]
    return path


# --------------------------------------------------------------------------
# Tree construction
# --------------------------------------------------------------------------


def _child_map(sessions: List[Session]) -> Tuple[Dict[str, List[Session]], Set[str]]:
    """Return ({parent id: children}, {ids that are nested under a parent}).

    A session whose ``parent_id`` doesn't resolve within the current,
    already filtered/sorted *sessions* list (parent excluded by a filter,
    or the link is simply unknown) is left out of ``nested`` so it still
    renders as its own top-level row rather than being silently dropped.
    """
    by_id: Dict[str, Session] = {s.id: s for s in sessions}
    children: Dict[str, List[Session]] = {}
    nested: Set[str] = set()
    for s in sessions:
        if s.parent_id and s.parent_id in by_id and s.parent_id != s.id:
            children.setdefault(s.parent_id, []).append(s)
            nested.add(s.id)
    return children, nested


def _blocks(sessions: List[Session]) -> List[List[Tuple[Session, str]]]:
    """Group *sessions* into blocks of (session, tree prefix) pairs.

    Each block starts with one top-level session and is followed by its
    descendants in depth-first order, each carrying the prefix string that
    draws its position in the tree. Blocks come out in the order their
    top-level session appears in *sessions*, so whatever sort the caller
    applied still governs the output.
    """
    children, nested = _child_map(sessions)
    blocks: List[List[Tuple[Session, str]]] = []
    visited: Set[str] = set()

    def walk(session: Session, prefix: str, block: List[Tuple[Session, str]]) -> None:
        if session.id in visited:
            return  # defends against a cyclic parent_id in corrupt/adversarial data
        visited.add(session.id)
        block.append((session, prefix))
        kids = children.get(session.id, [])
        for i, child in enumerate(kids):
            last = i == len(kids) - 1
            # The parent's own branch glyph is replaced by a continuation
            # bar (or blank, if the parent was the last child) so deeper
            # levels line up under the branch that produced them.
            base = prefix.replace(_LAST, _GAP).replace(_MID, _PIPE)
            walk(child, base + (_LAST if last else _MID), block)

    for s in sessions:
        if s.id in nested:
            continue
        block: List[Tuple[Session, str]] = []
        walk(s, "", block)
        if block:
            blocks.append(block)

    return blocks


# --------------------------------------------------------------------------
# Rows
# --------------------------------------------------------------------------


def _name_cell(session: Session, prefix: str, group_cwd: Optional[str]) -> str:
    name = session.name or session.role or "-"
    # A subagent almost always shares its coordinator's directory, which the
    # group heading already states. Call out the exception rather than
    # carrying a mostly-empty WORKSPACE column for it.
    if prefix and session.cwd and session.cwd != group_cwd:
        name = f"{name}  (in {_display_path(session.cwd)})"
    return prefix + name


def _grouped_row(
    session: Session, prefix: str, group_cwd: Optional[str], long: bool
) -> List[str]:
    cells = [session.provider, _fmt_time(session.updated_at)]
    if long:
        cells.append(_fmt_time(session.started_at))
    cells.append(session.id if long else _short_id(session.id))
    cells.append(_name_cell(session, prefix, group_cwd))
    if long:
        cells.append(str(session.path))
    return cells


def _flat_row(session: Session, long: bool) -> List[str]:
    cells = [session.provider, _fmt_time(session.updated_at)]
    if long:
        cells.append(_fmt_time(session.started_at))
    cells.append(session.name or session.role or "-")
    cells.append(session.cwd or "-")
    cells.append(session.id if long else _short_id(session.id))
    if long:
        cells.append(str(session.path))
    return cells


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _tally(blocks: Sequence[List[Tuple[Session, str]]]) -> Tuple[int, int]:
    """Return (top-level sessions, subagents) across *blocks*.

    A block is one top-level session plus its descendants, so the two
    numbers partition the rows -- nothing is counted twice, and their sum
    is the number of printed rows.
    """
    tops = len(blocks)
    subagents = sum(len(block) - 1 for block in blocks)
    return tops, subagents


def _counts_phrase(tops: int, subagents: int, joiner: str) -> str:
    parts = [_plural(tops, "session")]
    if subagents:
        parts.append(_plural(subagents, "subagent"))
    return joiner.join(parts)


def _summary_line(
    groups: Sequence[Tuple[Optional[str], List[List[Tuple[Session, str]]]]]
) -> str:
    """One closing line: how much was shown, over how many workspaces, when."""
    all_blocks = [block for _, blocks in groups for block in blocks]
    tops, subagents = _tally(all_blocks)
    text = _counts_phrase(tops, subagents, " and ")
    text += f" across {_plural(len(groups), 'workspace')}"

    stamps = [session.updated_at for block in all_blocks for session, _ in block]
    if stamps:
        first = min(stamps).astimezone().strftime("%Y-%m-%d")
        last = max(stamps).astimezone().strftime("%Y-%m-%d")
        text += f", {first}" if first == last else f", {first} to {last}"
    return text


def _widths(columns: Sequence[str], rows: List[List[str]]) -> List[int]:
    widths = [len(c) for c in columns]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    return widths


def _line(cells: Sequence[str], widths: Sequence[int]) -> str:
    return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells)).rstrip()


# --------------------------------------------------------------------------
# Table variants
# --------------------------------------------------------------------------


def _render_flat_table(sessions: List[Session], *, long: bool, header: bool) -> str:
    columns = _FLAT_LONG_COLUMNS if long else _FLAT_COLUMNS
    rows = [_flat_row(s, long) for s in sessions]
    widths = _widths(columns, rows)

    lines: List[str] = []
    if header:
        lines.append(_line(columns, widths))
    lines.extend(_line(row, widths) for row in rows)
    return "\n".join(lines)


def _render_grouped_table(sessions: List[Session], *, long: bool, header: bool) -> str:
    columns = _GROUPED_LONG_COLUMNS if long else _GROUPED_COLUMNS

    # Group blocks by the workspace of their top-level session, keeping the
    # order in which each workspace first appears so the caller's sort still
    # decides which workspace leads.
    groups: List[Tuple[Optional[str], List[List[Tuple[Session, str]]]]] = []
    index: Dict[Optional[str], int] = {}
    for block in _blocks(sessions):
        cwd = block[0][0].cwd
        if cwd not in index:
            index[cwd] = len(groups)
            groups.append((cwd, []))
        groups[index[cwd]][1].append(block)

    # Widths are computed across every group so the columns line up down the
    # whole table, not just within one workspace.
    all_rows = [
        _grouped_row(session, prefix, cwd, long)
        for cwd, blocks in groups
        for block in blocks
        for session, prefix in block
    ]
    widths = _widths(columns, all_rows)

    lines: List[str] = []
    if header:
        lines.append(_line(columns, widths))

    for cwd, blocks in groups:
        lines.append("")
        lines.append(f"{_display_path(cwd)}  ({_counts_phrase(*_tally(blocks), ', ')})")
        previous_was_tall = False
        for i, block in enumerate(blocks):
            tall = len(block) > 1
            # Set a coordinator-plus-subagents block apart from its
            # neighbours; runs of plain single-row sessions stay packed so
            # the table doesn't double in height for no added meaning.
            if i > 0 and (tall or previous_was_tall):
                lines.append("")
            for session, prefix in block:
                lines.append(_line(_grouped_row(session, prefix, cwd, long), widths))
            previous_was_tall = tall

    # The footer is chrome, like the column header: --no-header is asking
    # for rows and headings only, so it drops both.
    if header and groups:
        lines.append("")
        lines.append(_summary_line(groups))

    if not header and lines and lines[0] == "":
        lines.pop(0)
    return "\n".join(lines)
