# Neutral Streaming E2E Evaluation

This evaluation compares one Entity-skilled agent with the same agent running
without Entity skills. Both variants receive the exact text in `task.md` and
must emit the common `submission.json` contract.

The evaluation is currently `pre_gold`: task semantics and schemas are frozen,
but the exact Entity commit, timestep settings, and physics thresholds must be
fixed by the maintainer gold run before any formal comparison.

## Safety

轻量 A/B 对照以 [`RUNBOOK.md`](RUNBOOK.md) 为准：一个任务、两个变体、
每轮三条命令，立即可以开跑。下述 `pre_gold` 正式对照流程保留备用。

- The checked-in site profile is an example. Runtime credentials and writable
  roots are injected outside Git.
- The fake Slurm adapter never runs a simulation. It exists only to exercise
  submission, recovery, and evidence plumbing.
- `oracle/thresholds.json` fails closed while its status is `unfrozen`.

## Local checks

```bash
python3 oracle/validate_submission.py --submission <submission.json>
python3 oracle/validate_physics.py \
  --report <analysis-report.json> --thresholds oracle/thresholds.json
```

Formal execution is forbidden until `experiment.json.freeze.status` is
`frozen` and the referenced hashes have been reviewed.
