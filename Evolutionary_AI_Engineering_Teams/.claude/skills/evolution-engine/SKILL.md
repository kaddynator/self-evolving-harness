# Evolution Engine Skill

## Purpose
Implement organization harness mutation and selection logic.

## Instructions
1. Mutate the Organization Harness, not only prompts.
2. Candidate mutations must be grounded in failure signatures.
3. Every mutation must produce a candidate Organization IR.
4. Every candidate must go through proposal validation.
5. Store accepted and rejected mutations in MongoDB.

## MVP Mutations
- add_agent
- remove_agent
- modify_prompt
- modify_tools
- reorder_edges
- adjust_budget
- modify_runtime_policy
- modify_failure_recovery

## Rule
Never accept a mutation without validation.
