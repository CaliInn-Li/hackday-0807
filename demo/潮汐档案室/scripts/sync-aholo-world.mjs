import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const apiKey = process.env.AHOLO_API_KEY;
const worldId = process.env.AHOLO_WORLD_ID || '3FO4K4WYFVXB';
const outputDir = resolve('public/generated');

if (!apiKey) {
  console.error('Missing AHOLO_API_KEY. Copy .env.example or set the environment variable.');
  process.exit(1);
}

const response = await fetch(`https://api.aholo3d.cn/world/v1/${worldId}`, {
  headers: { Authorization: apiKey, 'x-source': 'hackday-codex' },
});

if (!response.ok) {
  throw new Error(`Aholo API ${response.status}: ${await response.text()}`);
}

const detail = await response.json();
const manifest = {
  worldId,
  name: detail.name || '潮汐档案馆：失落的星图',
  status: detail.status,
  progress: detail.progress ?? 0,
  source: 'Aholo Spatial Gen',
  upAxis: detail.assets?.semanticsMetadata?.upAxis ?? null,
  splats: detail.assets?.splats?.urls ?? null,
  updatedAt: new Date().toISOString(),
};

await mkdir(outputDir, { recursive: true });

const panoUrl = detail.assets?.imagery?.panoUrl;
if (panoUrl && detail.status === 'SUCCEEDED') {
  try {
    const panoResponse = await fetch(panoUrl);
    if (!panoResponse.ok) throw new Error(`Pano download ${panoResponse.status}`);
    await writeFile(resolve(outputDir, 'aholo-pano.jpg'), Buffer.from(await panoResponse.arrayBuffer()));
    manifest.panoFile = '/generated/aholo-pano.jpg';
  } catch (error) {
    manifest.panoDownloadError = error.message;
    console.warn(`World succeeded, but the panorama could not be cached: ${error.message}`);
  }
}

await writeFile(resolve(outputDir, 'world.json'), `${JSON.stringify(manifest, null, 2)}\n`);
console.log(JSON.stringify(manifest, null, 2));
