/**
 * End-to-end source video analysis.
 *
 * For each source clip listed in SOURCES (or the single id passed on argv),
 * this script:
 *
 *   1. Extracts keyframes at a fixed sampling interval (via ffmpeg).
 *   2. Runs Apple Vision OCR on every keyframe (via the Python sidecar).
 *   3. Detects freeze ranges (model-think-time stalls, idle dialogs, etc.).
 *   4. Writes the per-source analysis under
 *      `video/src/data/source-analysis/<sourceId>.json`.
 *   5. Maintains an index file `source-analysis/index.json` listing every
 *      analysed source for the curator to consume.
 *
 * CUSTOMISE the `SOURCES` array to list your demo's source recordings —
 * the `id` must match the basename you used in `assets/src/prepare.ts`.
 */
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { detectFreezes, extractKeyframes, probe } from './ffmpeg.js';
import { ocrKeyframes } from './ocr.js';
import type { SourceAnalysis } from './types.js';

const here = dirname(fileURLToPath(import.meta.url));
// analyzer/src/ → demo-root/
const DEMO_ROOT = resolve(here, '..', '..');
const VIDEO_PUBLIC = resolve(DEMO_ROOT, 'video', 'public');
const ANALYSIS_DIR = resolve(DEMO_ROOT, 'video', 'src', 'data', 'source-analysis');
const KEYFRAME_CACHE = resolve(DEMO_ROOT, 'analyzer', '.cache', 'keyframes');

interface SourceSpec {
  id: string;
  publicPath: string;
  /** Sampling interval for keyframes, in seconds. Lower = more frames + slower OCR. */
  intervalSec: number;
  /** Freeze-detect threshold; tune per-source if needed. */
  freeze?: { noise?: number; minDurationSec?: number };
}

// ───── CUSTOMISE ME ──────────────────────────────────────────────────────
// Each `id` becomes the source-analysis filename and is referenced by
// SCENE_SOURCE in video/scripts/warm-voice.ts.
const SOURCES: SourceSpec[] = [
  {
    id: 'harness-demo',
    publicPath: 'source/harness-demo.mp4',
    intervalSec: 2,
    freeze: { minDurationSec: 2, noise: 0.003 },
  },
];

function ensureDir(p: string) {
  if (!existsSync(p)) mkdirSync(p, { recursive: true });
}

async function analyseOne(spec: SourceSpec): Promise<SourceAnalysis> {
  const source = join(VIDEO_PUBLIC, spec.publicPath);
  if (!existsSync(source)) {
    throw new Error(`[analyzer] source missing: ${source}`);
  }
  console.log(`\n[analyzer] === ${spec.id} ===`);

  const meta = await probe(source);
  console.log(`[analyzer] ${meta.width}×${meta.height}, ${meta.durationSec.toFixed(1)}s`);

  const keyframesDir = join(KEYFRAME_CACHE, spec.id);
  console.log(`[analyzer] extracting keyframes @ 1/${spec.intervalSec}s → ${keyframesDir}`);
  const { count } = await extractKeyframes(source, keyframesDir, spec.intervalSec);
  console.log(`[analyzer] ✓ ${count} keyframes`);

  console.log(`[analyzer] OCR via Apple Vision...`);
  const keyframes = await ocrKeyframes(keyframesDir);
  const hits = keyframes.reduce((n, kf) => n + kf.ocr.length, 0);
  console.log(`[analyzer] ✓ ${hits} OCR boxes across ${keyframes.length} frames`);

  console.log(`[analyzer] freezedetect (noise=${spec.freeze?.noise ?? 0.003}, d=${spec.freeze?.minDurationSec ?? 2.5})`);
  const freezes = await detectFreezes(source, spec.freeze);
  if (freezes.length === 0) {
    console.log(`[analyzer] ✓ no freezes detected`);
  } else {
    for (const f of freezes) {
      console.log(`[analyzer] ⚠ freeze ${(f.startMs / 1000).toFixed(1)}s → ${(f.endMs / 1000).toFixed(1)}s (${(f.durationMs / 1000).toFixed(1)}s)`);
    }
  }

  return {
    sourceId: spec.id,
    publicPath: spec.publicPath,
    durationSec: meta.durationSec,
    width: meta.width,
    height: meta.height,
    keyframes,
    freezes,
  };
}

async function main() {
  ensureDir(ANALYSIS_DIR);
  ensureDir(KEYFRAME_CACHE);

  const filter = process.argv[2];
  const todo = filter ? SOURCES.filter((s) => s.id === filter) : SOURCES;
  if (todo.length === 0) {
    console.error(`[analyzer] no sources matched filter "${filter}"`);
    console.error(`[analyzer] available: ${SOURCES.map((s) => s.id).join(', ')}`);
    process.exit(2);
  }

  const index: Array<{ sourceId: string; analysisPath: string }> = [];
  for (const spec of todo) {
    const analysis = await analyseOne(spec);
    const out = join(ANALYSIS_DIR, `${spec.id}.json`);
    writeFileSync(out, JSON.stringify(analysis, null, 2));
    console.log(`[analyzer] → ${out}`);
    index.push({ sourceId: spec.id, analysisPath: `source-analysis/${spec.id}.json` });
  }

  const indexPath = join(ANALYSIS_DIR, 'index.json');
  let existing: typeof index = [];
  if (existsSync(indexPath)) {
    try {
      existing = JSON.parse(readFileSync(indexPath, 'utf-8')) as typeof index;
    } catch {
      existing = [];
    }
  }
  const merged = [...existing.filter((e) => !index.find((n) => n.sourceId === e.sourceId)), ...index];
  writeFileSync(indexPath, JSON.stringify(merged, null, 2));
  console.log(`\n[analyzer] index → ${indexPath}`);
}

main().catch((err) => {
  console.error('[analyzer] FAILED:', err);
  process.exit(1);
});
