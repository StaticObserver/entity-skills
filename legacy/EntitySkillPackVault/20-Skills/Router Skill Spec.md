# Router Skill Spec

## Role

Classify the user request type and load the minimum necessary Entity skill.

The Router should be thin and contain no detailed Entity API.

## Routing Table

| User Intent | Skill |
| --- | --- |
| Configure a run, write TOML, choose a pgen, submit a job | [[Simulation Skill Spec|Simulation Skill]] |
| Read output, plot, diagnose physical behavior | [[Analysis Skill Spec|Analysis Skill]] |
| Modify Entity source or add core features | [[Development Skill Spec|Development Skill]] |
| Diagnose build, runtime, output, or performance failures | [[Debug Skill Spec|Debug Skill]] |
| Write run notes, design notes, PR summaries, or reports | [[Docs Skill Spec|Docs Skill]] |

## Always Load

Before any task skill, always load:

- [[10-Architecture/Knowledge Model and Version Strategy|Knowledge Model and Version Strategy]]
- [[50-References/Entity Source of Truth|Entity Source of Truth]]

## Classification Examples

"Help me run reconnection on an A100" -> simulation.

"Plot the particle spectrum and check energy conservation" -> analysis.

"Add a new output quantity" -> development, possibly followed by analysis for verification.

"Crashes during ADIOS2 output" -> debug.

"Turn this run into a reproducible record" -> docs plus simulation.

## Router Output

The Router should state:

- which skill was chosen;
- why it was chosen;
- whether another skill may be needed later.
