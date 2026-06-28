export interface NarrationCue {
  cueId: string;
  scene: SceneId;
  text: string;
  clipTags?: string[];
}

export type SceneId =
  | 'hero'
  | 'problem'
  | 'product-demo'
  | 'feedback'
  | 'tech-stack'
  | 'outro';

export const NARRATION: NarrationCue[] = [
  // ── Hero ──────────────────────────────────────────────────────────────
  {
    cueId: 'hero-1',
    scene: 'hero',
    text: 'Self-evolving AI teams.',
  },

  // ── Problem ───────────────────────────────────────────────────────────
  {
    cueId: 'problem-1',
    scene: 'problem',
    text: "Today's AI agents are powerful — but most multi-agent systems remain fundamentally static. Developers predefine the agents, assign their responsibilities, and manually design how they collaborate.",
  },
  {
    cueId: 'problem-2',
    scene: 'problem',
    text: 'This works for predictable workflows. But it breaks down when tasks are unfamiliar, evolve over time, or require expertise nobody anticipated.',
  },

  // ── Product demo ──────────────────────────────────────────────────────
  {
    cueId: 'demo-1',
    scene: 'product-demo',
    text: 'This system takes a plain-English task and compiles it into a multi-agent team — ready to run, with no manual design.',
    clipTags: ['configure', 'task', 'compile'],
  },
  {
    cueId: 'demo-2',
    scene: 'product-demo',
    text: 'Each agent calls real tools, produces artifacts, and passes results to the next. The entire execution is traced.',
    clipTags: ['monitor', 'agent', 'tool'],
  },
  {
    cueId: 'demo-3',
    scene: 'product-demo',
    text: 'The system mines what went wrong — then proposes mutations: swap a model, tighten a budget, add a verifier, reorder the team.',
    clipTags: ['evolution', 'mutation', 'weakness'],
  },
  {
    cueId: 'demo-4',
    scene: 'product-demo',
    text: 'Only candidates that improve without regressing are promoted. Generation after generation — the team adapts on its own.',
    clipTags: ['gate', 'score', 'generation'],
  },

  // ── Feedback flywheel ─────────────────────────────────────────────────
  {
    cueId: 'feedback-1',
    scene: 'feedback',
    text: "And when the evolved workflow is still wrong — humans step in. They label what the correct output should have been. That feedback builds an evaluation set, and the system uses it to rebuild and re-evolve the workflow from the ground up.",
  },

  // ── Tech stack ────────────────────────────────────────────────────────
  {
    cueId: 'tech-1',
    scene: 'tech-stack',
    text: "The system runs on Gemini 2.5 Flash and Claude Sonnet for intelligence, MongoDB Atlas to track every agent run and evolution state, Qdrant for task similarity search, ClickHouse for scoring history, and DigitalOcean droplets running Docker for the vector and analytics layer.",
  },

  // ── Outro ─────────────────────────────────────────────────────────────
  {
    cueId: 'outro-1',
    scene: 'outro',
    text: 'Dynamic workflows, self-evolving agent teams, grounded by human judgment — this is the next frontier in AI.',
  },
];

export function cuesForScene(scene: SceneId): NarrationCue[] {
  return NARRATION.filter((c) => c.scene === scene);
}
