# Weakness Mining Skill

## Purpose
Convert execution traces into reusable failure signatures.

## When to use
Use after runtime execution and before mutation proposals.

## Instructions
1. Inspect trace events, tool calls, artifacts, and evaluator output.
2. Identify verifier-level cause.
3. Identify agent behavior that contributed.
4. Identify reusable mechanism.
5. Store the failure signature in MongoDB.
6. Cluster by exact signature for MVP.

## Failure Signature Shape
```json
{
  "verifier_cause": "...",
  "agent_behavior": "...",
  "mechanism": "..."
}
```

## MVP Mechanisms
- missing_required_artifact
- repeated_failed_tool_call
- unverified_completion
- excessive_exploration
- weak_requirements_grounding
- poor_handoff
- oversized_patch
