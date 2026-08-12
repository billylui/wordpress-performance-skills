# SPDX-License-Identifier: GPL-2.0-or-later
#!/bin/sh
set -eu

# Ninety two-second attempts allow three minutes for first-run image copying
# and database initialization on slow CI hosts without waiting indefinitely.
MAX_READY_ATTEMPTS=90
READY_RETRY_SECONDS=2
# The exact byte count is intentionally stable so evaluators have ground truth.
AUTOLOAD_PAYLOAD_BYTES=327680
export AUTOLOAD_PAYLOAD_BYTES

WP_PATH=/var/www/html
MU_PLUGIN_DIR="${WP_PATH}/wp-content/mu-plugins"
MU_PLUGIN_PATH="${MU_PLUGIN_DIR}/wp-perf-seed.php"

mkdir -p "${MU_PLUGIN_DIR}"

cat > "${MU_PLUGIN_PATH}" <<'PHP'
<?php
// SPDX-License-Identifier: GPL-2.0-or-later
/**
 * Plugin Name: WP performance evaluation defects
 * Description: Deterministic, intentionally bad public markup for local evaluations only.
 */

if (!defined('ABSPATH')) {
    exit;
}

// 384 KiB is large enough for preload competition to be observable while
// remaining small enough for fast, repeatable local evaluation runs.
const WP_PERF_FIXTURE_FONT_BYTES = 393216;
// Asset padding makes head resources visible to transfer-size audits without
// making the local fixture needlessly slow.
const WP_PERF_FIXTURE_CSS_BYTES = 49152;
const WP_PERF_FIXTURE_SCRIPT_BYTES = 49152;
// These source dimensions are deliberately much larger than the rendered slot.
const WP_PERF_FIXTURE_IMAGE_WIDTH = 2400;
const WP_PERF_FIXTURE_IMAGE_HEIGHT = 1600;
// The delay isolates the visibility-gating defect from network transfer time.
const WP_PERF_FIXTURE_REVEAL_DELAY_MS = 1800;
// Asset requests must preempt the page renderer; the page renderer runs after
// ordinary template_redirect callbacks have had a chance to establish context.
const WP_PERF_FIXTURE_ASSET_PRIORITY = 0;
const WP_PERF_FIXTURE_PAGE_PRIORITY = 100;
const WP_PERF_FIXTURE_FONT_SIGNATURE = 'wOF2';

function wp_perf_fixture_padded_text($text, $minimum_bytes) {
    $remaining = max(0, $minimum_bytes - strlen($text));
    return $text . str_repeat(' ', $remaining);
}

function wp_perf_fixture_send_asset() {
    if (!isset($_GET['wp_perf_asset'])) {
        return;
    }

    $asset = sanitize_text_field(wp_unslash($_GET['wp_perf_asset']));
    nocache_headers();

    if ($asset === 'unused-preload.woff2') {
        header('Content-Type: font/woff2');
        header('Content-Length: ' . WP_PERF_FIXTURE_FONT_BYTES);
        echo WP_PERF_FIXTURE_FONT_SIGNATURE;
        echo str_repeat(
            "\0",
            WP_PERF_FIXTURE_FONT_BYTES - strlen(WP_PERF_FIXTURE_FONT_SIGNATURE)
        );
        exit;
    }

    if ($asset === 'oversized-hero.svg') {
        $width = WP_PERF_FIXTURE_IMAGE_WIDTH;
        $height = WP_PERF_FIXTURE_IMAGE_HEIGHT;
        $svg = '<svg xmlns="http://www.w3.org/2000/svg" width="' . $width . '" height="' . $height . '" viewBox="0 0 ' . $width . ' ' . $height . '">' .
            '<rect width="2400" height="1600" fill="#17324d"/>' .
            '<circle cx="1850" cy="520" r="390" fill="#f2a65a"/>' .
            '<path d="M0 1280L650 620l480 510 410-360 860 830H0z" fill="#5f9e83"/>' .
            '</svg>';
        header('Content-Type: image/svg+xml; charset=UTF-8');
        header('Content-Length: ' . strlen($svg));
        echo $svg;
        exit;
    }

    if ($asset === 'blocking.css') {
        $css = <<<'CSS'
html { background: #f7f3ea; color: #17202a; font-family: Georgia, serif; }
body { margin: 0; }
.fixture-shell { margin: 0 auto; max-width: 960px; padding: 24px; }
.fixture-hero { align-items: center; display: grid; gap: 24px; grid-template-columns: 1fr 360px; min-height: 520px; opacity: 0; transition: opacity 240ms ease; }
.fixture-hero.is-visible { opacity: 1; }
.fixture-hero h1 { font-size: 72px; letter-spacing: -2px; line-height: 0.95; margin: 0; }
.fixture-hero img { display: block; height: auto; max-width: 360px; width: 100%; }
.fixture-note { border-top: 1px solid #8c8172; padding-top: 16px; }
CSS;
        $css = wp_perf_fixture_padded_text($css, WP_PERF_FIXTURE_CSS_BYTES);
        header('Content-Type: text/css; charset=UTF-8');
        header('Content-Length: ' . strlen($css));
        echo $css;
        exit;
    }

    if ($asset === 'blocking.js') {
        $delay = WP_PERF_FIXTURE_REVEAL_DELAY_MS;
        $script = "'use strict';\n" .
            "document.addEventListener('DOMContentLoaded', function () {\n" .
            "  window.setTimeout(function () {\n" .
            "    var hero = document.querySelector('.fixture-hero');\n" .
            "    if (hero) { hero.classList.add('is-visible'); }\n" .
            "  }, " . $delay . ");\n" .
            "});\n";
        $script = wp_perf_fixture_padded_text($script, WP_PERF_FIXTURE_SCRIPT_BYTES);
        header('Content-Type: application/javascript; charset=UTF-8');
        header('Content-Length: ' . strlen($script));
        echo $script;
        exit;
    }
}
add_action(
    'template_redirect',
    'wp_perf_fixture_send_asset',
    WP_PERF_FIXTURE_ASSET_PRIORITY
);

function wp_perf_fixture_render_page() {
    if (is_admin() || wp_doing_ajax() || (defined('REST_REQUEST') && REST_REQUEST)) {
        return;
    }

    $font_url = esc_url(home_url('/?wp_perf_asset=unused-preload.woff2'));
    $css_url = esc_url(home_url('/?wp_perf_asset=blocking.css'));
    $script_url = esc_url(home_url('/?wp_perf_asset=blocking.js'));
    $image_url = esc_url(home_url('/?wp_perf_asset=oversized-hero.svg'));
    status_header(200);
    header('Content-Type: text/html; charset=UTF-8');
    nocache_headers();
    ?>
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>WP performance evaluation fixture</title>
  <link rel="preload" href="<?php echo $font_url; ?>" as="font" type="font/woff2" crossorigin>
  <link rel="stylesheet" href="<?php echo $css_url; ?>">
  <script src="<?php echo $script_url; ?>"></script>
</head>
<body>
  <main class="fixture-shell">
    <section class="fixture-hero" aria-label="Seeded LCP region">
      <div>
        <h1>Performance should feel immediate.</h1>
        <p>This entire likely LCP region begins invisible and waits for JavaScript.</p>
      </div>
      <img src="<?php echo $image_url; ?>" width="2400" height="1600" loading="lazy" alt="Abstract mountain landscape">
    </section>
    <p class="fixture-note">This local page deliberately contains known performance defects.</p>
  </main>
</body>
</html>
    <?php
    exit;
}
add_action(
    'template_redirect',
    'wp_perf_fixture_render_page',
    WP_PERF_FIXTURE_PAGE_PRIORITY
);
PHP

attempt=1
while [ "${attempt}" -le "${MAX_READY_ATTEMPTS}" ]; do
    if [ -f "${WP_PATH}/wp-config.php" ] && wp db check --path="${WP_PATH}" --allow-root >/dev/null 2>&1; then
        break
    fi
    if [ "${attempt}" -eq "${MAX_READY_ATTEMPTS}" ]; then
        echo "error: WordPress files or database were not ready after ${MAX_READY_ATTEMPTS} attempts" >&2
        exit 4
    fi
    sleep "${READY_RETRY_SECONDS}"
    attempt=$((attempt + 1))
done

if ! wp core is-installed --path="${WP_PATH}" --allow-root >/dev/null 2>&1; then
    wp core install \
        --path="${WP_PATH}" \
        --url="http://localhost:${WP_PORT}" \
        --title="WP performance evaluation fixture" \
        --admin_user="fixture-admin" \
        --admin_password="${FIXTURE_ADMIN_PASSWORD}" \
        --admin_email="fixture@localhost" \
        --skip-email \
        --allow-root
fi

wp eval \
    --path="${WP_PATH}" \
    --allow-root \
    '$option_name = "wp_perf_fixture_autoload"; $payload_bytes = (int) getenv("AUTOLOAD_PAYLOAD_BYTES"); update_option($option_name, str_repeat("x", $payload_bytes), true); global $wpdb; $wpdb->update($wpdb->options, array("autoload" => "yes"), array("option_name" => $option_name), array("%s"), array("%s"));'

echo "Seed complete: http://localhost:${WP_PORT} (autoload payload ${AUTOLOAD_PAYLOAD_BYTES} bytes)"
