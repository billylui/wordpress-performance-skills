<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Security policy

This project produces tools that get pointed at production WordPress sites, sometimes by people
who are not developers, sometimes with credentials in the environment. That deserves a security
policy that says something specific rather than something reassuring.

## The no-egress guarantee

**These scripts do not phone home.** No telemetry, no analytics, no usage counters, no update
checks, no error reporting, no third-party APIs.

The only network destinations any shipped script may contact are:

1. the URL the operator explicitly passes it,
2. hosts referenced by that page's own markup (stylesheets, scripts, images, fonts — needed to
   measure page weight), and
3. an API endpoint the operator supplies themselves by flag or environment variable.

This is enforced, not merely promised. [`tools/check_no_egress.py`](tools/check_no_egress.py)
scans every shipped script for host literals and fails CI on anything outside a tiny allowlist
of RFC 2606 example domains and loopback. Run it yourself:

```bash
python3 tools/check_no_egress.py
```

The tradeoff is deliberate: we have **no usage analytics and never will**. Adoption is measured
by stars, forks, and issues.

## Why this matters for skills specifically

Agent skills are not passive documents. They execute shell commands, and Anthropic's own
documentation warns that skills fetching data from external URLs pose a particular
exfiltration risk, and that a malicious skill can direct an agent to misuse whatever access it
has. Treat every skill you install — including this one — as software you are installing.

**Audit before you install.** Read `SKILL.md`, read the scripts, check what the scripts talk to.
That advice applies to us as much as to anyone; the no-egress check exists so the audit takes
you a minute rather than an afternoon.

## Safety model of the tooling

- **The audit skill is read-only.** It uses no credentials, attempts no login, sends no
  authenticated request, and mutates nothing. It is safe to point at production by design.
- **The fix skill never acts unilaterally.** Every write needs explicit per-change approval, a
  rollback snapshot captured beforehand, and a verification afterwards against what a visitor
  actually receives. Approval for one change is never approval for the next.
- **Host constraints are a hard gate, not a suggestion.** Several managed hosts prohibit
  caching plugins, and remove disallowed ones from the site. The
  fix skill refuses to propose a change its host profile forbids, and routes to the permitted
  path instead.
- **Credentials stay outside the repo.** Nothing here asks you to commit a secret. Live-site
  verification configuration is gitignored.

## Reporting a vulnerability

Open a [security advisory](https://github.com/billylui/wordpress-performance-skills/security/advisories/new)
rather than a public issue, and please include the smallest reproduction you can manage.

Things we especially want to hear about:

- any path by which a script reaches a host it should not,
- any way the fix skill could apply a change without the required approval or without a
  recoverable rollback,
- any skill instruction that could be steered by content fetched from an audited site — a
  compromised site's markup is untrusted input, and must never be able to redirect the agent.

Expect an acknowledgement within a week.
