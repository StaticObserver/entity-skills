# Entity Skill Design Principles

## The Six Layers of a Mature Harness

In an Agent system, almost everything beyond the model itself that determines whether it can deliver reliably counts as part of the Harness. A mature Harness can roughly be broken down into six layers.

1. Context management

Whether a model performs consistently often depends not only on how smart it is, but also on what it sees.

The Harness's first responsibility is to let the model think within the right information boundaries. This usually involves three things:

- defining roles, goals, and success criteria;
- retrieving and selecting relevant information instead of piling it up;
- structuring rules, tasks, state, and external evidence.

Once information becomes chaotic, the model easily misses key points, forgets constraints, and even pollutes itself.

2. Tool system

Without tools, a large model is essentially still a text predictor: it can explain and summarize, but it cannot touch the real world. Once connected to tools, the model can actually do things, such as browsing the web, reading files, writing code, and calling APIs.

But a Harness is not simply about attaching tools; it has to solve three problems:

- which tools to give the model;
- when tools should be invoked;
- how tool results are fed back into the model.

Too few tools means insufficient capability; too many and the model misuses them. Don't look things up when you don't need to, and don't answer blindly when verification is called for. Nor should dozens of tool results be stuffed back verbatim — they should be distilled, filtered, and kept relevant to the task.

3. Execution orchestration

The core problem this layer solves is: what should the model do next?

Many Agent problems are not that a single step fails, but that the Agent cannot string all the steps together. It can search, summarize, and write code, yet the whole process wanders wherever it goes, ending in a pile of half-finished work.

A complete task usually needs a track like this: understand the goal; judge whether the information is sufficient and gather more if not; organize results and continue analyzing; produce output; check the output; correct or retry if requirements are not met.

This is already very close to how humans work. The difference is that humans rely on experience, while Agents rely on the environment the Harness provides.

4. Memory and state

An Agent without state suffers from amnesia every round. It doesn't know what it just did, which conclusions are confirmed, or which problems remain unsolved.

The Harness must manage state and distinguish at least three kinds of things:

- current task state;
- intermediate results within the session;
- long-term memory and user preferences.

If these three are mixed together, the system becomes increasingly messy. Once they are separated, the Agent behaves more like a stable collaborator.

5. Evaluation and observability

Many systems are not incapable of producing output; they just don't know whether what they produced is any good. Without independent evaluation and observability, an Agent will stay indefinitely in a state of "feeling good about itself."

This layer typically includes output acceptance, environment verification, automated tests, logs and metrics, error attribution, and so on. The system must not only be able to act, but also know whether it actually did things right.

6. Constraints, validation, failure recovery

The last layer often truly determines whether a system can go live. In real environments, failure is not the exception but the norm. Searches may be inaccurate, APIs may time out, document formats may be messy, and the model may misunderstand the task.

Without recovery mechanisms, an Agent has to start over every time something goes wrong.

A mature Harness must include:

- constraints: what can be done and what cannot;
- validation: how outputs are checked before and after;
- recovery: how to retry after failure, switch paths, or roll back to a stable state.
