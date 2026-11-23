---
name: artifact
description: Saves in gatito, as a versioned artifact, what you generate for the user and is worth keeping — an interactive HTML page, a report, a comparison, a runbook, a table, an image — to view in the chat and in the Artifacts view. Use it when the user asks for a page, a report, "save it" / "guárdalo", "make me an artifact" / "hazme un artefacto", something to share or consult later, or when your deliverable is a visual document that does not fit well in the chat.
---

# gatito artifacts

gatito stores what you generate in `~/gatito/state/artifacts/<id>/vN/` and shows it in
the **Artifacts** view (gallery, viewer, versions, downloads). The infrastructure
diagrams from the "diagram" skill are already saved automatically; this skill is for
everything else.

## When

- Yes: an HTML page (comparison with filters, step-by-step explanation, incident
  dashboard, runbook, checklist), a Markdown report, a CSV the user will want to
  download, an image you made.
- No: short answers, project code (that goes in the repo), one-off things.

## How

1. Write the file in a working folder (the project's or
   `~/gatito/state/diagrams/`), not directly in `state/artifacts`.
2. Save it:

       ~/gatito/bin/artifact save page.html --title "Ingress on AKS: comparison" --desc "one sentence"
       ~/gatito/bin/artifact save report.md data.csv --title "…" --principal report.md

   Same title (or `--id`) = new version of the same artifact; earlier ones are kept.
   `artifact list` shows what is saved; `artifact show <id>` shows its versions.
3. Paste in your reply, **alone on its line**, the `![Title](path)` line it prints.
   The chat shows a card that opens the artifact (images appear inline).
4. Add 1-3 sentences: what it is and what to look at first.

## HTML pages: rules

gatito opens them in an isolated iframe (sandbox without same-origin) with a policy that
**cuts off all network access**: no internet and no gatito API. Therefore:

- **Self-contained**: CSS in `<style>`, JS in `<script>`, images as `data:` (base64)
  or inline SVG. No CDN, Google Fonts, `fetch` or external `<script src>` / `<link href>`:
  they would not load.
- System font (`system-ui, sans-serif`), light background, readable on mobile
  (`<meta name="viewport" …>`, tables with horizontal scroll if they are wide).
- No forms that submit anything; no `localStorage` for important data.
- If you include an infra diagram, render it first with the "diagram" skill and put
  the SVG in the page (it is self-contained: it carries the icons inside).
- Short, clear `<title>`: it is the name shown if the file is downloaded.
- Write the page in the language the user is writing in.
