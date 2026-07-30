const { app, core, action } = require('photoshop');
const uxp = require('uxp');

const statusEl = () => document.getElementById('status');
const fs = uxp.storage.localFileSystem;
let dataFolderRef = null;

async function getDataFolder() {
  if (dataFolderRef) return dataFolderRef;
  dataFolderRef = await fs.getDataFolder();
  return dataFolderRef;
}

async function readJson(filename, fallback) {
  try {
    const folder = await getDataFolder();
    const file = await folder.getEntry(filename);
    if (!file) return fallback;
    const text = await file.read();
    return JSON.parse(text);
  } catch (_) {
    return fallback;
  }
}

async function writeJson(filename, obj) {
  const folder = await getDataFolder();
  const file = await folder.createFile(filename, { overwrite: true });
  await file.write(JSON.stringify(obj, null, 2));
}

function switchTab(tab) {
  document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
  document.querySelector(`.tab[data-tab="${tab}"]`).classList.add('active');
  document.getElementById(`tab-${tab}`).classList.add('active');
}

function setStatus(message) {
  statusEl().textContent = message;
}

function getSelectedScope() {
  const radios = Array.from(document.querySelectorAll('input[name="scope"]'));
  const checked = radios.find(r => r.checked);
  return checked ? checked.value : 'whole-document';
}

function base64ToArrayBuffer(base64) {
  const binaryString = atob(base64);
  const len = binaryString.length;
  const bytes = new Uint8Array(len);
  for (let i = 0; i < len; i++) {
    bytes[i] = binaryString.charCodeAt(i);
  }
  return bytes.buffer;
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  for (let i = 0; i < bytes.byteLength; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
}

function getMimeFromFilename(name) {
  const lower = (name || '').toLowerCase();
  if (lower.endsWith('.png')) return 'image/png';
  if (lower.endsWith('.jpg') || lower.endsWith('.jpeg')) return 'image/jpeg';
  if (lower.endsWith('.webp')) return 'image/webp';
  return 'image/png';
}

async function exportScopeToBase64(scope) {
  const dataFolder = await getDataFolder();
  const tmpFile = await dataFolder.createFile('seedream_input.png', { overwrite: true });
  const nativePath = tmpFile.nativePath;

  const originalDoc = app.activeDocument;
  await core.executeAsModal(async () => {
    // Duplicate the document to avoid altering the original
    const dupDoc = await originalDoc.duplicate();
    app.activeDocument = dupDoc;

    // Toggle visibility according to scope
    const layers = Array.from(dupDoc.layers);
    if (scope === 'current-layer') {
      const active = dupDoc.activeLayers[0];
      for (const ly of layers) ly.visible = (ly.id === active.id);
    } else if (scope === 'whole-document') {
      for (const ly of layers) ly.visible = true;
    } // visible-layers: keep as-is

    // Save as PNG to nativePath
    await action.batchPlay([
      {
        "_obj": "save",
        "as": { "_obj": "PNGFormat", "compression": 0 },
        "in": { "_path": nativePath, "_kind": "local" },
        "copy": true,
        "lowerCase": true
      }
    ], { synchronousExecution: true, modalBehavior: 'execute' });

    // Close duplicate without saving
    await dupDoc.closeWithoutSaving();
    app.activeDocument = originalDoc;
  }, { commandName: 'Export Scope Composite' });

  // Read file back as base64
  const buf = await tmpFile.read({ format: uxp.storage.formats.binary });
  return arrayBufferToBase64(buf);
}

async function placePngAsNewLayerFromArrayBuffer(pngArrayBuffer) {
  const dataFolder = await getDataFolder();
  const tmpFile = await dataFolder.createFile('seedream_output.png', { overwrite: true });
  await tmpFile.write(pngArrayBuffer, { format: uxp.storage.formats.binary });

  const originalDoc = app.activeDocument;
  await core.executeAsModal(async () => {
    const opened = await app.open(tmpFile);
    const srcDoc = app.activeDocument;
    const topLayer = srcDoc.layers[0];
    await topLayer.duplicate(originalDoc);
    await srcDoc.closeWithoutSaving();
  }, { commandName: 'Place Seedream Output' });
}

async function onGenerate(e) {
  e.preventDefault();
  const prompt = document.getElementById('prompt').value.trim();
  const useEnhanced = document.getElementById('use-enhanced').checked;
  const enhancedText = document.getElementById('prompt-enhanced').value.trim();
  const negative = document.getElementById('negative').value.trim();
  const seed = document.getElementById('seed').value ? Number(document.getElementById('seed').value) : null;
  const steps = document.getElementById('steps').value ? Number(document.getElementById('steps').value) : null;
  const guidance = document.getElementById('guidance').value ? Number(document.getElementById('guidance').value) : null;
  const width = document.getElementById('width').value ? Number(document.getElementById('width').value) : null;
  const height = document.getElementById('height').value ? Number(document.getElementById('height').value) : null;
  const scheduler = document.getElementById('scheduler').value.trim();
  const strength = Number(document.getElementById('strength').value);
  const scope = getSelectedScope();

  if (!prompt) {
    setStatus('Enter a prompt.');
    return;
  }

  setStatus('Generating...');

  try {
    // Optionally enhance prompt before sending
    let finalPrompt = prompt;
    if (useEnhanced) {
      if (enhancedText) {
        finalPrompt = enhancedText;
      } else {
        const computed = await enhancePromptIfRequested();
        if (computed) finalPrompt = computed;
      }
    }
    // Build init images: scope composite + user references (max 8 total)
    const refs = await loadReferences();
    const initImages = [];
    const scopeB64 = await exportScopeToBase64(scope);
    if (scopeB64) initImages.push(scopeB64);
    for (const r of refs) {
      if (initImages.length >= 15) break;
      initImages.push(r.base64);
    }

    const size = document.getElementById('size').value.trim();
    const aspectRatio = document.getElementById('aspect-ratio').value.trim();
    const sequential = document.getElementById('sequential').value.trim() || 'auto';
    const maxImages = Number(document.getElementById('max-images').value) || 4;
    const replicateKey = await findApiKey('replicate');

    const body = {
      prompt: finalPrompt,
      negative_prompt: negative || null,
      seed,
      num_inference_steps: steps,
      guidance_scale: guidance,
      scheduler: scheduler || null,
      strength,
      scope,
      width: width || app.activeDocument.width,
      height: height || app.activeDocument.height,
      init_images_base64: initImages,
      size: size || null,
      aspect_ratio: aspectRatio || null,
      sequential_image_generation: sequential,
    max_images: Math.max(1, Math.min(15, maxImages)),
    token: replicateKey || null
    };
    const resp = await fetch('http://127.0.0.1:8000/seedream/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });

    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(`Server error: ${resp.status} ${text}`);
    }

    const json = await resp.json();
    if (!json || !json.image_base64) {
      throw new Error('Invalid server response');
    }

    const arr = base64ToArrayBuffer(json.image_base64);
    await placePngAsNewLayerFromArrayBuffer(arr);
    setStatus('Done. Output added as a new layer.');
  } catch (err) {
    console.error(err);
    setStatus(`Error: ${err.message}`);
  }
}

document.getElementById('strength').addEventListener('input', (e) => {
  document.getElementById('strength-value').textContent = Number(e.target.value).toFixed(2);
});

document.getElementById('seedream-form').addEventListener('submit', onGenerate);

// Presets
function collectForm() {
  return {
    prompt: document.getElementById('prompt').value,
    negative: document.getElementById('negative').value,
    seed: document.getElementById('seed').value,
    steps: document.getElementById('steps').value,
    guidance: document.getElementById('guidance').value,
    width: document.getElementById('width').value,
    height: document.getElementById('height').value,
    scheduler: document.getElementById('scheduler').value,
    scope: getSelectedScope(),
    strength: document.getElementById('strength').value
  };
}

function applyForm(p) {
  document.getElementById('prompt').value = p.prompt || '';
  document.getElementById('negative').value = p.negative || '';
  document.getElementById('seed').value = p.seed || '';
  document.getElementById('steps').value = p.steps || '';
  document.getElementById('guidance').value = p.guidance || '';
  document.getElementById('width').value = p.width || '';
  document.getElementById('height').value = p.height || '';
  document.getElementById('scheduler').value = p.scheduler || '';
  const scope = p.scope || 'whole-document';
  const radios = Array.from(document.querySelectorAll('input[name="scope"]'));
  radios.forEach(r => { r.checked = (r.value === scope); });
  document.getElementById('strength').value = p.strength || 0.7;
  document.getElementById('strength-value').textContent = Number(document.getElementById('strength').value).toFixed(2);
}

async function loadPresets() {
  const data = await readJson('presets.json', { items: [] });
  return Array.isArray(data.items) ? data.items : [];
}

async function savePresets(items) {
  await writeJson('presets.json', { items });
}

function renderPresets(items) {
  const ul = document.getElementById('preset-list');
  ul.innerHTML = '';
  items.forEach((it, idx) => {
    const li = document.createElement('li');
    const left = document.createElement('div');
    left.textContent = it.name;
    const right = document.createElement('div');
    const useBtn = document.createElement('button');
    useBtn.textContent = 'Use';
    useBtn.addEventListener('click', () => applyForm(it.payload));
    const delBtn = document.createElement('button');
    delBtn.textContent = 'Delete';
    delBtn.addEventListener('click', async () => {
      items.splice(idx, 1);
      await savePresets(items);
      renderPresets(items);
    });
    right.appendChild(useBtn);
    right.appendChild(delBtn);
    li.appendChild(left);
    li.appendChild(right);
    ul.appendChild(li);
  });
}

async function initPresets() {
  const items = await loadPresets();
  renderPresets(items);
  document.getElementById('save-preset').addEventListener('click', async () => {
    const name = document.getElementById('preset-name').value.trim() || 'Preset';
    const payload = collectForm();
    items.push({ name, payload });
    await savePresets(items);
    renderPresets(items);
    setStatus('Preset saved');
  });
}

// Library
async function loadLibrary() {
  const data = await readJson('library.json', { items: [] });
  return Array.isArray(data.items) ? data.items : [];
}

async function saveLibrary(items) {
  await writeJson('library.json', { items });
}

function renderLibrary(items) {
  const ul = document.getElementById('library-list');
  ul.innerHTML = '';
  items.forEach((it, idx) => {
    const li = document.createElement('li');
    const left = document.createElement('div');
    left.textContent = it.name;
    const right = document.createElement('div');
    const insertBtn = document.createElement('button');
    insertBtn.textContent = 'Insert';
    insertBtn.addEventListener('click', () => {
      document.getElementById('prompt').value = it.prompt || '';
      document.getElementById('negative').value = it.negative || '';
      switchTab('generate');
    });
    const addToMixerBtn = document.createElement('button');
    addToMixerBtn.textContent = 'Add to Mixer';
    addToMixerBtn.addEventListener('click', async () => {
      const mixer = await loadMixer();
      mixer.items.push({ type: 'library', name: it.name, prompt: it.prompt, negative: it.negative });
      await saveMixer(mixer);
      renderMixer(mixer);
      setStatus('Added to mixer');
    });
    const delBtn = document.createElement('button');
    delBtn.textContent = 'Delete';
    delBtn.addEventListener('click', async () => {
      items.splice(idx, 1);
      await saveLibrary(items);
      renderLibrary(items);
    });
    right.appendChild(insertBtn);
    right.appendChild(addToMixerBtn);
    right.appendChild(delBtn);
    li.appendChild(left);
    li.appendChild(right);
    ul.appendChild(li);
  });
}

async function initLibrary() {
  const items = await loadLibrary();
  renderLibrary(items);
  document.getElementById('library-add').addEventListener('click', async () => {
    const name = document.getElementById('library-name').value.trim() || 'Entry';
    const prompt = document.getElementById('library-prompt').value.trim();
    const negative = document.getElementById('library-negative').value.trim();
    items.push({ name, prompt, negative });
    await saveLibrary(items);
    renderLibrary(items);
    setStatus('Added to library');
  });
}

// Tabs wiring
document.querySelectorAll('.tab').forEach(btn => {
  btn.addEventListener('click', () => switchTab(btn.dataset.tab));
});

(async function init() {
  await initPresets();
  await initLibrary();
})();

// Mixer
async function loadMixer() {
  const data = await readJson('mixer.json', { items: [], blend: 0.5 });
  if (!Array.isArray(data.items)) data.items = [];
  if (typeof data.blend !== 'number') data.blend = 0.5;
  return data;
}

async function saveMixer(data) {
  await writeJson('mixer.json', data);
}

function renderMixer(state) {
  const ul = document.getElementById('mixer-list');
  ul.innerHTML = '';
  state.items.forEach((it, idx) => {
    const li = document.createElement('li');
    const left = document.createElement('div');
    left.textContent = `${it.name || 'Item'} — ${it.type}`;
    const right = document.createElement('div');
    const upBtn = document.createElement('button');
    upBtn.textContent = 'Up';
    upBtn.addEventListener('click', async () => {
      if (idx === 0) return;
      [state.items[idx - 1], state.items[idx]] = [state.items[idx], state.items[idx - 1]];
      await saveMixer(state);
      renderMixer(state);
    });
    const downBtn = document.createElement('button');
    downBtn.textContent = 'Down';
    downBtn.addEventListener('click', async () => {
      if (idx >= state.items.length - 1) return;
      [state.items[idx + 1], state.items[idx]] = [state.items[idx], state.items[idx + 1]];
      await saveMixer(state);
      renderMixer(state);
    });
    const delBtn = document.createElement('button');
    delBtn.textContent = 'Remove';
    delBtn.addEventListener('click', async () => {
      state.items.splice(idx, 1);
      await saveMixer(state);
      renderMixer(state);
    });
    right.appendChild(upBtn);
    right.appendChild(downBtn);
    right.appendChild(delBtn);
    li.appendChild(left);
    li.appendChild(right);
    ul.appendChild(li);
  });

  const blendEl = document.getElementById('mixer-blend');
  const blendVal = document.getElementById('mixer-blend-value');
  blendEl.value = state.blend;
  blendVal.textContent = Number(state.blend).toFixed(2);
}

function mixPrompts(items, blend) {
  if (items.length === 0) return { prompt: '', negative: '' };
  if (items.length === 1) return { prompt: items[0].prompt || '', negative: items[0].negative || '' };

  // Use first two for simple A/B blending; extend later for N-way
  const a = items[0];
  const b = items[1];
  const wA = 1 - blend;
  const wB = blend;

  // Token-weighted merge by simple interpolation of word counts
  const mergeText = (ta, tb) => {
    const wa = Math.max(1, Math.round(ta.split(/\s+/).filter(Boolean).length * wA));
    const wb = Math.max(1, Math.round(tb.split(/\s+/).filter(Boolean).length * wB));
    const aWords = ta.split(/\s+/).filter(Boolean).slice(0, wa);
    const bWords = tb.split(/\s+/).filter(Boolean).slice(0, wb);
    return [...aWords, ...bWords].join(' ');
  };

  return {
    prompt: mergeText(a.prompt || '', b.prompt || ''),
    negative: mergeText(a.negative || '', b.negative || '')
  };
}

async function initMixer() {
  const state = await loadMixer();
  renderMixer(state);

  document.getElementById('mixer-blend').addEventListener('input', async (e) => {
    state.blend = Number(e.target.value);
    document.getElementById('mixer-blend-value').textContent = state.blend.toFixed(2);
    await saveMixer(state);
  });

  document.getElementById('mixer-clear').addEventListener('click', async () => {
    state.items = [];
    await saveMixer(state);
    renderMixer(state);
  });

  document.getElementById('mixer-add-from-library').addEventListener('click', async () => {
    const lib = await loadLibrary();
    if (lib.length === 0) {
      setStatus('Library is empty');
      return;
    }
    // Pick the first for now. Later: selection dialog
    const entry = lib[0];
    state.items.push({ type: 'library', name: entry.name, prompt: entry.prompt, negative: entry.negative });
    await saveMixer(state);
    renderMixer(state);
  });

  document.getElementById('mixer-apply').addEventListener('click', async () => {
    const { prompt, negative } = mixPrompts(state.items, state.blend);
    document.getElementById('prompt').value = prompt;
    document.getElementById('negative').value = negative;
    switchTab('generate');
  });

  document.getElementById('mixer-generate').addEventListener('click', async () => {
    const { prompt, negative } = mixPrompts(state.items, state.blend);
    if (!prompt.trim()) {
      setStatus('Mixer produced empty prompt');
      return;
    }
    document.getElementById('prompt').value = prompt;
    document.getElementById('negative').value = negative;
    // Submit the existing form handler
    document.getElementById('seedream-form').dispatchEvent(new Event('submit'));
  });
}

(async function initMixerBoot() {
  await initMixer();
})();

// References (up to 8)
async function loadReferences() {
  const data = await readJson('references.json', { items: [] });
  if (!Array.isArray(data.items)) return [];
  return data.items;
}

async function saveReferences(items) {
  await writeJson('references.json', { items });
}

function renderReferences(items) {
  const ul = document.getElementById('refs-list');
  if (!ul) return;
  ul.innerHTML = '';
  items.forEach((it, idx) => {
    const li = document.createElement('li');
    li.draggable = true;
    li.dataset.index = String(idx);

    // Drag events
    li.addEventListener('dragstart', (e) => {
      e.dataTransfer.setData('text/plain', String(idx));
      e.dataTransfer.effectAllowed = 'move';
    });
    li.addEventListener('dragover', (e) => {
      e.preventDefault();
      li.classList.add('drag-over');
      e.dataTransfer.dropEffect = 'move';
    });
    li.addEventListener('dragleave', () => li.classList.remove('drag-over'));
    li.addEventListener('drop', async (e) => {
      e.preventDefault();
      li.classList.remove('drag-over');
      const fromIdx = Number(e.dataTransfer.getData('text/plain'));
      const toIdx = idx;
      if (Number.isNaN(fromIdx) || fromIdx === toIdx) return;
      const [moved] = items.splice(fromIdx, 1);
      items.splice(toIdx, 0, moved);
      await saveReferences(items);
      renderReferences(items);
    });

    const left = document.createElement('div');
    left.className = 'ref-left';
    const thumb = document.createElement('img');
    thumb.className = 'thumb';
    const mime = it.mime || 'image/png';
    thumb.src = `data:${mime};base64,${it.base64}`;
    const title = document.createElement('div');
    title.className = 'ref-title';
    title.textContent = it.name || `Ref ${idx + 1}`;
    left.appendChild(thumb);
    left.appendChild(title);

    const right = document.createElement('div');
    const delBtn = document.createElement('button');
    delBtn.textContent = 'Remove';
    delBtn.addEventListener('click', async () => {
      items.splice(idx, 1);
      await saveReferences(items);
      renderReferences(items);
    });
    right.appendChild(delBtn);

    li.appendChild(left);
    li.appendChild(right);
    ul.appendChild(li);
  });
}

async function initReferencesUI() {
  const items = await loadReferences();
  renderReferences(items);

  const addScopeBtn = document.getElementById('ref-add-scope');
  const addFileBtn = document.getElementById('ref-add-file');
  const clearBtn = document.getElementById('ref-clear');

  if (addScopeBtn) addScopeBtn.addEventListener('click', async () => {
    const scope = getSelectedScope();
    const b64 = await exportScopeToBase64(scope);
    if (!b64) return;
    if (items.length >= 15) { setStatus('Max 15 references'); return; }
    items.push({ name: `Scope ${scope}`, base64: b64, mime: 'image/png' });
    await saveReferences(items);
    renderReferences(items);
  });

  if (addFileBtn) addFileBtn.addEventListener('click', async () => {
    try {
      const file = await fs.getFileForOpening({ types: ['png', 'jpg', 'jpeg', 'webp'] });
      if (!file) return;
      const buf = await file.read({ format: uxp.storage.formats.binary });
      const b64 = arrayBufferToBase64(buf);
      if (items.length >= 15) { setStatus('Max 15 references'); return; }
      items.push({ name: file.name, base64: b64, mime: getMimeFromFilename(file.name) });
      await saveReferences(items);
      renderReferences(items);
    } catch (err) {
      console.error(err);
      setStatus('Failed to add file');
    }
  });

  if (clearBtn) clearBtn.addEventListener('click', async () => {
    items.splice(0, items.length);
    await saveReferences(items);
    renderReferences(items);
  });
}

(async function initReferencesBoot() {
  await initReferencesUI();
})();

// Settings: per-model API keys
async function loadApiKeys() {
  const data = await readJson('api_keys.json', { items: [] });
  return Array.isArray(data.items) ? data.items : [];
}

async function saveApiKeys(items) {
  await writeJson('api_keys.json', { items });
}

function renderApiKeys(items) {
  const container = document.getElementById('api-keys-list');
  if (!container) return;
  container.innerHTML = '';
  items.forEach((it, idx) => {
    const row = document.createElement('div');
    row.className = 'row';
    const info = document.createElement('div');
    info.textContent = `${it.provider}`;
    const del = document.createElement('button');
    del.textContent = 'Delete';
    del.addEventListener('click', async () => {
      items.splice(idx, 1);
      await saveApiKeys(items);
      renderApiKeys(items);
    });
    row.appendChild(info);
    row.appendChild(del);
    container.appendChild(row);
  });
}

async function initSettings() {
  const items = await loadApiKeys();
  renderApiKeys(items);
  const saveBtn = document.getElementById('api-save');
  const clearBtn = document.getElementById('api-clear');
  saveBtn.addEventListener('click', async () => {
    const provider = document.getElementById('api-provider').value.trim();
    const key = document.getElementById('api-key').value.trim();
    if (!provider || !key) { setStatus('Provider and key required'); return; }
    // ensure single entry per provider (replace existing)
    const idx = items.findIndex(i => i.provider === provider);
    if (idx >= 0) items.splice(idx, 1, { provider, key }); else items.push({ provider, key });
    await saveApiKeys(items);
    renderApiKeys(items);
    setStatus('API key saved');
  });
  clearBtn.addEventListener('click', async () => {
    items.splice(0, items.length);
    await saveApiKeys(items);
    renderApiKeys(items);
  });
}

(async function initSettingsBoot() {
  await initSettings();
})();

function findApiKey(provider, model) {
  // provider-level keys only
  return loadApiKeys().then(items => {
    const rec = items.find(i => i.provider === provider);
    return rec ? rec.key : null;
  });
}

// Enhance flow
async function enhancePromptIfRequested() {
  const enhancerModel = document.getElementById('enhancer-model').value;
  const useEnhanced = document.getElementById('use-enhanced').checked;
  const original = document.getElementById('prompt').value.trim();
  if (!useEnhanced || !original) return null;
  // Model format: provider:modelSlug (for provider lookup)
  const [provider, modelSlug] = enhancerModel.split(':');
  const token = await findApiKey(provider, modelSlug);
  try {
    const resp = await fetch('http://127.0.0.1:8000/seedream/enhance', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text: original,
        provider,
        model: modelSlug,
        token
      })
    });
    if (!resp.ok) throw new Error(`Enhance failed: ${resp.status}`);
    const json = await resp.json();
    const enhanced = json.text || original;
    document.getElementById('prompt-enhanced').value = enhanced;
    return enhanced;
  } catch (e) {
    console.error(e);
    setStatus('Enhance failed');
    return null;
  }
}

document.getElementById('enhance-prompt').addEventListener('click', async () => {
  setStatus('Enhancing...');
  const res = await enhancePromptIfRequested();
  setStatus(res ? 'Enhanced' : 'Enhance failed');
});


