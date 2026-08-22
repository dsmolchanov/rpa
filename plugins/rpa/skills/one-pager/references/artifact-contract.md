# One-pager artifact contract

The digest produced by `/rpa:one-pager` and by
[`../scripts/onepager.py`](../scripts/onepager.py). This file is the single
source for the digest's paths, shape, bounds, determinism rules, and validator
checks. The script implements it; nothing else restates it.

A one-pager answers three questions about a repository — *what landed*, *what
is open*, *what is next* — from facts a machine can prove. Every fact comes
from `git`, `gh`, or a file under `thoughts/shared/`. The only model-written
part is an optional, marked `## Narrative`.

## Paths and naming

| Mode | Default path |
|---|---|
| `repo` (one repository) | `<repo>/thoughts/shared/one-pagers/YYYY-MM-DD-<slug>.md` |
| `all` (cross-repository) | `$RPA_HOME/one-pagers/YYYY-MM-DD-all.md` |

- `<slug>` is the kebab-cased basename of the repository root.
- `YYYY-MM-DD` is the **UTC date of the `window.head` commit**, not the wall
  clock: the name is then reproducible from the repository alone, and a
  session that does not commit keeps writing the same page.
- `--json` writes a `.json` companion beside the `.md` with the same stem.
- Same path → overwrite. Regeneration is idempotent (see *Determinism*).

`RPA_HOME` is introduced and owned by this contract: precedence `--out` >
`$RPA_HOME` > `~/.rpa`. The directory is created on write with mode `0700`.
Neither `RPA_HOME` nor any other absolute path ever appears **inside** a
digest.

**Self-reference.** `thoughts/shared/one-pagers/` is not an artifact source. A
digest never lists itself or a prior digest under `## Artifacts`, and there is
no `## Sources` row for it.

**Emitted paths are repository-relative.** In `mode: all`, each path is
rendered under its repository's `## <repo>` section, still repository-relative.
Absolute paths are a validation error (check `j`).

## Output modes

| Invocation | Effect |
|---|---|
| `generate` | Markdown to stdout |
| `generate --json` | canonical JSON to stdout |
| `generate --write` | write the default path for the mode (`.md`; plus `.json` with `--json`) |
| `generate --out <path>` | write exactly `<path>` (implies writing; `.json` companion with `--json`) |
| `generate --previous <path>` | use `<path>` as the previous digest (default: the newest digest at the default path) |
| `generate --repos <path>…` | `mode: all` over the listed repositories |

Containment: in `mode: repo`, `--out` must resolve inside the repository root;
in `mode: all`, `--out` must resolve **outside** every listed repository, and
`--write` goes to `RPA_HOME`. A violation is a usage error (exit 2).

## Window and fixed point

`--since` accepts an ISO date, a git ref, or `last` (the default).

`last` resolves as follows:

1. a previous digest exists and its `generated_from` **equals** `HEAD` →
   reuse its `window.since` verbatim;
2. a previous digest exists with a different `generated_from` → `since` is
   that `generated_from`;
3. no previous digest → the UTC date 14 days before the `HEAD` commit's
   committer date.

In `mode: all` this is resolved **per repository**: a cross-repository page
carries one header block per `## <slug>` section, and each repository's window
advances from its own recorded `generated_from`. Reading only a single
page-level block would send every repository back to a fresh 14-day window as
soon as any one of them advanced.

Rule 1 is the fixed point: without it, an unchanged rerun would scan `H..H`
and replace the page with an empty window.

The digest records only `window.since` and `window.head` (= `generated_from`).
The previous digest's **path is never emitted** — it is machine-specific and
would break byte-identity.

## Determinism

- Facts are sorted; lists are newest-first.
- The only wall-clock value is `generated_at`. It is **preserved from the
  previous digest whenever the canonical facts are identical**, so an
  unchanged rerun is byte-identical.
- Canonical JSON is `sort_keys=True`, separators `(",", ":")`.
- The Markdown is rendered from the canonical facts; a `.json` companion must
  render back to the same Markdown (check `h`).

## Structure

### `mode: repo`

```markdown
# One-pager: <slug>

mode: repo
generated_at: <ISO-8601 Z>
repo: <slug>
generated_from: <40-hex>
window.since: <ISO date | 40-hex>
window.head: <40-hex>

## Window

## Landed

## Open

## Artifacts

## Health

## Next

## Sources
```

`## Narrative` may follow `## Sources`; nothing else may.

### `mode: all`

```markdown
# One-pager (all repos)

mode: all
generated_at: <ISO-8601 Z>

## <slug>

repo: <slug>
generated_from: <40-hex>
window.since: <…>
window.head: <40-hex>

### Window
### Landed
### Open
### Next

## Sources
```

One `## <slug>` section per repository in the order given, then a single
`## Sources` whose rows are prefixed with the repository slug, then the
optional `## Narrative`.

## Section contents

- **Window** — `since`, `head` (short sha), `commits` (count in window).
- **Landed** — merged pull requests and commits not attributable to any pull
  request, in **one chronological list** ordered by full timestamp
  (`mergedAt` / committer date), newest first. The two kinds are interleaved
  rather than grouped, because the section is truncated at its tail: grouping
  would drop a recent commit while keeping an older pull request. Timestamps
  are compared at full precision — a date-only comparison leaves same-day
  entries in an arbitrary order, and most repositories do most of their work
  within a day. `merged_at` is stored as the full timestamp and rendered as a
  date. A commit is attributed when its sha is a
  pull request's `mergeCommit` **or** appears in that pull request's `commits`
  list (this covers merge, squash, and rebase merges). Everything else is
  **`unattributed`** — never "direct": without `gh` data, git cannot prove a
  commit did not arrive through a pull request.
- **Open** — open pull requests with draft flag, review decision, and a check
  rollup: `pass` when every check passes or is skipped, `fail` when any check
  fails, `pending` otherwise, and `unknown` when the rollup could not be read.
  `unknown` is never folded into `pending`: that would state something about
  the pull request when the truth is that a call failed.
- **Artifacts** — files under an artifact root that are in the **union** of
  (a) files changed by commits in the window and (b) dirty or untracked files
  reported by `git status --porcelain --untracked-files=all`. The union is
  what makes a session-end refresh honest: a TDD session log is written but
  not committed (`skills/tdd/SKILL.md` withholds commit authority), so a
  window-only scan would omit the artifact that triggered the refresh.
  Per-root status lines:

  | Root | Status line |
  |---|---|
  | `plans` | `satisfied S / open O / not-applicable N` (+ `enhanced <date>`) |
  | `tests` (test plan) | `<N> cases` |
  | `tests` (session log) | `<achieved phase>; cycle <state>; receipts <N\|none>` |
  | `implementations` | `present` (+ `plan <path>` when parseable) |
  | `handoffs` | up to 3 next-step bullets, or `no next-steps section` |
  | `research`, `debt`, `test-suite` | `present` |

- **Health** — the default branch's CI rollup, read from the `ci.yml`
  workflow explicitly (naming the workflow keeps the one-pager's own run from
  being reported as the repository's CI), plus open pull requests whose
  rollup is `fail`.
- **Next** — derived, over **all** active artifacts rather than only the
  window, in these shapes and no others:

  - `<N> open in <path>`
  - `<path> — cycle <continuing|blocked>`
  - `next: <text> (<path>)`
  - `#<N> checks fail`

- **Sources** — in `mode: repo`, one row per source: `git`, `gh-prs`,
  `gh-checks`, `gh-runs`, and one per artifact root (`plans`, `tests`,
  `implementations`, `handoffs`, `research`, `debt`, `test-suite`). Never a
  row for `one-pagers`.

  A row aggregates **every call behind it** — `gh-prs` covers the merged and
  open listings and one `gh pr view` per merged pull request; `gh-checks`
  covers one `gh pr checks` per open pull request. Any failed call fails the
  row, with a reason naming how many failed. A per-call outcome that never
  reaches the table is a degraded source presented as a healthy one.

  In `mode: all` the table carries **one aggregated row per repository**
  (`failed` when any of its sources failed, naming them; otherwise `passed`
  with the count of `not_applicable` sources). Eleven rows per repository
  would put the page over its bound before a single fact was rendered.

## Criterion states

A plan checkbox is:

- **satisfied** — `- [x]`;
- **not-applicable** — `- [ ]` whose text begins `Not applicable`, `Not run`,
  or `N/A` (case-insensitive);
- **open** — any other `- [ ]`.

Not-applicable criteria never appear in `## Next`. Reporting them as work
would make every finished plan look unfinished.

## Sources outcomes

Each row is `passed`, `failed`, or `not_applicable` with a reason:

| Source | `not_applicable` | `failed` |
|---|---|---|
| `git` | — (required) | not a repository → exit 1 |
| `gh-*` | `gh` absent, unauthenticated, or no GitHub remote | non-zero exit or malformed JSON |
| artifact root | directory absent | — |

A `failed` `gh` row does not stop the digest: it renders without that source
and still exits 0.

### Read-side containment

Artifact scanning reads only **regular files whose realpath is inside the
repository root and under `thoughts/shared/`**. Symlinks (at the file or any
parent), special files, and files over 1 MiB are skipped and counted in the
root's reason as `skipped: N symlink/special/oversized`. Skips from **both**
scans are counted — the window scan and the wider scan behind `## Next` —
deduplicated by path: a containment rejection is a degraded root wherever it
was found, and the `## Next` scan reaches artifacts the window never touches. Without this the
"nothing outside `thoughts/shared/`" promise would be false.

## Bounds

| Mode | Lines | Bytes |
|---|---|---|
| `repo` | 80 | 12 KiB |
| `all` | 160 | 24 KiB |

Each bullet is at most 200 bytes (truncated with `…`). Capacity is allocated
before filling: structure first, then a reserve of 13 lines / 1 KiB for an
optional narrative (its blank line, heading, marker, and up to 8 prose lines),
then list items. A list is truncated at its **tail**
(oldest) with a trailing `- [+N more]` marker, so the newest items and every
required heading always survive. The reserve is what makes appending a
narrative to an already-maximal digest safe.

Truncation is applied to the **facts**, not only to the rendered Markdown: the
lists in the JSON are sliced and the per-section counts recorded under
`truncated`. A companion that still described every item would fail the parity
check (`h`) on exactly the pages that need truncating.

When structure alone exceeds the bound — enough repositories that their
headers and source rows do not fit — generation **fails with a usage error**
naming the limit rather than emitting a page its own validator would reject.

## Narrative

The skill may append:

```markdown
## Narrative

_Model-written summary of the facts above; not a source._

<up to 8 lines>
```

The marker is required. The narrative may restate only facts already present
above it: a PR reference (`#N`), a repository-relative path, an artifact name,
or a count paired with a fact noun (`N PRs|commits|criteria|cases|receipts`)
that does not occur above the narrative is a validation error. Bare digits in
prose ("a one-screen page") are not flagged.

## JSON schema

```json
{
  "schema": 1,
  "mode": "repo",
  "generated_at": "2026-08-22T09:00:00Z",
  "repos": [
    {
      "repo": "demo",
      "generated_from": "<40-hex>",
      "window": {"since": "2026-08-08", "head": "<40-hex>", "commits": 2},
      "landed": [],
      "unattributed": [{"sha": "<40-hex>", "subject": "seed", "date": "2026-08-08T00:00:00Z"}],
      "open": [],
      "artifacts": [],
      "health": [],
      "next": [],
      "truncated": {"landed": 3},
      "sources": [{"source": "git", "outcome": "passed", "reason": ""}]
    }
  ]
}
```

## Validator checks

`onepager.py validate <file.md|file.json>` emits one
`one-pager: <check> — <detail>` line per error. Exit 0 valid, 1 invalid, 2
usage.

| Check | Rule |
|---|---|
| `a` | heading sequence for the mode |
| `b` | header block **order**, not mere presence: the page block is `mode`, `generated_at` (plus `repo`, `generated_from`, `window.since`, `window.head` in `mode: repo`); in `mode: all` each `## <slug>` block is `repo`, `generated_from`, `window.since`, `window.head`. Fields that merely exist somewhere in the file are not the header the contract describes |
| `c` | bounds selected by `mode` |
| `d` | every `## Sources` row carries a valid outcome |
| `e` | no receipt token (`` `receipt <hex12>` ``) anywhere — a digest cites logs, not receipts |
| `f` | every `## Next` bullet matches an allowed derived shape |
| `g` | narrative marker present, ≤ 8 lines, invents no facts |
| `h` | a `.json` companion renders to the same Markdown |
| `i` | `.json` input: `schema: 1`, then every check on the rendered Markdown |
| `j` | no absolute filesystem path anywhere |

## Refresh cadence

Event-driven and idempotent — **never per commit**:

1. **Session end** — the `tdd`, `create_handoff`, and `validate_plan`
   workflows end with `onepager.py generate --write`. Reported on failure,
   never blocking the primary artifact.
2. **Default-branch push** — a CI job regenerates the page and publishes it
   (job summary, artifact, and an unprotected status branch). It does not
   commit to a protected default branch.
3. **Schedule** — a local scheduled task runs the cross-repository page.

## Worked example

```markdown
# One-pager: demo

mode: repo
generated_at: 2026-08-22T09:00:00Z
repo: demo
generated_from: 1111111111111111111111111111111111111111
window.since: 2026-08-08
window.head: 1111111111111111111111111111111111111111

## Window

- since: 2026-08-08
- head: 1111111
- commits: 1

## Landed

- unattributed 1111111 seed (2026-08-08)

## Open

- none

## Artifacts

- plans thoughts/shared/plans/2026-08-08-demo.md — satisfied 1 / open 1 / not-applicable 0

## Health

- none

## Next

- 1 open in thoughts/shared/plans/2026-08-08-demo.md

## Sources

| source | outcome | reason |
| --- | --- | --- |
| git | passed |  |
| gh-prs | not_applicable | gh not found |
| plans | passed |  |
| tests | not_applicable | absent |
```
