# Deterministic scripts

Deterministic operations for the research workflow (conventions §2:
scripts are executed, never loaded into context).

Metadata gathering is served by the plugin-level
`scripts/spec_metadata.sh` (single source, conventions §9) — installed as
`~/.claude/scripts/spec_metadata.sh` by Quick Install and invoked by the
kernel's verification profile. No duplicate copy lives here; a script
lands in this directory only when it is specific to the research workflow
and not shared with other command families.
