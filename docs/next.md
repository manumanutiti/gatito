# Gatito: recent changes and what comes next

Last updated: October 17, 2026.

## Done

### Claude Code mod (`mod/` + `gatitod/modlink.py`)

A mod (TypeScript plugin) that runs inside every Claude Code session —background,
terminal and desktop— and talks to gatitod through the `state/gatito.sock` socket
(0600 permissions, no token, no network). Installed from the local folder: nothing is uploaded.

- **Live status.** The mod reports when each session and each turn starts and ends.
  The detail view shows "● live" and the status changes immediately.
- **Permissions from the web and the phone.** When Claude was about to ask you for
  permission, the session moves to "Waiting for you" with a card: what it asks for
  (command, file and content), and **Allow**, **Always allow** (the rule or mode Claude
  proposes, in plain sight) and **Deny** (what you type below goes as the reason).
  - The terminal dialog stays up at the same time: whoever answers first wins.
  - The phone notification only has "Deny"; to allow you have to open gatito.
  - Terminal sessions only notify after a minute without an answer.
  - With no decision in `perm_wait_min` minutes (`config.json`, 30), the normal dialog remains.
  - Everything is logged in `state/permissions.jsonl`.
- **Inbox.** Replying to a live session without changing model, permissions or effort
  reaches it without stopping or resuming it (once it finishes what it is doing). It
  also works to write to terminal sessions from gatito.
- **Safe by default.** If gatitod is not running, the mod does nothing; it never
  approves on its own. The installation is done by the user, never by an agent.

Verified with test agents (Haiku, disposable folders): `--bg` agents load the mod; the
permission shows up in gatito in ~3 s; allowing and denying with a reason reach the
agent; the inbox opens a turn without resuming; the session end arrives.

### Haiku summary, on demand only

Opening a session no longer calls Haiku. It shows the last saved summary (if any,
flagged if the conversation has moved on) and the **Summarize** / **Update** buttons
request one whenever you want.

## To verify

- **Auto mode.** We don't know whether the classifier ever asks or just denies.
  Review `state/permissions.jsonl` after a few days of use: the `mode` field tells.
- **Answering in the terminal while gatito waits.** Planned (gatito treats it as
  resolved within ≤40 s), not tested with a real session.
- **The permission card and the summary button** have not been seen rendered in the
  browser yet.

## Next

In order of value:

1. **`/haiku <instruction>`** in any session: a mod command (no Claude turn, zero tokens
   from the big model) that launches a Haiku agent with clean context in the same folder,
   notifies when done and leaves a note in the original session about what changed. For
   mechanical changes without paying for Opus or breaking its cache.
2. **`/gatito <text>` and a status line.** Send tasks to the backlog from the terminal
   (same router with dates) and see `🐱 2 working · 1 waiting for you · 3 queued`.
   A brief notice in the terminal when a background agent finishes or waits for you.
3. **gatito instructions through `prompt.compose`.** `DIAGRAM_PROMPT` and whatever
   comes next (memory, preferences) in every session, terminal ones too, in a single
   place instead of `--append-system-prompt`.
4. **gatito tools for Claude** (`$.tool.register`): `schedule_task`,
   `warn_mobile` ("tell me when the build finishes"), `ver_backlog`.
5. **"Review on finish"** (an ECC idea): when an agent finishes, run `/code-review`
   on its branch or worktree and notify with the result.
6. **Memory view** (an ECC idea, "instincts"): at the end of each session, Haiku
   extracts preferences and lessons; they are approved or deleted in the web UI before use.
7. **Security check** (an AgentShield idea): review the settings, hooks and MCP in
   `~/.claude` from a button, written by us.

### Discarded

- Installing Everything Claude Code (ECC) whole: 311 skills take up context in every
  session and its hooks are third-party code with your permissions.
- Elaborate terminal panels: gatito lives in the browser and on the phone.
- Approving permissions with our own model: auto mode already does that.
