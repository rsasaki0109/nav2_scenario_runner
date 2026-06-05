# Submission auto-review

Community benchmark submissions land on the [public leaderboard](https://rsasaki0109.github.io/nav2_scenario_runner/#benchmark)
automatically, so every submission pull request is validated by CI before merge.
The [`Validate submissions`](../.github/workflows/validate-submissions.yml)
workflow runs on any PR that adds or edits a file under
`examples/benchmark/submissions/`, and upserts a **single sticky comment** that
both reports problems and previews where the configuration would rank.

## What it checks

The `validate-submission` command (the same code the workflow runs) verifies:

- **Label** — the file stem is unique, lowercase, kebab-case (`acme-smac-tuned`).
- **Coverage** — the report covers the core scenarios (`straight_line`,
  `narrow_corridor`, `u_turn`) so the comparison is apples-to-apples.
- **Trajectories** — every `trajectory` point projects inside the
  [warehouse map](../examples/benchmark/maps/warehouse.yaml) bounds.
- **Metrics** — a warning (not a failure) when no numeric metrics are present,
  because the entry would score zero on every metric.

Anything in the first three groups is a hard error that fails the check; warnings
are surfaced but do not block merge.

## The review comment

When the submission is valid the comment includes a **leaderboard preview** built
with the live scoring, so a contributor sees their rank immediately:

```text
✅ All 1 submission(s) valid — ready to join the public leaderboard.

### ✅ acme-smac-tuned
Valid — 3 scenario(s) · 3 with trajectories.

### 🏁 Leaderboard preview (with your submission)
| Rank | Config | Score | Pass | Wins |
|:--:|:--|--:|:--:|--:|
| 🥇 | acme-smac-tuned ⬅️ your entry | 85.1 | 100% (3/3) | 9 |
| 🥈 | smac | 72.6 | 100% (3/3) | 10 |
```

When something is wrong it lists the exact problems and skips the preview:

```text
❌ 1 of 1 submission(s) need changes before merge.

### ❌ Bad_Label
**3 problem(s) must be fixed:**
- ❌ Label `Bad_Label` must be kebab-case (lowercase letters, digits, single hyphens).
- ❌ Missing core scenario(s): `narrow_corridor`, `u_turn`
- ❌ 1 trajectory point(s) fall outside the warehouse map bounds.
```

## Run it locally

```bash
nav2_scenario_runner validate-submission examples/benchmark/submissions/my-planner.json \
  --map examples/benchmark/maps/warehouse.yaml \
  --baseline navfn=examples/benchmark/navfn.json \
  --baseline smac=examples/benchmark/smac.json \
  --baseline teb=examples/benchmark/teb.json \
  --comment-output review.md
```

The command exits non-zero when any submission has errors, so it doubles as a
pre-submit check. Omit `--baseline` to validate without the rank preview.

See [examples/benchmark/submissions/README.md](../examples/benchmark/submissions/README.md)
for the submission format and [docs/pr-benchmark-bot.md](pr-benchmark-bot.md) for
the benchmark comment bot.
