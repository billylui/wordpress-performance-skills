<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# WordPress multisite shared-resource contention

A multisite network lets independently behaving sites compete for shared users, database capacity, PHP workers, caches, plugins, and storage operations.

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

One sub-site can have high origin TTFB, timeouts, cache churn, upload latency, or scheduled-task spikes while neighboring sites appear healthy. Under shared saturation, all sub-sites and Network Admin can slow together.

By default, `wp_users` and `wp_usermeta` are shared network-wide rather than duplicated per site. With a custom database prefix, the names change but the base user tables remain shared. User-heavy networks often expose this shared path first: Network Admin user searches, listings, role/capability lookups, and screens that join or scan growing usermeta degrade as the shared table grows.

## Detect

### At tier 0 (public URL only)

**WordPress multisite normally has no definitive public marker. At tier 0, `multisite` is almost always `unknown`.** Subdomains, subdirectories, a shared theme, similar headers, or common analytics can all be produced without multisite.

Run:

```sh
python3 skills/wp-perf-audit/scripts/fingerprint.py https://example.com/ --json fingerprint.json --quiet
```

The expected public result is `profile.multisite.value: "unknown"` with no invented confidence. Publicly visible `/wp-content/uploads/sites/<number>/` URLs are circumstantial evidence of per-site uploads, not definitive proof of the current topology: copied media and legacy paths can outlive a configuration.

At tier 0, measure suspected sub-sites separately and preserve their hostname/path, cache status header, origin TTFB, edge TTFB, and errors. Do not aggregate the network into one median before locating the slow segment.

### At tier 1+ (admin / REST)

Authenticated access settles the question when the operator can load `/wp-admin/network/` and the Network Admin Sites screen lists network sites. Capture the visible site count and the affected site's URL; a redirect to a normal site dashboard or a permissions error does not settle absence.

The definitive tier-1 evidence is an authenticated Network Admin screen, not the public REST index. The public REST index proves WordPress, not multisite or administrator capability.

Also capture:

- the Network Admin Users screen's response time and query count if the existing admin tooling exposes it;
- network-activated plugins versus plugins activated only for a site;
- the affected sub-site's upload URL and filesystem path shown by WordPress media/site information;
- whether a domain mapping or edge rule routes the hostname to the expected `blog_id`.

### At tier 2+ (WP-CLI / SSH)

These commands produce checkable evidence:

```sh
wp core is-installed --network
wp config get MULTISITE --type=constant
wp site list --fields=blog_id,url --format=json
wp plugin list --status=active-network --fields=name,status --format=json
```

`wp core is-installed --network` settling successfully and `wp site list` returning a JSON array of `blog_id`/`url` rows confirm multisite. Record failures literally; a command run against the wrong WordPress root proves nothing.

Use `wp db prefix` to determine the actual base prefix before referring to `wp_users` or `wp_usermeta`. Use the [official WordPress agent skills](https://github.com/WordPress/agent-skills) `wp-performance` workflow for query, usermeta, autoload, object-cache, and cron depth.

### By stack

| Stack | Signal | Confidence | Notes |
|---|---|---|---|
| subdomain network | Authenticated `wp site list --fields=blog_id,url --format=json` maps multiple hostnames to distinct `blog_id` values | high | DNS and certificates remain separate operational dependencies. |
| subdirectory network | The same output maps distinct paths on one hostname to distinct `blog_id` values | high | A reverse proxy can imitate this publicly, so tier 0 remains `unknown`. |
| `multilingualpress` | The `multilingual` signal is `multilingualpress`, and tier-1/2 evidence maps language sites to network `blog_id` values | high | See [Multilingual architecture and per-language work](./multilingual.md). |

## Attribute

Segment first, then compare:

1. Build the authoritative `blog_id` to URL map.
2. Measure each sub-site's representative anonymous page with the same repeats and warm-cache state. Keep origin and edge TTFB separate.
3. Tag application, PHP, database, cache, and scheduled-task evidence with hostname and `blog_id`. If a layer cannot be segmented, state that attribution is `unknown` and name the logging field or per-site run needed.
4. Compare the slow site's result with at least one healthy site on the same network and time window.
5. For Network Admin slowness, correlate the slow request with queries against the base-prefix users/usermeta tables; do not blame total network size without query evidence.
6. For upload problems, resolve WordPress's actual upload directory and URL for the affected site. Do not infer the write path solely from public markup.

A site-specific plugin request, cron burst, uncached endpoint, or database query that consumes the shared pool supports attribution. Disproof includes equally slow independent sites with no shared-resource saturation, or a delay entirely at one site's external CDN/origin path.

## Fix

### The change

Apply the smallest fix to the identified segment:

- Correct the slow sub-site's query, request, scheduled task, cache policy, or external dependency before scaling the whole network.
- Add or repair per-site observability keyed by hostname and `blog_id`; keep shared user-table measurements explicitly labeled network-wide.
- Reduce unnecessary usermeta reads/writes and clean only orphaned data proven safe by the official backend workflow. Do not bulk-delete usermeta by key-name guesswork.
- Network-activate a plugin only when every sub-site needs its boot hooks, assets, scheduled events, and database work. Otherwise prefer controlled per-site activation.
- Keep upload fixes scoped to the affected site's resolved directory and URL. Preserve attachment metadata and offload mappings.
- When one site legitimately needs exceptional capacity, isolate its workers, cache namespace, scheduled tasks, or hosting only after measurements show shared contention.

### Host constraints

| Host class | Permitted | Path |
|---|---|---|
| `wpengine` | Multisite topology, cache, and domain changes are conditional on the installed environment and current platform controls. | Confirm network support and the supported change path before mutation. |
| `kinsta` | Topology, worker, and cache changes are conditional on the installed environment and current platform controls. | Use platform observability to segment hostnames before requesting resource changes. |
| `pantheon` | Preserve platform routing and cache integration. | Confirm domain/site mapping and deployment workflow before topology changes. |
| `wpcom` | Available network and plugin controls depend on the site's operating model. | Escalate controls not exposed to the operator rather than bypassing them. |
| `wpvip` | Follow platform review for code, cache, and network-wide plugin changes. | Provide per-`blog_id` evidence with the change request. |
| `other` | Restrictions are `unknown` until multisite support, cache ownership, and filesystem policy are checked. | Record the host policy source before changing topology or shared services. |

### Risk

Network-wide changes have a multiplied blast radius. User-table cleanup can remove roles or capabilities across sites; network activation can add work to every request; upload path mistakes can break media for one site or the whole network; cache namespace mistakes can leak one site's content into another hostname.

## Verify

Purge only the affected cache namespaces where possible, then warm each comparison URL. Re-run identical measurements for the slow sub-site, a healthy control sub-site, and Network Admin if it was part of the symptom.

Verify:

- the `blog_id`/URL map is unchanged unless topology was intentionally changed;
- each hostname serves its own content and cache key;
- users retain the correct roles on representative sites;
- Network Admin Users and Sites screens complete correctly;
- network-active and per-site plugin states match the captured baseline;
- uploads create and render under the affected site's resolved path;
- shared worker, database, and cache saturation no longer correlates with the one site's workload.

Do not compare a cold post-purge request with a warm baseline.

## Rollback

Before change, capture `wp site list` JSON, network and per-site plugin lists, domain mappings, cache namespace rules, upload paths/URLs, relevant scheduled tasks, and database backups for any data mutation.

Rollback means restoring the previous plugin activation scope, routing/cache rule, scheduled-task ownership, upload configuration, or isolated resource assignment. Restore data from the captured backup rather than attempting inverse deletion. Purge the affected cache namespace and verify at least one representative URL per involved `blog_id`.

## Gotchas

- `wp_users` and `wp_usermeta` are the default-prefix names; use `wp db prefix` before issuing a query on a custom-prefix network.
- A single sub-site can exhaust shared PHP workers or database capacity even when its own page count is small.
- Network activation cost includes plugin bootstrap and hooks on sites that never use the feature.
- The main site's uploads commonly use the base uploads location while sub-sites use site-specific directories; resolve the actual path rather than constructing it from memory.
- Domain mapping can hide a network relationship completely from public HTML.
- A shared object cache needs correct site/blog key separation. Faster wrong-site data is a correctness failure, not a performance fix.
