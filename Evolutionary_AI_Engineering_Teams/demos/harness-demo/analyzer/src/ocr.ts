import { execa } from 'execa';
import { existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import type { Keyframe } from './types.js';

const here = dirname(fileURLToPath(import.meta.url));
const PKG_ROOT = resolve(here, '..');
const VENV_PY = resolve(PKG_ROOT, '.venv', 'bin', 'python');
const OCR_SCRIPT = resolve(PKG_ROOT, 'python', 'ocr_keyframes.py');

/** Spawn the Python OCR sidecar on a directory of `frame-NNNN-MMMMM.png` images. */
export async function ocrKeyframes(keyframesDir: string): Promise<Keyframe[]> {
  if (!existsSync(VENV_PY)) {
    throw new Error(
      `[ocr] missing venv python at ${VENV_PY}. Run \`npm run analyzer:bootstrap\` first.`
    );
  }
  if (!existsSync(OCR_SCRIPT)) {
    throw new Error(`[ocr] missing python entrypoint at ${OCR_SCRIPT}`);
  }
  const { stdout } = await execa(VENV_PY, [OCR_SCRIPT, keyframesDir], {
    stdio: ['ignore', 'pipe', 'inherit'],
    maxBuffer: 64 * 1024 * 1024,
  });
  return JSON.parse(stdout) as Keyframe[];
}
