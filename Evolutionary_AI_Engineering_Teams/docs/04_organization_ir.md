# Organization Harness IR Specification

## Purpose

The Organization Harness IR is the central abstraction of the project.

It represents the full non-parametric scaffold that governs agent behavior:
- agents
- prompts
- tools
- memory
- runtime policies
- verification rules
- recovery procedures
- communication topology
- evaluation metrics
- mutation rules

The Team / Harness Compiler outputs this IR. The Runtime executes it. The Evaluator scores it. The Evolution Engine mutates it. MongoDB stores every version.

---

## Compiler Analogy

```text
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
Trace Collection + Evaluation
    |
    v
Weakness Mining + Mutation
```

---

## Design Goals

1. Executable
2. Versionable
3. Inspectable
4. Mutable
5. Regression-testable
6. Tool-agnostic
7. Domain-agnostic

---

## Top-Level Schema

```yaml
organization:
  id: string
  name: string
  version: integer
  parent_id: string | null
  objective: string
  domain: string
  constraints: []
  assumptions: []

task:
  id: string
  title: string
  description: string
  inputs: {}
  success_conditions: []
  artifacts_expected: []

agents:
  - id: string
    name: string
    role: string
    responsibilities: []
    prompt: string
    tools: []
    budget: {}
    memory_policy: {}
    output_contract: {}

communication:
  topology: string
  edges: []
  shared_memory: {}

execution:
  mode: string
  phases: []
  retry_policy: {}
  stopping_conditions: []

runtime_policies:
  max_repeated_tool_errors: integer
  max_tool_calls_before_reflection: integer
  require_artifact_before_finish: boolean
  verify_before_conclude: boolean
  prevent_identical_retry: boolean
  exploration_to_implementation_threshold: integer

failure_recovery:
  on_tool_error: string
  on_missing_artifact: string
  on_test_failure: string
  on_timeout_risk: string

evaluation:
  metrics: []
  binary_checks: []
  scoring: {}
  validation_gate: {}

weakness_mining:
  enabled: boolean
  failure_signature_fields: []
  clustering: {}

mutation_policy:
  allowed_mutations: []
  protected_components: []
  proposal_width: integer
  exploration_strategy: string

observability:
  trace_level: string
  log_events: []
  collect_artifacts: boolean
```

---

## Runtime Policies

Runtime policies encode harness-level behavior that is not specific to one agent.

Examples:

```yaml
runtime_policies:
  max_repeated_tool_errors: 2
  max_tool_calls_before_reflection: 20
  require_artifact_before_finish: true
  verify_before_conclude: true
  prevent_identical_retry: true
  exploration_to_implementation_threshold: 12
```

These policies prevent common agent failures:
- endless exploration
- repeated failed commands
- concluding without verification
- forgetting required artifacts
- overusing tools

---

## Failure Recovery

```yaml
failure_recovery:
  on_tool_error: Inspect the error, change strategy, and do not repeat the exact same command.
  on_missing_artifact: Create the required artifact immediately before continuing.
  on_test_failure: Read the failing assertion and make the smallest targeted fix.
  on_timeout_risk: Stop exploration and produce the best verified artifact.
```

---

## Weakness Mining

After each run, trace records are converted into failure signatures.

```yaml
weakness_mining:
  enabled: true
  failure_signature_fields:
    - verifier_cause
    - agent_behavior
    - mechanism
  clustering:
    method: exact_signature
    min_cluster_size: 1
```

Example failure signature:

```json
{
  "verifier_cause": "missing_required_file",
  "agent_behavior": "agent_deleted_artifact_before_finish",
  "mechanism": "artifact_reliability_failure"
}
```

---

## Validation Gate

Mutations must pass a validation gate before promotion.

```yaml
evaluation:
  validation_gate:
    require_no_regression:
      - tests_pass
      - feature_works
    require_improvement_any:
      - total_score
      - tool_calls
      - runtime_seconds
    max_runtime_seconds: 600
```

---

## Mutation Policy

```yaml
mutation_policy:
  allowed_mutations:
    - add_agent
    - remove_agent
    - modify_prompt
    - modify_tools
    - reorder_edges
    - change_topology
    - adjust_budget
    - modify_runtime_policy
    - modify_failure_recovery
  protected_components:
    - task.success_conditions
    - evaluation.validation_gate
  proposal_width: 3
  exploration_strategy: validation_gated_mutate_winner
```

---

## MVP Guidance

Implement these first:
1. YAML loading
2. schema validation
3. runtime phases
4. event traces
5. scoring
6. failure signatures
7. rule-based proposals
8. validation gate
9. MongoDB persistence

Do not implement broad autonomous mutation until the deterministic loop works.

---

## Core Principle

The IR is not just a team description.

It is a full, evolvable agent harness.
