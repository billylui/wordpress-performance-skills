<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Host constraints: hard gate before a production change

This reference decides whether a proposed WordPress performance change may proceed on a hosting
platform. It is a refusal gate, not a compatibility guide.

## Contents

- [How to use this gate](#how-to-use-this-gate)
- [Summary gate](#summary-gate)
- [Host-specific constraints](#host-specific-constraints)
  - [`wpengine`](#wpengine)
  - [`kinsta`](#kinsta)
  - [`siteground`](#siteground)
  - [`godaddy`](#godaddy)
  - [`cloudways`](#cloudways)
  - [`flywheel`](#flywheel)
  - [`pressable`](#pressable)
  - [`rocket-net`](#rocket-net)
  - [`hostinger`](#hostinger)
  - [`bluehost`](#bluehost)
  - [`pantheon`](#pantheon)
  - [`wpcom`](#wpcom)
  - [`wpvip`](#wpvip)
  - [`shared-cpanel`](#shared-cpanel)
  - [`self-managed`](#self-managed)
  - [`other`](#other)
  - [`unknown`](#unknown)
- [Host permission is not site suitability](#host-permission-is-not-site-suitability)
- [The restrictive default for `unknown` and `other`](#the-restrictive-default-for-unknown-and-other)

## How to use this gate

1. Read `profile.host_class.value`, `confidence`, and `evidence` from the stack profile produced by
   `fingerprint.py`. The real invocation is:

   ```sh
   python3 "$SKILL_DIR/../wp-perf-audit/scripts/fingerprint.py" URL --json stack.json
   ```

2. A low-confidence host match does not authorize a write. Confirm the provider and exact hosting
   product in the account control plane, contract, invoice, or a support response. Public host
   headers are commonly stripped by a CDN, reverse proxy, or security rule; in that case
   `fingerprint.py` correctly reports `unknown`.
3. Match only the exact `host_class` identifiers in this file. Do not translate a marketing plan
   name into a different class by intuition.
4. Apply the page-cache result in the summary table. **`UNCONFIRMABLE` means `PROHIBITED until
   confirmed` by the host for the exact product, plan, plugin, and intended configuration.** Silence,
   an installation button, an already-installed plugin, and success on staging are not permission.
5. Apply every detailed constraint for the matching host. If the host documentation does not settle
   a cell, obtain confirmation from the host before planning the change. A general hosting policy
   does not prove that a reseller, legacy product, or custom enterprise environment follows it.
6. Record the first-party documentation or support response used for the decision in the change
   plan. Policies can change; re-open the linked host document at execution time.
7. If the gate is not satisfied, set the change's `risk_lane` to `prohibited`.
   [`validate_plan.py`](../scripts/validate_plan.py) must reject the plan rather than skip the change.

This gate does not replace the production loop. A permitted change still needs per-change approval,
a snapshot whose existence was verified, the correct layer-specific purge, visitor-visible
verification, and a warm re-measurement.

## Summary gate

`PERMITTED ONLY` is narrow permission for the named host-supported path, not blanket permission for
the plugin category. Every unnamed product remains `UNCONFIRMABLE` and therefore `PROHIBITED`.

| `host_class` | Page-cache plugin gate | Host plugin-policy list | Production path and file-survival gate |
|---|---|---|---|
| `wpengine` | **PROHIBITED** unless the exact plugin and caching feature are approved by WP Engine; listed page caches are disallowed. | **Yes:** first-party disallowed-plugin list. | Dashboard environment copy, SFTP, SSH, or GitPush may be in use. A later GitPush overwrites tracked direct edits. Confirm the site's authoritative path. |
| `kinsta` | **PROHIBITED** unless Kinsta explicitly supports the exact integration; supported optimization plugins may have their page cache disabled. | **Yes:** first-party banned/incompatible list. | MyKinsta can push selected files or database content between environments. A push can overwrite production scope; confirm the selected scope. |
| `siteground` | **PERMITTED ONLY:** `sg-optimizer` is the documented SiteGround path. Every other page-cache plugin is **UNCONFIRMABLE → PROHIBITED** until SiteGround confirms it. | **Unconfirmed:** confirm whether a list applies to the exact product. | Staging, Git, SSH, SFTP, and WP-CLI availability is product-dependent. Confirm the production deploy owner before editing files. |
| `godaddy` | **UNCONFIRMABLE → PROHIBITED.** Confirm with GoDaddy for the exact Managed Hosting for WordPress, Web Hosting, WooCommerce, VPS, or reseller product. | **Unconfirmed:** confirm with GoDaddy. | Managed-product staging can push files and optionally database content; SFTP and SSH/WP-CLI are plan-dependent. A staging sync can overwrite live data. |
| `cloudways` | **PERMITTED ONLY:** `breeze` and the specifically documented WP Rocket integration. Every other page-cache plugin is **UNCONFIRMABLE → PROHIBITED**. | **Unconfirmed:** confirm whether a list applies to the application. | Confirm staging and the authoritative Git/SFTP/SSH workflow for the application. Do not assume a direct file edit survives the next deployment. |
| `flywheel` | **PROHIBITED** for full-page caching. Flywheel documents server caching and lists caching plugins as unsupported/not recommended; optimization-only features require their cache feature to be off. | **Yes, but not a blanket ban:** first-party “not recommended plugins” list. | Dashboard staging/push and SSH/GitHub Actions may deploy code. Confirm which path owns production before editing. |
| `pressable` | **PROHIBITED** for third-party full-page caching. Pressable owns read-only `advanced-cache.php` and `object-cache.php`; use its platform cache controls. | **Unconfirmed:** no blanket disallowed list is established here. | Staging, SFTP, and SSH are documented. Managed drop-ins are read-only; other PHP file-write permissions can be controlled by the platform. |
| `rocket-net` | **UNCONFIRMABLE → PROHIBITED.** First-party documentation sufficient to verify a page-cache plugin allowance was not confirmed. | **Unconfirmed:** confirm with Rocket.net. | Staging, WP-CLI, deployment path, cron, object cache, and deployed-tree persistence all require confirmation for the exact account. |
| `hostinger` | **PERMITTED with conditions:** first-party docs allow a WordPress cache plugin alongside host cache and require only one cache plugin. Confirm the exact product and plugin before installation. | **Unconfirmed:** confirm with Hostinger. | hPanel staging publish replaces live files and database. Git and SSH availability vary by product; determine the authoritative path first. |
| `bluehost` | **PROHIBITED** on products covered by Bluehost's cache guidance: third-party page-cache plugins should not be installed and existing ones should be removed. For any other product, **UNCONFIRMABLE → PROHIBITED**. | **Unconfirmed:** confirm with Bluehost. | Staging, WP-CLI, deploy method, cron, and file persistence vary by product and must be confirmed. |
| `pantheon` | **UNCONFIRMABLE → PROHIBITED** unless the exact plugin and configuration are compatible with Pantheon's documented workflow. Do not add an independent page cache by default. | **Yes, but not a ban list:** first-party WordPress known-issues list; Pantheon says listed plugins are not automatically prevented. | Code moves Dev → Test → Live through Pantheon workflow. Test and Live code are read-only; runtime writes to the deployed code tree fail. |
| `wpcom` | **PROHIBITED.** WordPress.com supplies caching and blocks or disables incompatible caching plugins. | **Yes:** first-party incompatible-plugin list. | Staging, SFTP, SSH, WP-CLI, and GitHub deployment are plan-dependent. Core and platform-managed files are protected. |
| `wpvip` | **UNCONFIRMABLE → PROHIBITED** unless WordPress VIP approves the exact cache integration. The platform already owns page delivery. | **Unconfirmed as a blanket list:** use VIP code review, scanning, and support for the exact plugin. | Code moves through the application repository or an approved custom deployment. Web containers are read-only and there is no SFTP code path. |
| `shared-cpanel` | **UNCONFIRMABLE → PROHIBITED.** cPanel identifies a control panel, not a provider or cache policy. | **Unconfirmed:** ask the actual host/reseller. | Staging, SSH/WP-CLI, cron, object cache, and persistence are provider- and account-specific. Confirm every item. |
| `self-managed` | **PERMITTED ONLY** after the operator proves administrative authority and inventories every existing cache owner. No upstream host permission can be inferred from this label. | **Operator-owned:** document the local allow/deny policy. | The operator must identify the deployment source of truth, scheduler, object cache, writable paths, rollback, and purge path. |
| `other` | **UNCONFIRMABLE → PROHIBITED.** This is the most restrictive lane until the provider and product are mapped to documented policy. | **Unconfirmed:** ask the provider. | Treat staging, deployment, WP-CLI, cron, object cache, and file persistence as unavailable until confirmed. |
| `unknown` | **UNCONFIRMABLE → PROHIBITED.** This is the most restrictive lane; do not install, activate, configure, or remove a page-cache plugin. | **Unknown:** identify the provider first. | No production write is allowed until the provider, product, source of truth, writable scope, and rollback path are confirmed. |

## Host-specific constraints

### `wpengine`

- **Identify:** `fingerprint.py` reports `wpengine` only from `x-wpe-*` response headers at high
  confidence, or from a vendor label in the target hostname at low confidence. Confirm any
  low-confidence result in the WP Engine User Portal.
- **Page cache and policy list:** **PROHIBITED by default.** WP Engine maintains a disallowed list,
  explains that caching plugins can conflict with its built-in cache, and says listed plugins are
  eventually removed. Check the exact directory-name list before every proposal; do not infer that
  an unlisted cache is supported. [WP Engine: disallowed plugins](https://wpengine.com/support/disallowed-plugins/)
- **Staging and deploy:** Production, Staging, and Development are separate environments. The User
  Portal can copy between them; a filesystem copy is destructive to the destination. GitPush and
  SFTP are also possible, but a later GitPush reverts direct edits to tracked files. Never control
  one file through both SFTP and Git. [environments](https://wpengine.com/support/environments/),
  [environment copy](https://wpengine.com/support/copy-site/),
  [GitPush](https://wpengine.com/support/git/)
- **WP-CLI:** WP-CLI is documented through SSH Gateway. Its availability does not make it the
  authoritative deploy path; confirm whether GitPush or an environment copy owns the changed file.
  [SSH/WP-CLI troubleshooting](https://wpengine.com/support/troubleshoot-ssh-gateway/)
- **Cron:** Default `wp-cron` is visitor-triggered. WP Engine's Alternate Cron is a separate
  platform option that disables default `wp-cron`; adding `DISABLE_WP_CRON` alone does not enable
  it. Confirm the portal toggle before changing cron configuration.
  [event scheduling](https://wpengine.com/support/wp-cron-wordpress-scheduling/)
- **Object cache:** Platform object caching can be enabled per environment and has a separate purge
  control. Confirm its enabled state; do not infer it from page-cache headers.
  [object caching](https://wpengine.com/support/wp-engines-object-caching/)
- **Files and restrictions:** Disk writes are limited, and WP Engine directs operators to Support
  for exact privileges. GitPush rejects platform-owned files including `wp-config.php` and
  `wp-content/object-cache.php`. Treat any change to those paths as **PROHIBITED** unless Support
  supplies the supported path. [security environment](https://wpengine.com/support/wp-engines-security-environment/),
  [GitPush restrictions](https://wpengine.com/support/git/)

### `kinsta`

- **Identify:** `fingerprint.py` uses `x-kinsta-*` for a high-confidence `kinsta` result. If those
  headers are absent, confirm the site in MyKinsta rather than guessing from DNS or appearance.
- **Page cache and policy list:** **PROHIBITED by default.** Kinsta publishes a banned/incompatible
  plugin list, says caching plugins are generally not allowed, and blocks installation of banned
  plugins. A documented optimization-plugin exception does not grant its own page cache; the
  conflicting cache function can be disabled. [Kinsta: banned and incompatible plugins](https://kinsta.com/docs/wordpress-hosting/wordpress-plugins-themes/wordpress-banned-incompatible-plugins/)
- **Staging and deploy:** MyKinsta can push staging to live, live to staging, or between sites, with
  selective file and database scope. A target backup is created, but that does not make a push
  non-destructive. Record the exact selected scope and protect production-only transactional data.
  [push environments](https://kinsta.com/docs/wordpress-hosting/wordpress-push-environments/)
- **WP-CLI:** SSH is documented for managed WordPress sites and Kinsta documents WP-CLI cache
  controls. Use it only after confirming the target environment and the site's deploy source of
  truth. [SSH](https://kinsta.com/docs/wordpress-hosting/connect-to-ssh/),
  [caching](https://kinsta.com/docs/wordpress-hosting/caching/)
- **Cron:** A site can keep WordPress cron or use a real container crontab. Custom jobs at the top
  of the crontab can be overwritten by Kinsta maintenance, staging, or backup jobs. Confirm which
  scheduler owns each event before changing `DISABLE_WP_CRON`.
  [cron jobs](https://kinsta.com/docs/wordpress-hosting/site-management/cron-jobs/)
- **Object cache:** Redis is a separately enabled cache path in Kinsta's caching controls. Confirm
  that it exists on this environment before planning an `object` purge.
  [caching](https://kinsta.com/docs/wordpress-hosting/caching/)
- **Files and restrictions:** The host documentation cited here does not establish that an ad hoc
  production edit survives every customer-defined deploy workflow. **Confirm the repository,
  automation, and MyKinsta push scope; until then, treat direct production code edits as
  PROHIBITED.**

### `siteground`

- **Identify:** `fingerprint.py` uses `x-sg-*` for a high-confidence `siteground` result. Confirm
  the exact SiteGround product in Site Tools when the signal is low-confidence or missing.
- **Page cache and policy list:** **PERMITTED ONLY for the documented `sg-optimizer` path.** The
  host recommends Speed Optimizer and exposes Dynamic Cache separately. Its documentation also
  acknowledges third-party caches but does not establish blanket permission for every cache
  plugin. Any other page cache is **UNCONFIRMABLE → PROHIBITED** pending SiteGround confirmation.
  [PageSpeed guidance](https://www.siteground.com/kb/google-pagespeed-insights-guide/),
  [cache layers](https://www.siteground.com/kb/changes_not_showing_up_my_wordpress_site/)
- **Policy list:** A host-wide disallowed-plugin list was not confirmed in the first-party sources
  used here. Ask SiteGround about the exact plugin; treat the absence of a public list as no
  permission.
- **Staging and deploy:** SiteGround documents staging, Git, SSH/SFTP, and WP-CLI capabilities, but
  availability and the authoritative workflow can vary by hosting product. Confirm whether
  production is reached by staging publish, Git deployment, SFTP, or another Site Tools action.
  [managed WordPress features](https://download.siteground.com/files/managed-wordpress-hosting.pdf)
- **WP-CLI:** Confirm it by exercising it against the intended environment. Its presence does not
  authorize plugin installation, server configuration, or a bypass of staging.
- **Cron:** WordPress cron can remain enabled and Site Tools can schedule server cron jobs. The host
  docs do not prove which mode this site uses. Confirm both `DISABLE_WP_CRON` and Site Tools before
  changing either. [WordPress cron](https://eu.siteground.com/kb/enable-wordpress-cron/),
  [Site Tools cron](https://eu.siteground.com/kb/manage-cron-jobs/)
- **Object cache:** Site Tools exposes Memcached separately from Dynamic Cache. Confirm its enabled
  state and purge path for this site; never infer `object` from page-cache status.
  [cache layers](https://www.siteground.com/kb/changes_not_showing_up_my_wordpress_site/)
- **Files and restrictions:** File Manager can edit `public_html`, but this does not prove that a
  later Git or staging deployment will preserve the edit. Confirm the production source of truth;
  otherwise direct production code edits are **PROHIBITED**.

### `godaddy`

- **Identify:** `fingerprint.py` uses `x-gd-*` for a high-confidence `godaddy` result. The class
  does not distinguish Managed Hosting for WordPress, Web Hosting, WooCommerce, VPS, dedicated, or
  reseller products. Confirm the exact product before using any policy below.
- **Page cache and policy list:** **UNCONFIRMABLE → PROHIBITED.** A blanket first-party page-cache
  allowance or disallowed-plugin list was not confirmed for every product represented by this
  class. Ask GoDaddy about the exact product and plugin before installation, activation,
  configuration, deactivation, or removal.
- **Staging and deploy:** Managed-product staging is plan-dependent and uses dashboard sync. The
  documented push moves `wp-content` files and can optionally overwrite the production database;
  production-only orders, users, or content can be lost. SFTP is also documented. Record exactly
  which path owns production. [staging](https://www.godaddy.com/en-ph/help/set-up-a-staging-site-for-my-managed-hosting-for-wordpress-site-12292),
  [push to production](https://www.godaddy.com/en-ca/help/push-my-staging-site-to-the-production-site-16467),
  [SFTP](https://www.godaddy.com/help/upload-files-with-sftp-on-managed-hosting-for-wordpress-8940)
- **WP-CLI:** Managed-product WP-CLI is available through SSH on eligible plans; other products can
  differ. Confirm the plan and environment. The host documents a platform cache-flush command, but
  that command is not evidence that every cache layer is enabled or cleared.
  [SSH](https://www.godaddy.com/en-ca/help/enable-ssh-on-managed-wordpress-24596),
  [WP-CLI](https://www.godaddy.com/en-in/help/use-wp-cli-to-manage-your-site-12066)
- **Cron:** Whether `wp-cron` remains visitor-triggered or is replaced by a platform schedule was
  not confirmed for the exact product. Treat scheduler changes as **PROHIBITED** until GoDaddy
  confirms the configured mode.
- **Object cache:** WP-CLI documentation names object and Varnish flushing, but that does not prove
  the layers exist on this account. Confirm the live cache inventory and separate purge paths.
- **Files and restrictions:** SFTP writes are possible on the managed product, but a later staging
  sync can overwrite `wp-content`. Persistence outside that scope and on other GoDaddy products is
  unconfirmed. Do not write until the source of truth and overwrite behavior are documented.

### `cloudways`

- **Identify:** `fingerprint.py` uses `x-cw-*` for a high-confidence `cloudways` result. Confirm
  the application and server in the Cloudways control plane if that marker is absent.
- **Page cache and policy list:** **PERMITTED ONLY for documented integrations.** Cloudways
  documents `breeze` as its default WordPress cache with Varnish integration and separately
  documents WP Rocket. Every other page-cache plugin is **UNCONFIRMABLE → PROHIBITED** until
  Cloudways confirms it for the application. A blanket disallowed-plugin list was not confirmed.
  [Breeze](https://support.cloudways.com/en/articles/5126470-how-to-install-and-configure-breeze-wordpress-cache-plugin),
  [WP Rocket](https://support.cloudways.com/en/articles/5133598-how-to-configure-wp-rocket-plugin-for-wordpress)
- **Staging and deploy:** The first-party sources used here do not settle whether this application
  reaches production through staging, Git, SFTP, SSH, or customer automation. Confirm the
  authoritative path. Until then, direct production code edits are **PROHIBITED**.
- **WP-CLI:** Cloudways documents WP-CLI management and Breeze-specific purge commands through SSH.
  Use only commands documented for the exact component; a generic WordPress cache flush does not
  prove that Varnish or an edge was cleared. [WP-CLI](https://support.cloudways.com/en/articles/5126427-how-to-manage-wordpress-with-wp-cli),
  [Breeze purge](https://support.cloudways.com/en/articles/5126470-how-to-install-and-configure-breeze-wordpress-cache-plugin)
- **Cron:** Visitor-triggered versus server-scheduled cron was not confirmed for this application.
  Inspect `DISABLE_WP_CRON`, the server's scheduled jobs, and Cloudways controls; prohibit changes
  until ownership is known.
- **Object cache:** Redis with Object Cache Pro is a separately managed service. Confirm whether it
  is enabled before declaring an `object` layer or planning its purge.
  [services](https://support.cloudways.com/en/articles/5120718-what-can-i-do-in-the-manage-services-section-on-cloudways)
- **Files and restrictions:** Deployment overwrite behavior was not confirmed for the application.
  Record the repository/automation and persistent writable paths before any write.

### `flywheel`

- **Identify:** `fingerprint.py` uses `x-fw-*` for a high-confidence `flywheel` result. Confirm the
  site in the Flywheel dashboard when headers are stripped.
- **Page cache and policy list:** **PROHIBITED for full-page caching.** Flywheel documents server
  caching, calls caching plugins unsupported/not recommended, and says caching features in broader
  optimization plugins should be disabled. Treat its “not recommended plugins” page as a policy
  list, but not as proof that an unlisted page cache is allowed.
  [not recommended plugins](https://getflywheel.com/wordpress-support/what-plugins-are-not-recommended/)
- **Staging and deploy:** Flywheel documents dashboard staging with push to production and also
  advertises SSH/GitHub Actions deployment. Confirm which workflow owns the site's code; do not
  mix direct edits with a deployment source of truth.
  [staging](https://getflywheel.com/wordpress-support/flywheel-provide-staging-environment/),
  [support index](https://getflywheel.com/wordpress-support)
- **WP-CLI:** WP-CLI availability and whether it is the supported mutation path were not confirmed
  for this exact plan. Exercise and confirm it before using it; otherwise treat it as unavailable.
- **Cron:** A platform replacement for visitor-triggered `wp-cron` was not confirmed. Inspect the
  live configuration and ask Flywheel before changing scheduling.
- **Object cache:** Platform-provided persistent object caching was not confirmed for this exact
  site. Keep the `object` layer `unknown` until the control plane or Support proves it.
- **Files and restrictions:** Flywheel says plugins cannot write `wp-config.php`, and `.htaccess`
  modifications do not apply to its Nginx platform. Treat those plugin behaviors as **PROHIBITED**.
  Confirm whether the next dashboard/Git deployment overwrites other direct file edits.

### `pressable`

- **Identify:** `fingerprint.py` uses `x-pressable-*` for a high-confidence `pressable` result.
  Confirm the site in MyPressable when public headers are absent.
- **Page cache and policy list:** **PROHIBITED for third-party full-page caching.** Pressable
  documents Batcache, object cache, and edge cache as platform-owned. Its `advanced-cache.php` and
  `object-cache.php` are read-only symlinks, so third-party caches cannot take ownership reliably.
  A blanket disallowed-plugin list was not confirmed; that absence grants no permission.
  [cache management](https://pressable.com/knowledgebase/pressable-cache-management-plugin/),
  [platform cache behavior](https://pressable.com/knowledgebase/understand-wordpress-errors-a-troubleshooting-guide-for-pressable-sites/)
- **Staging and deploy:** Pressable documents staging, SFTP, and SSH file transfer. Confirm whether
  the account also uses an external repository or automation before treating direct writes as
  durable. [manual migration and staging](https://pressable.com/knowledgebase/how-to-migrate-your-wordpress-site-to-pressable/)
- **WP-CLI:** SSH and WP-CLI are supported, but Pressable may restrict individual shell and WP-CLI
  commands. A command's existence is not approval; confirm the exact command when it affects
  production. [SSH limitations](https://pressable.com/knowledgebase/connect-to-ssh-on-pressable/)
- **Cron:** Visitor-triggered versus platform-scheduled cron was not confirmed. Inspect the live
  `wp-config.php` and account controls, then confirm with Pressable before changing it.
- **Object cache:** Memcache-backed object caching is platform-provided and its purge is separate
  from edge cache. Use the documented Pressable control and verify the visitor path afterward.
  [cache management](https://pressable.com/knowledgebase/pressable-cache-management-plugin/)
- **Files and restrictions:** Never replace the platform's read-only cache drop-ins. Pressable also
  exposes a PHP filesystem-permission control; confirm its state and the persistent writable scope
  before any plugin or process that writes themes, plugins, or generated files.
  [bulk operations](https://pressable.com/knowledgebase/run-bulk-operations-on-your-pressable-sites/)

### `rocket-net`

- **Identify:** `fingerprint.py` uses `x-rocketcdn-*` for a high-confidence `rocket-net` result.
  Confirm the account in Rocket.net's control plane if the edge strips or replaces that header.
- **Page cache and policy list:** **UNCONFIRMABLE → PROHIBITED.** First-party documentation
  sufficient to verify either a blanket page-cache-plugin allowance or a maintained
  disallowed-plugin list was not confirmed. Ask Rocket.net about the exact plugin and feature; do
  not infer permission from successful installation.
- **Staging and deploy:** Staging availability, production promotion method, Git/SFTP ownership,
  and overwrite behavior were not confirmed for the exact product. Treat staging as unavailable
  and production code writes as **PROHIBITED** until Support documents the workflow.
- **WP-CLI:** Availability and supported mutation scope were not confirmed. Treat WP-CLI as
  unavailable until exercised and approved for the production environment.
- **Cron:** Whether `wp-cron` is visitor-triggered or replaced by a platform schedule was not
  confirmed. Do not change `DISABLE_WP_CRON` or add a scheduler.
- **Object cache:** Platform object-cache provision and purge path were not confirmed. Keep the
  layer `unknown` and prohibit object-cache changes.
- **Files and restrictions:** Persistent writable paths and deploy overwrites were not confirmed.
  No file mutation is allowed until Rocket.net identifies the source of truth and supported path.

### `hostinger`

- **Identify:** `fingerprint.py` uses `x-hcdn-*` for a high-confidence `hostinger` result. Because
  that can describe an outer delivery layer, confirm that Hostinger also owns the origin account.
- **Page cache and policy list:** **PERMITTED with conditions.** Hostinger documents that its Cache
  Manager can coexist with a WordPress cache plugin and says only one cache plugin should be used.
  This is not permission for an arbitrary plugin on every product: confirm the exact hosting
  product, plugin, and interaction with LiteSpeed and CDN cache. A disallowed list was not
  confirmed. [Cache Manager](https://www.hostinger.com/support/6215624-how-to-use-cache-manager-at-hostinger/)
- **Staging and deploy:** hPanel staging is product-dependent. Publishing staging replaces the
  live files and database, so live changes made after the staging copy can be lost. Hostinger also
  documents Git deployment for eligible products; confirm whether Git or staging is authoritative.
  [staging](https://www.hostinger.com/support/5720286-how-to-create-a-wordpress-staging-environment-in-hostinger/),
  [Git deployment](https://www.hostinger.com/support/1583302-how-to-deploy-a-git-repository-in-hostinger/)
- **WP-CLI:** SSH availability varies by product. Confirm SSH and exercise WP-CLI on the intended
  environment before using it; otherwise treat it as unavailable.
  [SSH plan boundary](https://www.hostinger.com/support/4469097-how-to-restore-the-wordpress-system-files-at-hostinger/)
- **Cron:** A host-specific replacement for visitor-triggered `wp-cron` was not confirmed for the
  account. Inspect hPanel scheduled jobs and `DISABLE_WP_CRON`; prohibit changes until both agree.
- **Object cache:** Hostinger documents LiteSpeed Memcached management, but availability is
  product-specific. Confirm it is enabled and identify its purge separately from page/CDN cache.
  [WordPress management index](https://www.hostinger.com/support/website/wordpress-management/)
- **Files and restrictions:** A staging publish overwrites live files and database. Git deployment
  can also replace its configured root. Direct edits are **PROHIBITED** until the operator records
  which workflow owns each changed path.

### `bluehost`

- **Identify:** `fingerprint.py` uses `x-bluehost-*` for a high-confidence `bluehost` result.
  Confirm the exact Bluehost shared, WordPress, WooCommerce, cloud, VPS, dedicated, or reseller
  product; one class cannot safely imply one platform policy.
- **Page cache and policy list:** **PROHIBITED** for products covered by Bluehost's first-party
  caching guidance. It says Bluehost manages page caching and that third-party page-cache plugins
  should not be installed; existing ones should be removed. For every other Bluehost product,
  policy is **UNCONFIRMABLE → PROHIBITED**. A blanket disallowed-plugin list was not confirmed.
  [Bluehost caching](https://www.bluehost.com/help/article/caching-at-bluehost)
- **Staging and deploy:** Staging availability and whether production is reached by dashboard,
  SFTP, Git, or another workflow were not confirmed for the exact product. Treat staging as
  unavailable and direct code edits as **PROHIBITED** until Bluehost confirms both.
- **WP-CLI:** WP-CLI availability and its supported mutation scope were not confirmed for the exact
  product. Exercise it and confirm the production target before using it.
- **Cron:** Visitor-triggered versus platform-scheduled cron was not confirmed. Do not change cron
  configuration without a host-confirmed scheduler and rollback.
- **Object cache:** Bluehost documents Redis object cache on named product families, but the
  `bluehost` class does not identify a product. Confirm the account and enabled state before adding
  `object` to the plan. [Bluehost caching](https://www.bluehost.com/help/article/caching-at-bluehost)
- **Files and restrictions:** Persistent writable scope and deployment overwrites were not
  confirmed. No production file write proceeds until the source of truth is recorded.

### `pantheon`

- **Identify:** `fingerprint.py` uses `x-pantheon-*` or `x-styx-*` for a high-confidence
  `pantheon` result. Confirm the site and environment in the Pantheon dashboard.
- **Page cache and policy list:** **UNCONFIRMABLE → PROHIBITED** for an independent page-cache
  plugin. Pantheon publishes a WordPress known-issues list and explicitly says it does not prevent
  installation of listed plugins, but several caches need writable-path adaptations or have cache
  conflicts. “Not blocked” is not “safe.” Require exact compatibility evidence and host approval.
  [WordPress known issues](https://docs.pantheon.io/wordpress-known-issues)
- **Staging and deploy:** Pantheon's workflow moves code through Dev, Test, and Live. Code changes
  are committed in Dev and deployed upward through the dashboard or Terminus; production is not an
  SFTP-edited tree. [WP-CLI deployment example](https://docs.pantheon.io/guides/wp-cli/install-wp-plugins-themes)
- **WP-CLI:** WP-CLI is used through Pantheon/Terminus workflows. Use the documented environment
  target and deployment sequence; do not install or edit code directly on Test or Live.
- **Cron:** Whether the site's WordPress events are visitor-triggered or use a platform scheduler
  was not confirmed by the sources used here. Inspect platform configuration and ask Pantheon
  before changing cron behavior.
- **Object cache:** Redis may be part of a Pantheon site, but provision and purge behavior were not
  confirmed for this environment. Keep `object` as `unknown` until the dashboard or Support proves
  it.
- **Files and restrictions:** Test and Live code are read-only. Plugins that assume writes to the
  deployed tree can fail; only documented writable paths such as uploads or explicit symlinks may
  be used. Runtime code-tree writes are **PROHIBITED** and will not become deployments.
  [WordPress known issues](https://docs.pantheon.io/wordpress-known-issues)

### `wpcom`

- **Identify:** `fingerprint.py` uses `x-nananana` for a high-confidence `wpcom` result. Confirm
  WordPress.com hosting and the site's plan in its Hosting Dashboard; a WordPress.com account alone
  does not prove that the origin is hosted there.
- **Page cache and policy list:** **PROHIBITED.** WordPress.com publishes an incompatible-plugin
  list, blocks or disables named caching plugins, and directs customers to its built-in cache.
  Check the linked list for the exact plugin at proposal time.
  [incompatible plugins](https://wordpress.com/support/plugins/incompatible-plugins/),
  [cache guidance](https://wordpress.com/support/check-your-sites-performance/)
- **Staging and deploy:** Staging, SFTP, SSH, database access, and GitHub deployment are
  plan-dependent. Confirm the plan and connected GitHub deployment before changing code; do not
  infer that SFTP is the source of truth. [plugin and access boundaries](https://wordpress.com/support/plugins/install-a-plugin/),
  [tools](https://wordpress.com/support/category/plugins-and-tools/tools/)
- **WP-CLI:** WordPress.com documents WP-CLI through SSH for eligible sites. Its availability does
  not bypass incompatible-plugin controls or protected files.
  [WP-CLI](https://developer.wordpress.com/docs/developer-tools/wp-cli/)
- **Cron:** WordPress-level WP-Cron continues to handle WordPress scheduled tasks; server cron jobs
  are a separate feature. Confirm whether a server job has replaced the visitor-triggered path
  before changing `DISABLE_WP_CRON`. [server cron jobs](https://developer.wordpress.com/docs/developer-tools/server-cron-jobs/)
- **Object cache:** WordPress.com documents platform Memcached object cache and separate global
  edge cache. Use only the platform purge controls and verify both visitor content and warm cache
  behavior. [clear site cache](https://wordpress.com/support/clear-your-sites-cache/)
- **Files and restrictions:** Core, default platform themes/plugins, `advanced-cache.php`, and
  `object-cache.php` are protected. Editable scope is principally `wp-content` plus documented
  configuration. Theme updates can erase direct theme edits; a connected deploy can also own code.
  [SFTP/SSH restrictions](https://wordpress.com/support/sftp/troubleshooting-sftp/)

### `wpvip`

- **Identify:** `fingerprint.py` uses `x-vip-*` for a high-confidence `wpvip` result. Confirm the
  application and environment in the VIP Dashboard before using VIP policy.
- **Page cache and policy list:** **UNCONFIRMABLE → PROHIBITED** unless VIP approves the exact
  integration. WordPress VIP owns a page-cache/CDN layer. First-party material says applications
  can choose plugins and receive scanning, but that does not establish blanket permission for a
  second full-page cache. Use VIP code review and Support for the exact plugin.
  [infrastructure](https://docs.wpvip.com/guidebooks/develop-on-wpvip/wpvip-infrastructure/),
  [plugins on VIP](https://wpvip.com/plugins-on-wordpress-vip/)
- **Staging and deploy:** Applications normally include non-production environments. Code moves
  upward from non-production to production through the application's GitHub repository, or through
  an explicitly enabled custom deployment. Content moves downward, not into production.
  [applications and environments](https://docs.wpvip.com/guidebooks/develop-on-wpvip/applications-and-environments/),
  [custom deployment](https://docs.wpvip.com/code-deployment/custom-deployment/)
- **WP-CLI:** Use VIP-CLI's authenticated environment workflow. Direct generic WP-CLI availability
  is not assumed, and production database operations can be restricted or read-only.
  [VIP infrastructure](https://docs.wpvip.com/guidebooks/develop-on-wpvip/wpvip-infrastructure/)
- **Cron:** VIP documents platform protections around WP-Cron, but the sources used here do not
  establish whether this application's tasks are visitor-triggered or replaced. Confirm the
  application schedule with VIP before changing it.
- **Object cache:** A platform object-cache policy and customer purge path were not confirmed for
  this application. Keep the layer `unknown` and coordinate any change with VIP.
- **Files and restrictions:** All web containers are read-only. There is no SFTP path for code;
  plugins and themes change only through deployment. Uploads map to the external VIP File System,
  whose directory and write semantics differ from a normal filesystem. Runtime writes to deployed
  code are **PROHIBITED**. [WordPress on VIP](https://docs.wpvip.com/wordpress-on-vip/)

### `shared-cpanel`

- **Identify:** `fingerprint.py` can report `shared-cpanel` from `x-cpanel-*`, but this identifies
  a control-panel family, not the provider, reseller, plan, server cache, or acceptable-use policy.
- **Page cache and policy list:** **UNCONFIRMABLE → PROHIBITED.** Identify the legal hosting
  provider and reseller, then obtain permission for the exact page-cache plugin. cPanel access is
  not permission and does not prove that LiteSpeed, Nginx, Varnish, or a hidden host cache is absent.
- **Staging and deploy:** Treat staging as unavailable until a specific staging system and promotion
  path are exercised. Determine whether File Manager, FTP/SFTP, Git, a reseller tool, or an external
  deployment is authoritative. Direct edits are prohibited until overwrite behavior is known.
- **WP-CLI:** Treat WP-CLI as unavailable until it is exercised against the correct document root
  and the provider confirms commands are permitted. Shell access alone does not authorize it.
- **Cron:** Inspect cPanel Cron Jobs and `DISABLE_WP_CRON`. Until both are confirmed, treat WordPress
  cron as visitor-triggered and **PROHIBIT** disabling it or adding a duplicate schedule.
- **Object cache:** Keep `object` as `unknown` until the provider/control plane and the WordPress
  drop-in identify the backend. Do not install Redis/Memcached clients merely because the server
  name appears in marketing material.
- **Files and restrictions:** Confirm quotas, inode limits, writable paths, backup exclusions,
  malware/security scanners, and whether provider automation restores files. Ask the host before
  generated-cache, backup, or preload work that can consume shared resources.

### `self-managed`

- **Identify:** `fingerprint.py` cannot prove `self-managed` from public vendor headers; this class
  requires operator evidence that they control the origin, operating system, web server, deploy
  pipeline, and hosting policy. A rented VPS managed by another party may be `other`, not
  `self-managed`.
- **Page cache and policy list:** **PERMITTED ONLY after authority and topology are proven.** The
  operator owns the allow/deny policy, but a second full-page cache is still prohibited until every
  `edge`, `server`, `page-plugin`, and `object` owner and purge path is inventoried.
- **Staging and deploy:** A working staging environment and an explicit production promotion path
  are required for staging-first changes. Record whether production comes from Git/CI, rsync/SFTP,
  image deployment, configuration management, or direct files. “We own the server” is not a deploy
  procedure.
- **WP-CLI:** Exercise WP-CLI against the intended root and user. It is a supported mutation path
  only if the operator's runbook says so and the snapshot/rollback covers its effect.
- **Cron:** Inspect both `DISABLE_WP_CRON` and every system/container/orchestrator scheduler. Choose
  one owner for due events; never disable visitor-triggered cron before the replacement is proven.
- **Object cache:** Identify the backend, endpoint, namespace, persistence, eviction policy, health
  check, and exact purge. A loaded `object-cache.php` alone does not prove a healthy backend.
- **Files and restrictions:** Identify persistent volumes and immutable/redeployed paths. Container
  or image files can disappear on restart or redeploy even when a write initially succeeds. No
  change proceeds without a verified snapshot outside the replacement scope.

### `other`

- **Identify:** `other` means a provider or hosting pattern is known but is not represented by a
  more specific closed identifier. Record the provider, product, and evidence without inventing a
  new identifier in the plan.
- **Page cache and policy list:** **UNCONFIRMABLE → PROHIBITED.** Ask the provider whether it has a
  disallowed-plugin list and whether the exact page-cache plugin and feature are permitted. Save the
  first-party documentation or support response.
- **Staging and deploy:** Treat staging as unavailable. Do not write until the provider confirms a
  production source of truth, promotion method, and overwrite boundary.
- **WP-CLI:** Treat WP-CLI as unavailable and unsupported for mutation until the provider confirms
  it and it is exercised against the intended environment.
- **Cron:** Treat cron ownership as unknown. Do not change `DISABLE_WP_CRON` or add a platform
  schedule until the provider confirms whether visitor-triggered or server-scheduled execution is
  authoritative.
- **Object cache:** Keep the `object` layer `unknown`. Do not configure or purge an object cache
  until the provider confirms its backend and supported purge path.
- **Files and restrictions:** Treat deployed-tree writes as non-persistent or overwrite-prone. Do
  not write until the provider confirms persistent paths, restrictions, source of truth, and
  deployment overwrite behavior.

### `unknown`

- **Identify:** `unknown` is the correct result when no vendor-specific public marker survives.
  This is common behind CDNs and proxies. Do not convert CDN identity, nameservers, an IP owner, a
  dashboard screenshot, or a WordPress plugin into a host guess.
- **Page cache and policy list:** **UNCONFIRMABLE → PROHIBITED.** Do not install, activate,
  configure, deactivate, or remove a page-cache plugin. The provider and its disallowed list are
  unknown.
- **Staging and deploy:** Apply the most restrictive lane: staging is unavailable and there is no
  authorized production deployment until the provider and source of truth are identified.
- **WP-CLI:** Treat WP-CLI as unavailable and unsupported for mutation. Its local presence would
  not prove access to the unknown production environment.
- **Cron:** Cron ownership is unknown. Do not disable visitor-triggered WordPress cron or add a
  replacement schedule.
- **Object cache:** Keep the `object` layer `unknown`; do not install, configure, flush, or remove
  an object cache.
- **Files and restrictions:** Treat every deployed-tree write as non-persistent or overwrite-prone
  and therefore **PROHIBITED**. Identify the provider from the operator's contract, invoice,
  control plane, DNS/origin records, or a support response; then regenerate the stack profile and
  apply the matching row.

## Host permission is not site suitability

A host may permit a plugin and the change may still be wrong for the site. In particular, adding a
second owner of anonymous HTML can create stale copies, inconsistent cache keys, unsafe
personalization, and independent purge paths. Before proposing any page-cache change, read
[Cache layers conflict or purge independently](../../wp-perf-audit/references/catalog/caching/cache-layer-conflicts.md)
and inventory all four closed layer identifiers: `edge`, `server`, `page-plugin`, and `object`.

Permission answers only “will the platform allow this?” It does not answer “will this improve the
site?” A permitted page cache remains prohibited for the change plan when an existing cache owner,
unknown purge path, personalized response, or unverified rollback makes the change unsafe.

## The restrictive default for `unknown` and `other`

For both `unknown` and `other`, the default is the **most restrictive lane**:

- page-cache changes are `prohibited`;
- staging is treated as unavailable;
- WP-CLI is treated as unavailable and unsupported for mutation;
- cron ownership remains unknown and must not be changed;
- object-cache provision and purge remain unknown;
- deployed-tree writes are treated as non-persistent or overwrite-prone;
- no production write is proposed until the provider, product, authoritative deploy path,
  writable scope, disallowed-plugin policy, snapshot location, and purge controls are confirmed.

“Confirm with the host” is a complete outcome. If confirmation cannot be obtained, refuse the
change; do not downgrade the gate.
