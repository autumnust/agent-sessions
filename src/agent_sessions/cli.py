"""Command-line entry point for agent-sessions."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path
from typing import List, Optional, Sequence

from . import __version__
from .discovery import discover
from .models import Session
from .render import render

DEFAULT_WORKSPACE_ROOTS = ["/home/ubuntu/work"]
ENV_WORKSPACE_ROOT = "AGENT_SESSIONS_WORKSPACE_ROOT"

EXAMPLES = """\
examples:
  agent-sessions
        List sessions under the default workspace root, most recently
        updated first.

  agent-sessions --named-only
        Only show sessions you bothered to name.

  agent-sessions -p codex -q sampler
        Codex sessions whose name contains "sampler".

  agent-sessions --all-workspaces --format jsonl | jq -r '.name'
        Every session on the machine, names only -- for scripts or agents.

  agent-sessions --since 2026-07-01 --sort started --reverse
        Sessions started on/after 2026-07-01, oldest first.

See agent-sessions(1) for the full manual (man ./man/agent-sessions.1
works directly from a checkout without installing it).
"""


def _default_claude_dir() -> str:
    return os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")


def _default_codex_dir() -> str:
    return os.environ.get("CODEX_HOME") or str(Path.home() / ".codex")


def _default_workspace_roots() -> List[str]:
    env_value = os.environ.get(ENV_WORKSPACE_ROOT)
    if env_value:
        return [p for p in env_value.split(os.pathsep) if p]
    return list(DEFAULT_WORKSPACE_ROOTS)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-sessions",
        description=(
            "List and filter Claude Code and Codex CLI session transcripts "
            "found on this machine."
        ),
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-V", "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "-p", "--provider",
        choices=["claude", "codex", "all"], default="all",
        help="restrict to one provider (default: %(default)s)",
    )
    parser.add_argument(
        "-w", "--workspace-root",
        action="append", dest="workspace_roots", metavar="PATH",
        help=(
            "only include sessions whose working directory is PATH or "
            "below it; repeatable. Default: $" + ENV_WORKSPACE_ROOT +
            " if set, else " + DEFAULT_WORKSPACE_ROOTS[0]
        ),
    )
    parser.add_argument(
        "-A", "--all-workspaces", action="store_true",
        help="disable the workspace-root filter; include every session found",
    )
    parser.add_argument(
        "-n", "--named-only", action="store_true",
        help="skip sessions that were never given a name",
    )
    parser.add_argument(
        "-q", "--query", metavar="TEXT",
        help="case-insensitive substring match against the session name",
    )
    parser.add_argument(
        "--since", metavar="DATETIME",
        help="only sessions last updated at/after this ISO-8601 date/time",
    )
    parser.add_argument(
        "--until", metavar="DATETIME",
        help="only sessions last updated at/before this ISO-8601 date/time",
    )
    parser.add_argument(
        "-s", "--sort",
        choices=["updated", "started", "name"], default="updated",
        help="sort key (default: %(default)s)",
    )
    parser.add_argument(
        "-r", "--reverse", action="store_true",
        help=(
            "reverse the default sort order: updated/started default to "
            "newest-first and become oldest-first; name defaults to A-Z "
            "and becomes Z-A"
        ),
    )
    parser.add_argument(
        "-L", "--limit", type=int, metavar="N",
        help="only show the first N results after sorting",
    )
    parser.add_argument(
        "-f", "--format",
        choices=["table", "json", "jsonl"], default="table",
        help="output format; jsonl is recommended for scripts/agents (default: %(default)s)",
    )
    parser.add_argument(
        "-l", "--long", action="store_true",
        help="table format: add started time, full id, and transcript path columns",
    )
    parser.add_argument(
        "--no-header", action="store_true",
        help="table format: omit the header row",
    )
    parser.add_argument(
        "--claude-dir", metavar="DIR", default=None,
        help="Claude Code config directory (default: $CLAUDE_CONFIG_DIR or ~/.claude)",
    )
    parser.add_argument(
        "--codex-dir", metavar="DIR", default=None,
        help="Codex CLI home directory (default: $CODEX_HOME or ~/.codex)",
    )
    return parser


def _parse_datetime(value: str) -> dt.datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed


def _matches_workspace(cwd: Optional[str], roots: Sequence[str]) -> bool:
    if not roots:
        return True
    if cwd is None:
        return False
    normalized = os.path.normpath(cwd)
    for root in roots:
        root_norm = os.path.normpath(root)
        if normalized == root_norm or normalized.startswith(root_norm + os.sep):
            return True
    return False


def _sort_key(session: Session, key: str):
    if key == "updated":
        return session.updated_at
    if key == "started":
        return session.started_at or dt.datetime.min.replace(tzinfo=dt.timezone.utc)
    return (session.name or "").lower()


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    providers = ["claude", "codex"] if args.provider == "all" else [args.provider]
    claude_dir = Path(args.claude_dir or _default_claude_dir()).expanduser()
    codex_dir = Path(args.codex_dir or _default_codex_dir()).expanduser()

    if args.all_workspaces:
        roots: List[str] = []
    elif args.workspace_roots:
        roots = args.workspace_roots
    else:
        roots = _default_workspace_roots()

    try:
        since = _parse_datetime(args.since) if args.since else None
        until = _parse_datetime(args.until) if args.until else None
    except ValueError as exc:
        parser.error(f"invalid --since/--until value: {exc}")

    try:
        sessions = list(discover(providers, claude_dir, codex_dir))
    except OSError as exc:
        print(f"agent-sessions: error scanning sessions: {exc}", file=sys.stderr)
        return 1

    sessions = [s for s in sessions if _matches_workspace(s.cwd, roots)]
    if args.named_only:
        sessions = [s for s in sessions if s.name]
    if args.query:
        needle = args.query.lower()
        sessions = [s for s in sessions if s.name and needle in s.name.lower()]
    if since is not None:
        sessions = [s for s in sessions if s.updated_at >= since]
    if until is not None:
        sessions = [s for s in sessions if s.updated_at <= until]

    newest_first_by_default = args.sort in ("updated", "started")
    reverse = (not args.reverse) if newest_first_by_default else args.reverse
    sessions.sort(key=lambda s: _sort_key(s, args.sort), reverse=reverse)

    if args.limit is not None:
        sessions = sessions[: args.limit]

    output = render(sessions, args.format, long=args.long, header=not args.no_header)
    if output:
        print(output)
    return 0
