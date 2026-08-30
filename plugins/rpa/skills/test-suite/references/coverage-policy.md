# Coverage threshold resolution

The workflow never invents a coverage percentage. A threshold exists only
when a source below defines one.

## Resolution order

1. **Repository policy is the floor.** A threshold configured in the
   repository (coverage tool config, CI gate, `coverageThreshold` in a test
   config, Makefile check) applies, cited with its defining file. It is
   non-weakenable: no mode may generate or propose a lower gate.
2. **An explicit plan or user requirement may only strengthen it.** When a
   named requirement is stricter than the repository floor, use the
   stricter value and cite both. If it is weaker or measures an
   irreconcilable metric/scope, stop for a decision — do not pick one
   silently.
3. **With no repository policy**, an explicitly named plan/user requirement
   stands alone.
4. **With neither**, the outcome is
   `not_applicable — no configured threshold`. CI generation then omits the
   coverage gate entirely; reports state coverage as measured data without
   a pass/fail judgment.

## Reporting

- Threshold status in any artifact names the resolved value and its source
  file. "At threshold" and "below threshold" are statements about the
  resolved policy, never about an assumed default.
- Measured coverage is reported from parsed backend data only. Missing or
  unparseable data is reported as such — never estimated.
