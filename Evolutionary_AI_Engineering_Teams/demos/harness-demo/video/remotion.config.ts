import os from 'node:os';
import { Config } from '@remotion/cli/config';

Config.setVideoImageFormat('jpeg');
Config.setOverwriteOutput(true);
Config.setCodec('h264');
Config.setCrf(18);
Config.setPixelFormat('yuv420p');
Config.setAudioCodec('aac');
Config.setAudioBitrate('192k');
// Render scenes in parallel where possible. Leave one core idle so the
// machine stays usable while a long render is in flight.
Config.setConcurrency(Math.max(1, os.cpus().length - 1));
Config.setChromiumOpenGlRenderer('angle');
