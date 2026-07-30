# BUG-08 acceptance contract: URL path segments are reported as suspects

Source: kai-crm dogfooding 2026-07-30
Owner: agent · Tier: near · Touches: [reflock_lib/grammar.py](../reflock_lib/grammar.py), [reflock_lib/engine.py](../reflock_lib/engine.py), [reflock_lib/commands.py](../reflock_lib/commands.py), [test_reflock.py](../test_reflock.py), [fixtures/](../evalbench/fixtures/)
Locked decisions: [D2](DECIDED.md#d2-inline-code-spans-are-not-references), [D3](DECIDED.md#d3-zero-runtime-dependencies)

## The defect

`suspects --all` on a repo with a `package-lock.json` reports roughly 150 hits
that are fragments of npm registry URLs:

```
tools/pipeline-showcase/package-lock.json:56  babel/core/-/core-7.29.7.tgz   [bare path, does not resolve]
```

`PATHISH` *appears* to exclude URLs already, and for a plain one it does - but
only by accident of the lookbehind. In `https://example.com/a/b/page.html`
every candidate start is preceded by `/` or `.`, both in the `(?<![\w./])`
exclusion class, so nothing matches. An `@` is not in that class, so an npm
scope re-opens a match mid-URL:

```
https://registry.npmjs.org/@babel/core/-/core-7.29.7.tgz  ->  babel/core/-/core-7.29.7.tgz
```

Three-quarters of the report on a real repo came from this one gap. The report
is a scrolling wall of `.tgz` URLs, which means the handful of genuine findings
underneath is invisible. That is worse than reporting nothing: it trains the
reader to ignore the command. False positives destroying trust in a gate is the
same principle that motivated D2 and reflock itself.

## Required behavior

A URL is not a path. `cmd_suspects` masks URLs out of a line before scanning it
for path-shaped tokens, the same way it already masks inline code spans:
same-length blanking, so no offsets shift and nothing later in the line is
silenced.

Masking a whole URL - not widening the lookbehind class - is the fix, because
the lookbehind only ever suppressed URLs incidentally. Any character outside
`[\w./]` appearing in a URL re-opens the same hole (`@` today; `~`, `+`, `,`
and `=` are all legal in a path segment). Excluding the construct is the rule
that actually holds.

The mask applies to every scanned file, markdown or not (`--all`): a URL in a
`.json` or `.py` string literal is no more a repo path than one in prose.

What counts as a URL, for this purpose: a `scheme://host/...` run, plus
protocol-relative `//host/...`. Bare `example.com/a/b.html` with no scheme is
left alone - it is indistinguishable from a relative path by inspection, and
today's behavior already reports it.

## Explicitly out of scope

- Reference *parsing*. `EXTERNAL` already classifies a scheme-prefixed target
  as external, so `check` was never affected; this is a `suspects`-only bug.
- Bare hostname-shaped tokens with no scheme (see above).
- `git@host:org/repo.git` scp-style remotes. Not observed, and the `:` form
  needs its own rule; if it shows up, it is a new item.

## Invariants

- Existing unit tests and evalbench fixtures stay green, unmodified - all seven
  `suspects-*` fixtures included.
- A path-shaped token in ordinary prose is still a suspect.
- A genuine suspect *after* a URL on the same line is still reported (the
  BUG-02/BUG-06 lesson: masking must not silence the rest of the line).
- Code-span masking and URL masking compose; neither undoes the other.
- No new imports outside the stdlib (D3).

## Fixtures to add

| Fixture | Asserts |
|---|---|
| `suspects-ignores-url-path-segments` | a scoped npm registry URL in a lockfile-shaped `.json` yields no suspect under `--all`, while a genuine bare path in the same file still does |

## Unit tests to add

- A scoped npm registry URL (`https://registry.npmjs.org/@babel/core/-/core-7.29.7.tgz`)
  produces no suspect.
- A plain URL with path segments produces no suspect (locks in the behavior the
  lookbehind was getting right by accident).
- A protocol-relative `//host/a/b.json` produces no suspect.
- A genuine dangling path later on the same line as a URL *is* reported.
- A URL inside a markdown link destination produces no suspect.
- `mask_urls` blanks same-length, asserted on the returned string, so the
  offset guarantee is tested directly rather than inferred.

## Verification

```
just gate
```

## Definition of done

1. Fixtures and tests above pass; nothing existing was modified.
2. `ROADMAP.yaml` marks BUG-08 `done`.
