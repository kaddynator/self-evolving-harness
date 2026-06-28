import React, { ReactNode } from 'react';
import { AbsoluteFill, useCurrentFrame } from 'remotion';

interface Props {
  children: ReactNode;
  /** Default off — modern enterprise visuals look better with a clean grain-only surface. */
  withParticles?: boolean;
  /** Optional override for the base colour. */
  background?: string;
}

/**
 * Premium dark surface used by every non-hero scene.
 *
 * Design intent: McKinsey / Stripe Sessions / Apple-keynote feel.
 *   1. Near-black slate base (#06070e) — colder + deeper than ink-900.
 *   2. Two very-low-opacity aurora spotlights (top-left indigo, bottom-right violet).
 *   3. Hairline grid masked by a centre vignette — present but subtle.
 *   4. SVG fractal-noise film grain (~7% opacity, overlay blend) for cinematic feel.
 *   5. Soft vignette at the edges so the eye lands in the middle.
 *
 * Particles off by default; pass `withParticles` only on scenes that benefit
 * from atmosphere (e.g. the outro fade).
 */

const FILM_GRAIN_DATA_URI =
  "url(\"data:image/svg+xml;utf8,%3Csvg xmlns%3D'http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg' width%3D'160' height%3D'160' viewBox%3D'0 0 160 160'%3E%3Cfilter id%3D'n'%3E%3CfeTurbulence type%3D'fractalNoise' baseFrequency%3D'0.9' numOctaves%3D'2' stitchTiles%3D'stitch'%2F%3E%3CfeColorMatrix values%3D'0 0 0 0 1 0 0 0 0 1 0 0 0 0 1 0 0 0 0.55 0'%2F%3E%3C%2Ffilter%3E%3Crect width%3D'100%25' height%3D'100%25' filter%3D'url(%23n)'%2F%3E%3C%2Fsvg%3E\")";

const PARTICLES = Array.from({ length: 18 }, (_, i) => ({
  id: i,
  left: (i * 137.5) % 100,
  delay: (i * 71) % 80,
  duration: 280 + ((i * 91) % 240),
  size: 1.5 + (i % 3),
}));

export const SceneShell: React.FC<Props> = ({
  children,
  withParticles = false,
  background,
}) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill
      style={{
        background: background ?? '#06070e',
        overflow: 'hidden',
      }}
    >
      {/* L1 — soft aurora spotlights */}
      <AbsoluteFill
        style={{
          background:
            'radial-gradient(ellipse 55% 38% at 18% 22%, rgba(99,102,241,0.075) 0%, transparent 70%), ' +
            'radial-gradient(ellipse 50% 32% at 82% 78%, rgba(168,85,247,0.055) 0%, transparent 70%)',
          pointerEvents: 'none',
        }}
      />

      {/* L2 — hairline grid, masked to the centre */}
      <AbsoluteFill
        style={{
          backgroundImage:
            'linear-gradient(rgba(255,255,255,0.015) 1px, transparent 1px), ' +
            'linear-gradient(90deg, rgba(255,255,255,0.015) 1px, transparent 1px)',
          backgroundSize: '120px 120px',
          maskImage: 'radial-gradient(ellipse 80% 70% at center, #000 35%, transparent 85%)',
          WebkitMaskImage: 'radial-gradient(ellipse 80% 70% at center, #000 35%, transparent 85%)',
          pointerEvents: 'none',
        }}
      />

      {/* L3 — optional drifting particles */}
      {withParticles && (
        <AbsoluteFill style={{ pointerEvents: 'none' }}>
          {PARTICLES.map((p) => {
            const cycle = (frame - p.delay) % p.duration;
            if (cycle < 0) return null;
            const progress = cycle / p.duration;
            const opacity =
              progress < 0.1
                ? progress * 6
                : progress > 0.9
                  ? (1 - progress) * 6
                  : 0.55;
            const y = 1080 - 1080 * progress;
            const x = p.left + progress * 5;
            return (
              <div
                key={p.id}
                style={{
                  position: 'absolute',
                  left: `${x}%`,
                  top: y,
                  width: p.size,
                  height: p.size,
                  borderRadius: '50%',
                  background: 'rgba(199,210,254,0.55)',
                  opacity,
                  filter: 'blur(0.5px)',
                }}
              />
            );
          })}
        </AbsoluteFill>
      )}

      {/* L4 — content */}
      <AbsoluteFill>{children}</AbsoluteFill>

      {/* L5 — film grain over content */}
      <AbsoluteFill
        style={{
          backgroundImage: FILM_GRAIN_DATA_URI,
          backgroundSize: '160px 160px',
          opacity: 0.07,
          mixBlendMode: 'overlay',
          pointerEvents: 'none',
        }}
      />

      {/* L6 — corner vignette */}
      <AbsoluteFill
        style={{
          background:
            'radial-gradient(ellipse 95% 90% at center, transparent 50%, rgba(0,0,0,0.55) 100%)',
          pointerEvents: 'none',
        }}
      />
    </AbsoluteFill>
  );
};
