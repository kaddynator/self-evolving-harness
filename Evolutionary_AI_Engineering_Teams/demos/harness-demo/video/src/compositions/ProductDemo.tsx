import React from 'react';
import { AbsoluteFill, Audio, Sequence, staticFile } from 'remotion';
import '../styles.css';
import { TIMELINE, type TimelineScene } from '../data/timeline';
import { HeroScene } from '../scenes/HeroScene';
import { ProblemScene } from '../scenes/ProblemScene';
import { FeedbackScene } from '../scenes/FeedbackScene';
import { TechStackScene } from '../scenes/TechStackScene';
import { VideoScene } from '../scenes/VideoScene';
import { OutroScene } from '../scenes/OutroScene';

/**
 * Top-level composition. CUSTOMISE the scene → component mapping in
 * `renderScene()` to add / remove / reorder scenes. Make sure the SceneId
 * values match what's in narration.ts and warm-voice.ts's sceneSpecs.
 *
 * Subtitles are disabled by default; re-enable by setting
 * ENABLE_SUBTITLES = true and reinstating the <Subtitle> sequence block.
 */
const ENABLE_SUBTITLES = false;

function renderScene(scene: TimelineScene) {
  switch (scene.scene) {
    case 'hero':
      return <HeroScene />;
    case 'problem':
      return <ProblemScene />;
    case 'product-demo':
      return (
        <VideoScene
          eyebrow="Live Demo"
          label="Evolutionary Harness · Walkthrough"
          cues={scene.cues}
          sceneStartFrame={scene.startFrame}
          totalFramesInScene={scene.durationFrames}
        />
      );
    case 'feedback':
      return <FeedbackScene />;
    case 'tech-stack':
      return <TechStackScene />;
    case 'outro':
      return <OutroScene />;
    default:
      return null;
  }
}

export const ProductDemo: React.FC = () => {
  return (
    <AbsoluteFill style={{ background: '#080614' }}>
      {/* Scenes */}
      {TIMELINE.scenes.map((scene) => (
        <Sequence
          key={`scene-${scene.scene}-${scene.startFrame}`}
          from={scene.startFrame}
          durationInFrames={scene.durationFrames}
          name={scene.scene}
        >
          {renderScene(scene)}
        </Sequence>
      ))}

      {/* Narration audio — one Sequence per cue, absolute frame offsets */}
      {TIMELINE.scenes.flatMap((scene) =>
        scene.cues.map((cue) => (
          <Sequence
            key={`audio-${cue.cueId}`}
            from={cue.startFrame}
            durationInFrames={cue.durationFrames}
            name={`tts:${cue.cueId}`}
          >
            <Audio src={staticFile(cue.wavPath)} />
          </Sequence>
        ))
      )}

      {/* Subtitles (disabled by default) */}
      {ENABLE_SUBTITLES && (
        <>{/* re-enable by importing Subtitle and mapping cues to it here */}</>
      )}

      {/* Outro music with linear fade */}
      {TIMELINE.music && (
        <Sequence
          from={TIMELINE.music.startFrame}
          durationInFrames={TIMELINE.music.durationFrames}
          name="music"
        >
          <MusicTrack
            trackPath={TIMELINE.music.trackPath}
            durationFrames={TIMELINE.music.durationFrames}
            fadeInFrames={TIMELINE.music.fadeInFrames}
            fadeOutFrames={TIMELINE.music.fadeOutFrames}
            volume={TIMELINE.music.volume}
          />
        </Sequence>
      )}
    </AbsoluteFill>
  );
};

interface MusicProps {
  trackPath: string;
  durationFrames: number;
  fadeInFrames: number;
  fadeOutFrames: number;
  volume: number;
}

const MusicTrack: React.FC<MusicProps> = ({
  trackPath,
  durationFrames,
  fadeInFrames,
  fadeOutFrames,
  volume,
}) => {
  return (
    <Audio
      src={staticFile(trackPath)}
      volume={(frame) => {
        const fadeIn = Math.min(1, frame / Math.max(1, fadeInFrames));
        const fadeOut = Math.min(
          1,
          (durationFrames - frame) / Math.max(1, fadeOutFrames)
        );
        return Math.max(0, Math.min(fadeIn, fadeOut)) * volume;
      }}
    />
  );
};
