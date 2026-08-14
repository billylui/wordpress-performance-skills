<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# GoDaddy: a published blocklist the policy table cannot safely act on

**Status:** OPEN · **Opened:** 2026-08-14 · **Owner:** unassigned

GoDaddy publishes a disallowed-plugin list for **Managed Hosting for WordPress**, names three of
the page caches this project recognizes on it, and says a detected blocklisted plugin *"will be
removed"*. That is exactly the evidence the host-policy table exists to carry, and it is now cited
on the `godaddy` entry — but the entry's verdict is `unconfirmable`, not `prohibited`, and this
file records why, so nobody "fixes" it back without reading the rest.

## Re-verify ground truth before acting

```bash
python3 -c "import json;print(json.load(open('skills/wp-perf-fix/references/host-policy.json'))['hosts']['godaddy'])"
grep -n "def detect_host" -A 60 skills/wp-perf-audit/scripts/fingerprint.py   # the hostname fallback
grep -n "disagreement at any confidence" -B 5 -A 25 skills/wp-perf-fix/scripts/validate_plan.py
```

## The problem

Three facts interact, and any two of them look fine:

1. **The class cannot establish the product.** `detect_host` matches `x-gd-*` and `x-gateway-*`,
   and also falls back to a **hostname label** — so a GoDaddy VPS, Web Hosting or reseller site can
   be classed `godaddy` at `low` confidence with no Managed WordPress marker present at all. The
   blocklist evidence is about one product; the class covers several.
2. **`prohibited` refuses `host_confirmation` outright.** `validate_host_policy` returns before the
   confirmation branch. `unconfirmable` refuses by default but leaves that route open.
3. **An operator cannot relabel out of it.** `cross_check_stack` refuses a plan whose declared
   `host_class` disagrees with the fingerprint *at any confidence*.

Together: a `prohibited` verdict on this class leaves an operator on a non-Managed GoDaddy product
with **no path at all** — not a stricter path, none — and no way to declare their way out. That is
a gate that refuses the ordinary case, which this project has repeatedly found gets argued around
rather than obeyed (WP-ESC-10, WP-ESC-12).

## What already shipped (LIVE — do not redo)

- The blocklist is **researched and cited** on the `godaddy` entry, with the named plugins and the
  non-exhaustive clause recorded in `reason`. That research is done; do not repeat it.
- `host-constraints.md` states plainly that Managed Hosting for WordPress should be treated as
  prohibited in practice and that no page-cache plugin should be proposed there.
- The entry verdict is `unconfirmable`, which is the **pre-existing, fail-closed** state. Nothing
  about this is less safe than before the research.

## The fix, when someone takes it

Give the policy product-level granularity, so evidence about one product is not applied to a class
covering several. Sketches, none chosen:

- A `host_product` field on the change plan, declared by the operator and required before a
  product-specific verdict applies — with the fail-closed default when it is absent.
- Per-product entries in `host-policy.json` under a host, with the class-level verdict staying
  `unconfirmable` until a product is named.
- Require `host_confirmation` to name the product, and let a product-specific `prohibited` apply
  only once it does.

Whichever is chosen, the acceptance test is the one this round failed: **an operator on a
non-Managed GoDaddy product must retain a path to legitimate work**, and a Managed Hosting for
WordPress site must still refuse a page-cache plugin.

## Why this is a handoff and not another fix round

Two attempts were made in one session. The first set `prohibited` for the whole class. The second
kept `prohibited` and told operators to declare `self-managed` instead — advice that does not work,
because of fact 3 above, and which rested on a claim about `detect_host` that was never checked
against `detect_host`. An independent review caught both. Per the convergence protocol, a second
finding that is a sibling of the first means stop and hand off, not a third attempt.
