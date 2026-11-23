# gatito icons

Everything is local: drawing downloads nothing.

- `library/` — the ~2,500 icons of the `diagrams` library (AWS, Azure, GCP, K8s, on-prem…).
  `bin/setup-diagrams.sh` (or `bin/diagram catalog`) creates them. The `azure/`, `generic/`
  and `onprem/` ones already come in the repo; the rest are copied from the package on install.
- `custom/` — yours (PNG, JPG or SVG): company logos, newer official icons you download by
  hand from the provider's site… They go in the repo. Use them with
  `from gatito import OwnIcon` and `OwnIcon('caption', 'file-name')`.
- `catalog.csv` — one icon per row: provider, category, class, aliases, the line to import
  and the file. It is rebuilt on its own when you add something to `custom/`.
  To search: `bin/diagram icons azure firewall` (or `grep -i firewall catalog.csv`).
