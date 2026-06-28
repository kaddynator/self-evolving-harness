# Weakness Mining

## Purpose

Weakness Mining turns execution traces into reusable failure signatures.

The goal is to avoid treating failures as isolated anecdotes.

## Inputs

- task
- organization harness version
- runtime trace
- tool calls
- artifacts
- evaluator outcome
- test output

## Output

A failure signature:

```json
{
  "verifier_cause": "tests_failed",
  "agent_behavior": "coder_modified_unrelated_files",
  "mechanism": "missing_requirements_grounding"
}
```

## Common Mechanisms

- missing_required_artifact
- repeated_failed_tool_call
- unverified_completion
- excessive_exploration
- weak_requirements_grounding
- poor_handoff
- wrong_tool_permission
- late_testing
- oversized_patch

## MVP Implementation

Start with rule-based classifiers:
- If tests fail -> verifier_cause = tests_failed
- If required artifact missing -> mechanism = missing_required_artifact
- If same tool error repeats -> mechanism = repeated_failed_tool_call
- If tool_calls > threshold and no patch -> mechanism = excessive_exploration

Later use Gemini to summarize and cluster traces.
