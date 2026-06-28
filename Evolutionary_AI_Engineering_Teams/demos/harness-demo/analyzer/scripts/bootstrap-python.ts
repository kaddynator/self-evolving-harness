/**
 * Idempotent venv bootstrap for the OCR sidecar.
 *
 * Creates `analyzer/.venv` with `ocrmac` + `pyobjc-framework-Vision` (Apple
 * Vision binding) so the analyzer can call out to Python without polluting
 * the user's global Python install.
 *
 * Run via `pnpm -F <scope>/<demo>-analyzer run bootstrap` or just
 * `npm run analyzer:bootstrap` from the workspace root.
 */
import { existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execa } from 'execa';

const here = dirname(fileURLToPath(import.meta.url));
const PKG_ROOT = resolve(here, '..');
const VENV = resolve(PKG_ROOT, '.venv');
const VENV_PIP = resolve(VENV, 'bin', 'pip');
const VENV_PY = resolve(VENV, 'bin', 'python');
const STAMP = resolve(VENV, '.bootstrap.ok');

const REQUIREMENTS = [
  // ocrmac wraps Apple Vision via pyobjc — installs the framework bindings as deps.
  'ocrmac==1.0.1',
  'Pillow>=10.4.0',
];

async function run(cmd: string, args: string[]) {
  console.log(`$ ${cmd} ${args.join(' ')}`);
  await execa(cmd, args, { stdio: 'inherit' });
}

async function main() {
  if (existsSync(STAMP)) {
    console.log(`[analyzer] venv already bootstrapped at ${VENV}`);
    return;
  }

  if (!existsSync(VENV)) {
    await run('python3', ['-m', 'venv', VENV]);
  }
  await run(VENV_PIP, ['install', '--upgrade', 'pip']);
  await run(VENV_PIP, ['install', ...REQUIREMENTS]);

  // Sanity check: import ocrmac
  await run(VENV_PY, ['-c', "import ocrmac; print('ocrmac', getattr(ocrmac, '__version__', 'imported'))"]);

  // Drop a stamp so re-runs short-circuit.
  await execa('touch', [STAMP]);
  console.log(`[analyzer] ✓ venv ready: ${VENV}`);
}

main().catch((err) => {
  console.error('[analyzer] bootstrap FAILED:', err);
  process.exit(1);
});
