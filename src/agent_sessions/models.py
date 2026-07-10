"""Data model for a single scanned agent session."""

from __future__ import annotations

import dataclasses
import datetime as dt
from pathlib import Path
from typing import Optional


@dataclasses.dataclass
class Session:
    """One coding-agent session, normalized across providers.

    provider     "claude" or "codex".
    id           The session/thread identifier used by the provider.
    name         Human-assigned name, if the session was ever renamed.
                 None if it never was. Subagents are never independently
                 renamed, so this is always None for them; see role.
    cwd          Working directory the session was started in, if it
                 could be recovered from the transcript.
    started_at   Timestamp of the session's first recorded event, if
                 recoverable.
    updated_at   Last-modified time of the underlying transcript file
                 (used as the "last activity" signal for both providers).
    path         Path to the transcript file backing this session.
    parent_id    id of the coordinator session this row was spawned from
                 as a subagent. None for top-level/coordinator sessions
                 and for plain resumes of the same thread -- only set for
                 an actual coordinator -> subagent fan-out.
    role         Short label for what this subagent was doing (its agent
                 type/nickname, or task description). None for top-level
                 sessions, which are identified by name/cwd instead.
    """

    provider: str
    id: str
    name: Optional[str]
    cwd: Optional[str]
    started_at: Optional[dt.datetime]
    updated_at: dt.datetime
    path: Path
    parent_id: Optional[str] = None
    role: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "id": self.id,
            "name": self.name,
            "cwd": self.cwd,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "updated_at": self.updated_at.isoformat(),
            "path": str(self.path),
            "parent_id": self.parent_id,
            "role": self.role,
        }
