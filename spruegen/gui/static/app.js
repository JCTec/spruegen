import * as THREE from "three";
import { STLLoader } from "./vendor/STLLoader.js";
import { OrbitControls } from "./vendor/OrbitControls.js";

const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const fmt = (x, d = 1) => (x == null || Number.isNaN(x) ? "–" : Number(x).toFixed(d));

// ------------------------------------------------------------------ state
const state = {
  presets: [],
  sid: null,
  name: null,
  analysis: null,
  result: null, // last generate response
  stale: false,
  busy: false,
};

// ------------------------------------------------------------------ viewer
const viewerEl = $("#viewer");
const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
viewerEl.prepend(renderer.domElement);
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 5000);
camera.position.set(60, 50, 80);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;

scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8478, 1.3));
const key = new THREE.DirectionalLight(0xffffff, 1.6);
key.position.set(1, 2, 1.5);
scene.add(key);
const rim = new THREE.DirectionalLight(0xffffff, 0.6);
rim.position.set(-1.5, 0.5, -1);
scene.add(rim);

const grid = new THREE.GridHelper(120, 24, 0x999999, 0xcccccc);
grid.material.transparent = true;
grid.material.opacity = 0.35;
scene.add(grid);

// Z-up (STL / spruegen) -> Y-up (three.js)
const root = new THREE.Group();
root.rotation.x = -Math.PI / 2;
scene.add(root);
const layers = {};
for (const name of ["ring", "tree", "vents", "zones", "final"]) {
  layers[name] = new THREE.Group();
  root.add(layers[name]);
}
layers.zones.matrixAutoUpdate = false;

const MAT = {
  ring: new THREE.MeshStandardMaterial({ color: 0xc9ccd2, metalness: 0.55, roughness: 0.32 }),
  tree: new THREE.MeshStandardMaterial({ color: 0xd9573b, metalness: 0.05, roughness: 0.55 }),
  vents: new THREE.MeshStandardMaterial({ color: 0x3b7dd9, metalness: 0.05, roughness: 0.5 }),
  final: new THREE.MeshStandardMaterial({ color: 0xc8894f, metalness: 0.6, roughness: 0.35 }),
};

function applyTheme() {
  const cs = getComputedStyle(document.documentElement);
  scene.background = new THREE.Color(cs.getPropertyValue("--view").trim() || "#eceae4");
}
applyTheme();
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", applyTheme);

function resize() {
  const w = viewerEl.clientWidth, h = viewerEl.clientHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / Math.max(h, 1);
  camera.updateProjectionMatrix();
}
new ResizeObserver(resize).observe(viewerEl);
resize();
(function loop() {
  controls.update();
  renderer.render(scene, camera);
  requestAnimationFrame(loop);
})();

const loader = new STLLoader();
async function loadMesh(url, material) {
  const geo = await loader.loadAsync(url);
  geo.computeVertexNormals();
  return new THREE.Mesh(geo, material);
}
function clear(group) {
  for (const c of [...group.children]) {
    group.remove(c);
    c.geometry?.dispose();
  }
}
function fit() {
  const box = new THREE.Box3();
  for (const [name, g] of Object.entries(layers)) if (g.visible && g.children.length) box.expandByObject(g);
  if (box.isEmpty()) return;
  const sphere = box.getBoundingSphere(new THREE.Sphere());
  const dist = sphere.radius / Math.sin((camera.fov * Math.PI) / 360) * 1.05;
  const dir = new THREE.Vector3(0.75, 0.55, 1).normalize();
  camera.position.copy(sphere.center).addScaledVector(dir, dist);
  camera.near = dist / 100;
  camera.far = dist * 20;
  camera.updateProjectionMatrix();
  controls.target.copy(sphere.center);
  grid.position.y = box.min.y - 0.01;
  const size = Math.max(40, Math.ceil(sphere.radius * 3 / 10) * 10);
  grid.scale.setScalar(size / 120);
}
$("#btn-fit").addEventListener("click", fit);

function layerBox(name) {
  const cb = $(`#layers input[data-layer="${name}"]`);
  return cb;
}
function setLayerAvailable(name, available, checked) {
  const cb = layerBox(name);
  cb.disabled = !available;
  if (checked !== undefined) cb.checked = checked;
  layers[name].visible = available && cb.checked;
  syncRingLook();
}
function syncRingLook() {
  const zonesOn = layers.zones.visible && layers.zones.children.length > 0;
  MAT.ring.transparent = zonesOn;
  MAT.ring.opacity = zonesOn ? 0.18 : 1;
  MAT.ring.depthWrite = !zonesOn;
  MAT.ring.needsUpdate = true;
}
$$("#layers input").forEach((cb) =>
  cb.addEventListener("change", () => {
    layers[cb.dataset.layer].visible = cb.checked && !cb.disabled;
    syncRingLook();
  })
);

// ------------------------------------------------------------------ ui helpers
function busy(on, text = "Working…") {
  state.busy = on;
  $("#busy").hidden = !on;
  $("#busy-text").textContent = text;
  refreshButtons();
}
function showError(msg) {
  $("#error-text").textContent = msg;
  $("#error").hidden = false;
}
$("#error-x").addEventListener("click", () => ($("#error").hidden = true));

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  let body = null;
  try { body = await res.json(); } catch { /* not json */ }
  if (!res.ok) throw new Error(body?.error || body?.detail || `Request failed (${res.status})`);
  return body;
}
const fileUrl = (rel, g = 0) => `/api/${state.sid}/file/${rel}?g=${g}`;

function refreshButtons() {
  const has = !!state.sid;
  $("#btn-analyze").disabled = !has || state.busy;
  $("#btn-generate").disabled = !has || state.busy;
  const canExport = has && !state.busy && state.result?.ok && !state.stale;
  for (const [id, path] of [["#btn-export", "export/stl"], ["#btn-zip", "export/zip"]]) {
    const a = $(id);
    a.setAttribute("aria-disabled", canExport ? "false" : "true");
    if (canExport) a.href = `/api/${state.sid}/${path}`; else a.removeAttribute("href");
  }
  $("#export-hint").textContent = !state.result
    ? "Generate a valid result first."
    : state.stale ? "Settings changed — generate again before exporting."
    : state.result.ok ? "Ready: validated and watertight." : "The result didn't pass validation.";
  $("#stale").hidden = !state.stale;
  $("#panel-result").classList.toggle("stale-dim", state.stale);
}

// ------------------------------------------------------------------ settings
function seg(id) {
  const el = $(id);
  el.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    el.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
    el.querySelectorAll("button").forEach((x) => x.setAttribute("aria-checked", x === b));
    onSettingsChange();
  });
  return () => el.querySelector("button.on").dataset.v;
}
function setSeg(id, v) {
  $(id).querySelectorAll("button").forEach((x) => {
    x.classList.toggle("on", x.dataset.v === v);
    x.setAttribute("aria-checked", x.dataset.v === v);
  });
}
const treeValue = seg("#tree");
const ventsValue = seg("#vents");
const stemValue = seg("#stem");

function currentPreset() {
  return state.presets.find((p) => p.name === $("#preset").value);
}
function fillAdvanced(p) {
  $$("[data-adv]").forEach((inp) => (inp.value = p.advanced[inp.dataset.adv]));
  $("#preset-notes").textContent = p.notes;
  setSeg("#stem", p.stem_kind);
  fillStemDims(p);
}
function fillStemDims(p) {
  const dims = stemValue() === "stub" ? p.stub : p.stem;
  $("#stem-d").value = dims.d_mm;
  $("#stem-h").value = dims.h_mm;
}
function config() {
  const p = currentPreset();
  const advanced = {};
  $$("[data-adv]").forEach((inp) => {
    const v = parseFloat(inp.value);
    if (!Number.isNaN(v) && v !== p.advanced[inp.dataset.adv]) advanced[inp.dataset.adv] = v;
  });
  const tree = treeValue();
  return {
    preset: p.name,
    tree_mode: tree,
    feeders: tree === "spider" || tree === "y" ? parseInt($("#feeders").value, 10) : null,
    vents: ventsValue(),
    stem: { kind: stemValue(), d_mm: parseFloat($("#stem-d").value), h_mm: parseFloat($("#stem-h").value) },
    advanced,
  };
}
function onSettingsChange() {
  const tree = treeValue();
  $("#feeders").disabled = !(tree === "spider" || tree === "y");
  if (state.result && !state.stale) state.stale = true;
  refreshButtons();
}
$("#preset").addEventListener("change", () => { fillAdvanced(currentPreset()); onSettingsChange(); });
$("#feeders").addEventListener("input", onSettingsChange);
$("#stem").addEventListener("click", (e) => { if (e.target.closest("button")) fillStemDims(currentPreset()); });
$$("#stem-d, #stem-h").forEach((i) => i.addEventListener("input", onSettingsChange));
$$("[data-adv]").forEach((i) => i.addEventListener("input", onSettingsChange));
$("#adv-reset").addEventListener("click", () => { fillAdvanced(currentPreset()); onSettingsChange(); });

async function loadPresets() {
  state.presets = await api("/api/presets");
  const sel = $("#preset");
  sel.innerHTML = "";
  for (const p of state.presets) {
    const o = document.createElement("option");
    o.value = p.name;
    o.textContent = `${p.metal} · ${p.process}  (${p.name})`;
    sel.append(o);
  }
  sel.value = state.presets.some((p) => p.name === "ag925") ? "ag925" : state.presets[0]?.name;
  fillAdvanced(currentPreset());
}

// ------------------------------------------------------------------ 1 load
const drop = $("#drop");
drop.addEventListener("click", (e) => { if (e.target !== $("#file")) $("#file").click(); });
drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("#file").click(); } });
$("#file").addEventListener("change", (e) => e.target.files[0] && loadRing(e.target.files[0]));
for (const ev of ["dragenter", "dragover"]) {
  document.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); });
}
for (const ev of ["dragleave", "drop"]) {
  document.addEventListener(ev, (e) => { e.preventDefault(); if (ev === "dragleave" && e.relatedTarget) return; drop.classList.remove("over"); });
}
document.addEventListener("drop", (e) => {
  const f = e.dataTransfer?.files?.[0];
  if (f) loadRing(f);
});

async function loadRing(file) {
  $("#error").hidden = true;
  busy(true, `Loading ${file.name}…`);
  try {
    const fd = new FormData();
    fd.append("file", file);
    const j = await api("/api/session", { method: "POST", body: fd });
    Object.assign(state, { sid: j.sid, name: j.name, analysis: null, result: null, stale: false });
    for (const g of Object.values(layers)) clear(g);
    layers.zones.matrix.identity();
    layers.ring.add(await loadMesh(fileUrl(j.mesh_url), MAT.ring));
    for (const n of ["tree", "vents", "zones", "final"]) setLayerAvailable(n, false, n !== "zones" && n !== "final");
    setLayerAvailable("ring", true, true);
    $("#empty").hidden = true;
    renderRingInfo(j);
    $("#analysis-short").hidden = true;
    $("#gen-short").hidden = true;
    $("#analysis-body").innerHTML = `Run <b>Analyze</b> to see where the ring is thick (hot spots), how many feeders it needs and where the metal arrives last.`;
    $("#result-body").innerHTML = `Run <b>Generate</b> to build the sprue tree and check it.`;
    $("#result-body").className = "muted";
    $("#analysis-body").className = "muted";
    fit();
  } catch (err) {
    showError(err.message);
  } finally {
    busy(false);
  }
}

function renderRingInfo(j) {
  const s = j.summary;
  const rows = [
    ["Volume", `${fmt(s.volume_mm3, 0)} mm³ (≈ ${fmt(s.volume_mm3 * 0.0104, 1)} g in silver)`],
    ["Inner Ø", s.inner_d_mm ? `${fmt(s.inner_d_mm, 1)} mm` : "–"],
    ["Band width", s.band_width_mm ? `${fmt(s.band_width_mm, 1)} mm` : "–"],
    ["Thickness", s.thickness_max_mm ? `${fmt(s.thickness_median_mm, 2)} typical · ${fmt(s.thickness_max_mm, 2)} max` : "–"],
    ["Head / setting", s.head ? "detected" : "none"],
  ];
  const el = $("#ring-info");
  el.hidden = false;
  el.innerHTML = `<div class="name">${escapeHtml(j.name)}</div><dl class="kv">${rows
    .map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>${warnList(j.warnings)}`;
}

// ------------------------------------------------------------------ 3 analyze
$("#btn-analyze").addEventListener("click", async () => {
  $("#error").hidden = true;
  busy(true, "Analyzing thickness and feeding…");
  const t0 = performance.now();
  try {
    const a = await api(`/api/${state.sid}/analyze`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(config()),
    });
    state.analysis = a;
    clear(layers.zones);
    for (const z of a.zones) {
      const m = await loadMesh(fileUrl(z.url, Date.now()),
        new THREE.MeshStandardMaterial({ color: z.color, roughness: 0.7, metalness: 0 }));
      layers.zones.add(m);
    }
    // zones are in the STL's own axes: align them with whatever frame the ring is shown in
    if (state.result?.transform) layers.zones.matrix.fromArray(state.result.transform.flat()).transpose();
    else layers.zones.matrix.identity();
    setLayerAvailable("zones", true, true);
    renderAnalysis(a, (performance.now() - t0) / 1000);
  } catch (err) {
    showError(err.message);
  } finally {
    busy(false);
  }
});

function renderAnalysis(a, secs) {
  const short = $("#analysis-short");
  short.hidden = false;
  short.innerHTML = `Suggests <b>${a.feeder_count}</b> feeder${a.feeder_count > 1 ? "s" : ""} · ${Math.round(a.coverage * 100)}% fed`;
  const legend = a.zones.map((z) => `<span><i style="background:${z.color}"></i>${escapeHtml(z.label)}</span>`).join("");
  const body = $("#analysis-body");
  body.className = "";
  body.innerHTML = `
    <div><span class="big-num">${a.feeder_count}</span> feeder${a.feeder_count > 1 ? "s" : ""} suggested ·
      ${Math.round(a.coverage * 100)}% of the ring fed · <span class="muted">${fmt(secs, 1)} s</span></div>
    <ul class="reasons">${a.reasons.map((r) => `<li>${escapeHtml(r)}</li>`).join("")}</ul>
    <div class="zone-legend">${legend}</div>
    ${a.map_url ? `<img src="${fileUrl(a.map_url, Date.now())}" alt="Unrolled ring map: thickness and feeding zones" title="Click to enlarge">` : ""}
    <p class="muted">Map = the ring cut open and laid flat (angle around the finger × height).
      Bright = thick hot spot. ▼ feeder, ★ where metal arrives last (best place for vents).</p>
    ${warnList(a.warnings)}`;
  body.querySelector("img")?.addEventListener("click", (e) => e.target.classList.toggle("big"));
}

// ------------------------------------------------------------------ 4 generate
$("#btn-generate").addEventListener("click", async () => {
  $("#error").hidden = true;
  busy(true, "Building the sprue tree and checking it…");
  const t0 = performance.now();
  try {
    const r = await api(`/api/${state.sid}/generate`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(config()),
    });
    state.result = r;
    state.stale = false;
    const g = r.generation;
    clear(layers.ring); clear(layers.tree); clear(layers.vents); clear(layers.final);
    layers.ring.add(await loadMesh(fileUrl(r.meshes.ring, g), MAT.ring));
    layers.tree.add(await loadMesh(fileUrl(r.meshes.tree, g), MAT.tree));
    if (r.meshes.vents) layers.vents.add(await loadMesh(fileUrl(r.meshes.vents, g), MAT.vents));
    if (r.meshes.final) layers.final.add(await loadMesh(fileUrl(r.meshes.final, g), MAT.final));
    layers.zones.matrix.fromArray(r.transform.flat()).transpose();
    setLayerAvailable("ring", true, true);
    setLayerAvailable("tree", true, true);
    setLayerAvailable("vents", !!r.meshes.vents, true);
    setLayerAvailable("final", !!r.meshes.final, false);
    setLayerAvailable("zones", layers.zones.children.length > 0, false);
    renderResult(r, (performance.now() - t0) / 1000);
    fit();
  } catch (err) {
    showError(err.message);
  } finally {
    busy(false);
  }
});

function renderResult(r, secs) {
  const short = $("#gen-short");
  short.hidden = false;
  short.innerHTML = `<span class="status ${r.ok ? "ok" : "bad"}">${r.ok ? "✓ Valid" : "✗ Not valid"}</span>
    ${escapeHtml(r.tree.label)} · ${r.feeders.length} feeder${r.feeders.length > 1 ? "s" : ""} · ${r.vents.length} vent${r.vents.length === 1 ? "" : "s"}`;
  const rows = r.feeders.map((f, i) => `<tr><td>${i + 1}</td><td>${f.kind}</td><td>Ø ${fmt(f.d_mm, 2)}</td>
    <td>${fmt(f.len_mm, 1)} mm</td><td>${fmt(f.angle_deg, 0)}°</td></tr>`).join("");
  const trunks = r.branches.map((b) => `<tr><td>—</td><td>Y trunk → ${b.arms.join(", ")}</td><td>Ø ${fmt(b.d_mm, 2)}</td><td></td><td></td></tr>`).join("");
  const checks = r.validation.checks.map((c) => `<li class="${c.ok ? "ok" : "bad"}"><span class="ic">${c.ok ? "✓" : "✗"}</span>
    <span>${escapeHtml(c.label)}</span><span class="det">${escapeHtml(c.detail || "")}</span></li>`).join("");
  const body = $("#result-body");
  body.className = "";
  body.innerHTML = `
    <div><span class="status ${r.ok ? "ok" : "bad"}">${r.ok ? "✓ Ready to export" : "✗ Did not pass"}</span>
      <b>${escapeHtml(r.tree.label)}</b> · ${r.stem.kind === "stub" ? "stub" : "stem"} Ø${r.stem.d_mm} × ${r.stem.h_mm} mm ·
      ${r.vents.length} vent${r.vents.length === 1 ? "" : "s"} · <span class="muted">${fmt(secs, 1)} s</span></div>
    <table class="feeders"><thead><tr><th>#</th><th>Feeder</th><th>Diameter</th><th>Length</th><th>Angle</th></tr></thead>
      <tbody>${rows}${trunks}</tbody></table>
    <ul class="checks">${checks}</ul>
    ${r.validation.errors.length ? `<ul class="warns" style="color:var(--bad)">${r.validation.errors.map((e) => `<li>${escapeHtml(e)}</li>`).join("")}</ul>` : ""}
    ${r.reasons.length ? `<p class="muted" style="margin-bottom:0">Why this tree:</p><ul class="reasons">${r.reasons.map((x) => `<li>${escapeHtml(x)}</li>`).join("")}</ul>` : ""}
    ${warnList(r.warnings)}`;
  refreshButtons();
}

// ------------------------------------------------------------------ misc
function warnList(ws) {
  if (!ws || !ws.length) return "";
  return `<ul class="warns">${ws.map((w) => `<li>${escapeHtml(w)}</li>`).join("")}</ul>`;
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

loadPresets().catch((e) => showError(`Couldn't load presets: ${e.message}`));
refreshButtons();
