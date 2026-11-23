---
name: notebook
description: Reads and writes the gatito notebooks (~/gatito/notebooks), the persistent state of long-running work — engineering projects, topics the user is learning, flows and runbooks — as Markdown notes with metadata, diagrams and tasks, shown in the Notebooks view and in Obsidian. Use it when you work inside a notebook, when the user says "note it down" / "apúntalo", "save it in the notebook" / "guárdalo en el cuaderno", "create a notebook" / "crea un cuaderno", "document this" / "documenta esto", "leave it in writing so I can pick it up later" / "déjalo por escrito para retomarlo", or asks to resume something from a notebook.
---

# gatito notebooks

A notebook is a folder of Markdown in `~/gatito/notebooks/<notebook>/` that keeps the
state of a long piece of work: what is understood, what was decided, the flows to
follow and the diagrams. The user reads it in gatito's **Notebooks** view (PC and
mobile) and in **Obsidian**. Conversations pass; the notebook stays. Write for someone
coming back in three weeks who remembers nothing.

Tool: `~/gatito/bin/notebook` (`listing`, `context`, `ver`, `create`, `folder`,
`note`, `attach`, `touch`, `review`, `search`, `kinds`).

## Language

**Write notes in the language of the notebook you are working in** (check it with
`notebook context`); reply in the chat in the language the user writes in. Keep the
section headings that the tooling parses (`## What is clear`, `## Decisions`,
`## Open questions`, `## Next steps`, `## History`) and the frontmatter keys and values
(`title`, `kind`, `status`, `in-progress`, …) exactly as they are.

## Structure

    notebooks/<notebook>/
      notebook.md          cover: goal, map, repos (`repos` metadata)
      status.md            the notebook's living memory
      <folder>/            a project or topic; can be nested
        README.md          folder index (kind: folder) with its metadata
        status.md          optional: living memory of that folder if it is a big project
        *.md               notes
        diagrams/         SVG/PNG and their .py source
      sessions/            conversation summaries (kind: session)

A notebook groups several related projects or topics (e.g. "hostinfo-azure" with
`red-hub-spoke/`, `aks/`, `gitops/`). File and folder names in lowercase with hyphens;
`notebook note` generates them from the title.

## At the start

1. `notebook context <notebook>` (or `notebook context <notebook> <folder>` if the
   work belongs to one folder). In ~2,000 tokens it gives the cover, the trimmed state,
   the folders and the notes with their one-line summary. **Do not also read
   `notebook.md` or `status.md` in full**: they already come in there.
2. Open only the notes the work needs, picking them by their summary. Do not explain
   or decide again what is already there: build on it.
3. If the state contradicts what you see in the code or in reality, say so and fix it.

## Looking after context

A notebook grows over weeks; your context does not. Rules:

- **Never read `.svg`, `.png`, `.html` or `.pdf` files from a notebook.** A diagram SVG
  carries its icons in base64 and weighs 50-300 KB (tens of thousands of tokens);
  gatito blocks reading them. To change a diagram, edit its `.py` and render it again.
- **Search before reading**: `notebook search "udr firewall" --in <notebook>` (15
  results with a snippet) instead of opening notes blindly or grepping everything.
- **Large notes** (the context flags them): read only the section you need with Read's
  `offset`/`limit`; find the line number first with Grep.
- **`sessions/` and the history** are archive: do not read them unless you need
  something specific from a past session.
- `notebook show` collapses `diagrams/`, `sessions/` and `attachments/` and cuts at 80
  lines; narrow it with a folder instead of asking for `--all`.
- **Write so that the next reader pays little**: a `summary` that really summarizes
  (the next agent decides from it whether to open the note), notes under 12 KB (if they
  grow, split them and link them) and an `status.md` under 5 KB.

## Metadata (mandatory on every note)

    ---
    title: How the firewall routes in hub & spoke
    kind: explanation
    status: in-progress
    tags: [azure, networks, firewall]
    summary: The UDRs send all spoke-to-spoke traffic to the hub firewall.
    created: "2026-11-09 16:20"
    updated: "2026-11-09 16:20"
    sessions: [<conversation id>]
    sources: [https://learn.microsoft.com/…]
    ---

(The values follow the notebook's language; the keys never change.)

- **Always create notes with `notebook note`**: it sets the metadata correctly, the
  type's template and this conversation's id in `sessions`. Then fill in with Edit.
- When editing a note by hand, update `updated` and the `status`, or run
  `notebook touch <file>` when done (it does it for you and records the session).
- `summary`: one sentence stating what the note claims or decides, not "notes on X".
- `kind`: `explanation` (understand something), `decision` (what and why, ADR style),
  `runbook` (operate or fix), `flow` (process to follow, with checkboxes), `reference`
  (commands, data, links), `journal` (dated log), `session` (summary of a conversation),
  `note` (everything else). `notebook`, `status` and `folder` are the special ones.
- `status`: `draft` → `in-progress` → `review` → `done`; `archived` if it no longer applies.
- `tags` and `aliases` in English because that is how Obsidian understands them; the
  rest in the notebook's language.
- Before finishing, run `notebook review <notebook>` and fix what comes up (missing
  metadata, notes over 12 KB, an `status.md` that is too long).

## status.md: the living memory

It is the first thing the next agent (and the user) reads. Keep it short and current;
**rewrite, do not accumulate**:

- **What is clear**: facts and concepts already understood or verified, linked to the note.
- **Decisions**: what was decided, one line each, linked to its `decision` note.
- **Open questions**: what is not known yet or the user is unsure about.
- **Next steps**: `- [ ]` checkboxes; mark them `- [x]` when done.
- **History**: one line per important session, dated (most recent on top);
  at most 8 lines: older ones are already in `sessions/`.

Update it when you finish something worth keeping, not on every message. Under 5 KB:
if it grows, rewrite it; long decisions go in their `decision` note and only the line here.

## Diagrams and images

- Flows, sequences or quick ideas: a ```` ```mermaid ```` block inside the note
  (gatito and Obsidian render it).
- Infra architecture with official icons ("diagram" skill): write the `.py` in the
  note's `diagrams/` folder and render it right there:

      ~/gatito/bin/diagram draw <notebook>/<folder>/diagrams/hub-spoke.py --png --output <notebook>/<folder>/diagrams

  and link it from the note with a relative path: `![Hub & spoke](diagrams/hub-spoke.svg)`.
- A file that already exists (an artifact, a screenshot): `notebook attach <notebook>
  <folder> file…` copies it to `diagrams/` and gives you the link.
- Links between notes: `[text](../aks/ingress.md)` or `[[ingress]]` (Obsidian style).

## How to write

- Conclusion first; then the why. Short sentences, no filler, no praise.
- An **explanation** is built one step at a time: start from something the user already
  has clear (look in `status.md`), begin with the truths that have no exceptions
  ("all traffic between spokes goes through the hub") and make each next step feel
  expected: why it would be needed, what problem it solves. End with 2-3 application
  questions under "To check I understand it" (a new case, not a repeat of the
  sentence above).
- A **flow** or **runbook** is steps with `- [ ]` checkboxes, each one verifiable,
  with the exact command in a code block.
- A **decision**: context, options with their drawbacks, the chosen one and its consequences.
- Commands and configuration always in code blocks with their language.
- Do not copy the conversation: summarize what remains. If a note grows a lot, split it.

## At the end of a session worth keeping

1. New or changed notes, with `status` and `updated` up to date.
2. `status.md` rewritten with the new information.
3. If it was a long session or had decisions: `notebook note <notebook> sessions
   "Topic" --kind session` with what was done, what was decided and what remains.
4. `notebook review <notebook>`.
5. In your reply, say which notes you touched (path relative to the notebook).

## Creating a notebook

    ~/gatito/bin/notebook create "Hostinfo Azure" --summary "Hub & spoke, AKS y GitOps" --repo infra-azure --tags azure,k8s
    ~/gatito/bin/notebook folder hostinfo-azure red-hub-spoke --title "Red hub & spoke" --summary "…"

`--repo` accepts a gatito project id or a path: agents launched in the notebook get
access to those repos. Afterwards fill in the goal and map in `notebook.md`.

## Limits

- Do not write outside `~/gatito/notebooks/` unless the user asks.
- Do not touch `.git/` or `.obsidian/`: gatito makes a local commit of `notebooks/`
  every few minutes (history and undo); do not commit there yourself.
- Deleting: better to mark `status: archived`. If something must be deleted, let the
  user do it from gatito (it goes to the trash).
