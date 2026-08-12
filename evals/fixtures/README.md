# SPDX-License-Identifier: GPL-2.0-or-later

# Seeded performance fixture

This fixture is deliberately defective. It reproduces defect classes with a generated
mu-plugin and plain markup; it does not install or imitate any commercial builder. Never use
this compose project for a public or persistent WordPress installation.

## Start the fixture

From `evals/fixtures/`:

```sh
docker compose up -d
docker compose logs seed
```

The default site is `http://localhost:8081`. `WP_PORT` changes the host port. The `seed`
service waits for WordPress and the database, installs a throwaway local site when necessary,
writes the mu-plugin, and exits after seeding the database option.

The default web image is `wordpress:6.7.1-php7.4-apache` and the default database is
`mariadb:10.11`. Images are fully parameterized:

```sh
WORDPRESS_IMAGE=wordpress:6.7.1-php7.4-apache \
WP_CLI_IMAGE=wordpress:cli-php7.4 \
DB_IMAGE=mysql:5.7 \
WP_PORT=8082 \
docker compose up -d
```

That is the supported PHP 7.4 + MySQL 5.7 compatibility path. A modern-runtime matrix entry can
substitute matching WordPress and WP-CLI images without changing the fixture. Database state and
WordPress files live in named volumes. To get a fresh fixture, remove this compose project's
volumes explicitly before starting it again.

## Ground truth

All public assets are same-origin query endpoints emitted by
`wp-content/mu-plugins/wp-perf-seed.php`. The exact defects are:

1. **JavaScript-gated likely LCP region.** `.fixture-hero` contains the large heading and hero
   image, starts at `opacity: 0`, and becomes visible only when `blocking.js` adds
   `.is-visible` 1,800 ms after `DOMContentLoaded`. A correct audit identifies the visibility
   gate and explains that LCP presentation is delayed even when bytes arrive quickly. It must
   not attribute the behavior to Elementor, Divi, or another builder; the fixture uses plain
   markup.

2. **Unused font preload.** The head preloads `unused-preload.woff2` as a cross-origin-mode
   WOFF2 response of exactly 393,216 bytes. There is no `@font-face`, CSS font-family reference,
   or rendered text using it. A correct audit reports an unused preload competing for bandwidth;
   it must not claim the font is used.

3. **Unresponsive, low-priority above-fold image.** `oversized-hero.svg` has intrinsic
   dimensions 2,400 by 1,600 but CSS limits it to approximately 360 by 240. The `<img>` has no
   `srcset` and no `sizes`, and it has `loading="lazy"` despite being above the fold and within
   the likely LCP region. A correct audit reports all three facts and recommends a right-sized
   responsive source plus eager/high-priority treatment if confirmed as the LCP image. The SVG
   keeps the fixture repository small; pixel dimensions, source selection, and loading semantics
   are the seeded defect, not compressed byte size.

4. **Bloated autoloaded option.** The seeder writes `wp_perf_fixture_autoload` with a value of
   exactly 327,680 bytes and forces its `wp_options.autoload` column to `yes`. This is backend
   ground truth and is not exposed in public markup. A correct tier-2/WP-CLI audit names the
   option, measures it read-only, and discusses request-bootstrap memory cost. At public tier 0,
   the correct result is `unknown at this tier`, not a guess.

5. **Render-blocking head resources.** The document head contains `blocking.css` as a normal
   stylesheet and `blocking.js` as a classic script with no `async`, `defer`, or `type="module"`.
   Each response is padded deterministically to 49,152 bytes. A correct audit identifies both
   resources as blocking from markup and distinguishes blocking semantics from transfer size.

## Direct checks

After the seed service reports success:

```sh
curl -fsS http://localhost:8081/
docker compose run --rm --entrypoint wp seed option get wp_perf_fixture_autoload --path=/var/www/html --allow-root
```

The second command is illustrative only: it prints a large value. For an exact, read-only byte
measurement, use a WP-CLI database query or `wp eval` with `strlen(get_option(...))`. Public-tier
scenarios must not run either backend command.
