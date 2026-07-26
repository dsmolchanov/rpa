# Development set (visible) — exactly 5 tasks

Used while building the candidate; **never counted toward the pass bar**
(pilot plan, Sequence step 3). The dev set is visible by design; only tasks
targeting this public repository are committed here. Tasks targeting
private repositories are held in the private eval workspace per the plan's
privacy rule — raw ground truth for private repos is not committed to this
public repository.

| Task | Archetype | Target repo | Location |
|---|---|---|---|
| dev-1 | 1 — subsystem end-to-end (mid-size) | livekit-voice-agent (private) | private eval workspace |
| dev-2 | 2 — same on the largest repo | neomenu (private) | private eval workspace |
| dev-3 | 3 — narrow "where is Y defined" | rpa (this repo) | `task-dev-3.md` |
| dev-4 | 4 — code + prior `thoughts/` docs | rpa (this repo) | `task-dev-4.md` |
| dev-5 | 5 — external library/API context | livekit-voice-agent (private) | private eval workspace |

Task-file format: frontmatter (`task-id`, `archetype`, `target-repo`,
`target-sha`, `set`), then `## Task prompt` (the only text an evaluated run
receives) and `## Ground truth` (dev set is visible, so it may live in the
same file; holdout ground truth is sealed separately).
