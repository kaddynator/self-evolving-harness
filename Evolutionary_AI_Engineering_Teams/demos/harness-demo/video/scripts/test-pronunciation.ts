/**
 * One-shot A/B test for how Kokoro reads different spellings of the brand.
 *
 * Generates short WAVs in `video/.tts-probe/` so a human can listen and
 * pick which spelling sounds closest to the intended pronunciation.
 *
 * Usage:
 *   pnpm -F <scope>/<demo>-video exec tsx scripts/test-pronunciation.ts
 *   # or:
 *   npx -y pnpm@9.7.1 --filter <scope>/<demo>-video exec tsx scripts/test-pronunciation.ts
 *
 * CUSTOMISE the VARIANTS array for your brand. Period-separated spellings
 * (`A.B.C.`) reliably trigger eSpeak's letter-by-letter pass.
 */
import { existsSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execa } from 'execa';

const here = dirname(fileURLToPath(import.meta.url));
const OUT_DIR = resolve(here, '..', '.tts-probe');

const VOICE = process.env.AICG_VOICE_ID ?? 'af_heart';
const SPEED = parseFloat(process.env.AICG_VOICE_SPEED ?? '1');

// ───── CUSTOMISE: brand-name spellings to probe ──────────────────────────
const VARIANTS = [
  { id: '01-naked',     label: 'PRODUCTNAME (no separator)',  text: 'Meet PRODUCTNAME, the unified control plane for AI.' },
  { id: '02-periods',   label: 'P.R.O.D.U.C.T.',              text: 'Meet P.R.O.D.U.C.T., the unified control plane for AI.' },
  { id: '03-hyphens',   label: 'P-R-O-D',                     text: 'Meet P-R-O-D, the unified control plane for AI.' },
  { id: '04-spaces',    label: 'P R O D (spaces)',            text: 'Meet P R O D, the unified control plane for AI.' },
  { id: '05-expanded',  label: 'Full Name (baseline)',        text: 'Meet PRODUCTNAME (Full Name Spelled Out), the unified control plane for AI.' },
];

async function main() {
  if (!existsSync(OUT_DIR)) mkdirSync(OUT_DIR, { recursive: true });

  console.log(`[probe] loading Kokoro-82M (q8, CPU)…`);
  const { KokoroTTS } = await import('kokoro-js');
  const tts = await KokoroTTS.from_pretrained('onnx-community/Kokoro-82M-v1.0-ONNX', {
    dtype: 'q8',
    device: 'cpu',
  });
  console.log(`[probe] model loaded — synthesising ${VARIANTS.length} variants.\n`);

  for (const v of VARIANTS) {
    const out = resolve(OUT_DIR, `${v.id}.wav`);
    process.stdout.write(`  • ${v.label.padEnd(36)} → ${v.id}.wav … `);
    const audio = await tts.generate(v.text, { voice: VOICE, speed: SPEED });
    audio.save(out);
    console.log('ok');
  }

  console.log(`\n[probe] done. Files in ${OUT_DIR}`);
  await execa('open', [OUT_DIR]).catch(() => undefined);
}

main().catch((err) => {
  console.error('[probe] FAILED:', err);
  process.exit(1);
});
