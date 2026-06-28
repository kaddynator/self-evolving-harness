import React from 'react';
import { AbsoluteFill, interpolate, useCurrentFrame } from 'remotion';
import { SceneShell } from '../components/SceneShell';
import { BrandMark } from '../components/BrandMark';

const STACK = [
  {
    category: 'Models',
    color: '#818cf8',
    items: ['Gemini 2.5 Flash', 'Claude Sonnet 4.6'],
  },
  {
    category: 'State & Memory',
    color: '#34d399',
    items: ['MongoDB Atlas', 'Kuzu Graph DB'],
  },
  {
    category: 'Vector & Analytics',
    color: '#f472b6',
    items: ['Qdrant', 'ClickHouse'],
  },
  {
    category: 'Infrastructure',
    color: '#fb923c',
    items: ['DigitalOcean Droplets', 'Docker'],
  },
];

export const TechStackScene: React.FC = () => {
  const frame = useCurrentFrame();
  const eyebrowOp = interpolate(frame, [0, 18], [0, 1], { extrapolateRight: 'clamp' });
  const titleOp = interpolate(frame, [8, 36], [0, 1], { extrapolateRight: 'clamp' });
  const titleY = interpolate(frame, [8, 38], [18, 0], { extrapolateRight: 'clamp' });

  return (
    <SceneShell>
      <div
        style={{
          position: 'absolute', top: 56, left: 76, opacity: eyebrowOp,
          display: 'flex', alignItems: 'center', gap: 14,
          fontSize: 11, letterSpacing: '5px', fontWeight: 700,
          color: 'rgba(199,210,254,0.7)',
        }}
      >
        <span style={{ opacity: 0.65 }}>BUILT WITH</span>
        <span style={{ opacity: 0.3 }}>—</span>
        <span style={{ color: '#fff', opacity: 0.85 }}>TECH STACK</span>
      </div>

      <div style={{ position: 'absolute', top: 50, right: 76, opacity: eyebrowOp * 0.7 }}>
        <BrandMark size={22} />
      </div>

      <AbsoluteFill
        style={{
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          padding: '140px 110px 100px',
        }}
      >
        <div
          style={{
            opacity: titleOp,
            transform: `translateY(${titleY}px)`,
            fontSize: 64,
            fontWeight: 300,
            letterSpacing: '-0.03em',
            color: 'rgba(255,255,255,0.9)',
            marginBottom: 72,
          }}
        >
          Every layer,{' '}
          <span style={{ fontWeight: 800 }} className="shimmer-text">
            purpose-built.
          </span>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 32 }}>
          {STACK.map((group, gi) => {
            const start = 40 + gi * 14;
            const op = interpolate(frame, [start, start + 26], [0, 1], { extrapolateRight: 'clamp' });
            const y = interpolate(frame, [start, start + 30], [20, 0], { extrapolateRight: 'clamp' });
            return (
              <div
                key={group.category}
                style={{
                  opacity: op,
                  transform: `translateY(${y}px)`,
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 0,
                  borderTop: `2px solid ${group.color}`,
                  paddingTop: 24,
                }}
              >
                <span
                  style={{
                    fontSize: 11,
                    letterSpacing: '4px',
                    fontWeight: 700,
                    color: group.color,
                    textTransform: 'uppercase',
                    marginBottom: 20,
                  }}
                >
                  {group.category}
                </span>
                {group.items.map((item) => (
                  <div
                    key={item}
                    style={{
                      fontSize: 22,
                      fontWeight: 600,
                      color: 'rgba(255,255,255,0.88)',
                      letterSpacing: '-0.01em',
                      lineHeight: 1.4,
                      padding: '10px 0',
                      borderBottom: '1px solid rgba(255,255,255,0.07)',
                    }}
                  >
                    {item}
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      </AbsoluteFill>
    </SceneShell>
  );
};
