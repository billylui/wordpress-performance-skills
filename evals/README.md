# SPDX-License-Identifier: GPL-2.0-or-later

# Evaluation harness

This harness measures whether a WordPress performance skill improves on a no-skill control. It
does not invoke an agent CLI, make network requests, or assume a vendor. A human or CI driver can
use any agent, then return the transcript for deterministic grading and review routing.

## Scenario seam

Every `scenarios/*.json` document has exactly these fields:

```json
{
  "id": "lcp-gated-element",
  "skills": ["wp-perf-audit"],
  "query": "Audit the likely LCP behavior at http://localhost:8081.",
  "files": [],
  "fixture": "plain-markup-seeded-defects",
  "expected_behavior": ["Identifies the JavaScript visibility gate"],
  "must_not": ["Attributes plain markup to a commercial builder"]
}
```

The runner validates every scenario file on every invocation, including filename/ID agreement,
required fields, types, and duplicate IDs. One malformed document fails the whole run with exit
code 2 and an actionable location; partial scenario loading would make comparisons misleading.

Run the seam as follows:

1. Emit the exact prompt, declared skill list, fixture, and grading rubric:

   ```sh
   python3 evals/run_evals.py --scenario lcp-gated-element --json /tmp/eval-packet.json
   ```

2. Give only `results[0].prompt` and the listed skills to the chosen agent. Keep the rubric out
   of the agent context. For a control run, use `--baseline`; its emitted `skills` array is empty.

3. Save the agent's complete response, then grade and record it:

   ```sh
   python3 evals/run_evals.py \
     --scenario lcp-gated-element \
     --transcript /tmp/agent-response.txt \
     --json /tmp/lcp-skilled.json

   python3 evals/run_evals.py \
     --baseline \
     --scenario lcp-gated-element \
     --transcript /tmp/baseline-response.txt \
     --json /tmp/lcp-baseline.json
   ```

   Use `--transcript -` to read standard input. A transcript is accepted only with
   `--scenario ID`, preventing one response from being applied to multiple prompts.

The JSON report records the prompt, effective skills, full rubric, transcript, transcript source,
SHA-256 digest, item results, and aggregate status. Keys, scenarios, checks, and human summary
ordering are deterministic. No timestamp is added, so identical inputs produce identical reports.
With `--json -`, JSON goes to stdout and the human summary goes to stderr; `--quiet` suppresses
the summary and requires `--json`.

## Grading rules

Rubric strings have two optional machine-gradeable forms:

- `contains: TEXT` in `expected_behavior` passes only when `TEXT` occurs as a
  case-insensitive substring. Absence is a named failure.
- `not_contains: TEXT` in `must_not` passes only when `TEXT` is absent as a
  case-insensitive substring. Presence is a named failure.

All unprefixed criteria require semantic judgement. The runner emits each criterion with
`status: "needs_review"` and the `human_or_judge_model` matcher. It never infers semantic
equivalence from keywords, and an ungradeable item never counts as a pass. Scenario aggregation
is conservative: any `fail` makes the scenario fail; otherwise any `needs_review` makes it
`needs_review`; only all-pass machine-gradeable criteria produce `pass`.

For human or judge-model review, supply the transcript and the emitted rubric, require a decision
for every `needs_review` item, and preserve those decisions alongside the runner report in the CI
system. The runner deliberately does not hardcode a judge vendor or silently rewrite review
results.

## Commands

```sh
python3 evals/run_evals.py --list
python3 evals/run_evals.py --scenario tier-degradation-public
python3 evals/run_evals.py --baseline --scenario tier-degradation-public
python3 evals/run_evals.py --scenario tier-degradation-public --transcript - --json - --quiet
```

Exit code 0 means scenario loading and requested grading completed, including results that need
review. Exit code 2 means invalid CLI input, malformed scenario data, unreadable transcript, or an
unwritable report path. The harness itself performs no target access, so target-specific exit
codes 3 and 4 are not produced here.

See `fixtures/README.md` for setup and the exact seeded ground truth. Baseline and skilled runs
must use the same fixture state and prompt; the only intended variable is whether the skill is
loaded.
