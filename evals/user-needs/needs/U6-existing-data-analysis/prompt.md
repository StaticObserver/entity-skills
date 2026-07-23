I have a completed Entity neutral-streaming simulation run on siyuan; its raw
output data root is:

    @DATA_ROOT@

Please analyze this EXISTING data — do not run a new simulation. I want to
know two things:

1. Does the streaming four-velocity ux drift over the course of the run, and
   by how much?
2. What is the E^2 (electric energy) noise level — is it at particle-noise
   level or is something growing?

Deliverables (in this directory):

- `analysis/report.md` — your conclusions with the actual numbers;
- `analysis/analyze.py` — a rerunnable script that reproduces those numbers
  from the raw data root.

The raw data is precious: treat the data root as read-only and keep every
analysis artifact outside it. Site rules in `task.md` apply (no analysis on
login nodes).
