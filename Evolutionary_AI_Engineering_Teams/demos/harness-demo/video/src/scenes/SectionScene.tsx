import React from 'react';
import { AbsoluteFill, interpolate, useCurrentFrame } from 'remotion';
import { SceneShell } from '../components/SceneShell';

export interface SectionContent {
  partIndex: number;
  partTotal: number;
  number: string;
  metaLabel: string;
  title: string;
  subtitle: string;
  steps: string[];
}

interface Props {
  content: SectionContent;
}

/**
 * Part divider — chapter break between major sections. Reused by exporting
 * one SectionContent constant per part below.
 *
 * CUSTOMISE: edit PLATFORM_SECTION (and add more) to describe each part of
 * your demo.
 */
export const SectionScene: React.FC<Props> = ({ content }) => {
  const frame = useCurrentFrame();

  const numberOp = interpolate(frame, [0, 22], [0, 1], { extrapolateRight: 'clamp' });
  const numberScale = interpolate(frame, [0, 26], [0.85, 1], { extrapolateRight: 'clamp' });
  const titleOp = interpolate(frame, [10, 30], [0, 1], { extrapolateRight: 'clamp' });
  const titleY = interpolate(frame, [10, 30], [14, 0], { extrapolateRight: 'clamp' });
  const subOp = interpolate(frame, [18, 36], [0, 1], { extrapolateRight: 'clamp' });
  const metaOp = interpolate(frame, [0, 18], [0, 1], { extrapolateRight: 'clamp' });

  return (
    <SceneShell>
      <div
        style={{
          position: 'absolute',
          top: 56,
          left: 76,
          display: 'flex',
          alignItems: 'center',
          gap: 14,
          fontSize: 12,
          letterSpacing: '4px',
          fontWeight: 700,
          color: 'rgba(165,180,252,0.85)',
          opacity: metaOp,
        }}
      >
        <span>
          PART {String(content.partIndex).padStart(2, '0')} / {String(content.partTotal).padStart(2, '0')}
        </span>
        <span style={{ color: 'rgba(165,180,252,0.35)' }}>·</span>
        <span style={{ color: 'rgba(255,255,255,0.9)' }}>{content.metaLabel.toUpperCase()}</span>
      </div>

      <AbsoluteFill
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '80px 100px',
          textAlign: 'center',
        }}
      >
        <div
          style={{
            opacity: numberOp,
            transform: `scale(${numberScale})`,
            width: 132,
            height: 132,
            borderRadius: 28,
            background: 'linear-gradient(135deg, #6366f1, #a855f7)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 56,
            fontWeight: 900,
            boxShadow: '0 22px 70px -16px rgba(99,102,241,0.5)',
            marginBottom: 36,
          }}
        >
          {content.number}
        </div>

        <h2
          style={{
            opacity: titleOp,
            transform: `translateY(${titleY}px)`,
            margin: 0,
            fontWeight: 900,
            fontSize: 86,
            lineHeight: 1.04,
            letterSpacing: '-0.02em',
            marginBottom: 22,
          }}
        >
          {content.title}
        </h2>

        <p
          style={{
            opacity: subOp,
            margin: 0,
            maxWidth: 1100,
            fontSize: 26,
            lineHeight: 1.5,
            color: 'rgba(255,255,255,0.7)',
            marginBottom: 54,
          }}
        >
          {content.subtitle}
        </p>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, width: 980 }}>
          {content.steps.map((step, i) => {
            const start = 28 + i * 10;
            const op = interpolate(frame, [start, start + 22], [0, 1], { extrapolateRight: 'clamp' });
            const y = interpolate(frame, [start, start + 22], [14, 0], { extrapolateRight: 'clamp' });
            return (
              <div
                key={i}
                style={{
                  opacity: op,
                  transform: `translateY(${y}px)`,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 18,
                  padding: '18px 26px',
                  borderRadius: 18,
                  border: '1px solid rgba(255,255,255,0.1)',
                  background: 'rgba(255,255,255,0.04)',
                  textAlign: 'left',
                }}
              >
                <span
                  style={{
                    width: 36,
                    height: 36,
                    flexShrink: 0,
                    borderRadius: '50%',
                    background: 'linear-gradient(135deg, rgba(99,102,241,0.5), rgba(168,85,247,0.5))',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: 16,
                    fontWeight: 800,
                  }}
                >
                  {i + 1}
                </span>
                <span
                  style={{ fontSize: 22, color: 'rgba(255,255,255,0.92)' }}
                  dangerouslySetInnerHTML={{ __html: step }}
                />
              </div>
            );
          })}
        </div>
      </AbsoluteFill>
    </SceneShell>
  );
};

// CUSTOMISE: export one SectionContent per part of your demo.
export const PLATFORM_SECTION: SectionContent = {
  partIndex: 1,
  partTotal: 1,
  number: '01',
  metaLabel: 'Platform',
  title: 'The PRODUCT Platform',
  subtitle: 'A guided tour of the foundation, in under ninety seconds.',
  steps: [
    'Bullet one — what the viewer will see in this part.',
    'Bullet two — second key idea.',
    'Bullet three — third key idea.',
  ],
};
