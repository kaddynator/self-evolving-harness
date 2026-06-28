import React from 'react';
import { AbsoluteFill, interpolate, useCurrentFrame } from 'remotion';
import { SceneShell } from '../components/SceneShell';
import { BrandMark } from '../components/BrandMark';

export const FeedbackScene: React.FC = () => {
  const frame = useCurrentFrame();
  const eyebrowOp = interpolate(frame, [0, 18], [0, 1], { extrapolateRight: 'clamp' });
  const titleOp = interpolate(frame, [10, 38], [0, 1], { extrapolateRight: 'clamp' });
  const titleY = interpolate(frame, [10, 40], [22, 0], { extrapolateRight: 'clamp' });
  const stepsOp = interpolate(frame, [36, 60], [0, 1], { extrapolateRight: 'clamp' });

  const STEPS = [
    { num: '01', label: 'Capture', body: 'Negative production feedback is caught by a sentinel.' },
    { num: '02', label: 'Label',   body: 'A human provides the correct expected output.' },
    { num: '03', label: 'Rebuild', body: 'The system re-evolves the workflow against the full evaluation set.' },
  ];

  return (
    <SceneShell>
      <div
        style={{
          position: 'absolute', top: 56, left: 76, opacity: eyebrowOp,
          display: 'flex', alignItems: 'center', gap: 14,
          fontSize: 11, letterSpacing: '5px', fontWeight: 700, color: 'rgba(199,210,254,0.7)',
        }}
      >
        <span style={{ opacity: 0.65 }}>THE FLYWHEEL</span>
        <span style={{ opacity: 0.3 }}>—</span>
        <span style={{ color: '#fff', opacity: 0.85 }}>HUMAN-IN-THE-LOOP</span>
      </div>

      <div style={{ position: 'absolute', top: 50, right: 76, opacity: eyebrowOp * 0.7 }}>
        <BrandMark size={22} />
      </div>

      <AbsoluteFill
        style={{
          display: 'flex', flexDirection: 'column', justifyContent: 'center',
          alignItems: 'flex-start', padding: '160px 140px 120px',
        }}
      >
        <div
          style={{
            opacity: titleOp,
            transform: `translateY(${titleY}px)`,
            fontSize: 80,
            lineHeight: 1.1,
            letterSpacing: '-0.035em',
            fontWeight: 300,
            color: 'rgba(255,255,255,0.95)',
            maxWidth: 1200,
            marginBottom: 80,
          }}
        >
          When the workflow is wrong,{' '}
          <span style={{ fontWeight: 800 }} className="shimmer-text">
            humans close the loop.
          </span>
        </div>

        <div
          style={{
            opacity: stepsOp,
            display: 'flex',
            gap: 64,
          }}
        >
          {STEPS.map((s, i) => (
            <Step key={s.num} step={s} index={i} frame={frame} />
          ))}
        </div>
      </AbsoluteFill>
    </SceneShell>
  );
};

const Step: React.FC<{ step: { num: string; label: string; body: string }; index: number; frame: number }> = ({ step, index, frame }) => {
  const start = 48 + index * 12;
  const op = interpolate(frame, [start, start + 24], [0, 1], { extrapolateRight: 'clamp' });
  const y = interpolate(frame, [start, start + 28], [16, 0], { extrapolateRight: 'clamp' });
  return (
    <div style={{ opacity: op, transform: `translateY(${y}px)`, display: 'flex', flexDirection: 'column', gap: 16, maxWidth: 380 }}>
      <span style={{ fontSize: 72, fontWeight: 900, letterSpacing: '-0.04em', color: 'rgba(99,102,241,0.4)', lineHeight: 1 }}>
        {step.num}
      </span>
      <span style={{ fontSize: 40, fontWeight: 800, letterSpacing: '-0.02em', color: '#fff', lineHeight: 1.1 }}>
        {step.label}
      </span>
      <span style={{ fontSize: 18, lineHeight: 1.6, color: 'rgba(255,255,255,0.55)' }}>
        {step.body}
      </span>
    </div>
  );
};
