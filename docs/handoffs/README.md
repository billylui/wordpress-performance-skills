<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Handoffs

Open work carried across sessions. One file per topic. Close an item by flipping its
`**Status:**` to `DONE` and pruning its row here in the same change that finishes it.

| Handoff | Status | Summary |
|---|---|---|
| [pre-launch-audit.md](pre-launch-audit.md) | MOSTLY DONE | What a claim audit found before going public. Every P1 is closed; one lower-severity item remains — campaign numbers with no artifact in the repository to check them against |
| [pre-publication.md](pre-publication.md) | OPEN | What is still unexercised now the repository is public — chiefly that `wp-perf-fix` has never applied a change to a production host — and what is deliberately deferred past v0.1 |
| [capability-gap-followups.md](capability-gap-followups.md) | DONE | Two capability-gap defects the ship review found, both closed: an undocumented `kind` field, and gaps naming a prerequisite that could not help. Kept as the worked example behind WP-ESC-18 |
| [no-target-gap-routing.md](no-target-gap-routing.md) | OPEN | A tier-0 gap (no `--target`) renders as "ask at step 4b", which comes after the measurement the URL is blocking. Wording only, and only on the bare invocation the documented flow never uses |
| [godaddy-product-granularity.md](godaddy-product-granularity.md) | OPEN | GoDaddy publishes a blocklist this project cannot safely act on, because the `godaddy` host class covers several products and cannot tell them apart. Two attempts at a stricter verdict were reverted; the research and citation are kept |
