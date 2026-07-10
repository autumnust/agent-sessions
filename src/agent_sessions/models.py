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
                 None if it never was.
    cwd          Working directory the session was started in, if it
                 could be recovered from the transcript.
    started_at   Timestamp of the session's first recorded event, if
                 recoverable.
    updated_at   Last-modified time of the underlying transcript file
                 (used as the "last activity" signal for both providers).
    path         Path to the transcript file backing this session.
    """

    provider: str
    id: str
    name: Optional[str]
    cwd: Optional[str]
    started_at: Optional[dt.datetime]
    updated_at: dt.datetime
    path: Path

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "id": self.id,
            "name": self.name,
            "cwd": self.cwd,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "updated_at": self.updated_at.isoformat(),
            "path": str(self.path),
        }
