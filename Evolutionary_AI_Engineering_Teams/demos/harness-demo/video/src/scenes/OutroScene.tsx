import React from 'react';
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from 'remotion';
import { BrandMark } from '../components/BrandMark';

/**
 * Cinematic outro — brand reveal.
 *
 * Layered composition:
 *   1. Deep cosmos-blue base (#03050e)
 *   2. Drifting mesh-gradient spotlights (very low opacity)
 *   3. SVG god-ray fan rotating slowly behind the brand mark
 *   4. Ascending particle field
 *   5. Brand mark + wordmark mask-reveal + editorial rule + tagline
 *   6. Footer credits
 *   7. SVG film grain overlay
 *   8. Scene-wide slow zoom-out + final fade-to-black on the last second
 *
 * CUSTOMISE:
 *   - Swap the wordmark for your product (the Cosmos.AI example below is a
 *     placeholder).
 *   - Adjust the colour palette to your brand (the cosmos-blue scheme works
 *     for most enterprise products; swap for your accent if needed).
 */

const FILM_GRAIN_DATA_URI =
  "url(\"data:image/svg+xml;utf8,%3Csvg xmlns%3D'http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg' width%3D'160' height%3D'160' viewBox%3D'0 0 160 160'%3E%3Cfilter id%3D'n'%3E%3CfeTurbulence type%3D'fractalNoise' baseFrequency%3D'0.9' numOctaves%3D'2' stitchTiles%3D'stitch'%2F%3E%3CfeColorMatrix values%3D'0 0 0 0 1 0 0 0 0 1 0 0 0 0 1 0 0 0 0.55 0'%2F%3E%3C%2Ffilter%3E%3Crect width%3D'100%25' height%3D'100%25' filter%3D'url(%23n)'%2F%3E%3C%2Fsvg%3E\")";

const PARTICLES = Array.from({ length: 36 }, (_, i) => ({
  id: i,
  leftPct: (i * 137.5) % 100,
  delay: (i * 23) % 320,
  duration: 360 + ((i * 71) % 220),
  size: 1.5 + (i % 4) * 0.6,
  color: ['#5fcdfe', '#008cff', '#a5b4fc'][i % 3],
}));

const RAY_COUNT = 14;

export const OutroScene: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();

  const bgOp = interpolate(frame, [0, 30], [0, 1], { extrapolateRight: 'clamp' });
  const raysOp = interpolate(frame, [10, 60], [0, 0.55], { extrapolateRight: 'clamp' });
  const wordmarkOp = interpolate(frame, [76, 110], [0, 1], { extrapolateRight: 'clamp' });
  const wordmarkY = interpolate(frame, [76, 110], [16, 0], { extrapolateRight: 'clamp' });
  const ruleOp = interpolate(frame, [108, 140], [0, 1], { extrapolateRight: 'clamp' });
  const ruleScale = interpolate(frame, [108, 150], [0, 1], { extrapolateRight: 'clamp' });
  const taglineOp = interpolate(frame, [140, 178], [0, 1], { extrapolateRight: 'clamp' });
  const taglineY = interpolate(frame, [140, 178], [14, 0], { extrapolateRight: 'clamp' });
  const footerOp = interpolate(frame, [200, 250], [0, 0.85], { extrapolateRight: 'clamp' });

  const sceneScale = interpolate(frame, [0, durationInFrames], [1.04, 1.0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const rayRotation = (frame * 0.18) % 360;

  const fadeStart = Math.max(0, durationInFrames - fps);
  const blackOp = interpolate(frame, [fadeStart, durationInFrames], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill style={{ background: '#03050e', overflow: 'hidden' }}>
      {/* L1: drifting mesh-gradient spotlights */}
      <AbsoluteFill
        style={{
          opacity: bgOp,
          background: [
            'radial-gradient(ellipse 60% 50% at 50% 78%, rgba(0,140,255,0.16) 0%, transparent 65%)',
            'radial-gradient(ellipse 50% 38% at 18% 22%, rgba(0,41,146,0.30) 0%, transparent 70%)',
            'radial-gradient(ellipse 45% 36% at 82% 28%, rgba(95,205,254,0.10) 0%, transparent 70%)',
            'radial-gradient(ellipse 45% 35% at 22% 82%, rgba(0,41,146,0.18) 0%, transparent 70%)',
          ].join(', '),
        }}
      />

      {/* L2: SVG god-ray fan */}
      <AbsoluteFill style={{ opacity: raysOp, pointerEvents: 'none' }}>
        <svg width={1920} height={1080} viewBox="0 0 1920 1080">
          <defs>
            <linearGradient id="rayGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="rgba(165,180,252,0.0)" />
              <stop offset="40%" stopColor="rgba(0,140,255,0.18)" />
              <stop offset="100%" stopColor="rgba(95,205,254,0.0)" />
            </linearGradient>
          </defs>
          <g transform={`translate(960 486) rotate(${rayRotation})`}>
            {Array.from({ length: RAY_COUNT }).map((_, i) => {
              const angle = (i * 360) / RAY_COUNT;
              return (
                <g key={i} transform={`rotate(${angle})`}>
                  <polygon points="-60,-1000 60,-1000 0,0" fill="url(#rayGrad)" opacity={0.45} />
                </g>
              );
            })}
          </g>
        </svg>
      </AbsoluteFill>

      {/* L3: ascending particle field */}
      <AbsoluteFill style={{ opacity: bgOp, pointerEvents: 'none' }}>
        {PARTICLES.map((p) => {
          const cycle = (frame - p.delay) % p.duration;
          if (cycle < 0) return null;
          const progress = cycle / p.duration;
          const opacity =
            progress < 0.15 ? progress * 5 : progress > 0.85 ? (1 - progress) * 5 : 0.7;
          const y = 1080 - 1080 * progress;
          return (
            <div
              key={p.id}
              style={{
                position: 'absolute',
                left: `${p.leftPct}%`,
                top: y,
                width: p.size,
                height: p.size,
                borderRadius: '50%',
                background: p.color,
                opacity,
                boxShadow: `0 0 ${4 + p.size * 2}px ${p.color}`,
              }}
            />
          );
        })}
      </AbsoluteFill>

      {/* L4: brand stage */}
      <AbsoluteFill
        style={{
          transform: `scale(${sceneScale})`,
          transformOrigin: 'center',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        {/* CUSTOMISE: replace with your product's wordmark/logo */}
        <div
          style={{
            opacity: wordmarkOp,
            transform: `translateY(${wordmarkY}px)`,
            fontSize: 132,
            fontWeight: 800,
            letterSpacing: '-0.04em',
            lineHeight: 1,
            color: '#fff',
            textShadow: '0 8px 40px rgba(0,140,255,0.25)',
            display: 'flex',
            alignItems: 'baseline',
          }}
        >
          <BrandMark size={132} />
        </div>

        <div
          style={{
            marginTop: 36,
            width: 360,
            height: 1,
            background:
              'linear-gradient(90deg, transparent 0%, rgba(95,205,254,0.55) 50%, transparent 100%)',
            opacity: ruleOp,
            transform: `scaleX(${ruleScale})`,
            transformOrigin: 'center',
          }}
        />

        <div
          style={{
            opacity: taglineOp,
            transform: `translateY(${taglineY}px)`,
            marginTop: 28,
            fontSize: 22,
            color: 'rgba(255,255,255,0.78)',
            fontWeight: 400,
            letterSpacing: '0.02em',
            textAlign: 'center',
          }}
        >
          The next frontier in AI — <span style={{ color: '#fff', fontWeight: 600 }}>self-evolving agent teams.</span>
        </div>

        <div
          style={{
            position: 'absolute',
            bottom: 80,
            opacity: footerOp,
            display: 'flex',
            alignItems: 'center',
            gap: 14,
            fontSize: 12,
            letterSpacing: '4px',
            color: 'rgba(255,255,255,0.45)',
            fontWeight: 600,
            textTransform: 'uppercase',
          }}
        >
          <span style={{ width: 48, height: 1, background: 'rgba(255,255,255,0.18)' }} />
          <span>EVOLUTIONARY AI HARNESS</span>
          <span style={{ color: 'rgba(255,255,255,0.25)' }}>·</span>
          <span>2026</span>
          <span style={{ width: 48, height: 1, background: 'rgba(255,255,255,0.18)' }} />
        </div>
      </AbsoluteFill>

      {/* L5: film grain overlay */}
      <AbsoluteFill
        style={{
          backgroundImage: FILM_GRAIN_DATA_URI,
          backgroundSize: '160px 160px',
          opacity: 0.075,
          mixBlendMode: 'overlay',
          pointerEvents: 'none',
        }}
      />

      {/* L6: corner vignette */}
      <AbsoluteFill
        style={{
          background:
            'radial-gradient(ellipse 95% 90% at center, transparent 50%, rgba(0,0,0,0.65) 100%)',
          pointerEvents: 'none',
        }}
      />

      {/* L7: final fade-to-black */}
      <AbsoluteFill style={{ background: '#000', opacity: blackOp, pointerEvents: 'none' }} />
    </AbsoluteFill>
  );
};
