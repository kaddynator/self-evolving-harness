import React from 'react';
import {
  AbsoluteFill,
  OffthreadVideo,
  Sequence,
  interpolate,
  staticFile,
  useCurrentFrame,
} from 'remotion';
import { BrandMark } from '../components/BrandMark';
import { FPS, type TimelineCue } from '../data/timeline';

interface Props {
  label: string;
  eyebrow?: string;
  /** Curated cues for this scene (each carries its own sourceClip). */
  cues: TimelineCue[];
  /** Composition-absolute frame where the parent Sequence starts. */
  sceneStartFrame: number;
  /** Total frames this scene holds. */
  totalFramesInScene: number;
}

const msToFrames = (ms: number) => Math.round((ms * FPS) / 1000);

/** Frames of opacity crossfade at each clip boundary — kills the "black flash"
 *  adjacent OffthreadVideo Sequences would otherwise produce when they hard-cut. */
const CROSSFADE_FRAMES = 9;

/**
 * Background video for a "video" scene. Renders a back-to-back sequence of
 * <OffthreadVideo> sub-clips — one per narration cue — each trimmed to the
 * curator-selected source range and stretched (via playbackRate) to fit the
 * cue's spoken duration. Adjacent clips overlap by CROSSFADE_FRAMES on both
 * sides and fade their opacity, so the cut between segments is smooth.
 *
 * FROZEN: do not rewrite. The crossfade + playbackRate logic took multiple
 * iterations to get right.
 */
export const VideoScene: React.FC<Props> = ({
  label,
  eyebrow,
  cues,
  sceneStartFrame,
  totalFramesInScene,
}) => {
  const frame = useCurrentFrame();
  const badgeOp = interpolate(frame, [0, 18], [0, 1], { extrapolateRight: 'clamp' });
  const badgeX = interpolate(frame, [0, 22], [-20, 0], { extrapolateRight: 'clamp' });
  const progress = interpolate(frame, [0, totalFramesInScene], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill style={{ background: '#000' }}>
      {cues.map((cue, idx) => {
        const clip = cue.sourceClip;
        if (!clip) return null;
        const baseFrom = cue.startFrame - sceneStartFrame;
        const isFirst = idx === 0;
        const isLast = idx === cues.length - 1;
        const leadFade = isFirst ? 0 : CROSSFADE_FRAMES;
        const tailFade = isLast ? 0 : CROSSFADE_FRAMES;
        const localFrom = Math.max(0, baseFrom - leadFade);
        const segDuration = cue.durationFrames + leadFade + tailFade;

        const clipDurationMs = clip.endMs - clip.startMs;
        const cueDurationMs = (cue.durationFrames / FPS) * 1000;
        const playbackRate =
          clipDurationMs > 0 && cueDurationMs > 0
            ? clipDurationMs / cueDurationMs
            : 1;

        return (
          <Sequence
            key={`vc-${cue.cueId}`}
            from={localFrom}
            durationInFrames={segDuration}
            name={`clip:${cue.cueId}`}
          >
            <ClipLayer
              src={staticFile(clip.publicPath)}
              startFrom={msToFrames(clip.startMs)}
              endAt={msToFrames(clip.endMs)}
              playbackRate={playbackRate}
              leadFade={leadFade}
              tailFade={tailFade}
              durationFrames={segDuration}
            />
          </Sequence>
        );
      })}

      {/* Vignette */}
      <AbsoluteFill
        style={{
          background:
            'radial-gradient(ellipse at center, transparent 65%, rgba(0,0,0,0.55) 100%)',
          pointerEvents: 'none',
        }}
      />

      {/* Bottom-left badge */}
      <div
        style={{
          position: 'absolute',
          left: 56,
          bottom: 56,
          display: 'flex',
          alignItems: 'center',
          gap: 18,
          padding: '14px 22px',
          borderRadius: 18,
          border: '1px solid rgba(255,255,255,0.1)',
          background: 'rgba(0,0,0,0.55)',
          backdropFilter: 'blur(10px)',
          opacity: badgeOp,
          transform: `translateX(${badgeX}px)`,
        }}
      >
        <BrandMark size={28} />
        <div style={{ width: 1, height: 32, background: 'rgba(255,255,255,0.15)' }} />
        <div>
          {eyebrow && (
            <div
              style={{
                marginBottom: 2,
                fontSize: 10,
                letterSpacing: '3px',
                textTransform: 'uppercase',
                color: 'rgba(165,180,252,0.85)',
              }}
            >
              {eyebrow}
            </div>
          )}
          <div style={{ fontSize: 18, fontWeight: 700, color: '#fff' }}>{label}</div>
        </div>
      </div>

      {/* Progress bar */}
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          bottom: 0,
          height: 4,
          background: 'rgba(255,255,255,0.1)',
        }}
      >
        <div
          style={{
            width: `${progress * 100}%`,
            height: '100%',
            background: 'linear-gradient(90deg, #6366f1, #a855f7)',
          }}
        />
      </div>
    </AbsoluteFill>
  );
};

interface ClipLayerProps {
  src: string;
  startFrom: number;
  endAt: number;
  playbackRate: number;
  leadFade: number;
  tailFade: number;
  durationFrames: number;
}

const ClipLayer: React.FC<ClipLayerProps> = ({
  src,
  startFrom,
  endAt,
  playbackRate,
  leadFade,
  tailFade,
  durationFrames,
}) => {
  const frame = useCurrentFrame();
  const fadeIn = leadFade > 0
    ? interpolate(frame, [0, leadFade], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' })
    : 1;
  const fadeOut = tailFade > 0
    ? interpolate(
        frame,
        [durationFrames - tailFade, durationFrames],
        [1, 0],
        { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
      )
    : 1;
  const opacity = Math.min(fadeIn, fadeOut);
  return (
    <AbsoluteFill style={{ opacity }}>
      <OffthreadVideo
        src={src}
        startFrom={startFrom}
        endAt={endAt}
        playbackRate={playbackRate}
        muted
        style={{ width: '100%', height: '100%', objectFit: 'contain' }}
      />
    </AbsoluteFill>
  );
};
