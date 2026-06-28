import React from 'react';
import { AbsoluteFill, interpolate, useCurrentFrame } from 'remotion';
import { SceneShell } from '../components/SceneShell';
import { BrandMark } from '../components/BrandMark';

/**
 * "What is X" — exec manifesto.
 *
 * Goal: answer "what is this product, in 20 seconds?". Single bold statement,
 * one supporting line, three abstract pillars. No jargon. Apple-keynote energy.
 *
 * CUSTOMISE:
 *   - Rewrite the hero statement (one bold sentence with an accent on 2-3 words).
 *   - Replace PILLARS with three things that matter strategically (not features).
 */

const PILLARS = [
  { kicker: 'Built for', title: 'Scale',  body: 'One sentence about scale.' },
  { kicker: 'Built for', title: 'Trust',  body: 'One sentence about trust.' },
  { kicker: 'Built for', title: 'Agents', body: 'One sentence about agent support.' },
];

export const WhatIsScene: React.FC = () => {
  const frame = useCurrentFrame();
  const eyebrowOp = interpolate(frame, [0, 18], [0, 1], { extrapolateRight: 'clamp' });
  const titleOp = interpolate(frame, [10, 38], [0, 1], { extrapolateRight: 'clamp' });
  const titleY = interpolate(frame, [10, 40], [22, 0], { extrapolateRight: 'clamp' });
  const subOp = interpolate(frame, [28, 56], [0, 1], { extrapolateRight: 'clamp' });
  const ruleOp = interpolate(frame, [54, 78], [0, 1], { extrapolateRight: 'clamp' });
  const ruleScaleX = interpolate(frame, [54, 90], [0, 1], { extrapolateRight: 'clamp' });

  return (
    <SceneShell>
      <div
        style={{
          position: 'absolute',
          top: 56,
          left: 76,
          opacity: eyebrowOp,
          display: 'flex',
          alignItems: 'center',
          gap: 14,
          fontSize: 11,
          letterSpacing: '5px',
          fontWeight: 700,
          color: 'rgba(199,210,254,0.7)',
        }}
      >
        <span style={{ opacity: 0.65 }}>OVERVIEW</span>
        <span style={{ opacity: 0.3 }}>—</span>
        <span style={{ color: '#fff', opacity: 0.85 }}>WHAT IS PRODUCT</span>
      </div>

      <div
        style={{
          position: 'absolute',
          top: 50,
          right: 76,
          opacity: eyebrowOp * 0.7,
        }}
      >
        <BrandMark size={22} />
      </div>

      <AbsoluteFill
        style={{
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          alignItems: 'center',
          padding: '160px 140px 120px',
          textAlign: 'center',
        }}
      >
        <div
          style={{
            opacity: titleOp,
            transform: `translateY(${titleY}px)`,
            fontSize: 96,
            lineHeight: 1.08,
            letterSpacing: '-0.035em',
            fontWeight: 300,
            color: 'rgba(255,255,255,0.95)',
            maxWidth: 1500,
          }}
        >
          Every AI workload,{' '}
          <span style={{ fontWeight: 800 }} className="shimmer-text">
            on one grid.
          </span>
        </div>

        <div
          style={{
            opacity: subOp,
            marginTop: 36,
            fontSize: 24,
            lineHeight: 1.55,
            color: 'rgba(255,255,255,0.6)',
            maxWidth: 1080,
            fontWeight: 400,
          }}
        >
          One supporting sentence in muted ink that explains what changes for
          your team when this product is in place. {/* CUSTOMISE */}
        </div>

        <div
          style={{
            marginTop: 70,
            width: 320,
            height: 1,
            background:
              'linear-gradient(90deg, transparent 0%, rgba(199,210,254,0.55) 50%, transparent 100%)',
            opacity: ruleOp,
            transform: `scaleX(${ruleScaleX})`,
            transformOrigin: 'center',
          }}
        />

        <div
          style={{
            marginTop: 64,
            display: 'grid',
            gridTemplateColumns: 'repeat(3, 1fr)',
            gap: 80,
            width: 1320,
          }}
        >
          {PILLARS.map((p, i) => (
            <Pillar key={p.title} pillar={p} index={i} frame={frame} />
          ))}
        </div>
      </AbsoluteFill>
    </SceneShell>
  );
};

interface PillarProps {
  pillar: typeof PILLARS[number];
  index: number;
  frame: number;
}

const Pillar: React.FC<PillarProps> = ({ pillar, index, frame }) => {
  const start = 80 + index * 10;
  const op = interpolate(frame, [start, start + 26], [0, 1], { extrapolateRight: 'clamp' });
  const y = interpolate(frame, [start, start + 30], [14, 0], { extrapolateRight: 'clamp' });
  return (
    <div
      style={{
        opacity: op,
        transform: `translateY(${y}px)`,
        display: 'flex',
        flexDirection: 'column',
        gap: 14,
        alignItems: 'flex-start',
        textAlign: 'left',
      }}
    >
      <span
        style={{
          fontSize: 11,
          letterSpacing: '4px',
          fontWeight: 700,
          color: 'rgba(199,210,254,0.55)',
          textTransform: 'uppercase',
        }}
      >
        {pillar.kicker}
      </span>
      <span
        style={{
          fontSize: 56,
          fontWeight: 800,
          letterSpacing: '-0.02em',
          lineHeight: 1,
          color: '#fff',
        }}
      >
        {pillar.title}
      </span>
      <span
        style={{
          fontSize: 16,
          lineHeight: 1.55,
          color: 'rgba(255,255,255,0.55)',
          maxWidth: 320,
          marginTop: 6,
        }}
      >
        {pillar.body}
      </span>
    </div>
  );
};
