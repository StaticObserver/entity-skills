# Entity Router v3 Control Protocol

Date: 2026-07-14
Status: current implementation baseline

## Control Objects

```text
Case -> Workflow -> Action -> Worker
```

A Case is identified by an immutable `case_uid`; `case_id/name` are merely labels. On the
controller side, each Case has at most one active mutating Action at a time. Workers are
bound to `(case_uid, execution_domain)`; runtime Agent IDs are not persisted.

## Action Contract v2

A Request contains Case revision/UID, owner/domain, `execution_site_id`, Locator
inputs/read roots/write roots/protected paths, constraints, expected outputs, and
acceptance checks. The owner envelope validates both site and path, and always protects
the controller Case root.

A remote Worker only reads the immutable request in the staging root; it cannot write to
the controller. A Result records terminal status, output Evidence, verification, blocker,
diagnosis, and suggested owner. The Router re-probes before writing the result and
advancing the state revision.

Fixed routing:

| Prefix | Owner | Domain |
|---|---|---|
| `pgen` | `entity-pgen` | `entity-pgen` |
| `source` | `router` | `playbook-sync` |
| `build` | `entity-env-build` | `entity-env-build` |
| `run` | `playbook-run` | `playbook-run` |
| `data` | `entity-nt2py` | `entity-nt2py` |
| `analysis` | `playbook-analysis` | `playbook-analysis` |
| `failure` | `failure-triage` | `failure-triage` |

## Standard Loop

1. Orient: precisely select Case/source authority/sites/current phase roots;
2. Recover: read the Case and re-probe external facts;
3. Decide: choose only from allowed actions;
4. Start: atomically write the controller request, staging to the remote side when needed;
5. Dispatch: the Worker loads only the owner skill/playbook and the request;
6. Verify: check output Locators, hashes, Git, scheduler/data evidence;
7. Commit: write result/event/state, propagate stale;
8. Continue/suspend/complete.

Once an Action has started, its owner, site, inputs, or envelope cannot be changed; to
change them, close the old Action and create a new one. Revision conflicts must be
re-read, never blindly retried.

## Behavioral Restrictions

- bounded read-only or genuinely standalone owner edits may call the task skill directly;
- writes to registered source require a matching active Action;
- PGen modifies PGen/TOML/design only on the source authority site;
- build writes only the build site envelope; run writes only run identity;
- source authority transfer must be a separate Action;
- never guess the "latest" checkout/build/run;
- never treat a Worker summary as evidence;
- never copy full raw data as the default analysis flow;
- cached observations from an offline site do not advance state.

The state tool `entity_router_state.py` manages Case/Action/revision/migration;
`entity_router_site.py` manages site/profile/probe/materialization. The generic core does
not store SSH credentials, partition/account/module fixes, or other site-specific content.
