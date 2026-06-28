import { execa } from 'execa';
import { existsSync, mkdirSync, readdirSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import type { FreezeRange } from './types.js';

/** Probe a media file for {duration, width, height}. */
export async function probe(file: string): Promise<{ durationSec: number; width: number; height: number }> {
  const { stdout } = await execa('ffprobe', [
    '-v',
    'error',
    '-select_streams',
    'v:0',
    '-show_entries',
    'stream=width,height',
    '-show_entries',
    'format=duration',
    '-of',
    'json',
    file,
  ]);
  const parsed = JSON.parse(stdout) as {
    streams: Array<{ width: number; height: number }>;
    format: { duration: string };
  };
  return {
    durationSec: parseFloat(parsed.format.duration),
    width: parsed.streams[0].width,
    height: parsed.streams[0].height,
  };
}

/**
 * Extract keyframes at a fixed sampling interval. Filenames encode the
 * timestamp so downstream tools (OCR, the curator) can map back without a
 * separate manifest:
 *     frame-0000-00000.png
 *     frame-0001-02000.png   (2 s later)
 *     ...
 */
export async function extractKeyframes(
  source: string,
  outDir: string,
  intervalSec: number
): Promise<{ count: number; sampleHz: number }> {
  if (existsSync(outDir)) {
    // Wipe any stale frames from a prior run so we don't OCR them again.
    for (const f of readdirSync(outDir)) {
      if (f.endsWith('.png')) rmSync(join(outDir, f));
    }
  } else {
    mkdirSync(outDir, { recursive: true });
  }

  const sampleHz = 1 / intervalSec;
  await execa(
    'ffmpeg',
    [
      '-hide_banner',
      '-y',
      '-i',
      source,
      '-vf',
      `fps=${sampleHz},scale=1280:-2`,
      '-vsync',
      'vfr',
      '-q:v',
      '3',
      join(outDir, 'tmp-%05d.png'),
    ],
    { stdio: 'pipe' }
  );

  // Rename tmp-NNNNN.png → frame-NNNN-MMMMM.png with the milliseconds embedded.
  const tmps = readdirSync(outDir)
    .filter((f) => f.startsWith('tmp-') && f.endsWith('.png'))
    .sort();
  for (let i = 0; i < tmps.length; i++) {
    const oldName = tmps[i];
    const tMs = Math.round(i * intervalSec * 1000);
    const newName = `frame-${String(i).padStart(4, '0')}-${String(tMs).padStart(6, '0')}.png`;
    await execa('mv', [join(outDir, oldName), join(outDir, newName)]);
  }
  return { count: tmps.length, sampleHz };
}

/**
 * Detect "freeze" ranges via ffmpeg's `freezedetect` filter.
 * A freeze is N seconds (`minDurationSec`) of low pixel difference (`noise`).
 */
export async function detectFreezes(
  source: string,
  opts: { noise?: number; minDurationSec?: number } = {}
): Promise<FreezeRange[]> {
  const noise = opts.noise ?? 0.003;
  const minDuration = opts.minDurationSec ?? 2.5;

  const result = await execa(
    'ffmpeg',
    [
      '-hide_banner',
      '-nostats',
      '-i',
      source,
      '-vf',
      `freezedetect=n=${noise}:d=${minDuration}`,
      '-an',
      '-f',
      'null',
      '-',
    ],
    { reject: false }
  );

  const text = `${result.stdout}\n${result.stderr}`;
  const ranges: FreezeRange[] = [];
  let pendingStart: number | null = null;
  for (const line of text.split('\n')) {
    const startMatch = /freeze_start: ([\d.]+)/.exec(line);
    if (startMatch) {
      pendingStart = parseFloat(startMatch[1]) * 1000;
      continue;
    }
    const endMatch = /freeze_end: ([\d.]+)/.exec(line);
    if (endMatch && pendingStart != null) {
      const endMs = parseFloat(endMatch[1]) * 1000;
      ranges.push({
        startMs: Math.round(pendingStart),
        endMs: Math.round(endMs),
        durationMs: Math.round(endMs - pendingStart),
      });
      pendingStart = null;
    }
  }
  return ranges;
}
