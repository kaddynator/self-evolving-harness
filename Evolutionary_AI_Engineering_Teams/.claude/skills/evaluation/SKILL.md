# Evaluation Skill

## Purpose
Implement scoring and validation gates.

## Instructions
1. Prefer deterministic checks over LLM judging.
2. Compute raw metrics and final score.
3. Validate candidate organizations against parent organizations.
4. Protect core success metrics from regression.
5. Store validation results.

## Metrics
- tests_pass
- feature_works
- reviewer_acceptance
- tool_calls
- runtime_seconds
- diff_size

## Rule
No evolution without reliable evaluation.
