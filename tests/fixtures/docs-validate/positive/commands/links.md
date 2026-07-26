---
description: Command exercising valid link forms
---

# Links

Inline [a](../skills/demo/SKILL.md), titled [b](./ok.md "title"), single [b2](./ok.md 't'), paren [b3](./ok.md (t)),
reference [c][ref1], implicit [ok.md][], angled [d][ang],
fragment [e](./ok.md#demo), self [f](#links).

[ref1]: ../agents/demo-agent.md
[ok.md]: ./ok.md
[ang]: <./ok.md>
Paren dest [p](./ok_(v2).md).

~~~
fenced [broken](./ghost.md) link ignored
~~~

Setext Title
============

Setext link [s](#setext-title), spaced ref [w][foo bar].

[foo   bar]: ./ok.md

Angled space [u](<./user guide.md>).

External schemes: [h](HTTPS://example.com/x), [f](ftp://example.com/file), [pr](//example.com/file).

Nested paren dest [n](./ok_(a_(b)).md).
