# Vision

Problem:
Today's multi-agent systems have static organizations designed by humans, and
once deployed they never learn from how they actually perform in production.

Hypothesis:
AI should learn how to build the right engineering organization for each task —
and keep improving it from real usage.

Core Idea:
Task -> Team Compiler -> Executable Organization -> Evaluation -> Evolution -> Better Organization

## What it is now

A **self-evolving harness for agentic workflows** with a **production feedback
flywheel**. We compile a task into an executable Organization Harness, serve it,
and let real usage drive its improvement:

- **Two evaluation modes.** When the user has ground-truth eval cases
  (input + expected output), we grade reference-against them. When no labels
  exist, an **LLM-as-judge** grades against success conditions and binary checks.
  The judge is real and on by default (see `docs/07_evaluation.md`).
- **A feedback flywheel.** Every served workflow is wrapped by a platform-level
  sentiment sentinel. Negative sentiment captures an eval case; a human labels
  the expected output; once a batch of labels accrues, evolution re-runs against
  the enriched dataset, grades candidates reference-against the labels, gates on
  no-regression over the full set, and redeploys. See
  `docs/14_feedback_flywheel.md`.

The object we evolve is still the full Organization Harness (agents, prompts,
tools, policies, topology) — the flywheel is what supplies the ground-truth
signal that makes the evolution converge on what real users actually want.
