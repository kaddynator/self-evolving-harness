import { Composition } from 'remotion';
import { ProductDemo } from './compositions/ProductDemo';
import { TIMELINE } from './data/timeline';

// CUSTOMISE: rename the Composition id + component to your product name.
export const RemotionRoot = () => {
  return (
    <>
      <Composition
        id="PRODUCTDemo"
        component={ProductDemo}
        durationInFrames={Math.max(TIMELINE.totalFrames, 30)}
        fps={TIMELINE.fps}
        width={1920}
        height={1080}
      />
    </>
  );
};
