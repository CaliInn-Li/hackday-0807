import { spawn } from 'node:child_process';

const intervalMs = Number(process.env.AHOLO_POLL_INTERVAL_MS || 30000);
const timeoutMs = Number(process.env.AHOLO_WAIT_TIMEOUT_MS || 20 * 60 * 1000);
const startedAt = Date.now();

function runSync() {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, ['scripts/sync-aholo-world.mjs'], {
      cwd: process.cwd(),
      env: process.env,
      stdio: ['ignore', 'pipe', 'inherit'],
    });
    let output = '';
    child.stdout.on('data', (chunk) => { output += chunk; });
    child.on('error', reject);
    child.on('close', (code) => {
      if (code !== 0) return reject(new Error(`sync-world exited with ${code}`));
      process.stdout.write(output);
      try { resolve(JSON.parse(output)); } catch { resolve({ status: 'UNKNOWN' }); }
    });
  });
}

while (Date.now() - startedAt < timeoutMs) {
  const manifest = await runSync();
  if (['SUCCEEDED', 'FAILED', 'CANCELED', 'TIMEOUT', 'REJECTED'].includes(manifest.status)) {
    process.exit(manifest.status === 'SUCCEEDED' ? 0 : 2);
  }
  console.log(`Aholo world is ${manifest.status}; checking again in ${Math.round(intervalMs / 1000)}s...`);
  await new Promise((resolve) => setTimeout(resolve, intervalMs));
}

throw new Error(`Aholo world did not reach a terminal state within ${Math.round(timeoutMs / 60000)} minutes.`);
