# Proposal Validation

## Purpose

Mutations must be validated before they are accepted.

The system should not accept an organization change merely because it sounds plausible.

## Acceptance Rule

MVP:

```text
accept if:
    no protected metric regresses
    AND at least one target metric improves
    AND runtime remains under limit
```

## Protected Metrics

- tests_pass
- feature_works
- task.success_conditions

## Improvement Metrics

- total_score
- fewer tool calls
- lower runtime
- smaller diff
- fewer failure signatures

## Candidate Proposal Record

```json
{
  "proposal_id": "proposal_v2_001",
  "parent_org_id": "org_rate_limiter_v1",
  "candidate_org_id": "org_rate_limiter_v2_candidate",
  "target_failure_signature": "...",
  "changed_surfaces": ["runtime_policies", "coder_agent.prompt"],
  "expected_effect": "reduce unverified completion",
  "regression_risk": "may increase runtime",
  "validation_result": "accepted"
}
```

## MVP Guidance

Run both parent and candidate against the same deterministic demo task.

If candidate succeeds and parent fails, accept.

If both succeed, prefer candidate only if it improves cost, runtime, or diff size.

If candidate fails, reject and store why.
