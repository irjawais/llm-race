// llm-race v0.3 — Three.js renderer + telemetry HUD.
// One file, no bundler. Loaded as ES module via importmap.

import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js';
import { FXAAShader } from 'three/addons/shaders/FXAAShader.js';

// ---------- DOM refs ----------
const canvas = document.getElementById('scene');
const clockEl = document.getElementById('clock');
const fpsEl = document.getElementById('fps-text');
const statusEl = document.getElementById('status-text');
const statusContainer = document.querySelector('.status');
const panelsEl = document.getElementById('hud-panels');
const leaderEl = document.getElementById('leader-callout');
const leaderName = document.getElementById('leader-name');
const leaderDelta = document.getElementById('leader-delta');
const promptEl = document.getElementById('prompt-text');
const targetEl = document.getElementById('target-text');
const missionTitle = document.getElementById('mission-title');
const finishOverlay = document.getElementById('finish-overlay');
const finishName = document.getElementById('finish-name');
const finishStats = document.getElementById('finish-stats');

// ---------- Three.js setup ----------
const renderer = new THREE.WebGLRenderer({
  canvas,
  antialias: true,
  alpha: false,
  powerPreference: 'high-performance',
});
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setClearColor(0x05060A, 1);

const scene = new THREE.Scene();
scene.fog = new THREE.FogExp2(0x05060A, 0.018);

const camera = new THREE.PerspectiveCamera(42, window.innerWidth / window.innerHeight, 0.1, 600);
camera.position.set(0, 4.2, 18);
camera.lookAt(0, 1.0, -40);

// Star/dust field — subtle dot points receding into fog.
const dustGeo = new THREE.BufferGeometry();
{
  const N = 1500;
  const positions = new Float32Array(N * 3);
  for (let i = 0; i < N; i++) {
    positions[i * 3 + 0] = (Math.random() - 0.5) * 200;
    positions[i * 3 + 1] = Math.random() * 80 - 4;
    positions[i * 3 + 2] = -Math.random() * 400;
  }
  dustGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
}
const dustMat = new THREE.PointsMaterial({
  color: 0x1F2937, size: 0.18, sizeAttenuation: true,
  transparent: true, opacity: 0.6,
});
const dust = new THREE.Points(dustGeo, dustMat);
scene.add(dust);

// Data-flow particles — small white points streaming toward camera along
// the conduit, suggesting "data is moving through this pipe". Cheap: one
// buffer geometry, recycled positions.
const FLOW_N = 240;
const flowGeo = new THREE.BufferGeometry();
const flowPositions = new Float32Array(FLOW_N * 3);
const flowSpeeds = new Float32Array(FLOW_N);
for (let i = 0; i < FLOW_N; i++) {
  flowPositions[i * 3 + 0] = (Math.random() - 0.5) * 7.0 + 1.5;
  flowPositions[i * 3 + 1] = 0.2 + Math.random() * 0.6;
  flowPositions[i * 3 + 2] = -Math.random() * 280;
  flowSpeeds[i] = 18 + Math.random() * 22;
}
flowGeo.setAttribute('position', new THREE.BufferAttribute(flowPositions, 3));
const flowMat = new THREE.PointsMaterial({
  color: 0x3A4A5E, size: 0.08, sizeAttenuation: true,
  transparent: true, opacity: 0.55,
  blending: THREE.AdditiveBlending, depthWrite: false,
});
const flow = new THREE.Points(flowGeo, flowMat);
scene.add(flow);

// Receding ground grid — perspective vanishing-point cue.
const grid = new THREE.GridHelper(800, 200, 0x1F2937, 0x0F1620);
grid.material.transparent = true;
grid.material.opacity = 0.55;
grid.position.y = -0.01;
scene.add(grid);

// Hairline horizon (bright thin line at vanishing point).
{
  const horizonMat = new THREE.LineBasicMaterial({ color: 0xF5C518, transparent: true, opacity: 0.35 });
  const horizonGeo = new THREE.BufferGeometry().setFromPoints([
    new THREE.Vector3(-200, 0.0, -300),
    new THREE.Vector3( 200, 0.0, -300),
  ]);
  scene.add(new THREE.Line(horizonGeo, horizonMat));
}

// Start line + finish line — bright cross-conduit markers so the track
// has a clear "00 → N" geometry. SpaceX-yellow at finish, dim white at start.
{
  const startMat = new THREE.LineBasicMaterial({ color: 0x6B7280, transparent: true, opacity: 0.5 });
  const startGeo = new THREE.BufferGeometry().setFromPoints([
    new THREE.Vector3(-4.0 + 1.5, 0.06, 4),
    new THREE.Vector3( 4.0 + 1.5, 0.06, 4),
  ]);
  scene.add(new THREE.Line(startGeo, startMat));

  const finMat = new THREE.LineBasicMaterial({ color: 0xF5C518, transparent: true, opacity: 0.85 });
  const finGeo = new THREE.BufferGeometry().setFromPoints([
    new THREE.Vector3(-4.0 + 1.5, 0.06, -276),
    new THREE.Vector3( 4.0 + 1.5, 0.06, -276),
  ]);
  scene.add(new THREE.Line(finGeo, finMat));
}

// Conduit outer rails — brighter, full-bright so they read.
function makeRail(x, color, opacity = 0.55) {
  const points = [];
  for (let z = 8; z >= -300; z -= 4) points.push(new THREE.Vector3(x, 0.05, z));
  const geo = new THREE.BufferGeometry().setFromPoints(points);
  const mat = new THREE.LineBasicMaterial({ color, transparent: true, opacity });
  return new THREE.Line(geo, mat);
}
// Outer rails follow LANE_OFFSET_X so the conduit walls match the lanes.
scene.add(makeRail(-4.0 + 1.5, 0x2A3340, 0.75));
scene.add(makeRail( 4.0 + 1.5, 0x2A3340, 0.75));

// Build a soft circular glow texture once, reused as a billboard for every orb.
function makeGlowTexture() {
  const SIZE = 128;
  const c = document.createElement('canvas');
  c.width = SIZE; c.height = SIZE;
  const ctx = c.getContext('2d');
  const g = ctx.createRadialGradient(SIZE/2, SIZE/2, 0, SIZE/2, SIZE/2, SIZE/2);
  g.addColorStop(0.00, 'rgba(255,255,255,1.0)');
  g.addColorStop(0.25, 'rgba(255,255,255,0.55)');
  g.addColorStop(0.55, 'rgba(255,255,255,0.18)');
  g.addColorStop(1.00, 'rgba(255,255,255,0.0)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, SIZE, SIZE);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}
const GLOW_TEX = makeGlowTexture();

// Tick marks every 10 units along the conduit (telemetry distance refs).
{
  const tickMat = new THREE.LineBasicMaterial({ color: 0x1F2937, transparent: true, opacity: 0.5 });
  const ticks = new THREE.Group();
  for (let z = 0; z >= -300; z -= 10) {
    const g = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(-3.6, 0.02, z),
      new THREE.Vector3( 3.6, 0.02, z),
    ]);
    ticks.add(new THREE.Line(g, tickMat));
  }
  scene.add(ticks);
}

// ---------- Post-processing: bloom + FXAA ----------
const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));

const bloom = new UnrealBloomPass(
  new THREE.Vector2(window.innerWidth, window.innerHeight),
  0.55,   // strength — lower so only bright cores bloom, not the whole HDR scene
  0.45,   // radius
  0.78,   // threshold — only emissive whites bloom; grid/dust stay sharp
);
composer.addPass(bloom);

const fxaa = new ShaderPass(FXAAShader);
composer.addPass(fxaa);

function resize() {
  const w = window.innerWidth;
  const h = window.innerHeight;
  renderer.setSize(w, h, false);
  composer.setSize(w, h);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  fxaa.material.uniforms.resolution.value.set(1 / w, 1 / h);
  bloom.setSize(w, h);
}
window.addEventListener('resize', resize);
resize();

// ---------- Runner orbs ----------
const TARGET_DEFAULT = 1024;  // overridden by bootstrap
const TRACK_LENGTH = 280;     // world units from start to finish
const Z_START = 4;
const Z_FINISH = Z_START - TRACK_LENGTH;

const runners = new Map();   // id → runnerState

// Lane positions are biased slightly right of world-center so the scene
// composes nicely in the visible canvas region (the left ~280px is taken
// by the telemetry panels and would otherwise occlude the frontrunner).
const LANE_OFFSET_X = 1.5;
function laneX(index, total) {
  if (total <= 1) return LANE_OFFSET_X;
  const span = 6.6;
  return -span / 2 + (span * index) / (total - 1) + LANE_OFFSET_X;
}

function makeOrb(colorHex, laneX) {
  const color = new THREE.Color(colorHex);
  const group = new THREE.Group();

  // Core sphere — small, full bright. UnrealBloomPass at threshold 0.78
  // picks up only this geometry, so the orb looks like a star, not a blob.
  const core = new THREE.Mesh(
    new THREE.SphereGeometry(0.16, 24, 24),
    new THREE.MeshBasicMaterial({ color: 0xffffff }),
  );
  group.add(core);

  // Inner shell — colored, slightly larger, contributes color without bloom.
  const shell = new THREE.Mesh(
    new THREE.SphereGeometry(0.22, 20, 20),
    new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.55,
      blending: THREE.AdditiveBlending, depthWrite: false }),
  );
  group.add(shell);

  // Glow billboard — 2D sprite, controlled scale, faces camera always.
  const glowMat = new THREE.SpriteMaterial({
    map: GLOW_TEX, color, transparent: true,
    blending: THREE.AdditiveBlending, depthWrite: false,
  });
  const glow = new THREE.Sprite(glowMat);
  glow.scale.set(1.1, 1.1, 1.1);
  group.add(glow);

  // Trail — additive points, runner color, capped count for perf.
  const TRAIL_N = 180;
  const trailGeo = new THREE.BufferGeometry();
  const positions = new Float32Array(TRAIL_N * 3);
  const colors = new Float32Array(TRAIL_N * 3);
  trailGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  trailGeo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  const trailMat = new THREE.PointsMaterial({
    size: 0.16, sizeAttenuation: true,
    transparent: true, opacity: 0.7,
    blending: THREE.AdditiveBlending, depthWrite: false,
    vertexColors: true,
  });
  const trail = new THREE.Points(trailGeo, trailMat);
  scene.add(trail);

  // Per-runner conduit rail — thin glowing line in the runner color, marks
  // the lane. Unlit base so it doesn't bloom; alpha 0.22 keeps it subtle.
  const railPts = [];
  for (let z = 8; z >= -300; z -= 4) railPts.push(new THREE.Vector3(laneX, 0.04, z));
  const railGeo = new THREE.BufferGeometry().setFromPoints(railPts);
  const railMat = new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.45 });
  const lane = new THREE.Line(railGeo, railMat);
  scene.add(lane);

  // Finish-line beam — revealed only when this runner crosses.
  const beamMat = new THREE.MeshBasicMaterial({
    color, transparent: true, opacity: 0,
    blending: THREE.AdditiveBlending, depthWrite: false,
  });
  const beam = new THREE.Mesh(new THREE.CylinderGeometry(0.18, 0.18, 50, 12, 1, true), beamMat);
  beam.position.set(laneX, 24, Z_FINISH);
  scene.add(beam);

  return { group, core, shell, glow, glowMat,
           trail, trailGeo, color, lane, beam, beamMat,
           trailHead: 0, trailFilled: 0, trailMax: TRAIL_N };
}

function buildRunners(meta, target) {
  // Clear any prior state (re-connect path).
  for (const r of runners.values()) {
    scene.remove(r.orb.group);
    scene.remove(r.orb.trail);
    scene.remove(r.orb.beam);
    scene.remove(r.orb.lane);
  }
  runners.clear();
  panelsEl.innerHTML = '';
  panelsEl.dataset.count = String(meta.length);

  meta.forEach((m, i) => {
    const lx = laneX(i, meta.length);
    const orb = makeOrb(m.color, lx);
    orb.group.position.set(lx, 0.6, Z_START);
    scene.add(orb.group);

    // Build per-runner HUD panel.
    const panel = document.createElement('div');
    panel.className = 'runner-panel';
    panel.style.setProperty('--runner-color', m.color);
    panel.innerHTML = `
      <div class="rp-row1">
        <span class="rp-id">${escapeHtml(m.label)}</span>
        <span class="rp-pos" data-pos>—</span>
      </div>
      <span class="rp-tps" data-tps>0.0</span>
      <span class="rp-tps-unit">tok·s⁻¹</span>
      <div class="rp-meta">
        <span><span class="label">TOK</span> <span class="v" data-tot>0</span></span>
        <span><span class="label">ELT</span> <span class="v" data-elt>0.0s</span></span>
        <span class="rp-state" data-state>STANDBY</span>
      </div>
      <canvas class="rp-spark" data-spark width="280" height="26"></canvas>
      <div class="rp-progress">
        <div class="rp-progress-fill" data-fill style="background: ${m.color}"></div>
        <span class="rp-progress-pct" data-pct>0%</span>
      </div>
    `;
    panelsEl.appendChild(panel);

    runners.set(m.id, {
      meta: m,
      orb,
      target,
      tokens: 0,
      tps: 0,
      tpsEMA: 0,
      lastTokenT: performance.now() / 1000,
      tpsHistory: new Array(120).fill(0),
      state: 'standby',
      finished: false,
      finishedAt: null,
      progress: 0,
      panel,
      els: {
        pos: panel.querySelector('[data-pos]'),
        tps: panel.querySelector('[data-tps]'),
        tot: panel.querySelector('[data-tot]'),
        elt: panel.querySelector('[data-elt]'),
        state: panel.querySelector('[data-state]'),
        spark: panel.querySelector('[data-spark]'),
        fill: panel.querySelector('[data-fill]'),
        pct: panel.querySelector('[data-pct]'),
      },
    });
  });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, ch => (
    { '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[ch]
  ));
}

// ---------- WebSocket ----------
let wsStartT = null;
let totalElapsed = 0;
let firstFinish = null;

function connect() {
  const ws = new WebSocket(`ws://${location.host}/race`);
  ws.onopen = () => setStatus('LIVE', true);
  ws.onclose = () => setStatus('CLOSED', false);
  ws.onerror = () => setStatus('ERROR', false);
  ws.onmessage = (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch { return; }
    handleMessage(msg);
  };
}

function setStatus(text, live) {
  statusEl.textContent = text;
  statusContainer.classList.toggle('live', !!live);
}

function handleMessage(msg) {
  if (msg.kind === 'config') {
    promptEl.textContent = msg.prompt || '—';
    targetEl.textContent = `${(msg.target_tokens || TARGET_DEFAULT).toLocaleString()} TOK`;
    missionTitle.textContent = (msg.title || 'TELEMETRY').toUpperCase();
    buildRunners(msg.runners, msg.target_tokens || TARGET_DEFAULT);
    wsStartT = performance.now() / 1000;
    return;
  }
  const r = runners.get(msg.runner_id);
  if (!r) return;

  switch (msg.kind) {
    case 'start':
      r.state = 'streaming';
      r.els.state.textContent = 'STREAM';
      r.els.state.className = 'rp-state streaming';
      break;
    case 'token': {
      const tNow = performance.now() / 1000;
      const dt = Math.max(0.01, tNow - r.lastTokenT);
      const newTokens = (msg.token_count || r.tokens + 1) - r.tokens;
      const instTps = newTokens / dt;
      r.tokens = msg.token_count || (r.tokens + 1);
      r.tpsEMA = r.tpsEMA === 0 ? instTps : (r.tpsEMA * 0.82 + instTps * 0.18);
      r.tps = r.tpsEMA;
      r.lastTokenT = tNow;
      r.tpsHistory.shift();
      r.tpsHistory.push(r.tpsEMA);
      r.progress = Math.min(1, r.tokens / r.target);
      break;
    }
    case 'think_open':
      r.state = 'thinking';
      r.els.state.textContent = 'THINK';
      r.els.state.className = 'rp-state thinking';
      break;
    case 'think_close':
      r.state = 'streaming';
      r.els.state.textContent = 'STREAM';
      r.els.state.className = 'rp-state streaming';
      break;
    case 'finish':
      r.state = 'done';
      r.finished = true;
      r.finishedAt = msg.elapsed;
      r.progress = 1;
      r.els.state.textContent = 'DONE';
      r.els.state.className = 'rp-state done';
      if (firstFinish === null) {
        firstFinish = r;
        showFinish(r);
      }
      break;
    case 'error':
      r.state = 'error';
      r.els.state.textContent = 'ERR';
      r.els.state.className = 'rp-state error';
      break;
  }
}

function showFinish(r) {
  finishName.textContent = (r.meta.label || r.meta.id).toUpperCase();
  const avg = r.finishedAt ? (r.tokens / r.finishedAt).toFixed(1) : '—';
  const t = r.finishedAt ? r.finishedAt.toFixed(1) : '—';
  finishStats.textContent = `${avg} TOK·S⁻¹ AVG · ${t} S`;
  finishOverlay.hidden = false;
  // Light up beam
  r.orb.beamMat.opacity = 0.6;
}

// ---------- HUD updates ----------
function updateLeaderboard() {
  const arr = [...runners.values()];
  arr.sort((a, b) => b.tokens - a.tokens);
  let lead = null;
  arr.forEach((r, idx) => {
    const pos = idx + 1;
    r.els.pos.textContent = `P${pos}`;
    r.els.tps.textContent = r.tps.toFixed(1);
    r.els.tot.textContent = r.tokens.toLocaleString();
    r.els.elt.textContent = wsStartT ? `${(performance.now()/1000 - wsStartT).toFixed(1)}s` : '0.0s';
    r.panel.classList.toggle('lead', idx === 0 && r.tokens > 0);
    const pct = Math.round(r.progress * 100);
    if (r.els.fill) r.els.fill.style.width = `${pct}%`;
    if (r.els.pct) r.els.pct.textContent = `${pct}%`;
    drawSparkline(r);
    if (idx === 0 && r.tokens > 0) lead = r;
  });

  if (lead) {
    const second = arr[1];
    const delta = second ? lead.tokens - second.tokens : lead.tokens;
    leaderEl.hidden = false;
    leaderName.textContent = (lead.meta.label || lead.meta.id).toUpperCase();
    leaderDelta.textContent = `+${delta} TOK`;
  } else {
    leaderEl.hidden = true;
  }
}

function drawSparkline(r) {
  const c = r.els.spark;
  const ctx = c.getContext('2d');
  const w = c.width;
  const h = c.height;
  ctx.clearRect(0, 0, w, h);
  const arr = r.tpsHistory;
  const max = Math.max(0.001, ...arr);
  ctx.lineWidth = 1;
  ctx.strokeStyle = r.meta.color;
  ctx.beginPath();
  for (let i = 0; i < arr.length; i++) {
    const x = (i / (arr.length - 1)) * w;
    const y = h - (arr[i] / max) * (h - 4) - 2;
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }
  ctx.stroke();

  // Faint fill below the line for the "telemetry trace" feel.
  ctx.lineTo(w, h);
  ctx.lineTo(0, h);
  ctx.closePath();
  ctx.globalAlpha = 0.08;
  ctx.fillStyle = r.meta.color;
  ctx.fill();
  ctx.globalAlpha = 1.0;
}

function formatClock(t) {
  if (!Number.isFinite(t)) return '00:00:00.0';
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const s = (t % 60);
  return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${s.toFixed(1).padStart(4,'0')}`;
}

// ---------- Animation loop ----------
let lastFrame = performance.now();
let fpsAcc = 0, fpsFrames = 0;
let cameraPhase = 0;

function tick(now) {
  requestAnimationFrame(tick);
  const dt = Math.min(0.05, (now - lastFrame) / 1000);
  lastFrame = now;

  // Animate orb positions toward progress with a small token-tick velocity bias.
  for (const r of runners.values()) {
    const targetZ = Z_START + (Z_FINISH - Z_START) * r.progress;
    const orb = r.orb;
    // smooth follow
    orb.group.position.z += (targetZ - orb.group.position.z) * Math.min(1, dt * 2.5);

    // glow sprite pulse — 2D billboard, modest scale change with tps.
    const pulse = 1.0 + Math.sin(now * 0.004 + r.tokens * 0.05) * 0.05;
    const tpsScale = 0.9 + Math.min(0.6, r.tps * 0.012);
    const s = pulse * tpsScale;
    orb.glow.scale.set(s, s, s);
    // shell stays steady, core stays white-hot for clean bloom pickup
    orb.shell.material.color.setHex(parseInt(r.meta.color.slice(1), 16));

    // emit trail particle proportional to tps (cap to ~2k total)
    const emit = Math.min(3, Math.ceil(r.tps * 0.05));
    for (let k = 0; k < emit && r.tokens > 0 && !r.finished; k++) {
      const idx = orb.trailHead;
      const px = orb.trailGeo.attributes.position.array;
      const cx = orb.trailGeo.attributes.color.array;
      const x = orb.group.position.x + (Math.random() - 0.5) * 0.18;
      const y = 0.5 + (Math.random() - 0.5) * 0.18;
      const z = orb.group.position.z + 0.6 + Math.random() * 0.4;
      px[idx * 3 + 0] = x;
      px[idx * 3 + 1] = y;
      px[idx * 3 + 2] = z;
      cx[idx * 3 + 0] = orb.color.r;
      cx[idx * 3 + 1] = orb.color.g;
      cx[idx * 3 + 2] = orb.color.b;
      orb.trailHead = (idx + 1) % orb.trailMax;
      orb.trailFilled = Math.min(orb.trailMax, orb.trailFilled + 1);
    }
    orb.trailGeo.attributes.position.needsUpdate = true;
    orb.trailGeo.attributes.color.needsUpdate = true;
    orb.trailGeo.setDrawRange(0, orb.trailFilled);

    // beam pulse if active
    if (orb.beamMat.opacity > 0) {
      orb.beamMat.opacity = Math.max(0.25, orb.beamMat.opacity - dt * 0.05);
    }
  }

  // dust drift
  dust.rotation.y += dt * 0.005;
  // grid scroll: subtle z-drift to convey forward motion even on standby
  grid.position.z = ((grid.position.z + dt * 4.0) % 4);

  // Data-flow particles stream toward camera (positive z direction).
  // When a particle passes the camera, recycle to far end of conduit.
  const fp = flowGeo.attributes.position.array;
  const camZ = camera.position.z;
  for (let i = 0; i < FLOW_N; i++) {
    fp[i * 3 + 2] += flowSpeeds[i] * dt;
    if (fp[i * 3 + 2] > camZ + 4) {
      fp[i * 3 + 2] = -280 + Math.random() * 4;
      fp[i * 3 + 0] = (Math.random() - 0.5) * 7.0 + 1.5;
      fp[i * 3 + 1] = 0.2 + Math.random() * 0.6;
    }
  }
  flowGeo.attributes.position.needsUpdate = true;

  // Framing-cam: park behind the rearmost runner so the whole pack is in
  // frame; aim toward the leader so motion + spread reads. Far better for
  // a side-by-side comparison than a pure chase-cam glued to position 1.
  cameraPhase += dt * 0.04;
  let leadZ = Z_START, rearZ = Z_FINISH;
  let any = false;
  for (const r of runners.values()) {
    const z = r.orb.group.position.z;
    if (!any) { leadZ = z; rearZ = z; any = true; }
    else { leadZ = Math.min(leadZ, z); rearZ = Math.max(rearZ, z); }
  }
  const targetCamZ = rearZ + 22;  // pull back so closest orb stays small
  camera.position.x = LANE_OFFSET_X + Math.sin(cameraPhase) * 0.4;
  camera.position.y = 5.4 + Math.sin(cameraPhase * 0.7) * 0.2;
  camera.position.z += (targetCamZ - camera.position.z) * Math.min(1, dt * 1.0);
  camera.lookAt(LANE_OFFSET_X, 0.8, leadZ - 6);

  composer.render();

  // Clock + FPS
  if (wsStartT !== null) {
    const t = performance.now() / 1000 - wsStartT;
    clockEl.textContent = formatClock(t);
    totalElapsed = t;
  }
  fpsAcc += dt; fpsFrames++;
  if (fpsAcc >= 0.5) {
    fpsEl.textContent = `${Math.round(fpsFrames / fpsAcc)}`;
    fpsAcc = 0; fpsFrames = 0;
  }
  updateLeaderboard();
}
requestAnimationFrame(tick);

connect();
