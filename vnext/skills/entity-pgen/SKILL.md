---
name: entity-pgen
description: Design, implement, review, or modify an Entity problem generator and its TOML-facing contract. Use for fields, particles, boundaries, custom hooks, output, normalization, and PGen API questions. Build, submission, run tracking, and output analysis belong to the corresponding Entity skills.
---

# Entity PGen

Treat PGen as Entity's ordinary user-code interface and as an object
independent from Source. The same PGen can be combined with multiple Source
commits.

## Facts that must remain stable

- A PGen object has an ID, entry file, and actual files.
- A Build records the PGen ID and stores the PGen snapshot it compiled.
- Once a PGen has been used by a Build, changed PGen content gets a new ID.
- A concrete TOML belongs to a Run. A PGen may carry example or template TOML,
  but those do not replace the Run's exact input TOML.
- Do not modify Build snapshots, Run inputs, attempts, or raw Data while doing
  PGen development.

No preflight, parameter confirmation record, design-document ceremony, or
fixed development sequence is universally required. Read the current code and
TOML contract, make the requested change, and verify it in proportion to its
physics and API risk. A concise design note is useful when it preserves
non-obvious intent, but it is not a gate.

Use ordinary project trust boundaries. Validate paths and inputs enough to
avoid wrong PGen or TOML selection, without adding a separate security or
approval workflow.

## Working guidance

- Keep PGen implementation and every TOML key it consumes consistent.
- Confirm decisions that materially change the physical model when the user
  has not already specified them.
- Verify version-sensitive APIs and normalization against the selected Source
  checkout; bundled references are guidance, not authority over source code.
- Distinguish implementation correctness from physical validation.
- For a durable simulation, register the settled PGen with `entity pgen add`,
  then let the Build record the chosen Source/PGen combination.

## Reference routing

Read only what the task needs from `references/`:

| Need | Reference |
|---|---|
| normalization, units, coordinate basis | `00-normalization.md` |
| PGen structure, traits, constructor, parameters | `01-skeleton.md` |
| initial fields or particles | `02-init-fields.md`, `03-particle-injection.md` |
| external current or force | `04-ext-current.md`, `05-ext-force.md` |
| boundaries | `06-boundary.md` |
| custom output or post-step behavior | `07-custom-output.md`, `08-custom-post-step.md` |
| TOML contract | `09-toml-config.md` |
| advanced algorithms or existing patterns | `10-higher-order.md`, `pgens-index.md` |

Use `entity-workspace` when object relationships, Site operations, Build/Run
creation, submission, or cross-session status are part of the request.
