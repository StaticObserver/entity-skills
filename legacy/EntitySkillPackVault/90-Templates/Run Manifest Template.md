# Run Manifest Template

The YAML field names below stay in English so agents and scripts can read them.

```yaml
run_id:
created_at:

entity:
  checkout_path:
  git_root:
  branch:
  commit:
  describe:
  dirty_state:

simulation:
  name:
  physics_goal:
  engine:
  metric:
  dimension:
  pgen:
  toml_path:

build:
  command:
  backend:
  mpi:
  gpu_aware_mpi:
  precision:
  deposit:
  shape_order:

run:
  command:
  scheduler:
  output_path:
  checkpoint_policy:

validation:
  level: config-check | smoke-run | numerical-sanity | physics-validation
  status: ready | partial | blocked
  checks:
    - name:
      result:
      evidence:

artifacts:
  info_file:
  err_file:
  log_file:
  stats_csv:
  plots:

risks:
  - 
```
