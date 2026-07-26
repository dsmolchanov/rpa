---
date: 2026-07-26
topic: SOTA repository-ontology patterns for coding agents (July 2026)
status: research complete
informs: docs/conventions.md §11
---

# SOTA repository ontology for coding agents — research synthesis

Question: what do leading agent harnesses use beyond CLAUDE.md/AGENTS.md so
that an agent, after reading a few files, knows precisely — with addresses —
where things live? Compiled from vendor docs, specs, and 2025–2026 studies
(sources listed inline; full survey in session research, July 2026).

## 1. The headline finding: exhaustive maps measurably hurt

- ETH Zurich + DeepMind, "Evaluating AGENTS.md" (Feb 2026): **LLM-generated
  context files reduced agent success in 5 of 8 settings** (−0.5% SWE-bench
  Lite, −2% AGENTbench) while adding steps and +20–23% cost — they restate
  what the agent finds faster itself. Human-curated files won (~+4 pts), and
  even that gain is modest.
- Anthropic (Claude 5-era context-engineering guidance, July 2026): keep
  CLAUDE.md lightweight; spend tokens on **gotchas**, not directory listings.
  Claude Code's `/doctor` now actively trims "directory layouts, dependency
  lists, and architecture overviews" from CLAUDE.md.
- Anthropic "Effective context engineering" (Sept 2025): prefer just-in-time
  retrieval via lightweight identifiers (paths, queries) over pre-retrieval;
  the filesystem itself is context.

Conclusion: the goal is not "one big map file". It is a **small always-loaded
orientation layer + a stable hand-curated map of what cannot be inferred +
everything else on demand or via tools**.

## 2. The four-layer consensus (mid-2026)

| Layer | Role | Mechanisms across harnesses |
|---|---|---|
| 1. Always-loaded orientation | commands, conventions, gotchas; <~200 lines | AGENTS.md (Codex, Copilot, Cursor, Amp, OpenCode, Zed, Junie, Cline, Roo, Gemini via contextFileName — 20+ adopters, Linux Foundation stewardship); CLAUDE.md (Claude Code; interop via `@AGENTS.md` import or symlink); Kiro steering `always` |
| 2. Stable map | coarse module map + invariants; changes ~yearly | ARCHITECTURE.md (matklad pattern; revived by OpenAI's harness-engineering practice: "a code map, not a code atlas", invariants stated as absences, name symbols not links); Kiro `structure.md` |
| 3. Conditional / on-demand leaves | loaded only when relevant | nested closest-wins files (Codex nested AGENTS.md — OpenAI's monorepo has ~88; Claude Code child CLAUDE.md on demand); path-scoped rules (Cursor `.mdc` globs, Claude `.claude/rules` `paths:`, Copilot `applyTo:`, Kiro `fileMatch`, Windsurf `trigger: glob`); skills progressive disclosure (frontmatter ~100 tokens → SKILL.md body → references/) |
| 4. Session/task memory | durable state across context windows | `thoughts/` (HumanLayer lineage — **this plugin's own pattern**), Cline memory-bank (stable ontology files vs volatile activeContext/progress), spec folders (spec-kit `specs/NNN/`, Kiro specs), OpenAI ExecPlans |

Plus an orthogonal mechanism replacing prompt-stuffed maps:

**Address-level precision is now delivered as tools, not files.** Aider-style
static repo maps injected every turn are a legacy pattern. Modern form:
LSP/symbol tools (Serena MCP: `find_symbol`, `find_referencing_symbols`),
code-graph servers (Sourcegraph SCIP MCP, Greptile), and agent-invoked
semantic search as a complement to grep at >~1k-file scale (Cursor semsearch,
Nov 2025: +12.5% avg accuracy, biggest on large repos). Claude Code's
baseline remains agentic grep/glob — precise and never stale.

## 3. Freshness (the reason most maps die)

1. Scope docs to what rarely changes; name symbols, don't link paths (matklad).
2. Pointers over copies — `file:line` references, never pasted snippets.
3. Promote invariants from prose to mechanism: linters, structural tests,
   hooks (OpenAI harness principle; Anthropic hook guidance).
4. CI drift detection (doc-drift, Fiberplane Drift: tree-sitter anchoring of
   docs to symbols) and agent-run "garbage collection" passes.
5. Generated artifacts only on-demand and task-scoped (Windsurf Codemaps) or
   aggressively human-trimmed — stale/redundant generated maps are worse than
   none (§1).

## 4. Implications for this plugin

1. **Layer 4 is already ours.** `thoughts/` is the HumanLayer pattern and
   matches SOTA; keep and strengthen (it is the review surface: ~200-line
   plans instead of ~2000-line diffs).
2. **Kernel/adapter mapping gets concrete.** AGENTS.md is the cross-tool
   kernel carrier (Codex reads it natively; Claude Code via `@AGENTS.md`
   import from CLAUDE.md). This resolves how the platform-neutral kernel of
   conventions v0.1 §1 reaches both harnesses without duplication.
3. **The plugin should assume/bootstrap a target-repo ontology** rather than
   grow its own map format: root AGENTS.md (+ CLAUDE.md importing it),
   optional ARCHITECTURE.md for larger repos, nested files in monorepos.
   `/research_codebase` should read layers 1–2 first and cite them; its
   output docs stay in layer 4.
4. **docs-auditor is the natural drift owner**: extend it from README
   accuracy to layer-1/2 drift (do the named symbols still exist? do the
   documented commands still run?), reporting into `/tech_debt_sweep`.
5. **Do not build a map generator.** An agent-maintained, human-reviewed
   ARCHITECTURE.md (drift-detect → propose PR) is SOTA; an auto-generated
   exhaustive index is measurably counterproductive.
