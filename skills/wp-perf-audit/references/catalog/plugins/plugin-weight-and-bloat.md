<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Plugin weight and request-wide bloat

A plugin becomes a performance defect when measured work, assets, queries, or autoloaded state run more broadly or more expensively than the feature requires.

## Contents

- [Symptom](#symptom)
- [Detect](#detect)
  - [At tier 0 (public URL only)](#at-tier-0-public-url-only)
  - [At tier 1+ (admin / REST)](#at-tier-1-admin--rest)
  - [At tier 2+ (WP-CLI / SSH)](#at-tier-2-wp-cli--ssh)
  - [By stack](#by-stack)
- [Attribute](#attribute)
- [Fix](#fix)
  - [The change](#the-change)
  - [Host constraints](#host-constraints)
  - [Risk](#risk)
- [Verify](#verify)
- [Rollback](#rollback)
- [Gotchas](#gotchas)

## Symptom

Pages transfer CSS or JavaScript for features they do not use, or every request shows added origin TTFB, queries, remote calls, scheduled work, or memory use. The operator may also find abandoned plugins, multiple plugins serving the same purpose, and large autoloaded options initialized on every WordPress request.

**Plugin count alone is a weak signal. Twenty lightweight plugins can cost less than one heavy page builder.** Count is inventory, not attribution, and a target such as “reduce plugins to ten” has no performance meaning without measurement.

## Detect

### At tier 0 (public URL only)

Use a payload walk and retain the JSON baseline:

```sh
python3 skills/wp-perf-audit/scripts/perf-probe.py --site https://example.com --repeats 3 --json baseline.json
```

For each representative page, inventory exact request URLs under `/wp-content/plugins/<slug>/`, transferred bytes, initiator, render-blocking position, and whether the page actually renders the plugin's feature. A vendor-namespaced asset path is strong ownership evidence for the asset, but it is not proof that the plugin caused all page delay.

Compare at least:

- a page that needs the feature;
- a page that does not need it;
- the homepage or another high-traffic template;
- a clean anonymous session and, where relevant, a logged-in session.

Public HTML cannot reveal the complete active-plugin list, PHP hook time, autoloaded option size, or database query ownership. Report those as `unknown` at tier 0 and name tier 1/2 as the next check.

### At tier 1+ (admin / REST)

Capture an active-plugin inventory and map each plugin to an owner, required feature, pages/routes, scheduled jobs, external services, and a rollback contact. Record plugins with no operator-recognized purpose as “unconfirmed,” not “unused.”

Use existing admin diagnostics, if already installed and approved, to capture per-request queries or HTTP calls. Do not install a profiler on production merely to make the table look complete.

Check for:

- settings that enqueue assets globally or enable modules not in use;
- duplicate-purpose plugins whose live responsibilities overlap;
- abandoned plugins with no active owner or required feature;
- options configured to autoload despite being large or used only on rare admin/background paths;
- recurring jobs or remote calls that execute on unrelated frontend requests.

### At tier 2+ (WP-CLI / SSH)

Inventory is checkable:

```sh
wp plugin list --fields=name,status,version --format=json
```

The list still does not attribute cost. For hook timing, slow queries, autoloaded option size, object cache, cron, and source attribution, use the [official WordPress agent skills](https://github.com/WordPress/agent-skills) `wp-performance` workflow. This catalog covers the complementary browser-visible, live-site comparison; do not recreate the backend workflow here.

Run `capabilities.py --target https://example.com/ --json capabilities.json` first and keep `cannot_measure` in the audit. If tier 2 was not actually confirmed, backend plugin attribution remains `unknown`.

### By stack

| Stack | Signal | Confidence | Notes |
|---|---|---|---|
| `elementor` | Builder-owned frontend assets and stored widget content are present on pages without the corresponding widget | medium | One heavy builder can dominate more than many small plugins; attribute modules/assets, not count. |
| `divi` | Theme/builder assets remain on a controlled page that does not use their feature | medium | Ownership can span theme and plugin; public paths alone may not separate them. |
| `wpbakery` | Vendor asset paths and rendered classes persist on a page without the component | medium | Stored shortcodes can make an apparently unused plugin a content dependency. |
| `page-plugin` | A caching/optimization plugin injects identifiable assets or markup while another layer already owns the same purpose | low | Overlap is a hypothesis; confirm actual configuration and measured work at tier 1. |

## Attribute

Use a controlled one-variable comparison, preferably on staging or an equivalent isolated environment with production-like data and cache layers:

1. Save a warm baseline with identical URLs, repeats, browser state, and cache status.
2. Change one plugin/module/asset-loading rule only.
3. Purge the same affected layers, warm again, and repeat the measurement.
4. Compare request count, transferred bytes, render blocking, origin/edge TTFB, and the relevant browser metric.
5. At tier 2, require the official backend workflow to identify plugin-owned hook, query, option, cron, or remote-call cost.
6. Restore the candidate before testing another one, unless the approved plan explicitly measures cumulative changes.

Attribute site-wide asset bloat when the plugin-owned request disappears from a page that does not need the feature and the measured metric improves without functional loss. Attribute server cost only when the plugin's controlled removal/configuration changes repeatable backend evidence.

Disproof includes no repeatable delta, an asset required by another component, cost owned by a theme or mu-plugin, or a change that merely shifts work to another request.

## Fix

### The change

Apply the smallest measured change:

- Configure the plugin to load its CSS/JavaScript only on routes or components that use the feature. Prefer the plugin's supported setting or conditional API over dequeuing handles by filename.
- Disable unused modules before disabling the whole plugin.
- Change autoload behavior only for options proven large, rarely required, and safe to load on demand; preserve serialized data and plugin upgrade expectations.
- Remove an abandoned or duplicate-purpose plugin only after mapping every shortcode, block, widget, endpoint, scheduled task, CLI job, and stored-data dependency to a retained replacement or an intentional retirement.
- Fix or reschedule measured recurring work and remote calls rather than suppressing all background processing.
- Keep a security, firewall, backup, audit, or compliance plugin when its work is required. Surface its measured cost and operational value as a tradeoff; optimize its configuration or architecture with the responsible operator.

Recommending that an operator disable a firewall to save 40 ms is bad advice. The security control may be doing exactly the work the operator wants.

### Host constraints

| Host class | Permitted | Path |
|---|---|---|
| `wpengine` | Ordinary conditional loading and redundant-plugin removal are conditional on current platform prohibited-plugin, cache, backup, and security policy. | Check policy and mu-plugins before changing overlapping infrastructure plugins. |
| `kinsta` | Ordinary conditional loading and redundant-plugin removal are conditional on current platform cache, backup, and security ownership. | Check policy and platform tooling before replacing infrastructure work. |
| `pantheon` | Preserve platform cache and deployment integration. | Test plugin/module changes in the platform workflow before production. |
| `wpcom` | Plugin and code controls may be unavailable to the operator. | Use exposed controls or platform support; do not devise an unsupported bypass. |
| `wpvip` | Code and plugin changes require the platform's review/deployment path. | Attach attribution evidence and rollback scope to the review. |
| `other` | Restrictions are `unknown` until the host's current prohibited-plugin and managed-service policy is checked. | Record who owns cache, firewall, backup, and deployment before removal. |

### Risk

Conditional dequeues can remove a dependency used by a modal, form, checkout, consent flow, or logged-in state. Removing a plugin can orphan shortcodes, blocks, tables, scheduled events, or security/backup coverage. Changing autoload flags can move cost rather than remove it or break code that assumes an option is initialized.

## Verify

After purging the affected `page-plugin`, `server`, and `edge` layers, warm the same URLs and compare against the saved baseline with:

```sh
python3 skills/wp-perf-audit/scripts/perf-probe.py --diff baseline.json after.json
```

Verify both performance and behavior:

- plugin-owned assets remain on every page/state that needs them and disappear only where unnecessary;
- forms, menus, modals, commerce, consent, search, logged-in, and error states still work;
- scheduled jobs, backups, firewall events, alerts, and external integrations still complete;
- the improvement repeats with matching cache status and no new console/network errors;
- tier-2 backend evidence, when available, confirms the targeted hook/query/option/job changed;
- no stored shortcode, block, widget, or endpoint became orphaned.

Do not compare a cold post-purge request with a warm baseline, and do not claim a win from plugin count alone.

## Rollback

Before change, capture plugin files/version source, settings export, active status, asset handles and conditions, relevant option rows with autoload state, scheduled events, dependencies, and the performance baseline. Capture a restorable database backup before data or autoload mutation.

Rollback means restoring the plugin/module, original enqueue conditions, option/autoload state, scheduled work, and any displaced infrastructure coverage. Purge affected caches, warm the original URLs, and repeat functional and performance verification.

## Gotchas

- `/wp-content/plugins/<slug>/` attributes a public asset to a path, not total server time to a plugin.
- An inactive-looking plugin can still own stored shortcodes, blocks, scheduled events, CLI jobs, or data needed during migration.
- Mu-plugins and host integrations may perform the apparent duplicate purpose without appearing in the ordinary active-plugin list.
- Combining plugins can reduce administration while increasing runtime cost; consolidation is not automatically optimization.
- Security and backup work often belongs off the visitor-critical path, but moving it requires an operational design, not blind disabling.
- A plugin's cost can be acceptable. The audit should present measured cost, benefit, risk, and alternatives so the operator can choose.
