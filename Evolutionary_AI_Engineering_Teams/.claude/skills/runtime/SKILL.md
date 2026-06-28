# Runtime Skill

## Purpose
Implement or modify the runtime that executes Organization IR.

## When to use
Use when building phase execution, agent orchestration, tool execution, tracing, or sandbox workers.

## Instructions
1. Load and validate Organization IR.
2. Execute phases in order.
3. Support parallel agents only after sequential execution works.
4. Record every event:
   - agent_started
   - agent_finished
   - tool_called
   - artifact_created
   - evaluation_completed
5. Start with mock agents before integrating Gemini.
6. Keep runtime deterministic for demo reliability.

## Priority
End-to-end execution is more important than perfect agent intelligence.
