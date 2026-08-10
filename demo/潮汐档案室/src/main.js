import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import './style.css';

const canvas = document.querySelector('#game-canvas');
const ui = {
  boot: document.querySelector('#boot'),
  start: document.querySelector('#start-btn'),
  hud: document.querySelector('#hud'),
  timer: document.querySelector('#timer'),
  objective: document.querySelector('#objective'),
  worldSource: document.querySelector('#world-source'),
  fragments: [...document.querySelectorAll('[data-fragment]')],
  interaction: document.querySelector('#interaction'),
  interactionLabel: document.querySelector('#interaction span'),
  reticle: document.querySelector('#reticle'),
  toast: document.querySelector('#toast'),
  toastText: document.querySelector('#toast p'),
  journal: document.querySelector('#journal'),
  journalList: document.querySelector('#journal-list'),
  journalEmpty: document.querySelector('#journal-empty'),
  journalButton: document.querySelector('#journal-btn'),
  hintButton: document.querySelector('#hint-btn'),
  cipher: document.querySelector('#cipher'),
  dials: document.querySelector('#dials'),
  cipherError: document.querySelector('#cipher-error'),
  submitCode: document.querySelector('#submit-code'),
  pause: document.querySelector('#pause'),
  ending: document.querySelector('#ending'),
  finalTime: document.querySelector('#final-time'),
  finalHints: document.querySelector('#final-hints'),
  finalRank: document.querySelector('#final-rank'),
  restart: document.querySelector('#restart-btn'),
  movement: [...document.querySelectorAll('.movement span')],
};

const transmissions = [
  {
    id: 'ORBIT-03',
    glyph: '△',
    title: '近地点 / 第一轨道',
    text: '译文：第一座望远镜越过两颗暗星，在第三颗星前停下。首位轨道常量为 3。',
    location: '西侧沉降书库',
  },
  {
    id: 'MIRROR-01',
    glyph: '◉',
    title: '月镜 / 第二轨道',
    text: '译文：破碎的月镜只保留一轮完整倒影。第二位轨道常量为 1。',
    location: '东侧潮汐仪廊',
  },
  {
    id: 'TIDE-04',
    glyph: '◇',
    title: '回潮 / 第三轨道',
    text: '译文：末次潮汐敲响四次，门才记起归航坐标。末位轨道常量为 4。',
    location: '南侧观测平台',
  },
];

const state = {
  started: false,
  ended: false,
  solved: false,
  collected: [false, false, false],
  hintCount: 0,
  startTime: 0,
  elapsed: 0,
  modal: null,
  target: null,
  toastTimer: null,
  dials: [0, 0, 0],
};
const demoMode = new URLSearchParams(location.search).get('demo') === '1';

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x03070b);
scene.fog = new THREE.FogExp2(0x071117, 0.028);

const camera = new THREE.PerspectiveCamera(70, innerWidth / innerHeight, 0.05, 160);
camera.rotation.order = 'YXZ';
camera.position.set(0, 1.68, 13.3);

const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' });
renderer.setPixelRatio(Math.min(devicePixelRatio, 1.65));
renderer.setSize(innerWidth, innerHeight);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 0.92;

const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
const bloom = new UnrealBloomPass(new THREE.Vector2(innerWidth, innerHeight), 0.62, 0.72, 0.78);
composer.addPass(bloom);

const clock = new THREE.Clock();
const raycaster = new THREE.Raycaster();
const centerNdc = new THREE.Vector2(0, 0);
const interactables = [];
const obstacles = [];
const animated = [];
const keys = new Set();
let yaw = 0;
let pitch = 0;
let audioContext;
let fallbackControl = false;
let dragLooking = false;
let hadPointerLock = false;
let atmosphereMesh;

function requestGamePointerLock() {
  try {
    const request = canvas.requestPointerLock?.();
    if (request?.catch) request.catch(() => {
      fallbackControl = true;
      ui.pause.classList.add('hidden');
    });
  } catch {
    // Embedded preview surfaces may not grant pointer lock; the game remains inspectable.
    fallbackControl = true;
    ui.pause.classList.add('hidden');
  }
}

const colors = {
  cyan: 0x65f4d3,
  cyanPale: 0xb9fff0,
  concrete: 0x1b2428,
  dark: 0x071014,
  brass: 0x8b6c3e,
  red: 0xff756b,
};

function material(color, options = {}) {
  return new THREE.MeshStandardMaterial({ color, roughness: 0.72, metalness: 0.12, ...options });
}

function addObstacle(mesh, padding = 0.12) {
  mesh.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(mesh).expandByScalar(padding);
  obstacles.push(box);
}

function makeBox(size, position, color = colors.concrete, rotationY = 0, collidable = true) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), material(color));
  mesh.position.set(...position);
  mesh.rotation.y = rotationY;
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  scene.add(mesh);
  if (collidable) addObstacle(mesh);
  return mesh;
}

function makeGlyphTexture(glyph) {
  const glyphCanvas = document.createElement('canvas');
  glyphCanvas.width = 256;
  glyphCanvas.height = 256;
  const context = glyphCanvas.getContext('2d');
  context.clearRect(0, 0, 256, 256);
  context.strokeStyle = '#76f6da';
  context.lineWidth = 3;
  context.beginPath();
  context.arc(128, 128, 94, 0, Math.PI * 2);
  context.stroke();
  context.fillStyle = '#bafff0';
  context.font = '90px Georgia';
  context.textAlign = 'center';
  context.textBaseline = 'middle';
  context.fillText(glyph, 128, 125);
  const texture = new THREE.CanvasTexture(glyphCanvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function createAtmosphere() {
  const geometry = new THREE.SphereGeometry(70, 48, 32);
  const shader = new THREE.ShaderMaterial({
    side: THREE.BackSide,
    uniforms: { time: { value: 0 } },
    vertexShader: `varying vec3 vPos; void main(){ vPos=position; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0); }`,
    fragmentShader: `
      varying vec3 vPos; uniform float time;
      float hash(vec3 p){ p=fract(p*.1031); p+=dot(p,p.yzx+33.33); return fract((p.x+p.y)*p.z); }
      void main(){
        vec3 d=normalize(vPos); float horizon=pow(1.0-abs(d.y),3.0);
        vec3 col=mix(vec3(.005,.012,.02),vec3(.025,.09,.10),horizon);
        float stars=step(.997,hash(floor(d*520.0)))*smoothstep(-.1,.15,d.y);
        float aurora=pow(max(0.0,sin(d.x*9.0+d.z*5.0+time*.04)*.5+.5),10.0)*horizon*.15;
        gl_FragColor=vec4(col+stars*.7+vec3(.05,.8,.55)*aurora,1.0);
      }`,
  });
  const sky = new THREE.Mesh(geometry, shader);
  scene.add(sky);
  atmosphereMesh = sky;
  animated.push({ update: (_, t) => { shader.uniforms.time.value = t; } });
}

function createArchitecture() {
  const floor = new THREE.Mesh(
    new THREE.CylinderGeometry(18, 18, 0.35, 80),
    material(0x10191d, { roughness: 0.35, metalness: 0.42 }),
  );
  floor.position.y = -0.2;
  floor.receiveShadow = true;
  scene.add(floor);

  const inset = new THREE.Mesh(
    new THREE.RingGeometry(3.1, 15.7, 96),
    new THREE.MeshStandardMaterial({ color: 0x102428, roughness: 0.2, metalness: 0.55, transparent: true, opacity: 0.72, side: THREE.DoubleSide }),
  );
  inset.rotation.x = -Math.PI / 2;
  inset.position.y = 0.01;
  scene.add(inset);

  for (let i = 0; i < 32; i += 1) {
    if (i >= 23 && i <= 25) continue;
    const angle = (i / 32) * Math.PI * 2;
    const wall = makeBox([3.55, 5.6, 0.65], [Math.cos(angle) * 17.45, 2.6, Math.sin(angle) * 17.45], colors.concrete, -angle + Math.PI / 2, false);
    wall.material.color.offsetHSL(0, 0, (i % 3) * 0.012);
  }

  for (const side of [-1, 1]) {
    makeBox([1.25, 7.4, 1.45], [side * 3.15, 3.45, -16.35], 0x263135, 0, true);
  }
  const lintel = makeBox([7.6, 1.25, 1.45], [0, 6.45, -16.35], 0x263135, 0, false);
  lintel.castShadow = true;

  const seamMaterial = new THREE.MeshBasicMaterial({ color: colors.cyan, transparent: true, opacity: 0.28, blending: THREE.AdditiveBlending });
  for (const radius of [3.5, 8.8, 15.55]) {
    const ring = new THREE.Mesh(new THREE.RingGeometry(radius - 0.025, radius + 0.025, 96), seamMaterial.clone());
    ring.rotation.x = -Math.PI / 2;
    ring.position.y = 0.025;
    scene.add(ring);
  }

  for (let i = 0; i < 10; i += 1) {
    const angle = (i / 10) * Math.PI * 2 + 0.12;
    const radius = i % 2 ? 9.8 : 7.3;
    const shelf = makeBox([4.15, 2.9, 0.72], [Math.cos(angle) * radius, 1.42, Math.sin(angle) * radius], 0x192225, -angle + Math.PI / 2, true);
    shelf.material.metalness = 0.35;
    for (let y = 0.35; y < 2.6; y += 0.56) {
      const line = new THREE.Mesh(new THREE.BoxGeometry(3.8, 0.035, 0.77), new THREE.MeshBasicMaterial({ color: 0x36504f }));
      line.position.set(0, y - 1.42, 0);
      shelf.add(line);
    }
  }

  for (let i = 0; i < 8; i += 1) {
    const angle = (i / 8) * Math.PI * 2 + Math.PI / 8;
    const pillar = new THREE.Mesh(new THREE.CylinderGeometry(0.42, 0.6, 5.2, 8), material(0x202b2e));
    pillar.position.set(Math.cos(angle) * 13.9, 2.55, Math.sin(angle) * 13.9);
    pillar.castShadow = true;
    scene.add(pillar);
    addObstacle(pillar, 0.08);
    const cap = new THREE.PointLight(colors.cyan, 1.2, 5.5, 2);
    cap.position.copy(pillar.position).setY(4.85);
    scene.add(cap);
  }

  const moon = new THREE.DirectionalLight(0x9ddaf0, 2.7);
  moon.position.set(-7, 14, 9);
  moon.castShadow = true;
  moon.shadow.mapSize.set(1024, 1024);
  moon.shadow.camera.left = -22;
  moon.shadow.camera.right = 22;
  moon.shadow.camera.top = 22;
  moon.shadow.camera.bottom = -22;
  scene.add(moon);
  scene.add(new THREE.HemisphereLight(0x39636d, 0x020406, 0.82));

  const beamMaterial = new THREE.MeshBasicMaterial({ color: 0x62d9c4, transparent: true, opacity: 0.035, depthWrite: false, side: THREE.DoubleSide, blending: THREE.AdditiveBlending });
  for (let i = 0; i < 4; i += 1) {
    const beam = new THREE.Mesh(new THREE.ConeGeometry(2.4, 13, 24, 1, true), beamMaterial.clone());
    beam.position.set(-10 + i * 6.7, 7.5, -2 + (i % 2) * 5);
    beam.rotation.z = (i - 1.5) * 0.12;
    scene.add(beam);
  }
}

function createOrrery() {
  const group = new THREE.Group();
  group.position.y = 1.6;
  scene.add(group);

  const base = new THREE.Mesh(new THREE.CylinderGeometry(1.65, 2.1, 1.1, 12), material(0x1b2426, { metalness: 0.6, roughness: 0.38 }));
  base.position.y = -1.03;
  base.castShadow = true;
  group.add(base);
  base.updateMatrixWorld(true);
  obstacles.push(new THREE.Box3(new THREE.Vector3(-2.15, -0.1, -2.15), new THREE.Vector3(2.15, 2.2, 2.15)));

  const coreMaterial = new THREE.MeshStandardMaterial({ color: 0x102a2a, emissive: colors.cyan, emissiveIntensity: 1.1, roughness: 0.18, metalness: 0.65 });
  const core = new THREE.Mesh(new THREE.IcosahedronGeometry(0.48, 1), coreMaterial);
  core.userData.interaction = { type: 'console' };
  group.add(core);
  interactables.push(core);

  const ringMaterial = new THREE.MeshStandardMaterial({ color: colors.brass, emissive: 0x261907, emissiveIntensity: 0.25, roughness: 0.28, metalness: 0.92 });
  const rings = [];
  [1.05, 1.43, 1.82].forEach((radius, index) => {
    const ring = new THREE.Mesh(new THREE.TorusGeometry(radius, 0.045, 10, 100), ringMaterial);
    ring.rotation.set(index * 0.75, index * 0.42, index * 0.56);
    group.add(ring);
    rings.push(ring);
  });

  const coreLight = new THREE.PointLight(colors.cyan, 3, 7, 2);
  group.add(coreLight);
  animated.push({
    update: (dt, t) => {
      rings.forEach((ring, i) => { ring.rotation.z += dt * (0.12 + i * 0.06) * (i % 2 ? -1 : 1); });
      core.rotation.y += dt * 0.4;
      core.position.y = Math.sin(t * 1.5) * 0.12;
      coreMaterial.emissiveIntensity = state.solved ? 3.2 : 0.85 + Math.sin(t * 2.1) * 0.25;
      coreLight.intensity = state.solved ? 6 : 2.5;
    },
  });
}

function createFragments() {
  const positions = [
    new THREE.Vector3(-11.9, 1.45, -4.5),
    new THREE.Vector3(11.7, 1.45, -5.7),
    new THREE.Vector3(-1.5, 1.45, 12.7),
  ];

  positions.forEach((position, index) => {
    const group = new THREE.Group();
    group.position.copy(position);
    scene.add(group);

    const pedestal = new THREE.Mesh(new THREE.CylinderGeometry(0.6, 0.83, 1.7, 6), material(0x1d282a, { metalness: 0.45 }));
    pedestal.position.y = -0.95;
    pedestal.castShadow = true;
    group.add(pedestal);
    group.updateMatrixWorld(true);
    addObstacle(pedestal, 0.1);

    const shardMaterial = new THREE.MeshStandardMaterial({ color: colors.cyanPale, emissive: colors.cyan, emissiveIntensity: 2.4, roughness: 0.18, metalness: 0.5 });
    const shard = new THREE.Mesh(new THREE.OctahedronGeometry(0.48, 0), shardMaterial);
    shard.scale.y = 1.45;
    shard.userData.interaction = { type: 'fragment', id: index };
    shard.castShadow = true;
    group.add(shard);
    interactables.push(shard);

    const glyph = new THREE.Mesh(new THREE.PlaneGeometry(0.68, 0.68), new THREE.MeshBasicMaterial({ map: makeGlyphTexture(transmissions[index].glyph), transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide }));
    glyph.position.z = 0.5;
    group.add(glyph);

    const halo = new THREE.Mesh(new THREE.TorusGeometry(0.82, 0.025, 8, 64), new THREE.MeshBasicMaterial({ color: colors.cyan, transparent: true, opacity: 0.65, blending: THREE.AdditiveBlending }));
    halo.rotation.x = Math.PI / 2;
    group.add(halo);

    const light = new THREE.PointLight(colors.cyan, 4.5, 6.5, 2);
    group.add(light);
    animated.push({
      update: (dt, t) => {
        group.rotation.y += state.collected[index] ? dt * 0.08 : dt * 0.36;
        shard.position.y = Math.sin(t * 1.7 + index) * 0.12;
        halo.rotation.z -= dt * 0.3;
        halo.scale.setScalar(1 + Math.sin(t * 2 + index) * 0.06);
        if (state.collected[index]) {
          shardMaterial.emissiveIntensity = 0.08;
          shardMaterial.color.setHex(0x31413f);
          light.intensity = 0;
          halo.material.opacity = 0.1;
        }
      },
    });
  });
}

function createPortal() {
  const group = new THREE.Group();
  group.position.set(0, 2.3, -15.78);
  scene.add(group);

  const frameMaterial = material(0x354144, { metalness: 0.75, roughness: 0.3 });
  const frame = new THREE.Mesh(new THREE.TorusGeometry(2.35, 0.22, 14, 72), frameMaterial);
  frame.scale.y = 1.25;
  group.add(frame);

  const gateMaterial = new THREE.MeshBasicMaterial({ color: colors.cyan, transparent: true, opacity: 0.035, side: THREE.DoubleSide, blending: THREE.AdditiveBlending, depthWrite: false });
  const gate = new THREE.Mesh(new THREE.CircleGeometry(2.05, 64), gateMaterial);
  gate.userData.interaction = { type: 'portal' };
  group.add(gate);
  interactables.push(gate);

  const runes = [];
  for (let i = 0; i < 12; i += 1) {
    const rune = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.25, 0.035), new THREE.MeshBasicMaterial({ color: colors.cyan, transparent: true, opacity: 0.18 }));
    const angle = (i / 12) * Math.PI * 2;
    rune.position.set(Math.cos(angle) * 2.65, Math.sin(angle) * 3.05, 0);
    rune.rotation.z = angle;
    group.add(rune);
    runes.push(rune);
  }

  const portalLight = new THREE.PointLight(colors.cyan, 0, 10, 2);
  portalLight.position.z = 1;
  group.add(portalLight);
  animated.push({
    update: (dt, t) => {
      group.rotation.z += state.solved ? dt * 0.08 : 0;
      gateMaterial.opacity = state.solved ? 0.45 + Math.sin(t * 3) * 0.12 : 0.025;
      portalLight.intensity = state.solved ? 7 + Math.sin(t * 2) : 0;
      runes.forEach((rune, i) => { rune.material.opacity = state.solved ? 0.45 + Math.sin(t * 2 + i) * 0.25 : 0.08; });
    },
  });
}

function createParticles() {
  const count = 720;
  const positions = new Float32Array(count * 3);
  for (let i = 0; i < count; i += 1) {
    const radius = Math.sqrt(Math.random()) * 17;
    const angle = Math.random() * Math.PI * 2;
    positions[i * 3] = Math.cos(angle) * radius;
    positions[i * 3 + 1] = 0.15 + Math.random() * 7.5;
    positions[i * 3 + 2] = Math.sin(angle) * radius;
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  const points = new THREE.Points(geometry, new THREE.PointsMaterial({ color: 0x8df9e5, size: 0.028, transparent: true, opacity: 0.48, depthWrite: false, blending: THREE.AdditiveBlending }));
  scene.add(points);
  animated.push({ update: (dt) => { points.rotation.y += dt * 0.012; } });
}

function createScene() {
  createAtmosphere();
  createArchitecture();
  createOrrery();
  createFragments();
  createPortal();
  createParticles();
}

async function loadAholoWorld() {
  try {
    const response = await fetch(`/generated/world.json?t=${Date.now()}`);
    if (!response.ok) throw new Error('manifest missing');
    const manifest = await response.json();
    const progress = Math.round((manifest.progress || 0) * 100);
    if (manifest.status === 'SUCCEEDED' && manifest.panoFile) {
      ui.worldSource.textContent = 'Aholo 生成空间 · 已同步';
      const texture = await new THREE.TextureLoader().loadAsync(manifest.panoFile);
      texture.mapping = THREE.EquirectangularReflectionMapping;
      texture.colorSpace = THREE.SRGBColorSpace;
      scene.background = texture;
      scene.environment = texture;
      atmosphereMesh.visible = false;
    } else if (manifest.status === 'FAILED') {
      ui.worldSource.textContent = '程序化档案馆 · 世界生成失败';
    } else {
      ui.worldSource.textContent = `Aholo 生成中 · ${progress}%`;
    }
  } catch {
    ui.worldSource.textContent = '程序化空间 · 离线模式';
  }
}

function formatTime(ms) {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
}

function showToast(message, duration = 4300) {
  clearTimeout(state.toastTimer);
  ui.toastText.textContent = message;
  ui.toast.classList.remove('hidden');
  state.toastTimer = setTimeout(() => ui.toast.classList.add('hidden'), duration);
}

function tone(frequency = 440, duration = 0.12, type = 'sine', gain = 0.08) {
  if (!audioContext) return;
  const oscillator = audioContext.createOscillator();
  const amp = audioContext.createGain();
  oscillator.type = type;
  oscillator.frequency.value = frequency;
  amp.gain.setValueAtTime(0.0001, audioContext.currentTime);
  amp.gain.exponentialRampToValueAtTime(gain, audioContext.currentTime + 0.015);
  amp.gain.exponentialRampToValueAtTime(0.0001, audioContext.currentTime + duration);
  oscillator.connect(amp).connect(audioContext.destination);
  oscillator.start();
  oscillator.stop(audioContext.currentTime + duration + 0.02);
}

function playSuccessChord() {
  [196, 293.66, 392, 587.33].forEach((frequency, index) => setTimeout(() => tone(frequency, 1.5, 'sine', 0.06), index * 130));
}

function updateJournal() {
  ui.journalList.innerHTML = '';
  let count = 0;
  transmissions.forEach((item, index) => {
    if (!state.collected[index]) return;
    count += 1;
    const entry = document.createElement('article');
    entry.className = 'journal-entry';
    entry.innerHTML = `<div class="sigil"><span>${item.glyph}</span></div><div><small>${item.id}</small><h3>${item.title}</h3><p>${item.text}</p></div>`;
    ui.journalList.append(entry);
  });
  ui.journalEmpty.classList.toggle('hidden', count > 0);
}

function updateObjective() {
  const count = state.collected.filter(Boolean).length;
  ui.fragments.forEach((fragment, index) => fragment.classList.toggle('active', state.collected[index]));
  if (state.solved) ui.objective.textContent = '前往北侧星门，上传归航坐标';
  else if (count === 3) ui.objective.textContent = '返回中央星仪，校准三段轨道常量';
  else ui.objective.textContent = `回收星图密钥 · ${count} / 3`;
}

function openModal(name) {
  state.modal = name;
  document.exitPointerLock?.();
  ui.pause.classList.add('hidden');
  ui[name].classList.remove('hidden');
  if (name === 'journal') updateJournal();
  if (name === 'cipher') renderDials();
}

function closeModal(name) {
  ui[name].classList.add('hidden');
  state.modal = null;
  if (state.started && !state.ended) requestGamePointerLock();
}

function collectFragment(index) {
  if (state.collected[index]) {
    showToast('该信号已写入日志。按 J 可随时复核。');
    return;
  }
  state.collected[index] = true;
  updateJournal();
  updateObjective();
  tone(330 + index * 110, 0.7, 'sine', 0.09);
  showToast(`已回收 ${transmissions[index].id}。${transmissions[index].text}`);
  if (state.collected.every(Boolean)) {
    setTimeout(() => {
      tone(740, 0.8, 'triangle', 0.06);
      showToast('三枚密钥形成共振：中央星仪已开放校准接口。', 5200);
    }, 1300);
  }
}

function interact() {
  if (!state.target || state.modal || state.ended) return;
  const { type, id } = state.target;
  if (type === 'fragment') collectFragment(id);
  if (type === 'console') {
    if (!state.collected.every(Boolean)) {
      const missing = state.collected.filter((value) => !value).length;
      tone(120, 0.15, 'square', 0.03);
      showToast(`星仪拒绝同步：仍缺少 ${missing} 枚星图密钥。`);
    } else if (!state.solved) openModal('cipher');
    else showToast('星仪已对齐。北侧星门正在等待归航坐标。');
  }
  if (type === 'portal') {
    if (state.solved) finishGame();
    else showToast('星门处于锁定状态。中央星仪尚未完成校准。');
  }
}

function renderDials() {
  ui.dials.innerHTML = '';
  state.dials.forEach((value, index) => {
    const dial = document.createElement('div');
    dial.className = 'dial';
    dial.innerHTML = `<button type="button" data-dial="${index}" data-step="1" aria-label="增加第 ${index + 1} 位">⌃</button><strong>${value}</strong><button type="button" data-dial="${index}" data-step="-1" aria-label="减少第 ${index + 1} 位">⌄</button>`;
    ui.dials.append(dial);
  });
}

function changeDial(index, step) {
  state.dials[index] = (state.dials[index] + step + 10) % 10;
  tone(220 + state.dials[index] * 18, 0.08, 'triangle', 0.035);
  renderDials();
}

function submitCipher() {
  if (state.dials.join('') === '314') {
    state.solved = true;
    ui.cipherError.textContent = '';
    updateObjective();
    closeModal('cipher');
    playSuccessChord();
    showToast('星图校准完成。北侧星门已开启——带着归航坐标离开这里。', 6500);
  } else {
    ui.cipherError.textContent = '轨道相位不匹配 · 请检查三段信号的先后顺序';
    tone(96, 0.35, 'sawtooth', 0.03);
  }
}

function requestHint() {
  state.hintCount += 1;
  const missingIndex = state.collected.findIndex((value) => !value);
  if (missingIndex >= 0) {
    const distance = camera.position.distanceTo([
      new THREE.Vector3(-11.9, 1.45, -4.5),
      new THREE.Vector3(11.7, 1.45, -5.7),
      new THREE.Vector3(-1.5, 1.45, 12.7),
    ][missingIndex]);
    showToast(`信号扫描：${transmissions[missingIndex].location}，距离约 ${Math.round(distance)} 米。寻找青色脉冲。`, 5500);
  } else if (!state.solved) {
    showToast('译码提示：按日志编号排列，三个轨道常量分别来自“三颗星、一轮月、四次潮”。', 6000);
  } else {
    showToast('出口提示：北侧是你初始朝向的正前方，星门位于高拱门之下。', 5000);
  }
}

function finishGame() {
  state.ended = true;
  state.elapsed = performance.now() - state.startTime;
  document.exitPointerLock?.();
  ui.hud.classList.add('hidden');
  ui.pause.classList.add('hidden');
  ui.ending.classList.remove('hidden');
  ui.finalTime.textContent = formatTime(state.elapsed);
  ui.finalHints.textContent = String(state.hintCount);
  const seconds = state.elapsed / 1000;
  ui.finalRank.textContent = state.hintCount === 0 && seconds < 240 ? 'S' : state.hintCount <= 2 && seconds < 420 ? 'A' : 'B';
  playSuccessChord();
}

function startGame() {
  if (state.started) return;
  state.started = true;
  state.startTime = performance.now();
  ui.boot.classList.add('hidden');
  ui.hud.classList.remove('hidden');
  audioContext = new (window.AudioContext || window.webkitAudioContext)();
  tone(220, 0.4, 'sine', 0.04);
  requestGamePointerLock();
  showToast('通讯恢复。追踪三处青色空间脉冲，读取星图密钥。', 5200);
  if (demoMode) setTimeout(() => openModal('cipher'), 450);
}

function playerCollides(position) {
  const radius = 0.34;
  if (Math.hypot(position.x, position.z) > 16.05) return true;
  const playerBox = new THREE.Box3(
    new THREE.Vector3(position.x - radius, 0.12, position.z - radius),
    new THREE.Vector3(position.x + radius, 1.82, position.z + radius),
  );
  return obstacles.some((box) => box.intersectsBox(playerBox));
}

function updateMovement(dt) {
  if (!state.started || state.ended || state.modal || (document.pointerLockElement !== canvas && !fallbackControl)) return;
  const forwardAmount = (keys.has('KeyW') || keys.has('ArrowUp') ? 1 : 0) - (keys.has('KeyS') || keys.has('ArrowDown') ? 1 : 0);
  const sideAmount = (keys.has('KeyD') || keys.has('ArrowRight') ? 1 : 0) - (keys.has('KeyA') || keys.has('ArrowLeft') ? 1 : 0);
  if (!forwardAmount && !sideAmount) return;

  const input = new THREE.Vector3(sideAmount, 0, -forwardAmount).normalize();
  input.applyAxisAngle(new THREE.Vector3(0, 1, 0), yaw);
  const speed = (keys.has('ShiftLeft') || keys.has('ShiftRight')) ? 5.35 : 3.55;
  const move = input.multiplyScalar(speed * Math.min(dt, 0.05));
  const candidateX = camera.position.clone();
  candidateX.x += move.x;
  if (!playerCollides(candidateX)) camera.position.x = candidateX.x;
  const candidateZ = camera.position.clone();
  candidateZ.z += move.z;
  if (!playerCollides(candidateZ)) camera.position.z = candidateZ.z;
  camera.position.y = 1.68 + Math.sin(performance.now() * 0.011) * 0.018;
}

function updateTarget() {
  if (!state.started || state.ended || state.modal) return;
  raycaster.setFromCamera(centerNdc, camera);
  const hit = raycaster.intersectObjects(interactables, false).find((result) => result.distance <= 3.75);
  state.target = hit?.object.userData.interaction || null;
  ui.interaction.classList.toggle('hidden', !state.target);
  ui.reticle.classList.toggle('active', Boolean(state.target));
  if (!state.target) return;
  if (state.target.type === 'fragment') ui.interactionLabel.textContent = state.collected[state.target.id] ? '复核信号' : '读取密钥';
  if (state.target.type === 'console') ui.interactionLabel.textContent = state.solved ? '查看星仪' : '校准星图';
  if (state.target.type === 'portal') ui.interactionLabel.textContent = state.solved ? '上传坐标并离开' : '检查星门';
}

function animate() {
  requestAnimationFrame(animate);
  const dt = Math.min(clock.getDelta(), 0.05);
  const t = clock.elapsedTime;
  updateMovement(dt);
  updateTarget();
  animated.forEach((item) => item.update(dt, t));
  if (state.started && !state.ended) {
    state.elapsed = performance.now() - state.startTime;
    ui.timer.textContent = formatTime(state.elapsed);
  }
  composer.render();
}

ui.start.addEventListener('click', startGame);
ui.restart.addEventListener('click', () => location.reload());
ui.journalButton.addEventListener('click', () => openModal('journal'));
ui.hintButton.addEventListener('click', requestHint);
ui.submitCode.addEventListener('click', submitCipher);
ui.dials.addEventListener('click', (event) => {
  const button = event.target.closest('[data-dial]');
  if (button) changeDial(Number(button.dataset.dial), Number(button.dataset.step));
});
document.querySelectorAll('[data-close]').forEach((button) => button.addEventListener('click', () => closeModal(button.dataset.close)));

document.addEventListener('keydown', (event) => {
  keys.add(event.code);
  if (event.code === 'Enter' && !state.started) startGame();
  if (event.code === 'KeyR' && state.ended) location.reload();
  if (!state.started || state.ended) return;
  if (event.code === 'KeyE' && !event.repeat) interact();
  if (event.code === 'KeyJ' && !event.repeat) state.modal === 'journal' ? closeModal('journal') : !state.modal && openModal('journal');
  if (event.code === 'KeyH' && !event.repeat && !state.modal) requestHint();
  if (event.code === 'Escape' && state.modal) closeModal(state.modal);
  ['KeyW', 'KeyA', 'KeyS', 'KeyD'].forEach((code, index) => ui.movement[index].classList.toggle('active', keys.has(code)));
});
document.addEventListener('keyup', (event) => {
  keys.delete(event.code);
  ['KeyW', 'KeyA', 'KeyS', 'KeyD'].forEach((code, index) => ui.movement[index].classList.toggle('active', keys.has(code)));
});

document.addEventListener('mousemove', (event) => {
  if ((document.pointerLockElement !== canvas && !(fallbackControl && dragLooking)) || state.modal) return;
  yaw -= event.movementX * 0.0022;
  pitch -= event.movementY * 0.002;
  pitch = THREE.MathUtils.clamp(pitch, -1.35, 1.35);
  camera.rotation.set(pitch, yaw, 0);
});

document.addEventListener('pointerlockchange', () => {
  if (!state.started || state.ended || state.modal) return;
  if (document.pointerLockElement === canvas) {
    hadPointerLock = true;
    fallbackControl = false;
    ui.pause.classList.add('hidden');
  } else if (hadPointerLock) {
    fallbackControl = false;
    ui.pause.classList.remove('hidden');
  }
});
canvas.addEventListener('click', () => {
  if (state.started && !state.ended && !state.modal && document.pointerLockElement !== canvas) {
    fallbackControl = true;
    ui.pause.classList.add('hidden');
    requestGamePointerLock();
  }
});
canvas.addEventListener('mousedown', () => { dragLooking = true; });
document.addEventListener('mouseup', () => { dragLooking = false; });

window.addEventListener('resize', () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
  composer.setSize(innerWidth, innerHeight);
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1.65));
});

createScene();
if (demoMode) {
  state.collected = [true, true, true];
  updateJournal();
}
updateObjective();
loadAholoWorld();
animate();
