<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Staging: a capability, not a precondition

Most WordPress sites have no staging environment. A fix skill that refuses to work without one is
not a safer skill — it is an unused one, or one whose gate gets argued around on the first site that
needs it. This project already settled the same question on the audit side, where
[access-tiers.md](../../wp-perf-audit/references/access-tiers.md) says tier 0 is *"a complete audit
of the frontend and cache layers — not a degraded mode."* Staging works the same way: **it changes
the process, never whether the work may proceed.**

## Contents

- [What staging can and cannot prove](#what-staging-can-and-cannot-prove)
- [Promotion depends on what the change touches](#promotion-depends-on-what-the-change-touches)
- [Declaring staging](#declaring-staging)
- [Working without staging](#working-without-staging)

## What staging can and cannot prove

This is the part that generic staging advice gets wrong for performance work.

**Staging proves safety.** Does the change fatal? Does the layout survive? Does the admin still
load? Those answers transfer to production, and they are the answers that matter most, because a
PHP fatal in a theme file takes the whole site down.

**Staging does not prove speed.** Managed staging environments routinely run with the caching that
dominates the numbers switched off. Kinsta's own documentation states it plainly: *"Because staging
environments are for development purposes, debugging, and testing, Kinsta's full-page caching and
OPcache are disabled by default."* A staging environment also has different hardware, a different
data volume, no real traffic, and usually no CDN edge in front of it.

So a before/after measured on staging is not evidence about production, and must never be reported
as if it were. **The measurement in step 8 always happens on production, warm.** Staging comes
earlier, and answers a different question.

If a report ever shows a staging number in the `## Result` scorecard, that is a defect in the
report, not a shortcut.

## Promotion depends on what the change touches

Getting a change from staging to production is not one operation, and the difference is the reason
this section exists rather than a single "push to live" instruction.

| Change target | Where it lives | How it reaches production |
|---|---|---|
| `theme-file`, `plugin-file`, `mu-plugin` | files | Push **files only** through the path that owns production |
| `wp-option`, `plugin-setting`, `builder-content` | the database | **Re-apply on production.** Never by database push |
| `media` | files, plus an attachment row | Re-apply; a media library push is rarely scoped the way you expect |

**A database push overwrites live data.** Kinsta documents that pushing files *and* database means
*"Any changes to the live site's database since the staging site was created will be lost, including
but not limited to: comments, new content, purchases on ecommerce sites, sign-ups on membership
sites, and forum posts."* WP Engine's push offers the same choice with the same consequence.

That matters here more than in ordinary development work, because **a large share of performance
fixes are database changes**: a cache plugin's settings, an autoloaded option, a builder's global
style. Promoting one of those by pushing the database would trade a page-speed improvement for lost
orders. Re-applying the same setting on production takes a minute and destroys nothing.

So the staging loop for a database-backed change is: apply on staging → confirm it is safe and does
what you expect → **re-apply the identical change on production** → purge → verify → measure warm.
Staging validated the change; it did not deliver it.

## Declaring staging

Staging is **declared, never inferred** — the same rule as `host_class` and the audit's
`--local-root`. Nothing observable from outside proves a given URL is this site's staging
environment, and being wrong points a write at the wrong installation.

```bash
python3 "$SKILL_DIR/../wp-perf-audit/scripts/capabilities.py" --target <URL> --staging-url <STAGING_URL>
```

Record it on the plan so the validator can see it:

```json
"staging": {
  "url": "https://staging.example.com",
  "confirmed_by": "MyKinsta staging environment for this site, confirmed in the control panel"
}
```

`confirmed_by` has to name something a human could check. "It looks like staging" is not a
confirmation; a control-panel environment, a host support response, or the operator's own statement
of how they created it, is.

**Many operators have staging and do not know it.** WP Engine, Kinsta, Cloudways, SiteGround,
Pressable and others all document one-click staging as part of the product. Before concluding a site
has none, say which host it is on and whether that host provides one — "your host includes staging,
shall we use it?" is a better question than assuming its absence.

## Working without staging

A change may still proceed. What changes is the evidence required around it.

For a **code** change with no staging — the case with real risk, because a PHP fatal takes the site
down — apply these, and say in the report which of them were used:

1. **Prefer the most reversible mechanism available.** A change that can be reverted without
   filesystem access beats one that cannot. `functions.php` is the worst of the options: a theme
   update overwrites it, and rolling the theme back does *not* restore the edit, so recovery needs a
   backup. If the same effect is available from a plugin setting or a small plugin, take that
   instead — and note that this is also the change whose promotion is simplest, since it never
   involves a file push.
2. **Syntax-check before writing**, where PHP is reachable: `php -l`. It catches the parse-error
   class outright, which is most edit-induced fatals.
3. **Verify what a visitor receives immediately after the write**, and roll back on a 5xx or on
   WordPress's critical-error page. The loop already requires verification; without staging it also
   becomes the trigger for an automatic revert.
4. **Check the safety net before relying on it.** WordPress 5.2 and later catch a fatal from a
   plugin or theme on a normal page load, pause the offending component *for the admin session*, and
   email a recovery link. Three limits matter: the **frontend still shows the critical-error page to
   visitors** in the meantime, cron and background tasks are not covered, and the recovery email can
   silently fail — WordPress documents that when the fatal happens before a mail plugin loads, mail
   goes out through the web server and *"might never reach the admin's inbox."* Confirm the admin
   address can actually receive mail before treating this as the fallback, and never present it as
   making an edit safe.
5. **Prefer a low-traffic window**, and say in the report that the change went to production
   untested, under `## Deliberate decisions`. A reader who is not told will assume it was staged.

For a **database** change with no staging, the picture is easier: the change is re-applied on
production either way, snapshots capture the prior value, and the rollback is setting it back.

**Sources:** [Kinsta staging environments](https://kinsta.com/docs/wordpress-hosting/staging-environment/) ·
[Kinsta push environments](https://kinsta.com/docs/wordpress-hosting/wordpress-push-environments/) ·
[WordPress Recovery Mode](https://wordpress.org/documentation/article/recovery-mode/)
