# Mode: run

Execute the suite and report. `run` persists no workflow artifact and
rejects `apply`.

## Procedure

1. Require a current manifest; execute its evidenced `commands.test` (or
   the narrower evidenced selector the user asked for), capturing output to
   a log file.
2. For large output (hundreds of lines, many failures, verbose traces),
   digest the log through `file-analyzer` instead of reading it into the
   main context: pass/fail/skip counts, each failure with test name,
   `file:line`, error, expected vs actual, repeated failures grouped by
   root error.
3. Report: command, duration, counts, each failure with evidence and a
   suggested next step. Note tests that are slow or approaching timeouts.
4. Report any repository delta the command itself caused (coverage output,
   caches, snapshots) as side effects — do not delete them and do not claim
   them as workflow artifacts.

Execution failures are reported honestly: a command that fails to start is
a setup issue with the exact error, not a fabricated result.
