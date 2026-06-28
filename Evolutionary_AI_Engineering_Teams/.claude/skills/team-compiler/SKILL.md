# Team Compiler Skill

## Purpose
Implement or modify the Team Compiler.

## When to use
Use when generating teams, agent roles, prompts, tool assignments, or communication graphs.

## Instructions
1. Input should include task, constraints, available tools, repo context, and prior memory.
2. Output must be valid Organization IR.
3. Start simple with templates:
   - minimal_team
   - planner_coder_tester_reviewer
   - specialist_team
4. Later allow Gemini to synthesize new organizations.
5. Always explain why each agent exists.

## Success
A compiled organization can be executed by the runtime without manual editing.
