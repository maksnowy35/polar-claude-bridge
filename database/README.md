# database/

Three levels of data, from "fine to publish" to "never leaves my machines".

| folder | in git | what lives there |
|---|---|---|
| `public/` | yes | synthetic samples and example outputs only, nothing measured on a real person |
| `private/` | no | raw Polar files (`raw/export`, `raw/api`), local SQLite `health.db`, generated `context/` |
| `confidential/` | no | `journal/log.csv`, `medical/` (timeline.md, labs.csv, scans of results) |

Production data sits in Postgres (see `docs/adr/001-database.md`); these folders are the local
working copy and the input for one-off imports. Only the README files are tracked in
`private/` and `confidential/`, see `.gitignore`.
