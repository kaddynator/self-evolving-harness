import React from 'react';
import { AbsoluteFill, interpolate, useCurrentFrame } from 'remotion';

interface Props {
  text: string;
  /** Frames the cue plays for; used to compute the fade-out timing. */
  durationFrames: number;
}

const FADE_FRAMES = 6;

/**
 * YouTube-CC-style subtitle bar. Placed inside a <Sequence> sized to the cue
 * so it appears at the cue's startFrame and vanishes when the audio ends.
 *
 * Disabled by default in the bundled composition; re-enable by reinstating
 * the <Sequence>/<Subtitle> block in your <Composition>.tsx.
 */
export const Subtitle: React.FC<Props> = ({ text, durationFrames }) => {
  const frame = useCurrentFrame();
  const fadeIn = interpolate(frame, [0, FADE_FRAMES], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const fadeOut = interpolate(
    frame,
    [durationFrames - FADE_FRAMES, durationFrames],
    [1, 0],
    { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
  );
  const opacity = Math.min(fadeIn, fadeOut);
  const y = interpolate(frame, [0, FADE_FRAMES], [8, 0], {
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill
      style={{
        pointerEvents: 'none',
        display: 'flex',
        alignItems: 'flex-end',
        justifyContent: 'center',
        paddingBottom: 56,
      }}
    >
      <div
        style={{
          maxWidth: 1280,
          padding: '12px 26px',
          background: 'rgba(8, 6, 20, 0.78)',
          color: '#fff',
          fontSize: 28,
          fontWeight: 500,
          lineHeight: 1.4,
          borderRadius: 6,
          textAlign: 'center',
          opacity,
          transform: `translateY(${y}px)`,
          fontFamily:
            'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        }}
      >
        {text}
      </div>
    </AbsoluteFill>
  );
};
