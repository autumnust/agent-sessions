# agent-sessions

List and filter [Claude Code](https://claude.com/product/claude-code) and
[Codex CLI](https://developers.openai.com/codex/cli) session transcripts from
the shell, without launching either tool.

```
$ agent-sessions --named-only
PROVIDER  UPDATED           NAME                          WORKSPACE                         ID
claude    2026-07-10 19:06  education_harness_enhancement /home/ubuntu/work/structured_dm  4c0f5d59
codex     2026-07-09 18:18  folder_structure_maintenance  /home/ubuntu/work/structured_dm  e2bec7f9
codex     2026-06-25 20:05  cudf_tensor_mapper_planning   /home/ubuntu/work/diskgraph      edee6f4b
```

## Why

Neither tool has a `sessions list` subcommand. `claude --resume` and
`codex resume` both open an interactive picker, which is the wrong shape
when you just want to know *which* session was about what, or when a script
or another agent needs that information as data. `agent-sessions` reads
their on-disk transcript stores directly and prints one line per session.

It is meant for two audiences equally: you, at a shell prompt, and any
coding agent that wants to look up prior session context for itself (hence
`--format jsonl`, and a man page written to be as useful to an agent
skimming it as to a human).

## Install

```bash
pipx install /path/to/agent-sessions      # recommended: isolated, on PATH
# or, for development:
pip install -e '.[dev]'
```

Either way installs two equivalent commands: `agent-sessions` and the
shorter alias `asess`.

## Usage

```bash
agent-sessions                                   # table, default workspace root, newest first
agent-sessions --named-only                      # only sessions you renamed
agent-sessions -p codex -q sampler                # Codex sessions with "sampler" in the name
agent-sessions --all-workspaces --format jsonl    # everything, machine-readable
agent-sessions --since 2026-07-01 --sort started --reverse
```

Full option reference:

```bash
agent-sessions --help
man ./man/agent-sessions.1        # works straight from a checkout
make man                          # installs the man page to ~/.local/share/man/man1
```

The default `--workspace-root` is `/home/ubuntu/work`, since that's where
most work happens on the machine this was built for. Override it with
`-w PATH` (repeatable), `$AGENT_SESSIONS_WORKSPACE_ROOT` (colon-separated),
or drop the filter entirely with `-A`/`--all-workspaces`.

## File formats

Both formats below are undocumented internals, reverse-engineered by
inspection, not a stable public contract. See the man page's `FILES` and
`CAVEATS` sections for the authoritative, current description; this is the
short version.

**Claude Code** writes one file per session at
`$CLAUDE_CONFIG_DIR/projects/<escaped-cwd>/<session-id>.jsonl`, appending to
it across resumes. The directory name encodes the working directory, but
lossily (`/` becomes `-`, which is ambiguous against a literal `-` in a path
component), so `agent-sessions` reads the `cwd` field that's recorded
directly on the transcript's own lines instead of decoding the directory
name. A `/rename` shows up as a `{"type": "system", "subtype":
"local_command", "content": "<local-command-stdout>Session renamed to:
...</local-command-stdout>"}` record; the file is scanned for the last one,
so the most recent rename wins. That match is deliberately scoped to
records shaped exactly like that confirmation, not a raw substring search
across the whole line -- a session transcript that happens to *write a
file* containing that same text (for example, this very tool's own test
fixtures, the first time it was smoke-tested against its own live session)
would otherwise register as a false positive.

**Codex CLI** writes one file per session, or per resume, at
`$CODEX_HOME/sessions/YYYY/MM/DD/rollout-<timestamp>-<id>.jsonl` -- resuming
a session across process restarts can start a *new* rollout file that
references the original thread via a `session_id` or `parent_thread_id`
field in its first record, rather than appending to the old one.
`agent-sessions` does not attempt to merge those into a single logical
session; each rollout file is one row. The first line is always a
`session_meta` record carrying `id`, `cwd`, and `timestamp`. Renames are
tracked separately, as an append-only `id` -> `thread_name` history in
`$CODEX_HOME/session_index.jsonl`; the entry with the latest `updated_at`
per id wins, and the lookup falls back from a rollout's own `id` to its
`session_id` then `parent_thread_id` so a resumed/spawned session still
resolves the name of the thread it belongs to.

If a scan of one provider starts coming back empty, or looks wrong, after a
tool upgrade, that provider's on-disk layout is the first thing to check --
run `agent-sessions -p <provider> --all-workspaces -l` and compare a row's
`PATH` against what's actually on disk.

## Development

```bash
pip install -e '.[dev]'
make test     # pytest
```

Tests build synthetic Claude/Codex session stores under `tmp_path` (see
`tests/helpers.py`) rather than depending on any real machine state, so they
run the same anywhere.

## License

MIT, see `LICENSE`.
