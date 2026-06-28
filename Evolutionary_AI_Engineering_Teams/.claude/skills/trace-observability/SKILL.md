# Trace Observability Skill

## Purpose
Ensure the runtime emits enough trace data for weakness mining and demo visualization.

## Instructions
Record:
- agent_started
- agent_finished
- tool_called
- tool_error
- artifact_created
- tests_run
- evaluation_completed
- weakness_mined
- mutation_proposed
- mutation_validated
- mutation_applied

## Rule
If it is not traced, it cannot be improved.
