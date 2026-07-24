# Entity Development Workflow

## Goal

Safely modify Entity source code and verify its behavior.

## Steps

1. Probe the Git root, branch, commit, and dirty state.
2. Confirm the target subsystem.
3. Search the current code with `rg`.
4. Read the relevant headers and call paths.
5. Write down verified facts.
6. Draft a minimal design.
7. Implement narrowly scoped changes.
8. Run focused tests or compile checks.
9. Run a small simulation smoke test when relevant.
10. Record remaining risks.

## Design Rules

Do not mix repo facts with proposed behavior. Keep them in separate sections of the development note.
