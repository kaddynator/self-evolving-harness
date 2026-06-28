/**
 * Build-time TTS + timeline generator.
 *
 * 1. Synthesises one WAV per unique narration cue using Kokoro-JS, writing
 *    them to demo-root/video/public/tts/{md5}.wav (idempotent).
 * 2. Probes each WAV duration with ffprobe.
 * 3. Probes the source MP4s so video-scene durations can match.
 * 4. Emits demo-root/video/src/data/timeline.json, which the Remotion root
 *    imports to size the composition.
 *
 * Re-run any time narration.ts changes (or whenever the source MP4s are
 * swapped for higher-quality versions). Cached WAVs are kept untouched.
 *
 * CUSTOMISE the SCENE_SOURCE map, sceneSpecs ordering, and *_MIN_HOLD_MS
 * constants to fit your demo's pacing.
 */
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execa } from 'execa';
import { NARRATION, type NarrationCue, type SceneId } from '../src/data/narration.ts';
import { curateCues, loadAnalysis, type SourceClip } from './curate.ts';

const here = dirname(fileURLToPath(import.meta.url));
const PKG_ROOT = resolve(here, '..');
const PUBLIC_DIR = resolve(PKG_ROOT, 'public');
const TTS_DIR = join(PUBLIC_DIR, 'tts');
const TIMELINE_OUT = resolve(PKG_ROOT, 'src', 'data', 'timeline.json');
const ANALYSIS_DIR = resolve(PKG_ROOT, 'src', 'data', 'source-analysis');

// ───── CUSTOMISE: hero + music paths (must match prepare.ts dest paths) ──
const HERO_VIDEO = join(PUBLIC_DIR, 'hero', 'harness-hero.mp4');
const MUSIC_PRIMARY = join(PUBLIC_DIR, 'music', 'outro-1.m4a');
const MUSIC_FALLBACK = join(PUBLIC_DIR, 'music', 'outro-2.m4a');

// ───── CUSTOMISE: which analyzed source mp4 powers each video scene ──────
const SCENE_SOURCE: Partial<Record<SceneId, string>> = {
  'product-demo': 'harness-demo',
};

const FPS = 30;
const VOICE = process.env.AICG_VOICE_ID ?? 'af_heart';
const SPEED = parseFloat(process.env.AICG_VOICE_SPEED ?? '1');

// ───── CUSTOMISE: pacing (ms) — tweak per scene as needed ────────────────
const SCENE_LEAD_IN_MS = 900;
const SCENE_TAIL_MS = 700;
const CUE_BREATH_MS = 280;

const HERO_MIN_HOLD_MS = 1_400;
const WHAT_IS_MIN_HOLD_MS = 1_400;
const ARCH_MIN_HOLD_MS = 8_500;
const SECTION_MIN_HOLD_MS = 1_000;
const OUTRO_MIN_HOLD_MS = 9_500;

const OUTRO_FADE_IN_FRAMES = 36;
const OUTRO_FADE_OUT_FRAMES = 66;
const OUTRO_VOLUME = 0.6;

interface CueAudio {
  cueId: string;
  scene: SceneId;
  text: string;
  hash: string;
  durationMs: number;
  publicPath: string;
}

function voiceHash(text: string): string {
  return createHash('md5').update(`${VOICE}:${text}`).digest('hex');
}

async function probeDuration(file: string): Promise<number> {
  const { stdout } = await execa('ffprobe', [
    '-v', 'error',
    '-show_entries', 'format=duration',
    '-of', 'default=noprint_wrappers=1:nokey=1',
    file,
  ]);
  return parseFloat(stdout.trim());
}

async function probeOptional(file: string): Promise<number | null> {
  if (!existsSync(file)) return null;
  return probeDuration(file);
}

async function synthesizeMissing(cues: NarrationCue[]): Promise<void> {
  if (!existsSync(TTS_DIR)) mkdirSync(TTS_DIR, { recursive: true });

  const pending = cues.filter((cue) => {
    const wav = join(TTS_DIR, `${voiceHash(cue.text)}.wav`);
    return !existsSync(wav);
  });

  if (pending.length === 0) {
    console.log(`[voice] all ${cues.length} cues already cached.`);
    return;
  }
  console.log(
    `[voice] generating ${pending.length}/${cues.length} cues with Kokoro-82M (q8, CPU)...`
  );

  const { KokoroTTS } = await import('kokoro-js');
  const tts = await KokoroTTS.from_pretrained('onnx-community/Kokoro-82M-v1.0-ONNX', {
    dtype: 'q8',
    device: 'cpu',
  });

  let i = 0;
  for (const cue of pending) {
    i++;
    const audio = await tts.generate(cue.text, { voice: VOICE, speed: SPEED });
    const wav = join(TTS_DIR, `${voiceHash(cue.text)}.wav`);
    audio.save(wav);
    console.log(`[voice] [${i}/${pending.length}] ${cue.text.slice(0, 60)}…`);
  }
}

async function loadCueAudio(): Promise<CueAudio[]> {
  const out: CueAudio[] = [];
  for (const cue of NARRATION) {
    const hash = voiceHash(cue.text);
    const wav = join(TTS_DIR, `${hash}.wav`);
    if (!existsSync(wav)) {
      throw new Error(`[voice] missing WAV after synthesis: ${wav}`);
    }
    const dur = await probeDuration(wav);
    out.push({
      cueId: cue.cueId,
      scene: cue.scene,
      text: cue.text,
      hash,
      durationMs: Math.round(dur * 1000),
      publicPath: `tts/${hash}.wav`,
    });
  }
  return out;
}

const msToFrames = (ms: number) => Math.round((ms * FPS) / 1000);
const msFromFrames = (frames: number) => Math.round((frames * 1000) / FPS);

interface ScenePlan {
  scene: SceneId;
  startFrame: number;
  durationFrames: number;
  sourceId?: string;
  cues: Array<{
    cueId: string;
    scene: SceneId;
    text: string;
    startFrame: number;
    durationFrames: number;
    wavPath: string;
    sourceClip?: SourceClip;
  }>;
}

interface MusicPlan {
  trackPath: string;
  startFrame: number;
  durationFrames: number;
  fadeInFrames: number;
  fadeOutFrames: number;
  volume: number;
}

interface TimelineJson {
  fps: number;
  voice: string;
  speed: number;
  totalFrames: number;
  scenes: ScenePlan[];
  music: MusicPlan | null;
}

function planScene(
  scene: SceneId,
  cuesForScene: CueAudio[],
  opts: { minHoldMs?: number } = {}
): { durationMs: number; cuePlans: ScenePlan['cues'] } {
  const leadIn = SCENE_LEAD_IN_MS;
  const tail = SCENE_TAIL_MS;

  let cursor = leadIn;
  const cuePlans: ScenePlan['cues'] = [];
  for (let i = 0; i < cuesForScene.length; i++) {
    const c = cuesForScene[i];
    cuePlans.push({
      cueId: c.cueId,
      scene: c.scene,
      text: c.text,
      startFrame: msToFrames(cursor),
      durationFrames: msToFrames(c.durationMs),
      wavPath: c.publicPath,
    });
    cursor += c.durationMs;
    if (i < cuesForScene.length - 1) cursor += CUE_BREATH_MS;
  }
  const narrationEnd = cursor;

  const minHold = opts.minHoldMs ?? 0;
  const durationMs = Math.max(narrationEnd + tail, leadIn + minHold + tail);
  return { durationMs, cuePlans };
}

async function buildTimeline(audio: CueAudio[]): Promise<TimelineJson> {
  const heroDurS = await probeOptional(HERO_VIDEO);
  if (heroDurS) {
    console.log(`[plan] hero loop = ${heroDurS.toFixed(1)}s (will loop)`);
  }

  const cuesByScene = (id: SceneId) => audio.filter((c) => c.scene === id);

  // ───── CUSTOMISE: scene ordering + per-scene minHoldMs ─────────────────
  const sceneSpecs: Array<{ id: SceneId; opts: { minHoldMs?: number } }> = [
    { id: 'hero' as SceneId,         opts: { minHoldMs: HERO_MIN_HOLD_MS } },
    { id: 'problem' as SceneId,      opts: { minHoldMs: WHAT_IS_MIN_HOLD_MS } },
    { id: 'product-demo' as SceneId, opts: {} },
    { id: 'feedback' as SceneId,     opts: { minHoldMs: WHAT_IS_MIN_HOLD_MS } },
    { id: 'tech-stack' as SceneId,   opts: { minHoldMs: WHAT_IS_MIN_HOLD_MS } },
    { id: 'outro' as SceneId,        opts: { minHoldMs: OUTRO_MIN_HOLD_MS } },
  ];

  const scenes: ScenePlan[] = [];
  let cursorFrames = 0;
  for (const spec of sceneSpecs) {
    const plan = planScene(spec.id, cuesByScene(spec.id), spec.opts);
    const durationFrames = msToFrames(plan.durationMs);
    const startFrame = cursorFrames;
    const sourceId = SCENE_SOURCE[spec.id];
    const cues = plan.cuePlans.map((c) => ({
      ...c,
      startFrame: startFrame + c.startFrame,
    }));

    if (sourceId) {
      try {
        const analysis = loadAnalysis(ANALYSIS_DIR, sourceId);
        const sceneCues = NARRATION.filter((n) => n.scene === spec.id);
        const cueDurMs = new Map(plan.cuePlans.map((c) => [c.cueId, msFromFrames(c.durationFrames)]));
        const clips = curateCues(sceneCues, analysis, cueDurMs);
        for (let i = 0; i < cues.length; i++) {
          cues[i].sourceClip = clips[i];
        }
        console.log(`\n[curate] ${spec.id} ← ${sourceId} (${analysis.keyframes.length} keyframes, ${analysis.freezes.length} freezes)`);
        for (const clip of clips) {
          const span = ((clip.endMs - clip.startMs) / 1000).toFixed(1);
          const tag = clip.matchedTag ? `tag="${clip.matchedTag}"` : 'tag=∅';
          const fb = clip.fellBack ? ' ⚠ fallback' : '';
          console.log(`[curate]   ${clip.startMs}ms→${clip.endMs}ms  (${span}s)  ${tag}${fb}`);
        }
      } catch (err: any) {
        console.warn(`[curate] ${spec.id}: ${err.message}`);
      }
    }

    scenes.push({
      scene: spec.id,
      startFrame,
      durationFrames,
      sourceId,
      cues,
    });
    cursorFrames += durationFrames;
  }
  const totalFrames = cursorFrames;

  let musicTrack: MusicPlan | null = null;
  const musicSrc = existsSync(MUSIC_PRIMARY)
    ? MUSIC_PRIMARY
    : existsSync(MUSIC_FALLBACK)
      ? MUSIC_FALLBACK
      : null;
  if (musicSrc) {
    const outroScene = scenes.find((s) => s.scene === 'outro')!;
    const trackPath = musicSrc === MUSIC_PRIMARY
      ? `music/${MUSIC_PRIMARY.split('/').pop()}`
      : `music/${MUSIC_FALLBACK.split('/').pop()}`;
    const musicStart = outroScene.startFrame;
    const musicDuration = outroScene.durationFrames;
    musicTrack = {
      trackPath,
      startFrame: musicStart,
      durationFrames: musicDuration,
      fadeInFrames: OUTRO_FADE_IN_FRAMES,
      fadeOutFrames: OUTRO_FADE_OUT_FRAMES,
      volume: OUTRO_VOLUME,
    };
  } else {
    console.warn('[plan] no outro music available; rendering silent ending');
  }

  return {
    fps: FPS,
    voice: VOICE,
    speed: SPEED,
    totalFrames,
    scenes,
    music: musicTrack,
  };
}

function summarise(t: TimelineJson) {
  console.log('────────────────────────────────────────────────────────');
  console.log(`demo timeline — ${(t.totalFrames / FPS).toFixed(1)}s @ ${FPS}fps`);
  for (const s of t.scenes) {
    console.log(
      `  ${(s.startFrame / FPS).toFixed(1).padStart(6)}s  ${s.scene.padEnd(18)} ${(s.durationFrames / FPS).toFixed(1)}s · ${s.cues.length} cue(s)`
    );
  }
  if (t.music) {
    console.log(
      `  ${(t.music.startFrame / FPS).toFixed(1).padStart(6)}s  music (${t.music.trackPath}) ${(t.music.durationFrames / FPS).toFixed(1)}s`
    );
  }
  console.log('────────────────────────────────────────────────────────');
}

async function main() {
  console.log(`[voice] cache dir = ${TTS_DIR}`);
  console.log(`[voice] voice    = ${VOICE}, speed = ${SPEED}`);

  await synthesizeMissing(NARRATION);
  const audio = await loadCueAudio();
  const timeline = await buildTimeline(audio);
  summarise(timeline);

  writeFileSync(TIMELINE_OUT, JSON.stringify(timeline, null, 2));
  console.log(`[voice] timeline → ${TIMELINE_OUT}`);
}

main().catch((err) => {
  console.error('[voice] FAILED:', err);
  process.exit(1);
});
