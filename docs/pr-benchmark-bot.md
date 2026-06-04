# PR Benchmark Bot

Turn `nav2_scenario_runner` into a **drop-in GitHub Action** that ranks your
Nav2 configurations and posts a single, self-updating benchmark comment on every
pull request.

```
🤖 Nav2 Benchmark

🏆 Winner: navfn — score 73.8 / 100 · pass 100% (3/3)

| Rank | Config | Score | Pass        | Wins |
|:----:|:-------|------:|:-----------:|-----:|
|  🥇  | navfn  |  73.8 | 100% (3/3)  |    5 |
|  🥈  | smac   |  73.3 | 100% (3/3)  |   11 |
|  🥉  | teb    |  46.7 |  67% (2/3)  |    7 |

📈 Trend vs previous run
⚠️ 6 regression(s), 0 improvement(s) across the latest run.
```

## How it fits together

The bot is a thin, composable pipeline over commands you already have:

```
evaluate --json-output  ─┐
                         ├─►  pr-comment ──►  comment.md  ──►  sticky PR comment
trend    --json-output  ─┘        (marker for upsert)
```

1. `evaluate` ranks the configs into `evaluation.json`.
2. `trend` (optional) summarizes drift into `trend.json`.
3. `pr-comment` reads those two artifacts and renders a compact Markdown body
   that begins with a hidden marker:

   ```
   <!-- nav2-scenario-runner:benchmark -->
   ```

   A CI step finds the comment carrying that marker and **updates it in place**
   instead of posting a new comment on every push.

## Using the bundled action

`action.yml` at the repository root is a composite GitHub Action. Reference it
by repo (after you tag a release, e.g. `@v1`) or use a pinned commit:

```yaml
permissions:
  contents: read
  pull-requests: write          # required to post/update the comment

jobs:
  benchmark:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      # ... produce one JSON run report per Nav2 config (run / record / etc.) ...

      - uses: rsasaki0109/nav2_scenario_runner@v1
        id: bench
        with:
          entries: |               # LABEL=report.json, one per line, minimum two
            navfn=reports/navfn.json
            smac=reports/smac.json
            teb=reports/teb.json
          history: reports/history.jsonl                       # optional
          title: "Nav2 Benchmark"
          dashboard-url: "https://example.com/benchmark"       # optional footer link

      - uses: actions/github-script@v7
        env:
          COMMENT_FILE: ${{ steps.bench.outputs.comment-file }}
        with:
          script: |
            const fs = require('fs');
            const marker = '<!-- nav2-scenario-runner:benchmark -->';
            const body = fs.readFileSync(process.env.COMMENT_FILE, 'utf8');
            const { owner, repo } = context.repo;
            const issue_number = context.issue.number;
            const { data: comments } = await github.rest.issues.listComments({ owner, repo, issue_number });
            const existing = comments.find(c => c.body && c.body.includes(marker));
            if (existing) await github.rest.issues.updateComment({ owner, repo, comment_id: existing.id, body });
            else await github.rest.issues.createComment({ owner, repo, issue_number, body });
```

### Inputs

| Input | Required | Default | Description |
|:--|:--:|:--|:--|
| `entries` | yes | — | Whitespace/newline-separated `LABEL=report.json` pairs (min 2). |
| `history` | no | `""` | History JSONL store; enables the trend/regression section. |
| `title` | no | `Nav2 Benchmark` | Heading at the top of the comment. |
| `dashboard-url` | no | `""` | URL linked in the comment footer. |
| `output-dir` | no | `nav2-benchmark` | Where generated artifacts are written. |
| `python-version` | no | `3.11` | Python used to run the runner. |

### Outputs

| Output | Description |
|:--|:--|
| `comment-file` | Path to the rendered Markdown comment. |
| `evaluation-file` | Path to `evaluation.json`. |
| `winner` | Label of the top-ranked configuration. |

The action also writes `evaluation.html` and `trend.html` into `output-dir`, so
you can `actions/upload-artifact` the full dashboards alongside the comment.

## Rendering the comment by hand

`pr-comment` is a first-class CLI command, useful for local previews or custom
CI:

```bash
nav2_scenario_runner pr-comment \
  --evaluation reports/evaluation.json \
  --trend reports/trend.json \
  --title "Nav2 Benchmark" \
  --dashboard-url https://example.com/benchmark \
  --output reports/comment.md
```

Omit `--trend` for a leaderboard-only comment, and `--output` to print to
stdout.

## Notes

- **Fork PRs**: pull requests from forks run with a read-only `GITHUB_TOKEN`, so
  the comment step cannot post. Use `pull_request_target` (carefully) or gate the
  comment step on `github.event.pull_request.head.repo.fork == false` if you need
  fork coverage.
- **First run**: when `history` has a single recorded run there is nothing to
  compare against, and the trend section says so instead of inventing deltas.
- The dogfood workflow [`benchmark-pr.yml`](../.github/workflows/benchmark-pr.yml)
  runs this action against the bundled [example benchmark suite](../examples/benchmark/)
  on pull requests that touch the runner or fixtures.
