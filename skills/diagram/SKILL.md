---
name: diagram
description: Draws a diagram or explanatory image of an IT topic (architecture, networks, flows, Kubernetes, CI/CD, security, protocols, AWS/Azure/GCP infrastructure) to view in the gatito web UI. Use it when the user asks for a diagram, chart, schema, drawing or image that explains something ("diagrama", "gráfico", "esquema", "dibujo"), a "professional" architecture or infra diagram, or says "explain it to me with a drawing" / "explícamelo con un dibujo".
---

# Diagrams for gatito

The user (DevOps) reads conversations in the gatito web UI (`~/gatito`), which draws
the diagrams inside the chat. In the terminal only the code is visible, so tell them to
view it in gatito.

## Choose the engine

| What you explain | Engine |
|---|---|
| Simple flow, protocol, sequence, lifecycle, quick idea | **mermaid** |
| Infra architecture: cloud (AWS, Azure, GCP), Kubernetes, networks, on-prem, CI/CD, something for documentation | **infra** (`~/gatito/bin/diagram`, official icons) |
| Something very visual that fits neither | hand-written SVG |

If you hesitate between mermaid and infra and provider icons would appear, or the user
says "professional", "for documentation", "architecture" or "topology" ("profesional",
"para documentación", "arquitectura", "topología"): infra.

## 1. Mermaid

In the reply, in a ```` ```mermaid ```` block:
- `flowchart LR` / `TD` for flows; `sequenceDiagram` for protocols (OAuth, TLS, OIDC);
  `stateDiagram-v2` for lifecycles; `erDiagram` / `classDiagram` for data.
- Short labels. In flowchart, if they contain spaces, `/`, `:`, parentheses or accents,
  put them in quotes: `A["kube-apiserver :6443"]`. In `sequenceDiagram`, no quotes.
- Simple ids, no HTML and no trailing `;`. One diagram per idea.

## 2. Infra with official icons

Uses the Python library `diagrams` (mingrammer): ~2,500 icons for AWS, Azure, GCP, K8s,
OCI, IBM, Alibaba, DigitalOcean, OpenStack, on-prem (nginx, postgres, grafana, ArgoCD,
Jenkins, Terraform, Vault…), SaaS, generic (network, firewall, router) and C4.

The icons are local, in `~/gatito/icons/`: nothing is downloaded when rendering.
`catalog.csv` has one per row (provider, category, class, alias, what to import,
file); `custom/` holds the user's own (logos, newer official icons).

**Step 1 — look up the icons in the catalog, never invent them:**

    ~/gatito/bin/diagram icons azure firewall
    ~/gatito/bin/diagram icons aws nat gateway
    ~/gatito/bin/diagram icons k8s ingress
    ~/gatito/bin/diagram icons own              # the user's own
    ~/gatito/bin/diagram icons --list onprem      # categories of a provider

It returns the import lines, ready to copy. Search in English. A custom icon is used
like this: `from gatito import OwnIcon` and `OwnIcon('label', 'file-name')` (accepts
`col=`, `row=` like any node). If the user names a product that is not in the catalog,
say so and use the closest generic one; do not look for icons on the internet.

**Step 2 — think about the placement before writing.** Clean lines come from placing
the nodes well, not from tweaking arrows. Classify each relationship:

- **Main path**: the route you are explaining (the user's request, the deployment).
  In one row, in reading order, with `rol='principal'` (comes out straight, thicker
  and in blue).
- **Branch or store** (DB, secrets, logs, queues): right above or below the node that
  uses it, in the same column. All branches of a row on the same side.
- **Return** (something that goes back to an earlier node: egress to the internet
  through the firewall, a response, a replica going back): `rol='back'`. It is placed
  as if it went forward and runs on the outside, in gray, without disordering the rest.
- **Second access** to a node that already has an entry (office VPN, bastion): on
  another row, so it enters from another side.
- `rol='secondary'`: a relationship that must not pull on the placement.

If there are more than ~6 nodes or groups next to each other, **fix the grid**: `col=`
and `row=` on every node (integers; in `LR` the column advances to the right and the
row downwards). Gaps in the grid fill themselves. Draw it in your head first: a
`Cluster` must occupy a rectangle of cells with no foreign nodes inside.

**Step 3 — write the diagram** in a `.py` (for example
`~/gatito/state/diagrams/<short-topic>.py`; when rendered, a copy is saved with the
artifact). The `Diagram(...)` title names the artifact: if you repeat it, it creates a
new version of the same one; if you change it, another artifact.
Full example with grid and roles: `~/gatito/docs/diagrams/azure-hub-spoke.py`.

```python
from diagrams import Cluster, Diagram, Edge
from diagrams.aws.network import ALB, NATGateway
from diagrams.aws.compute import EKS
from diagrams.aws.database import RDS
from diagrams.onprem.network import Internet

with Diagram('EKS in the VPC', direction='LR'):
    internet = Internet('Internet', col=0, row=0)
    with Cluster('VPC 10.0.0.0/16'):
        with Cluster('Public subnet'):
            alb = ALB('alb', col=1, row=0)
            nat = NATGateway('nat-gw', col=1, row=1)
        with Cluster('Private subnet'):
            eks = EKS('eks-prod', col=2, row=0)
            rds = RDS('postgres', col=3, row=0)
    internet >> Edge(label='443', rol='principal') >> alb
    alb >> Edge(rol='principal') >> eks
    eks >> Edge(label='5432', rol='principal') >> rds
    eks >> Edge(style='dashed', rol='back') >> nat
    nat >> Edge(rol='back') >> internet
```

- Do not set `filename`, `outformat` or `show`: the program decides them.
- `Cluster` for VPC/VNet, subnets, subscriptions, accounts, namespaces, regions.
  Nesting 2-3 levels looks good; more reads badly.
- `Edge(label='443')` ports/protocols, short (≤ 12 characters; the detail goes in the
  text). `style='dashed'` for VPN, replica or async; `style='dotted'` for weak
  dependencies (secrets, logs).
- Arrows are orthogonal (right angles). `direction='LR'` usually reads better than
  `'TB'` for infrastructure.
- Short node labels; `\n` for a second line (IP, SKU, range).
- One diagram per view: network, deployment and data flow separately if it is big.

**Step 4 — render it and fix until it comes out clean:**

    ~/gatito/bin/diagram draw ~/gatito/state/diagrams/<short-topic>.py --png

Besides rendering, it **measures the quality** on the real layout: arrow crossings,
overlapping arrows, arrows passing over an icon or a group title, and covered labels.
If it finds anything it lists it and exits with code 3 (the drawing exists).

- On code 3, fix the placement (not the arrows one by one): move the end that is not on
  the main path, mark the returns, change `col`/`row`. Repeat.
  At most 3 rounds; if a minor defect remains, deliver it and say so in one sentence.
- Open the PNG with Read and look at it before calling it good: the measurer cannot
  tell whether the composition tells the story well.
- `--dot` also saves the graphviz source, for debugging.

Every render is saved as a gatito **artifact** (Artifacts view: SVG, PNG and the
`.py`, with versions; rendering the same thing twice does not duplicate). It prints the
line `![Title](<absolute path>/state/artifacts/<id>/vN/<id>.svg)`: copy it as is,
alone on its line, in your reply and gatito draws it (click to enlarge). The SVG
carries the icons inside: it can be opened, sent or pasted into Confluence/Markdown as is.
`--output DIR` renders into a loose folder without saving it as an artifact.

- `--png`: 160 dpi PNG (for Teams, Slack, PowerPoint, Word, and for you to review).
- `--theme dark`: dark background. The default is light (the documentation one). In
  dark, the black `generic` and `onprem` icons are barely visible: avoid it if you use them.
- If it fails with "The library is missing", tell the user to run
  `bash ~/gatito/bin/setup-diagrams.sh`.

## 3. Hand-written SVG

Self-contained, with Write at `~/gatito/state/diagrams/<short-topic>.svg` (background
`#1e1e2e`, text `#cdd6f4`, accents `#cba6f7` / `#89b4fa`, `viewBox` set, no scripts)
and linked with its absolute path, using your real home (`echo $HOME`; on macOS it is
`/Users/<user>`): `![Description]($HOME/gatito/state/diagrams/<short-topic>.svg)` with `$HOME` already expanded

## Always

Accompany the diagram with 2-5 sentences explaining how to read it, in the language the
user writes in. The diagram supports the explanation, it does not replace it.
