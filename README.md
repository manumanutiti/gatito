# Gatito — agent coordinator

Command center to launch Claude Code agents, watch them work, summarize their
conversations (with Haiku, cheap) and reply to them. From the PC and from the phone
on the home network.

## Parts

- `gatitod/core.py`    — core: list/launch/reply to agents, models/permissions/effort, config.
- `gatitod/profiles.py` — task profiles (`profiles/*.md`): each agent's prompt, mode and rules.
- `gatitod/backlog.py` — waiting tasks: queued, at a given time (with repetition) or manual.
- `gatitod/convo.py`   — reads the conversations (.jsonl) and summarizes them with Haiku (incremental).
- `gatitod/history.py` — history: all conversations in `~/.claude/projects`, with search.
- `gatitod/router.py`  — classifies what you type (action / question / task) with Haiku.
- `gatitod/store.py`   — read/write state JSON without threads overwriting each other (atomic writes).
- `gatitod/tls.py`     — HTTPS on the home network: own CA and a certificate for the PC's IP.
- `gatitod/push.py`    — phone/PC notifications with Web Push (VAPID + RFC 8291 encryption).
- `gatitod/modlink.py` — link with the Claude Code mod (socket `state/gatito.sock`).
- `mod/`               — the "gatito" mod that runs inside every Claude Code session.
- `gatitod/web.py`     — web server (stdlib) for PC and phone, with token. `@api` route table.
- `gatitod/index.html` — UI structure (Catppuccin Mocha/mauve, Figtree font).
- `gatitod/static/`    — `app.css` and one JS per view: `util.js` (shared), `sessions.js`,
  `board.js` (kanban + edit sheet), `week.js` (week), `art.js` (artifacts),
  `main.js` (navigation and refresh).
- `gatitod/artifacts.py` — versioned artifact store (`state/artifacts`).
- `gatitod/notebooks.py` — notebooks: Markdown notes with metadata in `notebooks/` (Notebooks
  view, `static/js/nb.js` and `static/nb.css`; `bin/notebook` and the "notebook" skill for agents).
- `bin/diagram`, `bin/artifact` — render infra diagrams and save artifacts.
- `icons/`            — local icons and their catalog; `skills/` — Claude Code skills.
  They are served on every request: editing the web UI does not require restarting gatito.
- `gatitod/vendor/`    — mermaid and the fonts, local (the web UI does not depend on the internet).
- `config.json`        — settings (`max_parallel`). Anything missing takes `CONFIG_DEFAULTS` from core.py.
- `projects.json`      — projects the router can pick. Regenerate with `bin/gen-projects.py`.
- `actions.json`       — local actions (shared with the gatito menu).
- `state/`             — token, backlog.json, summaries, history, status.json, `tls/` (CA and
  certificate), `push/` (VAPID keys and subscriptions), `uploads/` (pasted images).

It depends only on the stdlib and on `python3-cryptography` (system package, for HTTPS and
notifications; without it gatito works over HTTP and without notifications).

## Start

    systemctl --user daemon-reload
    systemctl --user enable --now gatitod     # after copying gatitod.service to ~/.config/systemd/user/

or by hand:  `/usr/bin/python3 ~/gatito/gatitod/web.py`

It listens in two places:

- `https://<PC-IP>:8777` — the home network (phone). Certificate from the gatito CA.
- `http://127.0.0.1:8778` — this PC only (opened by the menu's gatito). For the browser,
  localhost is already secure, so notifications work here too. The PC's browser
  does not need to pair: it is accepted without a token if the request comes from the
  gatito page itself (`Host` and `Sec-Fetch-Site` headers; another website or a script still can't get in).

## Pair the phone

    bash ~/gatito/bin/pair.sh      # shows a QR on the PC; scan it with the phone

The first time the phone doesn't know the gatito CA: accept the browser warning, press
**Notifications** and follow the steps to install `gatito-ca.crt` (downloaded from `/ca.crt`).
The CA is created once; if the PC's IP changes, the certificate is rebuilt on its own at startup.

## Notifications

**Notifications** button in the bar (bottom on the phone). Each device enables them and
chooses which ones it wants: an agent is waiting for you, an agent finished, a task could
not be launched, a scheduled task fires. They are end-to-end encrypted (the browser's push
service cannot read them) and also arrive away from home.

In **Brave** you have to turn on "Use Google services for push messaging"
(privacy settings; on the PC `brave://settings/privacy`): without it, sign-up fails with
"push service error". On iPhone, only from gatito added to the home screen.

## Images

Paste (Ctrl+V), drag or attach images in the composer or in a session's reply. They are
downscaled if large, saved in `state/uploads/` and the message carries them as
`![image](path)`: the agent opens them with Read (it has that directory allowed) and the
conversation shows them. With images, the router uses Sonnet and can see them.

## Infrastructure diagrams

For quick explanations, agents use mermaid. For serious architecture (AWS, Azure, GCP,
Kubernetes, on-prem networks, CI/CD) they use `bin/diagram`: the
[`diagrams`](https://diagrams.mingrammer.com) library with ~2,500 official icons, rendered
with graphviz to an SVG that carries the icons inside (shown in the chat and pasteable into
Confluence or Markdown) and, with `--png`, to a PNG for Teams or Word.

    bash ~/gatito/bin/setup-diagrams.sh          # library, icons, catalog and skills (repeatable)
    bin/diagram icons azure firewall            # what to import (never invent icons)
    bin/diagram draw docs/diagrams/azure-hub-spoke.py --png [--theme dark]

**Local icons** (`icons/`, see its README): `library/` with the library's icons,
`custom/` for your own (`from gatito import OwnIcon`) and `catalog.csv` with one per row
(what to import and where it is). Rendering downloads nothing; the network is only used when
installing the library with the script (pinned version).

The skills live in `skills/diagram/`, `skills/artifact/` and `skills/notebook/` (the script links them into
`~/.claude/skills/`; whatever was there before is kept in `~/.local/share/gatito/skills-previous`).
In a session, the **Infra diagram** button asks the agent for one.

Ideas taken from [archify](https://github.com/tt-a1i/archify) (Apache-2.0) so arrows don't
come out messy: an optional grid (`col=`, `row=` on each node), arrow roles
(`rol='principal' | 'back' | 'secondary'`) and a quality check after every render
(crossings, overlapping arrows or arrows over icons and titles, covered labels; it exits
with code 3 if there are defects so the agent fixes the placement).

## Artifacts

**Artifacts** view (`#/artifacts`, shortcut 4): what agents generate that is worth keeping.
Each diagram rendered with `bin/diagram` is saved automatically (SVG, PNG and its `.py`);
HTML pages, reports or tables are saved with `bin/artifact save <files>
--title "…"` ("artifact" skill). Gallery with search, viewer, versions (each in its
own folder: an old chat keeps showing what it saw), downloads, rename and delete
(to `state/artifacts/.trash`). In the chat, an artifact appears as an image or a card.

HTML pages open in a sandboxed iframe without same-origin and the server serves them
with a no-network CSP: they cannot call the internet or the gatito API, so they must be
self-contained.

## Notebooks

**Notebooks** view (`#/notebooks`, shortcut 5): the solid state of long-running work
—an engineering project, something you are learning, a flow you follow— so you don't
start from scratch in every conversation. They are plain Markdown folders in
`~/gatito/notebooks/`, so they open as is in Obsidian (or link your vault there:
`ln -s ~/Obsidian/Gatito ~/gatito/notebooks`).

    notebooks/<notebook>/notebook.md     cover: goal, map, related repos
    notebooks/<notebook>/status.md       living memory: what is clear, decisions, doubts, next steps
    notebooks/<notebook>/<folder>/       a project or topic (README.md with its metadata); nestable
    …/<folder>/diagrams/                SVG/PNG with official icons and their .py source
    notebooks/<notebook>/sessions/       summaries of important conversations

Agents write notes in the language of the notebook they work in. The section headings the
code parses (`What is clear`, `Decisions`, `Open questions`, `Next steps`, `History`) and the
metadata keys and values are English.

- **Metadata on each note** (YAML frontmatter): `title`, `kind` (explanation,
  decision, runbook, flow, reference, journal, session, note), `status` (draft → in
  progress → review → done → archived), `tags`, `summary`, `created`, `updated`,
  `sessions` (ids of the conversations that wrote it), `sources`, `repos`.
  `bin/notebook note` sets them right from the start; `bin/notebook review` flags
  missing ones.
- **In the web UI**: notebook list, tree with type/status/tasks of each note, cover
  with the state and recent items, notes with diagrams (mermaid and SVG), Obsidian callouts
  (`> [!warning]`), tables, `[[links]]` and **checkboxes you tick with a tap** (from the
  phone too). Edit, search across all notes, create notes/folders/notebooks.
- **Conversations**: not copied. The ones that worked in the notebook's folder and the
  ones that cite its notes (`sessions`) appear in the notebook and open in Sessions.
- **Session here**: launches an agent with the notebook as its project (also in the
  "Project" selector, Notebooks group). It works in its folder, reads `notebook.md` and
  `status.md` at the start, writes notes with metadata, renders the diagrams in `diagrams/`
  and updates `status.md` at the end (`notebook_prompt` in core.py and the "notebook" skill);
  it has access to the repos on the cover (`repos:`).
- **Bounded context**: a large notebook doesn't eat the agent's context. It starts with
  `notebook context <notebook> [<folder>]` (≤ 8,000 characters: cover, state with the
  actionable parts first and each section capped, folders and notes with their summary) and
  opens only what it needs. `ver` collapses `diagrams/` and `sessions/` and cuts at 80 lines; `search`
  gives 15 results; `review` flags notes over 12 KB and an `status.md` over
  5 KB. Reading diagram `.svg` files (base64 icons, 50-300 KB) is blocked for gatito
  agents (`DENY_TOOLS` in core.py).
- **History and undo**: `notebooks/` is its own git repo (local, outside gatito's).
  Every `notebooks_autosave_min` minutes (`config.json`, 10; 0 turns it off) a commit is
  made if something changed; a note's History button shows and restores versions.
  Deleting moves to `notebooks/.trash`.

## History

At the end of the session list, **History** gathers all your Claude Code conversations,
including terminal ones you already closed, with search (title, first message and
folder). They open to read and, by typing below, continue in the background
(`claude --bg --resume` in their folder): they become one more gatito session.

## Panels

The session list (`[`) and the left bar (`]`) can be hidden; it is remembered
per browser. With no session open, the composer sits in the center, like on AI websites.

The token is stored in the phone's browser (1-year cookie). Other devices on the wifi
can't get in without that token.

## Add a local action

Edit `actions.json`. It shows up both in the gatito menu (in its group) and
for the router. Today it supports `gsettings-toggle`.

## Backlog

In the composer, the "When" selector decides what happens to the task:

- **Now** — launched immediately, as always.
- **Queued** — launched as soon as there is room, in order of arrival: at most
  `max_parallel` background agents working at once (`config.json`).
- **Schedule…** — at a date and time; optionally every day, Monday to Friday or
  every week. If the PC was off at that time, it launches when gatito starts.
- **To do** — stays waiting until you launch it yourself.

You can also say it in words: the router understands "mañana a las 9 …" / "tomorrow at 9 …",
"cada día a las 8 …" / "every day at 8 …", "de lunes a viernes …" / "weekdays …",
"ponlo en la cola …" / "put it in the queue …" or "apúntame para luego …" / "note it for later …"
and sends it to the backlog (and "en una rama aparte" / "on a separate branch" turns on the
worktree). If you pick "When" by hand, that wins. With a project picked by hand, the router
is only consulted if the text talks about time (`TIME_RE` in index.html).

The web UI has three views (sidebar on the PC, tabs at the bottom on the phone; shortcuts 1, 2, 3):

- **Sessions** (`#/`) — the agents, their conversation and the composer.
- **Backlog** (`#/backlog`) — kanban: To do · Queued · Scheduled · Running · Done.
  Dragging a card changes when it launches (to "Running" launches it now; inside
  "Queued" it changes the order). Click to edit it in the side sheet. `n` creates a task.
- **Week** (`#/week`) — calendar of what is scheduled, with repetitions on each day
  they apply and what was already launched marked at its time. Click a slot to schedule there;
  drag a task to move it. On the phone, a single day with a selector on top.

Each project has a fixed color in the three views. A `web.py` thread checks the
backlog every 20 s.

## Worktrees

The branch button, next to "Project", launches the agent isolated in a worktree
(`claude --worktree`): a copy of the repo in `<repo>/.claude/worktrees/<name>`,
on its own branch `worktree-<name>`. This way several agents can work on the
same project at once without stepping on each other or touching your working copy. Only in git repos
(`/api/meta` marks each project with `git`). It also works for backlog tasks.

- The detail shows the branch and a shortcut "Merge into the main branch" that asks
  the agent for a commit + local merge (never push).
- When the session is deleted, `claude rm` removes the worktree and the branch if there are
  no unmerged changes; if there are, it leaves them.
- Each repo should ignore `.claude/worktrees/` (gatito already does).

## Profiles

A task profile fixes how an agent works and, above all, what it can touch: "Review",
"Security", "Diagnosis", "Infra change", "Document"… It is chosen in the composer's
"Profile" selector (or in a backlog task's sheet); the model, mode and effort selectors
take its values and can be changed, except the mode of a read-only profile. The session
remembers its profile (`state/profiles-session.json`): when you reply to it or resume it,
also from History, it is applied again. If a read-only profile's file disappears, its
sessions stay read-only.

**Profiles** view (`#/profiles`, shortcut 6): each profile from the inside — what it can and
cannot touch, its instructions, the effective rules Claude Code receives (with the read-only
allowlist and the always-on denials), the exact text added to the prompt and the file.
Files that fail validation also appear, with the reason. "Use in a session" leaves the
composer with that profile selected. The profile label in a session's detail links here.

**Creating one**: a file `profiles/<id>.md` (id in lowercase, numbers and hyphens). It is read on
every use: no restart needed. A badly written profile is ignored with a warning in the gatitod log.

    ---
    title: Review                      # required
    description: Review a change without touching anything     # one line, shown in the web UI
    model: opus                          # default (what you pick in the web UI wins)
    mode: auto                            # same; never bypassPermissions
    effort: high                        # same
    read_only: true                    # allowlist: see below
    worktree: false                       # default value of the worktree button
    notebooks: [infra]                    # starts with `notebook context infra` (if it exists)
    allow:                             # extra Claude Code tool rules
      - Bash(stern *)
    deny:
      - "@infra-writes"
    ---
    Text added to the system prompt: what to do first, what to look at, what not to do and
    the format of the deliverable.

Rules use Claude Code syntax (`Bash(kubectl get *)`, `Edit(//path/**)`) or a named
set from `profiles.py`: `@read` (the read allowlist) and
`@infra-writes` (the verbs that change something in kubectl, helm, terraform/tofu, argocd, flux,
aws, az, docker and gh, with flags or a path in front, plus `sh -c`/`eval`). Every field is treated as
untrusted data: a rule that doesn't start with a letter or has line breaks is discarded, and
`DENY_TOOLS` and `SAFETY_PROMPT` always apply.

### What read-only guarantees

It runs in `dontAsk` mode with an **allowlist** (`READ_ALLOW`): whatever is not allowed is
denied without asking. It was tested with real agents and fake binaries: `touch` does not get through, not even with
`bash -c`, `env`, `timeout`, `xargs`, `FOO=1` or `cd .. &&` in front; nor redirections, `| tee`,
`;`, `&&`, `$(…)`, `find -exec`, `sed -i`, `python3 -c`, `sort -o`; nor `kubectl delete/exec`,
`terraform apply`, `git log --output`; nor Edit/Write in the repo, nor reading outside the working
folders. On top there are denials (`READ_DENY`, which wins over allow) because the allowlist
alone isn't enough: `aws * describe-*` and `az * show*` have the wildcard in the middle and it
eats spaces (`az vm delete --name show1` got through), and some read commands write or
reveal secrets (`kubectl get secret -o yaml`, `get-secret-value`, `helm --post-renderer`,
`terraform plan -out`). `terraform plan` is only allowed as `terraform plan -lock=false …`
(without that it takes the remote state lock). It can write its deliverable in gatito's folders
(diagrams, artifacts, notebooks), but not in their `.git` or `.claude`, nor notebook
covers nor `notebook create` (a notebook's `repos:` grant access to the next session).

**What it does NOT guarantee** (known gaps):

- `terraform plan` runs providers and `data "external"`; `helm diff` and kubectl/helm
  plugins are programs. A malicious repo can run code through them.
- `kubectl diff` uses `KUBECTL_EXTERNAL_DIFF` if it is already in gatitod's environment.
- aws/az verbs that are not in `@infra-writes` would get through the middle wildcard; and the
  list has some false positives (a value starting with "start-").
- Secrets read through unforeseen paths (a `describe` output with environment variables,
  `docker inspect`). The prompt asks not to show them, but it is a request.
- It can write notes in any notebook and copy files to artifacts (`artifact save`).
- Whatever doesn't go through Claude Code's tools (third-party MCP, hooks) is out of scope.
- Claude Code's sandbox (bubblewrap) would be the real barrier for the filesystem,
  but here it doesn't start (AppArmor doesn't allow creating the user namespace and `socat` is missing), and its
  network filter would cut off kubectl and the cloud CLIs.

**`change-infra` and `document` are not read-only**: they edit and can write and run a
script, so their denials are a guardrail against slips, not against an agent that
wants to get around them. `change-infra` runs in `acceptEdits`: whatever isn't on its list asks you for
permission ("Waiting for you") instead of the classifier deciding. Tested: in `auto` mode
`sh -c "terraform apply"` and `eval "kubectl delete …"` got through, and in `acceptEdits`
`python3 -c "os.system(…)"` and `sh script.sh` got through without asking; now they are denied
(`@infra-writes` and the profile's `deny`), but a script called by its absolute path or
`awk 'BEGIN{system(…)}'` would still be a way around. The real protection is the
**credentials**: launch these agents with a read-only kubeconfig, AWS role or Azure identity
(or with no access to production).

## Debug

The "Debug" profile (`profiles/debug.md`, read-only, Opus at medium effort) is for debugging live,
testing by hand alongside the agent. It is launched with the **Debug** button in the composer (it picks
the profile and leaves "Symptom: …" written) or with the selector. It does not read the notebooks.

- **The whiteboard** is a small JSON per session (`state/debug/<session>.json`, `gatitod/debug.py`)
  that the agent changes one line at a time with `bin/whiteboard` (`symptom`, `cause`, `module`,
  `probe`, `status`, `next_step`, `close`, `ver`): it never rewrites it, so each step costs a few
  tokens. Two phases: **usual causes** of the symptom first, then the **path** (link, IP, DNS, ports,
  app, and Kubernetes or cloud on top), adapted to what fails and bottom-up when there is no clue.
  Pieces are green (fine, or inferred from a higher test: dashed), red (fails / confirmed cause),
  yellow (suspect) or gray (not checked).
- **Each test** records the command or question, where it ran (`agent@<host>` or `you@<host>`), the
  result and the lines of output that prove it: that is what a postmortem will be built from.
- **In the web UI** the board shows as soon as the session opens (with the stack in gray until the
  agent draws its own): a column to the right of the chat on the PC, full screen with the header's
  "Whiteboard" button on the phone. Every piece is clickable and unfolds its tests (copyable command,
  where, what came out, output). The **next step** has buttons: *Run it* (sends it to the agent),
  *I'll run it* (copies the command and leaves the reply ready for the output), *Skip*; a piece has
  *Look at this*. While the session works it is asked every 2 s (`GET /api/debug?ids=…&m=<mtime>`,
  which answers `{same}` if nothing changed).
- **Network tests** the agent runs on its own: the `@net-read` set (`ping -c`, `traceroute`,
  `tracepath`, `mtr -r`, `dig`, `nslookup`, `host`, `getent hosts`, `resolvectl status|query`, `ip`
  in its show forms, `ss`, `nc -z`, `openssl s_client`, `systemctl status`, `journalctl -u|-n`), with
  their write holes denied (`ip … add|del|set…`, `nc -l|-e`, `openssl -out`, journald upkeep).
  `curl`/`wget` stay out: those tests are proposed to you.
- **On resume** with another session id, `core.resume_session` keeps the board (`whiteboard` in the
  session's profile info); if the CLI still cannot find it, it adopts the open board touched most
  recently (12 h).
- Old whiteboards (notes of type `debugging` in a notebook) are still shown whole with the
  Notebooks renderer, and so are the other notes that cite a session.

## How to grow

- **New endpoint:** a function with `@api('GET'|'POST', '/api/...')` in `web.py`.
  GET receives the query as a dict, POST the JSON; it returns something serializable.
- **New background process:** a `start()` in its module that starts a thread, and a
  call in `main()` of `web.py` (like `backlog.start()`).
- **New setting:** add it to `CONFIG_DEFAULTS` in core.py and read it with `core.config()`.
- **New state on disk:** `store.read` / `store.write` / `with store.edit(...)`
  in `state/`, never a bare `write_text` if more than one thread touches it.
- **New model / mode:** lists `MODELS`, `MODES`, `EFFORTS` in core.py; the web UI
  receives them through `/api/meta`.

## Diagrams

The web UI draws in the chat the ```` ```mermaid ```` blocks and the images (SVG/PNG)
that agents write. Agents launched from gatito carry an instruction to
accompany IT explanations with diagrams (`DIAGRAM_PROMPT` in
`core.py`) and can save SVGs in `state/diagrams/`. In terminal sessions,
the `diagram` skill (`~/.claude/skills/diagram`) does the same. Mermaid is served
locally from `gatitod/vendor/` (v11.4.1), with a patch: mermaid passes each
label through markdown and, if it starts with `1. `, `- `, `# ` or has a URL or some
`code`, it rendered "Unsupported markdown: list" (or `link`, `codespan`…). With the
patch the text is rendered as is. If you update mermaid, apply it again with
`bin/patch-mermaid` (it warns if it doesn't fit the new version).

## Claude Code mod

`mod/` is a mod (Claude Code plugin in TypeScript) that runs inside every session
—background, terminal and desktop ones— and talks to gatitod through the socket
`state/gatito.sock` (only your user can open it; nothing is opened to the network).

- **Live:** gatito knows right away whether a session is working or idle (● live).
- **Permissions from the phone:** when Claude was about to ask you for permission, the session moves to
  "Waiting for you" with what it asks for (command, file…) and the buttons **Allow**,
  **Always allow** (the rule or mode Claude proposes, in plain sight) and **Deny**
  (what you type below goes as the reason). The terminal dialog stays up at the same time: whoever
  answers first wins. The phone notification only has "Deny"; to allow you have to
  open gatito and see it. Terminal sessions only notify if they've gone a minute without an
  answer. If nobody decides in `perm_wait_min` minutes (`config.json`, 30), the usual
  dialog remains. Everything is logged in `state/permissions.jsonl`.
- **Inbox:** what you write to a live session reaches it without stopping or resuming it
  (once it finishes what it is doing). Also for terminal sessions. If you change
  model, permissions or effort, it is resumed as before.

If gatitod is not running, the mod does nothing and Claude works the same as without it.

**Install it** (do it yourself, not an agent: the mod can answer permissions):

    claude plugin marketplace add ~/gatito/mod
    claude plugin install gatito@gatito

It is read from that folder: after editing `mod/hooks/register.ts`, `/reload-plugins` in
each open session (new ones load it on their own). Check it: `claude plugin validate ~/gatito/mod`.
Uninstall it: `claude plugin uninstall gatito@gatito`.

## Security

- Agents are launched in `auto` mode unless you choose another (never `bypassPermissions`).
- The mod only applies what you decide; it never approves on its own. Denial rules
  (`DENY_TOOLS`, settings) act first and don't go through it.
  If they need permission, they are blocked and notify you (badge in gatito + "Waiting for you" list).
- The router never offers `vaults`, `pentest_vault`, `auditorias` or keys
  (see `EXCLUDE` in `bin/gen-projects.py`).
- The web UI listens on the LAN over HTTPS; protect it with the token and, if you want, a ufw
  rule limiting port 8777 to your subnet. Port 8778 (HTTP) only listens on 127.0.0.1.
- The CA, server and VAPID keys are in `state/` (outside git).

## Install

Linux or macOS, with a single repeatable script (each step checks whether it is already done):

    git clone <this repo> ~/gatito
    bash ~/gatito/bin/install.sh            # --simulate: says what it would do without touching services

What it does: checks the Xcode tools (macOS) or git and curl (Linux); picks the newest
`python3` (3.9 or later) among those covered by `requirements.lock`; creates the
`~/.local/share/gatito/venv` environment and installs with `pip --require-hashes --only-binary=:all:`
(pinned versions and hashes: nothing is resolved on the spot); graphviz with Homebrew or
apt; `state/` for your user only; diagrams and skills (`setup-diagrams.sh`); and the
service: a `local.gatito.gatitod` LaunchAgent on macOS (template in `packaging/`,
log in `~/Library/Logs/gatito/gatitod.log`) or the systemd unit on Linux. At the end it
tells you what is up to you (the `claude` login, trust for the folders, the mod).

- **Network, only at install time.** pip (PyPI) and Homebrew/apt. Once installed, gatito
  downloads nothing; the pairing QR is drawn by gatitod itself (`/pair`).
- **Pinned dependencies.** `requirements.in` (cryptography, diagrams) → `bin/gen-lock.sh`
  (pip only; uses the network, it's for development) → `requirements.lock` with the hashes for
  Linux x86_64 and aarch64 (ARM) and macOS arm64/x86_64, Python 3.9 to 3.14.
- **Linux with the previous service.** If `~/.config/systemd/user/gatitod.service` already exists,
  the installer carries on with `/usr/bin/python3` and `python3-cryptography` and doesn't touch the
  service; `--venv` moves it to gatito's environment.
- **macOS: this machine only.** By default gatito listens only on
  `127.0.0.1:8778`. For the phone, `"listen_lan": true` in `config.json` (on Linux it is
  the default) and, with the macOS firewall on, allow the venv's Python
  (the installer prints the `socketfilterfw` command).
- **The agents' PATH.** launchd starts with a minimal PATH; the plist carries your
  shell's at install time. If you change something there (new Homebrew, another tool),
  run `install.sh` again. Variables Claude needs (proxy, Bedrock/Vertex,
  corporate CA) go in `~/.claude/settings.json` → `env`, not in `.zshrc`.
- **Network settings in `config.json`:** `listen_lan`, `lan_ip` (pins the IP if the VPN
  confuses it), `push_sub` (VAPID contact; Apple's service may reject the default),
  `ca_extra` (PEM of a corporate proxy's CA for notifications).
- **Laptop.** gatito checks the IP every minute: if it changes (home, office) it rebuilds the
  certificate and the pairing link without restarting. The certificate also carries
  the machine's Bonjour name (`<name>.local`), which doesn't change with the network.
- What differs between systems is in `gatitod/hostinfo.py` (tests in
  `tests/test_hostinfo.py`, with macOS simulated).

## Migrate to another machine

    bash ~/gatito/bin/export-state.sh [file.tar.gz]

It carries the notebooks (git bundle, with their history), `state/artifacts`,
`state/diagrams` and `config.json`, with a `LEEME.txt` on how to import it. It does **not** carry:
the token (pair again: the cookie is tied to the address), the CA and the
certificate (each machine creates its own; the new ones only cover `.local` names and
private IPs, and are installed on the phone like the first one), the VAPID keys and
subscriptions (each device enables notifications again), the history and
permissions, the backlog (scheduled tasks would fire on both machines) nor
`projects.json` (start from scratch on the new machine). Nor `~/.claude`
(credentials and conversations: on macOS the login goes to the keychain) nor the Python
environments, which are rebuilt with `install.sh`. Copy the code with `git clone`, not a zip.

## First day on a Mac (manual tests)

What can't be verified without a Mac in front of you:

1. `bin/install.sh` on a clean Mac: the Xcode dialog, which Python it picks, that pip
   installs from `requirements.lock` without compiling anything, and `launchctl print
   gui/$(id -u)/local.gatito.gatitod` (state, PATH, descriptor limit).
2. `~/.local/share/gatito/venv/bin/python -c "import urllib.request as u;
   u.urlopen('https://web.push.apple.com', timeout=10)"`: an HTTP error is fine;
   `CERTIFICATE_VERIFY_FAILED` is not (then `ca_extra`).
3. Launch a task from the web UI ("say hi and run `which dot gh git`"): keychain,
   inherited PATH and `claude agents --json` under launchd.
4. Claude Code trust in `notebooks/`, in `~/.local/share/gatito/chats` and in
   each project; no project in `~/Documents`, `~/Desktop` or iCloud (TCC blocks
   a launchd process without telling you).
5. The mod: "● live" in the web UI and a permission approved from it (Unix socket on macOS).
6. Notifications: macOS Safari and Brave on `http://127.0.0.1:8778` ("Test notification"), and the
   iPhone (PWA) against `web.push.apple.com`; if it gives 403 `BadJwtToken`, `push_sub`.
   Allow notifications for the browser in System Settings.
7. With `"listen_lan": true`: the iPhone connects through `https://<name>.local:8777` with and
   without the company VPN, the macOS firewall and the "Local Network" permission.
   Install the new CA on the iPhone and enable it in Trust settings.
8. `bin/diagram draw docs/diagrams/azure-hub-spoke.py --png` with Homebrew's graphviz.
9. Notebook autosave (10 min or the button) without Xcode dialogs.
10. Close the lid with a scheduled task and check that it fires on wake; switch
    wifi and see "the IP changes from … to …" in the log.
11. Before anything else: whether company policy allows Homebrew, listening on the local
    network and installing a CA on the phone.
