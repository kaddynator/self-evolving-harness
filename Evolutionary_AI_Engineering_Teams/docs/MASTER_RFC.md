# Evolutionary AI Engineering Teams
## Master Design Document (RFC v0.2)

> Primary context for Claude Code and any AI coding agent working on this hackathon project.

---

# 1. Executive Summary

We are building a self-improving AI system that learns how to design, execute, evaluate, and improve AI engineering organizations.

The core insight:

> The agent team is only one part of the system. The full object we evolve is the **Organization Harness**.

An Organization Harness includes:
- agent roles
- prompts
- tool permissions
- communication graph
- execution order
- runtime policies
- memory behavior
- recovery rules
- verification gates
- evaluation metrics

The system compiles a task into an executable Organization Harness IR, runs it, collects traces, mines weaknesses, proposes bounded harness edits, validates those edits, and stores accepted improvements in MongoDB.

---

# 2. Hackathon Alignment

Primary theme:
- Self-Improvement Stack

Secondary theme:
- Continual Learning

Research direction:
- Recursive Intelligence

This project improves the infrastructure that builds and operates AI systems. It does not merely optimize a single answer or a single prompt.

---

# 3. Updated Framing

Old framing:
- Evolutionary AI Engineering Teams

Improved framing:
- Evolutionary AI Organization Harnesses

Public-facing phrase:
- "We built a system that learns how to design better AI engineering organizations."

Technical phrase:
- "A validation-gated Organization Harness compiler and optimizer."

---

# 4. Core Loop

Task Specification
    |
    v
Team / Harness Compiler
    |
    v
Organization Harness IR
    |
    v
Runtime Execution
    |
    v
Trace Collection
    |
    v
Weakness Mining
    |
    v
Harness Mutation Proposal
    |
    v
Proposal Validation
    |
    v
Accept / Reject
    |
    v
MongoDB Memory
    |
    v
Future Compiler Context

---

# 5. Why Self-Harness Matters

Self-Harness shows that agent performance is shaped by the surrounding harness, not only the model.

Important lesson:
A useful harness edit should specify:
- the behavior it aims to change
- the harness surface it modifies
- the evidence that motivated it
- the validation result that justifies promotion

We adopt this principle directly.

---

# 6. Organization Harness IR

The IR is the central object of the system.

It should include:
- organization metadata
- task details
- agents
- prompts
- tools
- communication graph
- execution phases
- runtime policies
- failure recovery policies
- evaluation metrics
- mutation policy
- observability settings

The IR is:
- compiled by the Team / Harness Compiler
- executed by the Runtime
- evaluated by the Evaluator
- mutated by the Evolution Engine
- stored in MongoDB

---

# 7. Weakness Mining

After each run, the system should not simply say "failed."

It should identify reusable failure mechanisms.

Failure signature:

```json
{
  "verifier_cause": "tests_failed",
  "agent_behavior": "coder_changed_unrelated_files",
  "mechanism": "missing_requirements_grounding"
}
```

Examples:
- missing artifact
- unverified final answer
- repeated failed command
- too much exploration
- ignored acceptance criteria
- wrong tool access
- weak test generation
- poor handoff between agents

---

# 8. Harness Proposal

The proposer generates bounded candidate edits.

Examples:
- add Requirements Agent
- remove Planner Agent
- move Tester before Reviewer
- modify Coder prompt
- limit repeated tool calls
- require verification before finish
- add artifact creation policy
- change tool permissions

Each proposal must include:
- target failure signature
- changed surface
- expected behavior change
- regression risk
- rollback plan

---

# 9. Proposal Validation

No mutation should be accepted because it sounds good.

A mutation is accepted only if:
- core success metrics do not regress
- at least one metric improves
- execution remains within budget
- required artifacts are produced
- tests remain deterministic

MVP validation rule:

```text
accept if:
    tests_pass is not worse
    AND score improves OR tool_calls decrease
    AND runtime does not exceed limit
```

---

# 10. MongoDB Memory

MongoDB stores:
- tasks
- organizations
- runs
- traces
- failure_signatures
- proposals
- validations
- accepted_mutations
- rejected_mutations
- lessons

This makes improvement inspectable and reusable.

---

# 11. Demo Strategy

Use a deterministic software engineering task.

Recommended demo task:
- Add a per-user API rate limiter to a small Express or FastAPI repo.

Show:
1. Initial Organization Harness V1.
2. Run V1.
3. Show failure or inefficiency.
4. Mine weakness.
5. Propose bounded mutation.
6. Validate mutation.
7. Run V2.
8. Show improved score.
9. Show MongoDB memory.

Demo line:

> "We are not optimizing answers. We are evolving AI organization harnesses."

---

# 12. Implementation Roadmap

Phase 1:
- Organization Harness IR schema
- YAML loader
- validator
- mock runtime

Phase 2:
- evaluator
- trace collection
- MongoDB persistence

Phase 3:
- weakness mining
- proposal generation
- validation-gated mutation

Phase 4:
- Gemini integration
- DigitalOcean sandbox workers
- live demo polish

---

# 13. Non-Goals for MVP

Do not overbuild:
- generic UI dashboard
- open-ended browser automation
- full AutoML
- broad vulnerability repair
- live multi-hour evolution

The MVP should show one reliable end-to-end improvement loop.

---

# 14. Success Criteria

Judges should understand:

1. Most agent systems have static human-designed teams.
2. Our system compiles a task into an organization harness.
3. It learns from traces.
4. It proposes bounded changes.
5. It validates those changes.
6. It stores reusable organizational knowledge.

End of RFC v0.2.
