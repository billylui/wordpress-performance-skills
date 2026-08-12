---
name: A stack was misidentified
about: The audit got your builder, host, cache layer or CDN wrong — the most useful report you can send
title: "Misidentified: "
labels: stack-coverage
---

<!--
This is the most valuable issue type for this project. WordPress runs on an enormous variety of
builders, hosts and caching arrangements, and no maintainer has seen them all. If the audit read
your setup wrong, that is a bug worth fixing.

Please do NOT include credentials, admin URLs, or anything you would not post publicly.
-->

## What it said

Paste the relevant part of the `fingerprint.py` output, or the audit's stack table:

```json

```

## What it actually is

| Layer | Actual |
|---|---|
| Builder / editor | |
| Theme | |
| Host | |
| Page cache | |
| CDN / edge | |
| Multilingual | |

## How you know

What tells you the real answer — the hosting dashboard, the installed plugin list, your own
configuration. This matters because the fix is usually "detect signal X", and we need to know
which signal is trustworthy.

## Site URL, if you can share one

A public URL that reproduces it makes this dramatically faster to fix. Leave blank if you would
rather not — a description of the stack is still useful.

## Anything else

For example: does the host strip identifying headers? Is there a reverse proxy in front? Is the
site behind authentication?
