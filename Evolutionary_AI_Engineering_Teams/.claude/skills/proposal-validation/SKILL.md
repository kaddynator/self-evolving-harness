# Proposal Validation Skill

## Purpose
Validate candidate Organization Harness mutations before accepting them.

## Instructions
1. Compare candidate organization against parent organization.
2. Protect task success metrics from regression.
3. Accept only if at least one meaningful metric improves.
4. Reject if runtime, tool calls, or failures exceed thresholds.
5. Store validation decision and reason.

## MVP Acceptance Rule
```text
accept if:
    tests_pass does not regress
    AND feature_works does not regress
    AND total_score improves OR tool_calls decrease
```

## Never
Never accept a mutation only because the rationale sounds good.
