<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Risk lanes

The lane is set by what happens when the change is wrong, not by how confident you feel.

## Contents

- [The consequence sets the lane](#the-consequence-sets-the-lane)
- [Two factors before every production write](#two-factors-before-every-production-write)
- [Decision table](#decision-table)
- [When staging does not exist](#when-staging-does-not-exist)
- [Changes that are never autonomous](#changes-that-are-never-autonomous)
- [Order several planned changes](#order-several-planned-changes)

## The consequence sets the lane

Use only the change-plan lanes `direct`, `staging-first`, and `prohibited`.

- `direct` is for a narrowly scoped, reversible change whose failure is visible and does not
  prevent the operator from reaching the restoration path. It still requires approval,
  snapshot, purge, visitor verification, and warm measurement.
- `staging-first` is for a change that can cause a fatal, make the site or administration
  interface unreachable, corrupt shared behavior, or require a fragile recovery path. Prove the
  exact change and rollback on a representative staging environment before production.
- `prohibited` means this skill refuses the production change. A host prohibition, an
  unconfirmed host policy, an unavailable rollback, or an action outside the autonomous boundary
  cannot be overridden by confidence or convenience.

Confidence changes how much evidence is needed to propose a change; it does not reduce the
consequence of being wrong. “It is only one line” is therefore not an argument for changing the
lane. One malformed line in an active `theme-file`, `plugin-file`, or `mu-plugin` can cause a PHP
fatal before WordPress can render the site or `wp-admin`. These targets remain `staging-first`
even when the diff is one character and the author is certain it is correct.

Check [host constraints](./host-constraints.md) before assigning the final lane. The table below
is a default, not permission from a host. A host's own current documentation may make a change
`prohibited` that would otherwise be `direct` or `staging-first`. When the policy cannot be
verified from that documentation, record it as `unknown` and treat the change as `prohibited`.
A host rule can tighten a lane; it never loosens the safety classification here.

## Two factors before every production write

Every production write requires both:

1. explicit approval for that specific change, after the operator is told the target, worst
   case, visitor impact, and rollback; and
2. a snapshot artifact captured before the write, then verified to exist and be complete enough
   to perform the recorded rollback.

Neither factor is sufficient alone. A snapshot is not consent. Approval is not reversibility.
Earlier approval, a general instruction to optimize the site, or an audit recommendation does
not approve the next change. A valid approval and snapshot also do not override a `staging-first`
or `prohibited` lane.

## Decision table

Kinds are ordered from the broadest likely blast radius to the narrowest. The “raise or lower”
column describes consequence-based reassignment only; confidence never appears there.

| `target.kind` | Default lane | Worst case when wrong | What would raise or lower it |
|---|---|---|---|
| `dns-or-cdn-setting` | `prohibited` | The hostname stops resolving or routes to the wrong origin; TLS, cache, redirect, or access rules can take every visitor offline or expose traffic. | Never lowered by this skill. A human operator or provider must own a separately authorized runbook and read-back verification. Unknown provider policy remains `prohibited`. |
| `server-config` | `staging-first` | The web server refuses its configuration or serves the wrong root, redirects every request, exposes files, disables PHP, or makes the whole site unreachable. | Becomes `prohibited` when host policy forbids it, policy is `unknown`, the active include chain is not known, or no verified restoration interface exists. Never lowered to `direct`. |
| `mu-plugin` | `staging-first` | Must-use code loads automatically and can fatal every request, including `wp-admin`; it may not be recoverable through the plugin screen. | Becomes `prohibited` when the host forbids the code, policy is `unknown`, or file-level recovery is unavailable. Never lowered to `direct`. |
| `plugin-file` | `staging-first` | Active plugin code can fatal the public site and `wp-admin`, corrupt shared hooks, or break checkout, login, forms, or scheduled work. | Becomes `prohibited` when the host forbids the edit, policy is `unknown`, or the original artifact cannot be restored outside WordPress. Never lowered to `direct`. |
| `theme-file` | `staging-first` | A PHP syntax or bootstrap error can take down the entire site with a fatal, including `wp-admin`; template errors can also remove navigation or content site-wide. | Becomes `prohibited` when the host or deployment model forbids direct file edits, policy is `unknown`, or out-of-band recovery is unavailable. Never lowered to `direct`. |
| `wp-option` | `direct` | A site URL, routing, authentication, cron, serialization, or autoload mistake can redirect or break the site globally and can lock the operator out. | Raise to `staging-first` for site-wide bootstrap, URL, routing, authentication, scheduled-task, or integrity-sensitive options. Make `prohibited` when ownership or serialization is `unknown`, host policy forbids it, or rollback cannot preserve the raw value. No lane is lower than `direct`. |
| `plugin-setting` | `direct` | A global setting can disable a business function, expose private output, invalidate cache keys, or make personalized pages cacheable. | Raise to `staging-first` for reversible security, routing, full-page caching, checkout, login, forms, or other site-wide behavior. Make `prohibited` when the failure can disclose private data or cause another irreversible external effect, or when storage or host policy is `unknown`. No lane is lower than `direct`. |
| `builder-content` | `direct` | A page, template, header, footer, form, or dynamic binding can disappear or render incorrect content to visitors. | Raise to `staging-first` for global templates, checkout/account flows, navigation, forms, or shared dynamic data. Deletion is `prohibited` for autonomous execution. No lane is lower than `direct`. |
| `media` | `direct` | Visitors see the wrong, broken, oversized, or distorted asset; attachment metadata and generated sizes can become inconsistent. | Raise to `staging-first` when the asset is integrity-sensitive or globally critical and a preview is needed. Deletion, an incomplete attachment snapshot, an operation that can create untracked derivative paths, or an unknown delivery policy makes the action `prohibited`. No lane is lower than `direct`. |

A `direct` default is not a blanket classification for every identifier of that kind. Record the
actual target and failure consequence in each change-plan entry, then choose the stricter lane
when its scope is broader than the default row assumes.

## When staging does not exist

If a change is `staging-first` and no representative staging environment exists, the lane is
**BLOCKED**. It does not silently downgrade to `direct`, and production is not a substitute for a
test environment.

A responsible operator chooses one of three paths:

1. provision representative staging and test the change, rollback, and required purge there;
2. have the accountable business and technical owners accept the specific documented production
   risk in writing and run it as a separately controlled human exception; or
3. leave the change undone.

Written risk acceptance does not rewrite the plan's lane, create staging, or authorize autonomous
execution. It records who chose to own an exceptional production procedure. Treat this as an
escalation, not a routine way around the gate.

“Representative” means the staging path matches every property that controls the proposed
failure: relevant WordPress code and data shape, PHP behavior, theme and plugin state, builder or
option storage, server configuration, and cache ownership. Record the compared properties and
their evidence. If a material property is `unknown` or cannot be reproduced, staging has not
proven this production change; keep it blocked or use the documented human-exception path.

## Changes that are never autonomous

The following actions require explicit human direction at the point of action and a separately
controlled procedure, regardless of the lane normally associated with a nearby `target.kind`:

- plugin or theme installation, activation, or removal;
- WordPress core, plugin, or theme updates;
- database schema changes;
- deletion of content or media;
- credential changes;
- DNS or CDN configuration;
- backup restores.

Do not infer authority for one of these from approval of a related file, option, setting, content,
or media change. If the action is also `prohibited` by the table or by
[host constraints](./host-constraints.md), explicit approval does not make it valid for this
skill.

## Order several planned changes

Apply changes one at a time, most-reversible first. Complete the entire guarded loop for one
change—apply, purge the actual cache layers, verify what a visitor receives, warm, re-measure,
and record—before asking for approval on the next production write.

Never place two changes between measurements. If the metric or visitor response moves, two
changes make attribution impossible; if something breaks, they also make rollback ambiguous.
Stop the sequence and roll back the current change first when anything resembles an incident.
