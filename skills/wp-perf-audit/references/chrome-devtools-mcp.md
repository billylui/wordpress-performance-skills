<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Chrome DevTools MCP

Chrome DevTools MCP is Google's official MCP server for exposing Chrome DevTools capabilities to an
agent. It provides the browser-rendered measurement path that the command-line scripts in this
project intentionally do not implement.

## Contents

- [What the browser path adds](#what-the-browser-path-adds)
- [How it complements perf-probe.py](#how-it-complements-perf-probepy)
- [Check availability in the current session](#check-availability-in-the-current-session)
- [Run a browser measurement](#run-a-browser-measurement)
- [Repeat pages and viewports](#repeat-pages-and-viewports)
- [Fallbacks](#fallbacks)
- [Reporting rules](#reporting-rules)

## What the browser path adds

Chrome DevTools MCP can expose Lighthouse audits, performance traces, Core Web Vitals with
attribution, console output, and network inspection against a live page. Because Chrome parses,
lays out, paints, and executes the page, this path can measure effects that a static HTTP payload
walk cannot see.

Use it for:

- LCP and attribution to the specific largest element, its resource, and relevant load or render
  delay.
- CLS and attribution to the elements or insertions involved in layout shifts.
- INP only after performing and measuring a representative interaction path; a load-only audit does
  not establish INP.
- Render-blocking behavior, main-thread work, long tasks, request priority, and the timing of actual
  browser fetches.
- Console errors and warnings that explain broken resources or scripts.
- Network evidence that a resource was requested, served from cache, blocked, redirected, or never
  fetched during the tested rendering path.

These are lab observations unless a separate field-data source is explicitly queried and returns
eligible real-user data. Label them accordingly.

## How it complements perf-probe.py

`perf-probe.py --site URL [--repeats N] [--quick] [--json PATH]` measures public HTTP timing and a
referenced-resource payload walk. It does not run a rendering engine, execute JavaScript, identify
the LCP element, perform an interaction, or produce LCP, INP, or CLS.

The two paths answer different questions:

| Question | `perf-probe.py` | Chrome DevTools MCP |
|---|---|---|
| Is uncached WordPress render slow? | Origin TTFB with unique cache-busters | Trace context may corroborate, but this is not its primary separation |
| What does a visitor-facing cache path return? | Bare-URL edge TTFB and public cache header | Browser network timing for the rendered navigation |
| How many referenced bytes were measurable? | HTML/CSS discovery and measured payload buckets | Actual requests made by this browser path |
| Which element became the largest paint? | Not measured | LCP attribution to a specific element |
| Which elements shifted? | Not measured | CLS attribution in the trace/audit |
| How did a real interaction respond? | Not measured | Interaction trace and INP when the path supports it |

Use both when available. A referenced font may remain in the static CSS walk but not be requested by
the browser; an image can be small in bytes yet become late LCP because it was discovered or
prioritized poorly. Neither result invalidates the other.

## Check availability in the current session

MCP availability is a session capability, not merely a binary on `PATH`. Check it in this order:

1. Inspect the current agent session's available tool list or MCP server registry for Chrome
   DevTools capabilities.
2. If tools are listed, exercise a harmless operation against the target, such as opening or
   inspecting the public page. A successful tool call confirms the path is usable now.
3. If the current session exposes no Chrome DevTools tools after that check, report the MCP browser
   path as absent from **this session**. Do not claim it is uninstalled everywhere.
4. Run `capabilities.py [--target URL] [--json PATH]` to inventory local fallback evidence, but do
   not let that local process override the session tool registry.

`capabilities.py` checks deterministic local package locations and local MCP client configuration
files. Its `tools.chrome_devtools_mcp.present: true` means it found a package or configuration
reference; it does not prove that the server is connected, started, or callable in the current
agent session. Confirm availability by exercising an exposed MCP tool.

Conversely, `tools.chrome_devtools_mcp.present: false` does **not** confirm absence. The script adds
a note that Chrome DevTools MCP could not be confirmed locally and that a browser path may still be
available through the agent's own MCP tools. This is “not confirmable from here,” not “confirmed
absent.” Only the current session's tool inventory can establish that no MCP browser path is
available to that session.

This distinction belongs in the report:

- **Confirmed usable:** an MCP operation succeeded in the current session.
- **Configured locally, not exercised:** package/config evidence exists, but no successful session
  operation has confirmed it.
- **Not confirmable locally:** `capabilities.py` found no package/config evidence; session tools
  still require a separate check.
- **Confirmed absent from this session:** the current session exposes no applicable MCP tools after
  its capability registry was checked.

## Run a browser measurement

Before measuring, record:

- Exact page URL and whether authentication, consent state, or a route transition is involved.
- Viewport dimensions or named mobile/desktop profile.
- Network and CPU throttling profile, when the tool exposes them.
- Cache condition and whether the navigation is cold or warm.
- Interaction steps required for INP, including the exact control and expected completion state.
- Any console or network condition that invalidates the run.

For a load trace, navigate to the exact page and wait for the selected audit or trace completion
condition. Preserve the measured number and its attribution, not just a screenshot of the summary.
A useful LCP record names the element or selector, relevant resource URL when one exists, and timing
breakdown available from the tool. A useful CLS record names the affected nodes. A useful
interaction record says what was clicked, typed, or selected and how the interaction completed.

Run the public command-line probe separately when origin-versus-edge TTFB or referenced payload is
part of the diagnosis. Keep its cache state aligned with the scenario; see
[measurement](measurement.md).

## Repeat pages and viewports

Measure the same page more than once. Browser startup, scheduling, cache state, background work,
and network variation can move a single lab result. Preserve each run, use a central tendency only
across comparable valid runs, and keep an outlier visible rather than deleting it silently.

Measure more than one viewport. At minimum, test a representative mobile and desktop viewport when
both are in scope. Mobile and desktop can select different responsive images, menus, DOM branches,
font behavior, ad slots, or JavaScript work. Their results can diverge sharply: a page can pass on
desktop while failing badly on mobile.

Do not average mobile and desktop into one number. Report them as separate scenarios with their own
attribution. If a page is important in more than one template or state, test each representative
URL/state instead of assuming one homepage trace covers the site.

For INP, repeat the same representative interaction after returning the page to the same state.
Do not compare a menu-open interaction on mobile with an unrelated search interaction on desktop.

## Fallbacks

When Chrome DevTools MCP is unavailable, use these fallbacks in order:

### 1. Local Lighthouse CLI

Use a locally available Lighthouse CLI against the exact public URL. Preserve its lab environment,
viewport, audit output, and attribution. `capabilities.py` checks whether the `lighthouse` binary is
present locally and reports it under `tools.lighthouse_cli`.

Lighthouse can supply lab LCP and CLS. It cannot establish INP without a real interaction path, so
report INP as unmeasured unless another exercised browser workflow actually measures it.

### 2. PageSpeed Insights API

Use a PageSpeed Insights API call only with an operator-supplied key. Do not invent, retrieve, or
embed a credential. `capabilities.py` checks only whether a supported key environment-variable name
is present; it deliberately does not read the value or call the API.

Label returned lab and field sections separately. Field data may be absent when the page or origin
does not have enough eligible traffic. If a metric is absent from the response, it remains
unmeasured; do not infer it from a performance score.

### 3. Report Core Web Vitals as unmeasured

If neither an MCP browser path, a local Lighthouse CLI, nor an authorized PageSpeed Insights call
is available, state that Core Web Vitals could not be measured in this session. Continue the tier 0
HTTP, frontend, and cache-layer audit. Lack of a browser path narrows the measurement boundary; it
does not invalidate the measurements the session did perform.

## Reporting rules

The standing rule is absolute: never report a Core Web Vitals number the session did not actually
measure. Do not estimate LCP from image size, infer CLS from missing dimensions, derive INP from
JavaScript bytes, or copy a number from an unrelated run.

For every browser metric that is reported, include:

- Whether it is lab or field.
- Exact page or origin scope.
- Mobile/desktop viewport and important throttling conditions.
- Run count and treatment of variance.
- Cold or warm cache state.
- Attribution to the specific element, shift source, or interaction when the tool provides it.
- Errors or missing data that limit the conclusion.

When no browser path exists, write “Core Web Vitals were unmeasured in this session” and name the
unavailable path. Unmeasured is not zero, passing, failing, or estimated.
