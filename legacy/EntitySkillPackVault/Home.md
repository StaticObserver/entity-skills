# Entity Skill Pack

## Purpose

Build a general-purpose skill pack for Entity that:

- helps users run simulations safely and reproducibly;
- helps users analyze results, with the evidence strength of conclusions made explicit;
- helps users develop Entity features from the current checkout, rather than relying on stale memory.

This design deliberately distinguishes "using Entity" from "developing Entity". These two kinds of work require different knowledge depth, risk control, and validation standards.

## Navigation

### Architecture

- [[10-Architecture/Entity Skill Pack Architecture|Entity Skill Pack Architecture]]
- [[10-Architecture/Knowledge Model and Version Strategy|Knowledge Model and Version Strategy]]
- [[10-Architecture/Agent Collaboration Model|Agent Collaboration Model]]

### Skill Specifications

- [[20-Skills/Router Skill Spec|Router Skill Spec]]
- [[20-Skills/Env Build Skill Spec|Env Build Skill Spec]]
- [[20-Skills/Entity Case Skill Spec|Entity Case Skill Spec]]
- [[20-Skills/Simulation Skill Spec|Simulation Skill Spec]]
- [[20-Skills/Analysis Skill Spec|Analysis Skill Spec]]
- [[20-Skills/Development Skill Spec|Development Skill Spec]]
- [[20-Skills/Debug Skill Spec|Debug Skill Spec]]
- [[20-Skills/Docs Skill Spec|Docs Skill Spec]]

### Playbooks

- [[30-Playbooks/New Simulation Workflow|New Simulation Workflow]]
- [[30-Playbooks/Analysis Workflow|Analysis Workflow]]
- [[30-Playbooks/Entity Development Workflow|Entity Development Workflow]]
- [[30-Playbooks/Debugging Workflow|Debugging Workflow]]

### Development

- [[40-Development/Development Plan|Development Plan]]
- [[40-Development/Backlog|Backlog]]
- [[40-Development/Acceptance Criteria|Acceptance Criteria]]

### References

- [[50-References/Entity Source of Truth|Entity Source of Truth]]
- [[50-References/Local Context and Overlays|Local Context and Overlays]]

### Templates

- [[90-Templates/Run Manifest Template|Run Manifest Template]]
- [[90-Templates/Simulation Plan Template|Simulation Plan Template]]
- [[90-Templates/Development Design Note Template|Development Design Note Template]]
- [[90-Templates/Analysis Report Template|Analysis Report Template]]

## Writing Conventions

Notes in this vault were originally written in Chinese; necessary English technical terms, code identifiers, commands, paths, and YAML field names were kept in English.

## Design Principles

The skill pack should not try to memorize every detail of Entity. It should teach agents how to find authoritative details in the current checkout and organize those details into reliable workflows.
