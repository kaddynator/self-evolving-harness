import React from 'react';
import { AbsoluteFill, interpolate, useCurrentFrame } from 'remotion';
import { SceneShell } from '../components/SceneShell';
import { BrandMark } from '../components/BrandMark';

export const ProblemScene: React.FC = () => {
  const frame = useCurrentFrame();
  const eyebrowOp = interpolate(frame, [0, 18], [0, 1], { extrapolateRight: 'clamp' });
  const titleOp = interpolate(frame, [10, 38], [0, 1], { extrapolateRight: 'clamp' });
  const titleY = interpolate(frame, [10, 40], [22, 0], { extrapolateRight: 'clamp' });
  const subOp = interpolate(frame, [28, 56], [0, 1], { extrapolateRight: 'clamp' });
  const ruleOp = interpolate(frame, [54, 78], [0, 1], { extrapolateRight: 'clamp' });
  const ruleScaleX = interpolate(frame, [54, 90], [0, 1], { extrapolateRight: 'clamp' });

  const PILLARS = [
    { kicker: 'Problem', title: 'Static',  body: 'Teams are hand-crafted once and never adapt.' },
    { kicker: 'Problem', title: 'Fragile', body: 'New tasks expose expertise gaps no one anticipated.' },
    { kicker: 'Problem', title: 'Manual',  body: 'Every failure requires a human to debug and redeploy.' },
  ];

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
        <span style={{ opacity: 0.65 }}>THE PROBLEM</span>
        <span style={{ opacity: 0.3 }}>—</span>
        <span style={{ color: '#fff', opacity: 0.85 }}>STATIC AGENT TEAMS</span>
      </div>

      <div style={{ position: 'absolute', top: 50, right: 76, opacity: eyebrowOp * 0.7 }}>
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
            fontSize: 88,
            lineHeight: 1.08,
            letterSpacing: '-0.035em',
            fontWeight: 300,
            color: 'rgba(255,255,255,0.95)',
            maxWidth: 1400,
          }}
        >
          Most AI teams are{' '}
          <span style={{ fontWeight: 800 }} className="shimmer-text">
            built once
          </span>
          {' '}and never evolve.
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
          Developers predefine every agent, every responsibility, every collaboration path —
          before they know what the tasks will actually demand.
        </div>

        <div
          style={{
            marginTop: 70,
            width: 320,
            height: 1,
            background: 'linear-gradient(90deg, transparent 0%, rgba(199,210,254,0.55) 50%, transparent 100%)',
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

const Pillar: React.FC<{ pillar: { kicker: string; title: string; body: string }; index: number; frame: number }> = ({ pillar, index, frame }) => {
  const start = 80 + index * 10;
  const op = interpolate(frame, [start, start + 26], [0, 1], { extrapolateRight: 'clamp' });
  const y = interpolate(frame, [start, start + 30], [14, 0], { extrapolateRight: 'clamp' });
  return (
    <div style={{ opacity: op, transform: `translateY(${y}px)`, display: 'flex', flexDirection: 'column', gap: 14, alignItems: 'flex-start', textAlign: 'left' }}>
      <span style={{ fontSize: 11, letterSpacing: '4px', fontWeight: 700, color: 'rgba(248,113,113,0.7)', textTransform: 'uppercase' }}>
        {pillar.kicker}
      </span>
      <span style={{ fontSize: 56, fontWeight: 800, letterSpacing: '-0.02em', lineHeight: 1, color: '#fff' }}>
        {pillar.title}
      </span>
      <span style={{ fontSize: 16, lineHeight: 1.55, color: 'rgba(255,255,255,0.55)', maxWidth: 320, marginTop: 6 }}>
        {pillar.body}
      </span>
    </div>
  );
};
