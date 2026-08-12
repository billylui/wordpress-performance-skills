<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Rollback before change

A change is reversible only after its original state has been captured, verified, and paired
with a restoration procedure before production is written.

## Contents

- [Standing rules](#standing-rules)
- [The snapshot envelope](#the-snapshot-envelope)
- [File-based targets](#file-based-targets)
  - [`theme-file`](#theme-file)
  - [`plugin-file`](#plugin-file)
  - [`mu-plugin`](#mu-plugin)
- [Database-backed targets](#database-backed-targets)
  - [`wp-option`](#wp-option)
  - [`plugin-setting`](#plugin-setting)
  - [`builder-content`](#builder-content)
- [Asset and infrastructure targets](#asset-and-infrastructure-targets)
  - [`media`](#media)
  - [`server-config`](#server-config)
  - [`dns-or-cdn-setting`](#dns-or-cdn-setting)
- [Purging after restoration](#purging-after-restoration)
- [What this skill cannot roll back](#what-this-skill-cannot-roll-back)
- [Incident order](#incident-order)

## Standing rules

1. Capture the snapshot before applying the change. Verify that the artifact exists and is
   non-empty before applying the change. A snapshot that was never written is how a small mistake
   becomes an incident.
2. Store every snapshot outside the web root and, for deployed files, outside the deployed tree.
   It must never be publicly reachable or replaced by a deployment of the tree it protects.
3. Record the exact rollback command or control-plane action in the change plan at planning time,
   not afterwards. Resolve every placeholder: source, destination, database/site identifier,
   authorized interface, and purge order.
4. Verify completeness, not merely a zero exit status. Compare row counts, byte lengths,
   cryptographic digests, file inventories, identifiers, modes, or control-plane read-back as the
   target requires.
5. If the snapshot cannot be verified, stop. Approval does not compensate for missing rollback.
6. A restore is not complete until the visitor path serves the restored state. Use
   [live verification](./verify-live.md) after the required purge and warm-up.
7. Serialize writes to the target. Immediately before apply, prove the authoritative state still
   matches the snapshot; after apply, record the changed state's digest or row manifest. Before
   rollback, verify the target still matches that recorded changed state. An unexpected mismatch
   means another write occurred: do not silently overwrite it; escalate to the incident owner.

The artifact file itself must be non-empty. A legitimate captured value may be zero bytes—for
example an empty option—but its non-empty snapshot envelope must still prove the row existed and
record its zero byte length and digest. Absence and an intentionally empty value are different
states and must never be conflated.

## The snapshot envelope

Every change-plan snapshot should resolve to an operator-readable manifest plus its payloads. The
manifest records:

- change ID, site, environment, `target.kind`, and exact target identifier;
- capture interface and the authoritative source read;
- capture time, payload paths, byte lengths, and cryptographic digests;
- database table, site/blog scope, row keys, row count, and ordering where applicable;
- original file paths, ownership, permissions, symlink targets, and an inventory of related files
  where applicable;
- the pre-change cache layers found in the stack profile;
- the exact restoration command or authorized UI/API sequence; and
- the inner-to-outer purge sequence that follows restoration.

After capture, open or parse the artifact independently of the capture command. Confirm every
manifest payload exists outside the web root, is readable by the recovery operator, has the
recorded size, and matches its recorded digest. The manifest or archive container must be
non-empty; an individual value payload may be zero bytes only when the manifest explicitly
records that length and digest. For a multi-file or multi-row snapshot, verify the inventory
count and every member, not only the archive container.

Do not assume a database export is complete because it can be opened. Confirm the expected site,
table prefix, table names, keys, row counts, raw byte lengths, and digests against a second
read-only query or export. Do not place secrets in the change plan; the artifact location may be
recorded there while access remains appropriately restricted.

## File-based targets

For every file-based target, copy the original file outside the deployed tree and web root. Keep
the original bytes unchanged. Record a checksum for both the deployed source and snapshot copy,
then verify that the two digests, byte lengths, ownership, permissions, and resolved paths match
the manifest. If the deployed path is a symlink, capture the link and its resolved target; do not
silently turn it into a regular file during rollback.

This autonomous procedure changes existing files only. Creating a new file would require deleting
it to restore the prior absence, and autonomous file deletion is not a rollback this skill may
perform. Classify that plan `prohibited` and hand it to a human-controlled procedure.

Restore file bytes through an atomic replacement supported by the deployment environment, then
restore the recorded owner, mode, and symlink shape. Read the deployed file back and prove its
digest equals the pre-change digest before purging. When PHP bytecode caching is active, use only
the host-documented invalidation or process-reload path and verify the restored code executes;
when that path is `unknown`, stop and confirm it with the host. This runtime step precedes the
WordPress cache-layer purge. A source-control reference alone is not a snapshot: generated,
ignored, or locally modified production files may differ from that revision.

### `theme-file`

**Capture:** Copy the exact active theme or child-theme file. Also record whether a parent or
child theme resolves the path, because restoring the same relative name in the wrong theme does
not restore behavior. Capture every existing file the planned edit will replace. A rename or new
path is outside the autonomous procedure because exact rollback would require a deletion.

**Verify:** Resolve the active file path from the production deployment, compare source and
snapshot digest and length, and confirm the snapshot is outside the deployed tree. Record owner,
mode, and symlink information. The recovery interface must work without `wp-admin`, because a PHP
fatal can make `wp-admin` unavailable.

**Restore:** Use that out-of-band interface to atomically replace the deployed path with the
captured bytes; restore owner, mode, and symlink shape; then read back the deployed digest. Purge
affected `object` data only when the theme change altered cached data, followed by every detected
HTML layer that can hold the output: `page-plugin`, then `server`, then `edge`. Warm and verify the
restored visitor response.

### `plugin-file`

**Capture:** Copy the exact deployed plugin file and record the plugin directory, active scope,
and whether the file is shared across a multisite network. Capture every file the single planned
change touches; do not substitute a separately downloaded plugin package for production bytes.

**Verify:** Compare each deployed source with its snapshot by digest and length; verify the full
file inventory, permissions, owner, and recovery path outside WordPress. Confirm that restoration
does not depend on loading the edited plugin.

**Restore:** Atomically replace only the changed files, restore metadata, and read back every
digest. Do not activate, deactivate, install, remove, or update the plugin as part of rollback.
Purge affected `object` entries first when applicable, then `page-plugin`, `server`, and `edge`
layers that cache the plugin's visitor-facing output. Warm and verify the affected paths.

### `mu-plugin`

**Capture:** Copy the exact must-use file plus each included file the planned change touches.
Record the loader path and include relationships, because the administration plugin screen is not
a reliable recovery surface for automatically loaded code.

**Verify:** Digest and inventory every captured source and snapshot, record file metadata, and
exercise the out-of-band restoration path. Prove the artifact can be read without bootstrapping
WordPress.

**Restore:** Atomically restore the included files before the loader when their order matters,
then restore the loader; reinstate metadata and verify deployed digests. Purge affected `object`
entries when applicable, then detected `page-plugin`, `server`, and `edge` HTML caches from inner
to outer. Warm and verify public and administration recovery paths.

## Database-backed targets

Database snapshots must preserve raw stored values. Exporting a visually equivalent decoded value
is not sufficient: serialization, encoding, duplicate rows, ordering, numeric types, and byte
lengths may be behaviorally significant. Use the database's binary-safe raw export/read path and
identify the exact site and tables before capture. Restoration must be a targeted transaction,
not a whole-database restore.

Immediately before the write, compare the authoritative row manifest with the snapshot and abort
if another writer changed it. Record the post-write row manifest. Before rollback, compare again;
an unexpected row or digest is a concurrent change and must not be overwritten silently. A plan
that creates or deletes rows is `prohibited` for autonomous execution because exact rollback would
require destructive database work; the procedures below update rows proven to exist.

### `wp-option`

**Capture:** Export the exact option row from the correct site options table, including the option
name, raw stored value, autoload field, and stable row identifier when present. Capture serialized
values verbatim. Do not read them through an API that unserializes and later re-serializes them: a
round-trip can alter string lengths, types, object payloads, or encoding even when the displayed
value looks equivalent.

**Verify:** Confirm the table prefix and site/blog scope, exactly one intended row or the expected
row, raw byte length, and digest with a second binary-safe read. Parse and verify the non-empty
snapshot envelope, verify its value payload exists with the recorded length and digest, and
compare its row count and raw-value digest to the source read. The value payload may be zero bytes
when the envelope records that fact; an absent row is a `prohibited` create/delete plan, not this
autonomous procedure.

**Restore:** In one targeted transaction, replace the row's stored value and autoload field with
the captured raw bytes without creating or deleting any row. Read the authoritative row back as
raw bytes and compare its digest and length before ending rollback.
Invalidate the affected option in `object` cache, then purge each detected `page-plugin`, `server`,
and `edge` layer that can hold rendered output derived from it. Warm and verify the affected URLs.

### `plugin-setting`

**Capture:** First prove where the plugin stores the setting. Many settings use one or more option
rows; others use site options, post meta, or custom tables. If storage remains `unknown`, do not
change it. Export every affected row with its table, site scope, primary key, ordering, raw values,
and surrounding fields required to distinguish absence from an empty value.

**Verify:** Compare a second read against the manifest row count, keys, raw byte lengths, and
digests. For custom tables, verify the table schema needed to interpret the captured rows, but do
not alter that schema. For option-backed settings, apply all `wp-option` raw-value checks. A plugin
UI screenshot is supporting evidence, not a restorable artifact.

**Restore:** Use a targeted transaction to replace exactly the captured rows and values without
decode/encode round-trips, then read them back through the authoritative storage path and compare
row count and digests. Invalidate affected plugin or option data in `object`, then purge detected
`page-plugin`, `server`, and `edge` layers holding derived output. Warm and verify both the setting
read-back and the visitor behavior.

### `builder-content`

**Capture:** Page builders commonly store content in serialized or JSON-ish post meta, sometimes
across several rows plus post fields. Capture the raw stored value byte-for-byte, not the builder's
decoded export alone. Include every affected post row and meta row, duplicate key, stable row ID,
row order, raw byte length, and value digest. Record the post/site identity and the exact set of
rows that existed before the change.

**Verify:** Perform a second raw database read and compare table scope, post ID, row count, row
identities, ordering, byte lengths, and every value digest. Parse any separate builder export only
as a secondary completeness check. A decode/encode round-trip is not verification: it can change
the payload while preserving its apparent meaning.

**Restore:** In one targeted transaction, restore the captured post fields and meta rows with
their raw bytes, identities, duplicates, and ordering; do not decode and re-encode the payload.
Read all restored rows back raw and prove the complete ordered manifest and digests match the
snapshot exactly. Invalidate relevant post/meta data in `object`, then purge `page-plugin`,
`server`, and `edge` layers that cache the affected page or shared template. Warm and verify every
URL that consumes the restored content.

## Asset and infrastructure targets

### `media`

**Capture:** Copy the original uploaded file, every existing generated derivative that the
operation can overwrite, and the attachment's database state. The database snapshot includes the
attachment post fields and raw attachment metadata, backup-size metadata, file path metadata, alt
text, and any operation-specific rows. Replacing a file and regenerating sizes is not
automatically reversible; the original alone cannot reconstruct old crops, encodings, names, or
metadata.

**Verify:** Inventory the original and derivatives by relative path, byte length, digest, owner,
and mode, and compare every snapshot copy with its source. Verify the attachment/site ID, database
row count, raw-value digests, and the exact pre-change path set. Confirm the artifact is outside
the web root and that the restore account can write the original locations. Prove beforehand that
the operation overwrites only this path set; if it can create a new derivative path, classify it
`prohibited` because exact rollback would require autonomous deletion.

**Restore:** Atomically restore the original and every overwritten derivative, including file
metadata, then restore the attachment post and raw metadata rows in a targeted transaction. Read
back file digests and raw database values. Point restored metadata only at the pre-change path
set and verify that no other path was created. Invalidate attachment metadata in `object`; purge
affected HTML from `page-plugin` and `server` when markup changed, then purge media or HTML objects
from `edge`. Warm and verify the attachment URL and every representative page that embeds it.

### `server-config`

**Capture:** Copy each exact configuration file and included snippet the change touches, outside
the deployed tree and web root. Record include order, active symlink targets, owner, mode, virtual
host/site identity, and the authoritative control-plane export when configuration is generated.
If the active include chain or the host-approved interface is `unknown`, do not change it.

**Verify:** Compare every source and snapshot digest and length, validate the complete inventory,
and read the control plane back to prove the captured site and active revision are correct. When
the server provides an official configuration-test mechanism, test the restoration artifact in a
non-active context. A text copy of one visible file is incomplete when another include or provider
template owns the effective configuration.

**Restore:** Through the host-documented interface, restore generated control-plane state first or
atomically replace the exact files and symlinks; run the official configuration test before the
documented reload. If that test fails, do not reload—escalate with the captured artifact. After a
successful reload, read back the active state and digests. Purge the detected `server` cache, then
`edge`; also purge `page-plugin` when the restored routing or response rules changed its cached
representation. Warm and verify public, administration, static asset, redirect, and error paths
affected by the configuration.

### `dns-or-cdn-setting`

This `target.kind` is `prohibited` for autonomous production changes. The following defines the
minimum rollback evidence for a separately authorized human/provider procedure; it does not grant
permission to perform one.

**Capture:** Export the authoritative zone or CDN configuration and record every affected record,
TTL, proxy state, origin, hostname, TLS mode, cache rule, redirect, security rule, worker/function,
ordering, and provider-specific identifier. Capture screenshots only as supporting evidence; use
a machine-readable control-plane export or complete read-back as the restorable source. Confirm
the provider's own current documentation and exact restore interface. If policy or coverage is
`unknown`, stop.

**Verify:** Parse the export, match account and zone/site identifiers, enumerate every affected
object, and compare it with a second authoritative control-plane read. Verify non-empty artifact
size, object count, field values, rule order, and digests. Prove the authorized operator can reach
the restoration interface without relying on the hostname being changed.

**Restore:** The authorized human or provider restores the exact prior objects and ordering, then
reads them back from the authoritative control plane. DNS recursive caches have no common purge
interface. The plan must name the resolver/network observations that represent affected visitors
and use the captured record TTL to set the observation window. Restoration passes only when the
authoritative answer and every named observation return the captured route after its TTL window,
and TLS plus the visitor response match the restored origin. For CDN changes, purge affected
`edge` objects after the old configuration is active; if a changed origin or rule allowed stale
inner output, also invalidate affected `object`, `page-plugin`, and `server` layers inner-to-outer
before the final `edge` purge. Warm and verify every visitor path named in the plan.

## Purging after restoration

Restoring origin state while leaving the changed representation in cache is not rollback from a
visitor's perspective. Use the site-specific, previously verified paths in the
[cache purge matrix](./cache-purge-matrix.md); there is no common purge command across hosts or
products, and some controls exist only in a dashboard.

Invalidate only affected data, from inner source toward outer delivery: `object`, then
`page-plugin`, then `server`, then `edge`. Include only layers actually detected and only when they
can hold the restored data or response. Record every purge result, request the normal visitor path
to warm it, and use [live verification](./verify-live.md) to compare the received body, headers,
asset bytes, or behavior with the restored artifact. A command exit or dashboard success message
does not prove visitors received the restore.

## What this skill cannot roll back

Do not autonomously attempt an effect that cannot be reversed after a visitor or external system
has consumed it. Purging a cache is reversible in the relevant sense because the representation
can be rebuilt; an email, notification, webhook, payment, order transition, credential disclosure,
or externally submitted message cannot be recalled by restoring a file or row.

Do not autonomously perform any destructive database operation, including dropping or truncating
tables, changing schema, bulk deletion, or a transformation that discards the prior value. A
targeted raw snapshot does not make an unbounded destructive operation safe. Content or media
deletion and full backup restores are also outside this skill's autonomous boundary.

When the proposed change has an irreversible side effect or needs destructive database recovery,
classify it `prohibited`, leave it undone, and hand the evidence and proposed operator runbook to
the accountable human.

## Incident order

When anything looks like an incident—fatal errors, 5xx responses, missing content, broken login,
checkout failure, misrouting, or an unexpected visitor response—roll back first and diagnose
second. Restore service with the already recorded procedure, purge the layers that can retain the
bad state, warm them, and confirm the restored state with
[live verification](./verify-live.md). Investigate cause only after service is restored.
