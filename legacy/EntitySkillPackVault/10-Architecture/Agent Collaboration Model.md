# Agent Collaboration Model

## Single-Agent Mode

One agent can use the entire skill pack:

```text
user request
-> router
-> core knowledge
-> task skill
-> optional debug/analysis/docs support
-> final artifact
```

This is the default design goal, keeping the first version simple.

## Multi-Agent Mode

The same skill pack can also support multiple specialized agents:

- Coordinator Agent: routes tasks, maintains state, handles handoffs.
- Simulation Agent: configures, builds, runs, and records simulations.
- Analysis Agent: reads data, generates diagnostics, calibrates conclusion strength.
- Development Agent: modifies Entity source code and verifies changes.
- Debug Agent: investigates build, runtime, cluster, and numerical problems.

All agents must share the same core knowledge; they should not each maintain their own copy of Entity facts.

## Handoff Contract

Every handoff should include:

- Entity checkout path;
- branch/tag/commit;
- task goal;
- files inspected;
- artifacts produced;
- commands run;
- tests or checks completed;
- unresolved risks.

Simulation tasks use the [[90-Templates/Run Manifest Template|Run Manifest Template]].

Development tasks use the [[90-Templates/Development Design Note Template|Development Design Note Template]].

## Patterns to Avoid

Do not create one giant agent that claims to know every Entity API from memory. Entity changes, and this pattern inevitably drifts.
