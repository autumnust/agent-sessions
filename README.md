# agent-sessions

List and filter [Claude Code](https://claude.com/product/claude-code) and
[Codex CLI](https://developers.openai.com/codex/cli) session transcripts from
the shell, without launching either tool.

```
$ agent-sessions -p codex --limit 4
PROVIDER  UPDATED           NAME     WORKSPACE                         ID
codex     2026-07-10 19:21  sdk_112  /home/ubuntu/work/structured_dm  019f1641
codex     2026-07-10 18:50  └─ explorer:Jason                        019f4d59
codex     2026-07-10 18:50  └─ explorer:Nash                         019f4d5a
codex     2026-07-09 18:59  └─ worker:Laplace                        019f399e
```

A coordinator's subagents nest under it instead of showing up as unrelated
rows that happen to share its name -- see [Subagents](#subagents).

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
agent-sessions -p codex -q sampler                # sessions/subagents matching "sampler"
agent-sessions --all-workspaces --format jsonl    # everything, machine-readable
agent-sessions --since 2026-07-01 --sort started --reverse
agent-sessions --flat -p codex                    # subagents as plain rows, no nesting
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
`session_id` then `parent_thread_id` so a *resumed* session still resolves
the name of the thread it belongs to. A *subagent* spawn is deliberately
excluded from that fallback -- see below.

If a scan of one provider starts coming back empty, or looks wrong, after a
tool upgrade, that provider's on-disk layout is the first thing to check --
run `agent-sessions -p <provider> --all-workspaces -l` and compare a row's
`PATH` against what's actually on disk.

## Subagents

A coordinator session that spawns subagents links each child back to it,
but the two tools record that link completely differently, and both were
reverse-engineered the same way as everything else here:

**Claude Code** writes each subagent to its own file at
`<same project dir>/<coordinator-id>/subagents/agent-<hash>.jsonl`, with a
companion `agent-<hash>.meta.json` carrying `agentType` and `description` --
used as the subagent's role (`"<agentType>: <description>"`), since
subagents are never independently renamed.

**Codex CLI** writes each subagent to an ordinary-looking rollout file whose
first record has `payload.thread_source == "subagent"` and
`payload.parent_thread_id` pointing at the coordinator (occasionally nested
instead under `payload.source.subagent.thread_spawn` -- both shapes have
been observed, and `payload.source` itself is sometimes a plain string
rather than an object, which crashed an earlier version of this tool on
real data). The role comes from `agent_role`/`agent_nickname`:
`"<role>:<nickname>"`.

`thread_source == "subagent"` is exactly what separates a real subagent
spawn from a plain resume of the same thread -- both carry
`parent_thread_id`, but a resume's `thread_source` is `"user"`. Only a
subagent spawn gets folded under its coordinator; a resume keeps showing
the thread's own name, as before. Getting this distinction wrong is the
literal bug that motivated adding `parent_id`/`role` in the first place: an
earlier version of this tool applied the same name-inheritance fallback to
both cases, so three unrelated subagent rows would each show their
coordinator's name with no indication they were the same fan-out.

In table format, a session with a `parent_id` that resolves within the
current (already filtered/sorted) result set is indented under its parent
instead of listed flat; identical workspace paths are blanked on the nested
row to cut repetition. A subagent whose coordinator got excluded by a
filter (`--since`, `--named-only`, a `--workspace-root` mismatch, ...)
still shows up, just as a standalone row rather than a nested one -- it's
never silently dropped. `--flat` disables nesting entirely. `json`/`jsonl`
output is always flat and carries `parent_id`/`role` directly, so a script
or another agent can reconstruct the tree itself instead of parsing tree
glyphs out of a table.

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
