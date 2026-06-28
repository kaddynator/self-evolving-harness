/**
 * Stage every binary asset Remotion needs under video/public/.
 * Idempotent: re-runs are cheap, existing files of the right size are kept.
 *
 *   1. (Optional) Download HTTPS-hosted source mp4s   → video/public/source/
 *   2. (Optional) Copy local source mp4s              → video/public/source/
 *   3. Copy the hero loop                             → video/public/hero/
 *   4. (Optional) Extract outro music from a source   → video/public/music/
 *   5. (Optional) Copy brand assets                   → video/public/brand/
 *
 * CUSTOMISE the DOWNLOADS, LOCAL_SOURCES, HERO_SRC, OUTRO_*, and BRAND_*
 * constants for your demo. Delete sections you don't need.
 */
import { createWriteStream, copyFileSync, existsSync, mkdirSync, statSync } from 'node:fs';
import { request } from 'node:https';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execa } from 'execa';

const here = dirname(fileURLToPath(import.meta.url));
// assets/src/ → assets/ → demo-root/
const DEMO_ROOT = resolve(here, '..', '..');
const WORKSPACE_ROOT = resolve(DEMO_ROOT, '..', '..');

const PUBLIC_DIR = resolve(DEMO_ROOT, 'video/public');
// Where to find user-private source clips that shouldn't enter the repo.
const SOURCE_DIR = resolve(WORKSPACE_ROOT, '.local/videos');

// ───── CUSTOMISE: HTTPS downloads ────────────────────────────────────────
interface DownloadSpec {
  url: string;
  dest: string;
  /** Set to 0 to skip the size check. */
  expectedBytes: number;
}

const DOWNLOADS: DownloadSpec[] = [
  // {
  //   url: 'https://your-server/path/to/recording.mp4',
  //   dest: join(PUBLIC_DIR, 'source', 'product-feature-1.mp4'),
  //   expectedBytes: 50_000_000,
  // },
];

// ───── CUSTOMISE: local source copies ────────────────────────────────────
const LOCAL_SOURCES: Array<{ src: string; dest: string }> = [
  {
    src: join(SOURCE_DIR, 'harness-demo.mp4'),     // ← drop your recording here
    dest: join(PUBLIC_DIR, 'source', 'harness-demo.mp4'),
  },
];

// ───── CUSTOMISE: hero loop ──────────────────────────────────────────────
const HERO_SRC = join(SOURCE_DIR, 'harness-hero.mp4');  // ← short hero loop (optional)
const HERO_DEST = join(PUBLIC_DIR, 'hero', 'harness-hero.mp4');

// ───── CUSTOMISE: outro music (delete if not using) ──────────────────────
const MUSIC_SOURCES = [
  // { src: join(SOURCE_DIR, 'prior-demo.mp4'), dest: join(PUBLIC_DIR, 'music', 'outro-1.m4a'), tag: 'prior-demo' },
];
const OUTRO_TAIL_SECONDS = 16;
const OUTRO_LEAD_SKIP_SECONDS = 2;  // skip any spoken intro on the music source

// ───── CUSTOMISE: brand assets (delete if not using) ─────────────────────
const BRAND_SRC_DIR = resolve(WORKSPACE_ROOT, '.local', 'files');
const BRAND_DEST_DIR = join(PUBLIC_DIR, 'brand');
const BRAND_FILES: Array<{ src: string; dest: string }> = [
  // { src: 'product-logo.svg', dest: 'product-logo.svg' },
];

function ensureDir(p: string) {
  if (!existsSync(p)) mkdirSync(p, { recursive: true });
}

function downloadHttps(url: string, dest: string, redirects = 5): Promise<void> {
  return new Promise((resolveP, reject) => {
    const req = request(url, { method: 'GET' }, (res) => {
      if (
        res.statusCode &&
        res.statusCode >= 300 &&
        res.statusCode < 400 &&
        res.headers.location &&
        redirects > 0
      ) {
        downloadHttps(res.headers.location, dest, redirects - 1).then(resolveP, reject);
        return;
      }
      if (res.statusCode !== 200) {
        reject(new Error(`HTTP ${res.statusCode} for ${url}`));
        return;
      }
      const stream = createWriteStream(dest);
      res.pipe(stream);
      stream.on('finish', () => stream.close((err) => (err ? reject(err) : resolveP())));
      stream.on('error', reject);
    });
    req.on('error', reject);
    req.end();
  });
}

async function downloadIfNeeded(spec: DownloadSpec) {
  ensureDir(dirname(spec.dest));
  if (existsSync(spec.dest)) {
    const size = statSync(spec.dest).size;
    if (spec.expectedBytes === 0 || Math.abs(size - spec.expectedBytes) < 4096) {
      console.log(`[assets] ✓ ${spec.dest.split('/').pop()} (cached)`);
      return;
    }
    console.warn(`[assets] size mismatch ${size}/${spec.expectedBytes}, redownloading`);
  }
  console.log(`[assets] ⬇ ${spec.url}`);
  await downloadHttps(spec.url, spec.dest);
  console.log(`[assets] ✓ ${(statSync(spec.dest).size / 1_048_576).toFixed(1)} MB`);
}

function copyLocal({ src, dest }: { src: string; dest: string }) {
  if (!existsSync(src)) {
    console.warn(`[assets] skip ${dest.split('/').pop()}: missing source ${src}`);
    return;
  }
  ensureDir(dirname(dest));
  if (existsSync(dest) && statSync(dest).size === statSync(src).size) {
    console.log(`[assets] ✓ ${dest.split('/').pop()} (cached)`);
    return;
  }
  copyFileSync(src, dest);
  console.log(`[assets] ✓ ${dest.split('/').pop()} staged`);
}

async function probeDuration(file: string): Promise<number> {
  const { stdout } = await execa('ffprobe', [
    '-v', 'error',
    '-show_entries', 'format=duration',
    '-of', 'default=noprint_wrappers=1:nokey=1',
    file,
  ]);
  return parseFloat(stdout.trim());
}

async function extractOutroAudio(src: string, dest: string, tag: string) {
  if (!existsSync(src)) {
    console.warn(`[assets] skip ${tag}: missing ${src}`);
    return;
  }
  ensureDir(dirname(dest));
  if (existsSync(dest)) {
    console.log(`[assets] ✓ ${tag} outro audio (cached)`);
    return;
  }
  const duration = await probeDuration(src);
  // Window the last `OUTRO_TAIL_SECONDS`, but jump in `OUTRO_LEAD_SKIP_SECONDS`
  // later so any spoken outro is dropped.
  const start = Math.max(0, duration - OUTRO_TAIL_SECONDS - OUTRO_LEAD_SKIP_SECONDS) + OUTRO_LEAD_SKIP_SECONDS;
  await execa(
    'ffmpeg',
    [
      '-hide_banner', '-y',
      '-ss', String(start),
      '-i', src,
      '-vn',
      '-c:a', 'aac',
      '-b:a', '192k',
      '-ac', '2',
      dest,
    ],
    { stdio: 'inherit' }
  );
  console.log(`[assets] ✓ ${tag} outro audio (${OUTRO_TAIL_SECONDS}s tail)`);
}

function copyBrandAssets() {
  if (BRAND_FILES.length === 0) return;
  if (!existsSync(BRAND_SRC_DIR)) {
    console.warn(`[assets] brand source dir missing: ${BRAND_SRC_DIR}`);
    return;
  }
  ensureDir(BRAND_DEST_DIR);
  for (const f of BRAND_FILES) {
    const src = join(BRAND_SRC_DIR, f.src);
    const dest = join(BRAND_DEST_DIR, f.dest);
    if (!existsSync(src)) {
      console.warn(`[assets] missing brand file: ${src}`);
      continue;
    }
    if (existsSync(dest) && statSync(dest).size === statSync(src).size) {
      console.log(`[assets] ✓ brand/${f.dest} (cached)`);
      continue;
    }
    copyFileSync(src, dest);
    console.log(`[assets] ✓ brand/${f.dest} staged`);
  }
}

async function main() {
  ensureDir(PUBLIC_DIR);
  for (const d of DOWNLOADS) await downloadIfNeeded(d);
  for (const s of LOCAL_SOURCES) copyLocal(s);
  copyLocal({ src: HERO_SRC, dest: HERO_DEST });
  copyBrandAssets();
  for (const m of MUSIC_SOURCES) await extractOutroAudio(m.src, m.dest, m.tag);
  console.log('[assets] done.');
}

main().catch((err) => {
  console.error('[assets] FAILED:', err);
  process.exit(1);
});
