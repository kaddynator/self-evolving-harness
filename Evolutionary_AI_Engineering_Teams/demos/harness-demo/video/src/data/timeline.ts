/**
 * Reads the build-time timeline.json (emitted by scripts/warm-voice.ts) and
 * converts it into Remotion-friendly frame offsets.
 *
 * timeline.json is regenerated whenever narration text changes; the totals
 * here drive Composition.durationInFrames so re-running `voice:warm` is the
 * only step needed to retime the whole video after editing narration.
 */
import timelineJson from './timeline.json';
import type { SceneId } from './narration';

export const FPS = 30;

export interface TimelineCue {
  cueId: string;
  scene: SceneId;
  text: string;
  startFrame: number;
  durationFrames: number;
  wavPath: string;
  /** Curator-picked source clip window (video scenes only). */
  sourceClip?: {
    sourceId: string;
    publicPath: string;
    startMs: number;
    endMs: number;
    matchedTag?: string;
    fellBack?: boolean;
  };
}

export interface TimelineScene {
  scene: SceneId;
  startFrame: number;
  durationFrames: number;
  /** Set if this scene plays a curated source video. */
  sourceId?: string;
  cues: TimelineCue[];
}

export interface TimelineMusicTrack {
  trackPath: string;
  startFrame: number;
  durationFrames: number;
  fadeInFrames: number;
  fadeOutFrames: number;
  volume: number;
}

export interface Timeline {
  fps: number;
  totalFrames: number;
  scenes: TimelineScene[];
  music: TimelineMusicTrack | null;
}

export const TIMELINE: Timeline = timelineJson as unknown as Timeline;

export function findScene(scene: SceneId): TimelineScene | undefined {
  return TIMELINE.scenes.find((s) => s.scene === scene);
}

export const msToFrames = (ms: number, fps = FPS) => Math.round((ms * fps) / 1000);
