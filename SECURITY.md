# Security policy

## Supported versions

The latest released version is the only supported one. reflock is a single
file - upgrading is replacing it.

## Reporting a vulnerability

Please report privately via GitHub's
[private vulnerability reporting](https://github.com/a-grasso/reflock/security/advisories/new)
rather than opening a public issue. Expect an acknowledgement within a week.

## Threat model, so you can judge severity

reflock reads files in a repository you already trust and writes pins back into
them. It makes no network calls, executes nothing it reads, and has no runtime
dependencies. The realistic exposure is:

- **Path traversal on write.** A reference whose target path escapes the repo
  root causing `stamp` to write outside it.
- **Denial of service by input.** A pathological file causing the reference
  grammar's regexes to blow up on a repo running reflock in CI.
- **The install path.** `install.sh` symlinks a checkout onto `PATH`; the
  Homebrew formula and the pre-commit hook pin a release tag.

Reports about reflock failing to *detect* a stale reference are correctness
bugs, not vulnerabilities - please open a normal issue for those.
