import React from 'react';
import { AbsoluteFill, OffthreadVideo, interpolate, staticFile, useCurrentFrame } from 'remotion';
import { BrandMark } from '../components/BrandMark';

/**
 * Full-bleed hero: the hero loop fills the entire 1920×1080 canvas; copy is
 * overlaid on the left third on top of a dark-to-clear gradient that preserves
 * readability without blocking the right-side animation.
 *
 * CUSTOMISE:
 *   - Update the hero src path to match prepare.ts dest.
 *   - Rewrite the eyebrow / headline / supporting / chips for your product.
 *   - Optional: add a parent-brand lockup in the bottom-left.
 */
export const HeroScene: React.FC = () => {
  const frame = useCurrentFrame();
  const eyebrowOp = interpolate(frame, [0, 20], [0, 1], { extrapolateRight: 'clamp' });
  const eyebrowY = interpolate(frame, [0, 24], [12, 0], { extrapolateRight: 'clamp' });
  const titleOp = interpolate(frame, [8, 34], [0, 1], { extrapolateRight: 'clamp' });
  const titleY = interpolate(frame, [8, 38], [18, 0], { extrapolateRight: 'clamp' });
  const subOp = interpolate(frame, [18, 44], [0, 1], { extrapolateRight: 'clamp' });
  const chipsOp = interpolate(frame, [28, 56], [0, 1], { extrapolateRight: 'clamp' });
  const bgOp = interpolate(frame, [0, 24], [0, 1], { extrapolateRight: 'clamp' });

  return (
    <AbsoluteFill style={{ background: '#080614' }}>
      {/* L1 — full-bleed hero loop */}
      <AbsoluteFill style={{ opacity: bgOp }}>
        <OffthreadVideo
          src={staticFile('hero/harness-hero.mp4')}
          muted
          loop
          style={{ width: '100%', height: '100%', objectFit: 'cover' }}
        />
      </AbsoluteFill>

      {/* L2 — left-side dark gradient overlay so copy reads cleanly */}
      <AbsoluteFill
        style={{
          background:
            'linear-gradient(90deg, rgba(8,6,20,0.92) 0%, rgba(8,6,20,0.78) 28%, rgba(8,6,20,0.45) 48%, rgba(8,6,20,0.05) 62%, rgba(8,6,20,0) 100%)',
          pointerEvents: 'none',
        }}
      />

      {/* L3 — bottom vignette for a cinematic frame */}
      <AbsoluteFill
        style={{
          background:
            'linear-gradient(180deg, rgba(8,6,20,0.4) 0%, transparent 18%, transparent 78%, rgba(8,6,20,0.55) 100%)',
          pointerEvents: 'none',
        }}
      />

      {/* L4 — copy column, anchored to the left third */}
      <AbsoluteFill
        style={{
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          paddingLeft: 110,
          paddingRight: 60,
        }}
      >
        <div style={{ maxWidth: 880 }}>
          <div
            style={{
              opacity: eyebrowOp,
              transform: `translateY(${eyebrowY}px)`,
              fontSize: 13,
              letterSpacing: '5px',
              textTransform: 'uppercase',
              color: '#a5b4fc',
              fontWeight: 700,
              marginBottom: 30,
            }}
          >
            EVOLUTIONARY AI · ENGINEERING TEAMS
          </div>

          <h1
            style={{
              opacity: titleOp,
              transform: `translateY(${titleY}px)`,
              margin: 0,
              fontWeight: 900,
              fontSize: 110,
              lineHeight: 1.02,
              letterSpacing: '-0.035em',
              color: '#fff',
              marginBottom: 34,
              textShadow: '0 8px 32px rgba(0,0,0,0.45)',
            }}
          >
            Agent teams that{' '}
            <span className="shimmer-text">evolve.</span>
          </h1>

          <p
            style={{
              opacity: subOp,
              margin: 0,
              maxWidth: 720,
              fontSize: 26,
              lineHeight: 1.45,
              color: 'rgba(255,255,255,0.82)',
              marginBottom: 48,
              textShadow: '0 4px 18px rgba(0,0,0,0.45)',
            }}
          >
            From a plain-English task to a self-improving multi-agent workflow — no manual design required.
          </p>

          <div
            style={{
              opacity: chipsOp,
              display: 'flex',
              gap: 12,
              flexWrap: 'wrap',
              borderTop: '1px solid rgba(255,255,255,0.18)',
              paddingTop: 28,
              width: 'fit-content',
            }}
          >
            <Chip text="Compile" />
            <Chip text="Execute" />
            <Chip text="Evolve" />
            <Chip text="Self-Improve" />
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const Chip: React.FC<{ text: string }> = ({ text }) => (
  <div
    style={{
      padding: '8px 16px',
      fontSize: 13,
      fontWeight: 600,
      letterSpacing: '0.4px',
      color: 'rgba(255,255,255,0.85)',
      borderRadius: 999,
      border: '1px solid rgba(165,180,252,0.35)',
      background: 'rgba(99,102,241,0.12)',
      backdropFilter: 'blur(6px)',
    }}
  >
    {text}
  </div>
);
