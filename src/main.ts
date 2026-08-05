import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import "./style.css";

const SPLAT_COUNT = 60_000;

type ShapeName = "galaxy" | "sphere" | "torus";
const SHAPES: ShapeName[] = ["galaxy", "sphere", "torus"];

const canvas = document.querySelector<HTMLCanvasElement>("#scene")!;
const statCount = document.querySelector<HTMLElement>("#stat-count")!;
const statFps = document.querySelector<HTMLElement>("#stat-fps")!;
const btnRegen = document.querySelector<HTMLButtonElement>("#btn-regen")!;
const btnShape = document.querySelector<HTMLButtonElement>("#btn-shape")!;
const btnRotate = document.querySelector<HTMLButtonElement>("#btn-rotate")!;

const renderer = new THREE.WebGLRenderer({
  canvas,
  antialias: true,
  alpha: false,
});
renderer.setClearColor(0x05060b, 1);

const scene = new THREE.Scene();
scene.fog = new THREE.FogExp2(0x05060b, 0.055);

const camera = new THREE.PerspectiveCamera(60, 1, 0.1, 100);
camera.position.set(0, 2.2, 7);

const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.autoRotate = true;
controls.autoRotateSpeed = 0.8;
controls.minDistance = 2.5;
controls.maxDistance = 18;

// A round, soft sprite texture so each splat reads as a fuzzy gaussian blob
// rather than a hard square — a lightweight stand-in for real 3DGS splats.
function makeSplatTexture(): THREE.Texture {
  const size = 64;
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const ctx = c.getContext("2d")!;
  const g = ctx.createRadialGradient(
    size / 2,
    size / 2,
    0,
    size / 2,
    size / 2,
    size / 2
  );
  g.addColorStop(0, "rgba(255,255,255,1)");
  g.addColorStop(0.35, "rgba(255,255,255,0.65)");
  g.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, size, size);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

const splatTexture = makeSplatTexture();

const geometry = new THREE.BufferGeometry();
const positions = new Float32Array(SPLAT_COUNT * 3);
const colors = new Float32Array(SPLAT_COUNT * 3);
geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));

const material = new THREE.PointsMaterial({
  size: 0.07,
  map: splatTexture,
  vertexColors: true,
  transparent: true,
  depthWrite: false,
  blending: THREE.AdditiveBlending,
  sizeAttenuation: true,
});

const points = new THREE.Points(geometry, material);
scene.add(points);

const inside = new THREE.Color();
const outside = new THREE.Color();
const tmp = new THREE.Color();

function buildShape(shape: ShapeName): void {
  inside.setHSL(Math.random(), 0.85, 0.6);
  outside.setHSL(Math.random(), 0.75, 0.5);

  for (let i = 0; i < SPLAT_COUNT; i++) {
    const i3 = i * 3;
    let x = 0;
    let y = 0;
    let z = 0;
    let t = 0;

    if (shape === "galaxy") {
      const radius = Math.pow(Math.random(), 0.7) * 5;
      const branch = ((i % 4) / 4) * Math.PI * 2;
      const spin = radius * 0.9;
      const spread = 0.35 * radius;
      const rx = (Math.random() - 0.5) * spread;
      const ry = (Math.random() - 0.5) * spread * 0.4;
      const rz = (Math.random() - 0.5) * spread;
      x = Math.cos(branch + spin) * radius + rx;
      y = ry;
      z = Math.sin(branch + spin) * radius + rz;
      t = radius / 5;
    } else if (shape === "sphere") {
      const r = 3.4 * Math.cbrt(Math.random());
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      x = r * Math.sin(phi) * Math.cos(theta);
      y = r * Math.cos(phi);
      z = r * Math.sin(phi) * Math.sin(theta);
      t = r / 3.4;
    } else {
      const R = 3.2;
      const tube = 1.1;
      const u = Math.random() * Math.PI * 2;
      const v = Math.random() * Math.PI * 2;
      const jitter = (Math.random() - 0.5) * 0.3;
      x = (R + tube * Math.cos(v)) * Math.cos(u);
      y = (tube + jitter) * Math.sin(v);
      z = (R + tube * Math.cos(v)) * Math.sin(u);
      t = (Math.cos(v) + 1) / 2;
    }

    positions[i3] = x;
    positions[i3 + 1] = y;
    positions[i3 + 2] = z;

    tmp.copy(inside).lerp(outside, t);
    colors[i3] = tmp.r;
    colors[i3 + 1] = tmp.g;
    colors[i3 + 2] = tmp.b;
  }

  geometry.attributes.position.needsUpdate = true;
  geometry.attributes.color.needsUpdate = true;
  geometry.computeBoundingSphere();
  statCount.textContent = SPLAT_COUNT.toLocaleString();
}

let shapeIndex = 0;
buildShape(SHAPES[shapeIndex]);

btnRegen.addEventListener("click", () => buildShape(SHAPES[shapeIndex]));

btnShape.addEventListener("click", () => {
  shapeIndex = (shapeIndex + 1) % SHAPES.length;
  buildShape(SHAPES[shapeIndex]);
});

btnRotate.addEventListener("click", () => {
  controls.autoRotate = !controls.autoRotate;
  btnRotate.setAttribute("aria-pressed", String(controls.autoRotate));
  btnRotate.textContent = `Auto-rotate: ${controls.autoRotate ? "on" : "off"}`;
});

function resize(): void {
  const w = window.innerWidth;
  const h = window.innerHeight;
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
window.addEventListener("resize", resize);
resize();

let lastFpsSample = performance.now();
let frames = 0;

function animate(): void {
  requestAnimationFrame(animate);
  controls.update();
  renderer.render(scene, camera);

  frames++;
  const now = performance.now();
  if (now - lastFpsSample >= 500) {
    statFps.textContent = String(Math.round((frames * 1000) / (now - lastFpsSample)));
    frames = 0;
    lastFpsSample = now;
  }
}
animate();
