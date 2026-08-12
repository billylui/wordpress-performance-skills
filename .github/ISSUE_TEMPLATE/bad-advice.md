---
name: Bad or unsafe advice
about: The skill recommended something wrong, harmful, or prohibited on your host
title: "Bad advice: "
labels: correctness
---

<!--
Treat this as high priority. This project recommends changes to production websites, so advice
that is wrong for a stack is worse than no advice at all.

If the problem is a security vulnerability rather than bad guidance, please use a security
advisory instead: https://github.com/billylui/wordpress-performance-skills/security/advisories/new
-->

## What it recommended

Quote the recommendation, and name the catalog entry it came from if you know it.

## Why that is wrong here

For example: your host prohibits it, it would break a documented behaviour, the mechanism does
not apply to your stack, or it is simply incorrect.

## Your stack

| Layer | Value |
|---|---|
| Builder / editor | |
| Host | |
| Page cache | |
| CDN / edge | |
| PHP version | |

## Did anything break?

If you applied it: what happened, and did the rollback in the catalog entry actually restore
things? A rollback that does not work is its own bug and we want to know.

## Source, if the advice is about a host policy

Host policies change and we try to cite first-party documentation for every one. If you have a
link to the host's own docs contradicting what the skill said, that settles it immediately.
