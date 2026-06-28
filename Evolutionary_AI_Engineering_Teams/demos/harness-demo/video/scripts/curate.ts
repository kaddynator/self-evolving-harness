/**
 * Curator — picks the best clip range inside each source video for every
 * narration cue that carries `clipTags`.
 *
 * Inputs:
 *   - NARRATION cues (with clipTags) for each video scene
 *   - source-analysis/<sourceId>.json from the analyzer (keyframes + freezes)
 *   - the cue's spoken duration in ms (from the freshly probed WAV)
 *
 * Output (per cue): { sourceId, startMs, endMs } — the source-time window
 * to play behind that cue. The warm-voice script embeds this in
 * timeline.json so the multi-segment VideoScene can render
 * `<OffthreadVideo startFrom endAt>` per cue.
 *
 * Matching policy:
 *   1. Find every keyframe whose OCR text contains any of the cue's tags
 *      (case-insensitive substring match across the concatenated OCR text).
 *   2. Group hits into contiguous ranges (gap ≤ 4 s = same logical scene).
 *   3. Score each range by its **non-freeze duration** (so a long range
 *      mostly occupied by a stall loses to a shorter, fully-active range).
 *   4. Pick the highest-scoring range that's at least 60 % of the target
 *      length; if nothing qualifies, fall back to the longest range we have.
 *   5. Walk forward from the range's start, skipping freezes, to collect
 *      enough non-freeze seconds to cover the target. Return [startMs,
 *      endMs] of the walk (freezes inside the returned window will still
 *      play; OffthreadVideo's startFrom/endAt can only do contiguous spans).
 */
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import type { NarrationCue } from '../src/data/narration.ts';

const SAMPLE_INTERVAL_MS = 2000; // keyframes are sampled every 2 s
const GROUP_GAP_MS = 4000; // gap to consider two hits part of the same range
const LEAD_MS = 600; // padding before narration starts
const TAIL_MS = 400; // padding after narration ends
const MAX_FREEZE_RATIO = 0.25; // a candidate window with more than this freeze % is penalised

export interface Keyframe {
  frame: number;
  tMs: number;
  ocr: Array<{ text: string; conf: number; box: number[] }>;
}
export interface FreezeRange {
  startMs: number;
  endMs: number;
  durationMs: number;
}
export interface SourceAnalysis {
  sourceId: string;
  publicPath: string;
  durationSec: number;
  width: number;
  height: number;
  keyframes: Keyframe[];
  freezes: FreezeRange[];
}

export interface SourceClip {
  sourceId: string;
  publicPath: string;
  /** Inclusive start ms in the source. */
  startMs: number;
  /** Exclusive end ms in the source. */
  endMs: number;
  /** Diagnostic — what the curator thought it was matching. */
  matchedTag?: string;
  /** True if the curator had to fall back because no tag matched. */
  fellBack?: boolean;
}

/** Load the analyzer output for one source. Throws if missing. */
export function loadAnalysis(analysisDir: string, sourceId: string): SourceAnalysis {
  const p = join(analysisDir, `${sourceId}.json`);
  if (!existsSync(p)) {
    throw new Error(`[curate] missing analysis: ${p}. Run \`npm run analyze\` first.`);
  }
  return JSON.parse(readFileSync(p, 'utf-8')) as SourceAnalysis;
}

function ocrBlob(kf: Keyframe): string {
  return kf.ocr.map((b) => b.text).join(' ').toLowerCase();
}

interface Match {
  tagHit?: string;
  startMs: number;
  endMs: number;
  freezeMs: number;
}

function findMatchingRanges(
  keyframes: Keyframe[],
  tags: string[],
  freezes: FreezeRange[]
): Match[] {
  const tagsLower = tags.map((t) => t.toLowerCase());
  const ranges: Match[] = [];
  let cur: { startMs: number; lastMs: number; tagHit?: string } | null = null;

  for (const kf of keyframes) {
    const blob = ocrBlob(kf);
    const hit = tagsLower.find((t) => blob.includes(t));
    if (hit) {
      if (!cur) {
        cur = { startMs: kf.tMs, lastMs: kf.tMs, tagHit: hit };
      } else if (kf.tMs - cur.lastMs <= GROUP_GAP_MS + SAMPLE_INTERVAL_MS) {
        cur.lastMs = kf.tMs;
      } else {
        ranges.push(closeRange(cur, freezes));
        cur = { startMs: kf.tMs, lastMs: kf.tMs, tagHit: hit };
      }
    }
  }
  if (cur) ranges.push(closeRange(cur, freezes));
  return ranges;
}

function closeRange(
  cur: { startMs: number; lastMs: number; tagHit?: string },
  freezes: FreezeRange[]
): Match {
  const startMs = cur.startMs;
  const endMs = cur.lastMs + SAMPLE_INTERVAL_MS;
  return {
    startMs,
    endMs,
    tagHit: cur.tagHit,
    freezeMs: freezeOverlap(startMs, endMs, freezes),
  };
}

function freezeOverlap(startMs: number, endMs: number, freezes: FreezeRange[]): number {
  let total = 0;
  for (const f of freezes) {
    const lo = Math.max(startMs, f.startMs);
    const hi = Math.min(endMs, f.endMs);
    if (hi > lo) total += hi - lo;
  }
  return total;
}

export function curateCues(
  cues: NarrationCue[],
  analysis: SourceAnalysis,
  cueDurMs: Map<string, number>
): SourceClip[] {
  const out: SourceClip[] = [];
  const usedRanges: Array<{ startMs: number; endMs: number }> = [];
  const totalMs = Math.round(analysis.durationSec * 1000);

  for (const cue of cues) {
    const cueMs = cueDurMs.get(cue.cueId) ?? 5000;
    const wantedMs = cueMs + LEAD_MS + TAIL_MS;

    const matches = cue.clipTags && cue.clipTags.length > 0
      ? findMatchingRanges(analysis.keyframes, cue.clipTags, analysis.freezes)
      : [];

    const chosen = pickClip(matches, wantedMs, analysis, usedRanges, totalMs)
      ?? fallbackClip(wantedMs, analysis, usedRanges, totalMs);

    usedRanges.push({ startMs: chosen.startMs, endMs: chosen.endMs });
    out.push(chosen);
  }
  return out;
}

function scoreWindow(
  startMs: number,
  windowMs: number,
  freezes: FreezeRange[],
  usedRanges: Array<{ startMs: number; endMs: number }>,
  totalMs: number
): { freezeMs: number; reuseMs: number; valid: boolean } {
  const endMs = startMs + windowMs;
  if (endMs > totalMs) return { freezeMs: windowMs, reuseMs: windowMs, valid: false };
  const freezeMs = freezeOverlap(startMs, endMs, freezes);
  const reuseMs = usedRanges.reduce((sum, used) => {
    const lo = Math.max(startMs, used.startMs);
    const hi = Math.min(endMs, used.endMs);
    return sum + Math.max(0, hi - lo);
  }, 0);
  return { freezeMs, reuseMs, valid: true };
}

function pickClip(
  matches: Match[],
  windowMs: number,
  analysis: SourceAnalysis,
  usedRanges: Array<{ startMs: number; endMs: number }>,
  totalMs: number
): SourceClip | null {
  if (matches.length === 0) return null;

  let best: { score: number; startMs: number; tag?: string; fellBack: boolean } | null = null;

  for (const m of matches) {
    for (let s = m.startMs; s + windowMs <= m.endMs + SAMPLE_INTERVAL_MS; s += SAMPLE_INTERVAL_MS) {
      const score = scoreWindow(s, windowMs, analysis.freezes, usedRanges, totalMs);
      if (!score.valid) continue;
      const totalScore = score.freezeMs + score.reuseMs * 2;
      if (!best || totalScore < best.score) {
        best = { score: totalScore, startMs: s, tag: m.tagHit, fellBack: false };
      }
    }
  }

  if (!best) {
    const last = matches[matches.length - 1];
    const startMs = Math.max(0, Math.min(last.startMs, totalMs - windowMs));
    best = { score: 0, startMs, tag: last.tagHit, fellBack: true };
  }

  const score = scoreWindow(best.startMs, windowMs, analysis.freezes, usedRanges, totalMs);
  const heavilyFrozen = score.freezeMs / windowMs > MAX_FREEZE_RATIO;

  return {
    sourceId: analysis.sourceId,
    publicPath: analysis.publicPath,
    startMs: best.startMs,
    endMs: best.startMs + windowMs,
    matchedTag: best.tag,
    fellBack: best.fellBack || heavilyFrozen,
  };
}

function fallbackClip(
  windowMs: number,
  analysis: SourceAnalysis,
  usedRanges: Array<{ startMs: number; endMs: number }>,
  totalMs: number
): SourceClip {
  let bestStart = 0;
  let bestScore = Infinity;
  for (let s = 0; s + windowMs <= totalMs; s += SAMPLE_INTERVAL_MS) {
    const score = scoreWindow(s, windowMs, analysis.freezes, usedRanges, totalMs);
    if (!score.valid) continue;
    const totalScore = score.freezeMs + score.reuseMs * 2;
    if (totalScore < bestScore) {
      bestScore = totalScore;
      bestStart = s;
    }
  }
  return {
    sourceId: analysis.sourceId,
    publicPath: analysis.publicPath,
    startMs: bestStart,
    endMs: bestStart + windowMs,
    fellBack: true,
  };
}
