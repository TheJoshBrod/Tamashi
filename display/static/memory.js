/* ═══════════════════════════════════════════════════════════
   Tamashi | Memory Cartography
   ═══════════════════════════════════════════════════════════ */

let network = null;
let nodes = new vis.DataSet([]);
let edges = new vis.DataSet([]);
let selectedNodeJid = null;
let selectedEdgeId = null;
let currentSidebarMode = 'node'; // 'node' | 'edge'
let pendingEdgeData = null;
let pendingEdgeCallback = null;
let physicsEnabled = true;

/* ── Type styling ─────────────────────────────────────────── */
const TYPE_META = {
  person: { border: '#e87c8a', bg: '#1a0c10', shadow: 'rgba(232,124,138,0.55)' },
  concept: { border: '#7cb4e8', bg: '#0c1220', shadow: 'rgba(124,180,232,0.55)' },
  goal: { border: '#7ce8a8', bg: '#0c1a14', shadow: 'rgba(124,232,168,0.55)' },
  event: { border: '#e8c87c', bg: '#1a1510', shadow: 'rgba(232,200,124,0.55)' },
  place: { border: '#b47ce8', bg: '#100c1a', shadow: 'rgba(180,124,232,0.55)' },
  object: { border: '#e87cb4', bg: '#1a0c15', shadow: 'rgba(232,124,180,0.55)' },
  other: { border: '#7090a4', bg: '#0c0e14', shadow: 'rgba(112,144,164,0.45)' },
};

/* ── Bootstrap ────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  initBackground();
  initGraph();
  refreshGraph();

  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      if (network) network.disableEditMode();
      closeSidebar();
      closeRelationModal(false);
      closeFab();
    }
  });
});

/* ═══════════════════════════════════════════════════════════
   PARTICLE BACKGROUND
   ═══════════════════════════════════════════════════════════ */
function initBackground() {
  const canvas = document.getElementById('bg-canvas');
  const ctx = canvas.getContext('2d');
  const CONNECT_DIST = 110;
  const COUNT = 70;

  function resize() {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
  }
  resize();
  window.addEventListener('resize', resize);

  const particles = Array.from({ length: COUNT }, () => ({
    x: Math.random() * canvas.width,
    y: Math.random() * canvas.height,
    vx: (Math.random() - 0.5) * 0.12,
    vy: (Math.random() - 0.5) * 0.12,
    r: Math.random() * 1.2 + 0.4,
    o: Math.random() * 0.35 + 0.08,
  }));

  function frame() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    /* connections */
    for (let i = 0; i < COUNT; i++) {
      for (let j = i + 1; j < COUNT; j++) {
        const dx = particles[i].x - particles[j].x;
        const dy = particles[i].y - particles[j].y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < CONNECT_DIST) {
          const a = (1 - dist / CONNECT_DIST) * 0.07;
          ctx.beginPath();
          ctx.moveTo(particles[i].x, particles[i].y);
          ctx.lineTo(particles[j].x, particles[j].y);
          ctx.strokeStyle = `rgba(201,168,76,${a})`;
          ctx.lineWidth = 0.5;
          ctx.stroke();
        }
      }
    }

    /* points */
    particles.forEach(p => {
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(201,168,76,${p.o})`;
      ctx.fill();

      /* drift & wrap */
      p.x += p.vx;
      p.y += p.vy;
      if (p.x < 0) p.x = canvas.width;
      if (p.x > canvas.width) p.x = 0;
      if (p.y < 0) p.y = canvas.height;
      if (p.y > canvas.height) p.y = 0;
    });

    requestAnimationFrame(frame);
  }

  frame();
}

/* ═══════════════════════════════════════════════════════════
   VIS.JS GRAPH
   ═══════════════════════════════════════════════════════════ */
function initGraph() {
  const container = document.getElementById('graph-container');

  const options = {
    nodes: {
      shape: 'dot',
      size: 20,
      font: {
        color: '#ece4d4',
        size: 13,
        face: '"JetBrains Mono", monospace',
        strokeWidth: 3,
        strokeColor: '#040410',
      },
      borderWidth: 2,
      shadow: { enabled: false }, // Disabled: massive performance impact during zoom
      scaling: { label: { enabled: true, min: 12, max: 22 } },
    },
    edges: {
      width: 1.4,
      color: {
        color: 'rgba(201,168,76,0.18)',
        highlight: 'rgba(201,168,76,0.75)',
        hover: 'rgba(201,168,76,0.45)',
      },
      arrows: { to: { enabled: true, scaleFactor: 0.38 } },
      font: {
        size: 10,
        color: 'rgba(201,168,76,0.55)',
        face: '"JetBrains Mono", monospace',
        align: 'middle',
        strokeWidth: 3,
        strokeColor: '#040410',
      },
      smooth: { type: 'dynamic', roundness: 0.15 }, // use 'dynamic' for performance
    },
    physics: {
      enabled: true,
      solver: 'forceAtlas2Based',
      forceAtlas2Based: {
        gravitationalConstant: -50,
        centralGravity: 0.01,
        springConstant: 0.08,
        springLength: 100,
        damping: 0.4,
        avoidOverlap: 0,
      },
      maxVelocity: 45,
      stabilization: {
        enabled: true,
        iterations: 200,
        updateInterval: 50,
      },
    },
    interaction: {
      hover: true,
      multiselect: false,
      navigationButtons: false,
      tooltipDelay: 200,
      hideEdgesOnDrag: true, // drastically improves drag performance on large webs
    },
    manipulation: {
      enabled: true,
      addNode: false,
      editNode: (data, callback) => callback(data),
      addEdge: (edgeData, callback) => showRelationModal(edgeData, callback),
      deleteNode: (data, callback) => {
        const jid = data.nodes[0];
        if (confirm('Permanently remove this subject from memory?')) {
          apiDeleteSubject(jid, () => callback(data));
        } else {
          callback(null);
        }
      },
      deleteEdge: (data, callback) => {
        const edge = edges.get(data.edges[0]);
        if (confirm('Delete this relationship?')) {
          apiDeleteRelation(edge, () => callback(data));
        } else {
          callback(null);
        }
      },
    },
  };

  network = new vis.Network(container, { nodes, edges }, options);

  network.on('click', (params) => {
    if (params.nodes.length > 0) {
      showDetails(params.nodes[0]);
    } else if (params.edges.length > 0) {
      showEdgeDetails(params.edges[0]);
    } else {
      closeSidebar();
    }
  });

  network.on('stabilized', () => {
    setLoading(false);
    if (window._stabilizeTimeout) clearTimeout(window._stabilizeTimeout);
  });
}

/* ═══════════════════════════════════════════════════════════
   DATA LAYER
   ═══════════════════════════════════════════════════════════ */
async function refreshGraph({ focusName } = {}) {
  setLoading(true);
  try {
    const res = await fetch('/display/api/memory/graph');
    const data = await res.json();

    const formattedNodes = data.nodes.map(subject => {
      const type = subject.subject_type?.toLowerCase() || 'other';
      const meta = TYPE_META[type] || TYPE_META.other;
      return {
        id: subject.jid,
        label: subject.name,
        title: buildTooltip(subject),
        color: {
          background: meta.bg,
          border: meta.border,
          highlight: { background: meta.bg, border: '#c9a84c' },
          hover: { background: meta.bg, border: meta.border },
        },
        // shadow disabled globally for performance
        subject,
      };
    });

    nodes.clear();
    edges.clear();

    /* Update stats */
    const sEl = document.getElementById('stat-subjects');
    const rEl = document.getElementById('stat-relations');
    sEl.textContent = formattedNodes.length;
    rEl.textContent = data.edges.length;
    sEl.classList.toggle('loaded', formattedNodes.length > 0);
    rEl.classList.toggle('loaded', data.edges.length > 0);

    /* Keep datalist in sync for the new-relation sidebar */
    const datalist = document.getElementById('subjects-list');
    datalist.innerHTML = '';
    formattedNodes.forEach(n => {
      const opt = document.createElement('option');
      opt.value = n.label;
      datalist.appendChild(opt);
    });

    if (formattedNodes.length > 0) {
      /* Switch solver based on graph size */
      if (formattedNodes.length > 500) {
        network.setOptions({ physics: { solver: 'barnesHut' } });
      } else {
        network.setOptions({ physics: { solver: 'forceAtlas2Based' } });
      }

      nodes.add(formattedNodes);
      edges.add(data.edges);
      document.getElementById('empty-state').style.display = 'none';

      populateFilterPanel();
      applyFilter();

      if (focusName) {
        const target = formattedNodes.find(n => n.label === focusName);
        if (target) {
          const onStabilized = () => {
            network.off('stabilized', onStabilized);
            network.selectNodes([target.id]);
            network.focus(target.id, {
              scale: 1.4,
              animation: { duration: 700, easingFunction: 'easeInOutQuad' },
            });
          };
          network.on('stabilized', onStabilized);
        }
      } else {
        /* Default to a highly zoomed out perspective to avoid initial render lag */
        /* as nodes violently repel from (0,0) */
        network.moveTo({ scale: 0.15 });
      }


      /* Backup timeout in case stabilization takes forever or physics is paused */
      if (window._stabilizeTimeout) clearTimeout(window._stabilizeTimeout);
      window._stabilizeTimeout = setTimeout(() => setLoading(false), 2500);

    } else {
      document.getElementById('empty-state').style.display = 'block';
      setLoading(false);
    }
  } catch (err) {
    console.error('Failed to refresh graph:', err);
    showToast('Error loading graph: ' + err.message);
    setLoading(false);
  }
}

/* ── Subject CRUD ─────────────────────────────────────────── */
async function saveSubject() {
  const jid = document.getElementById('edit-jid').value;
  const isNew = !jid;

  const payload = {
    name: document.getElementById('edit-name').value.trim(),
    summary: document.getElementById('edit-summary').value.trim(),
    description: document.getElementById('edit-description').value.trim(),
    subject_type: document.getElementById('edit-type').value,
  };

  if (!payload.name) { showToast('Name is required'); return; }

  setLoading(true);
  const url = isNew
    ? '/display/api/memory/subjects'
    : `/display/api/memory/subjects/${encodeURIComponent(jid)}`;
  const method = isNew ? 'POST' : 'PUT';

  try {
    const res = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (res.ok) {
      showToast(isNew ? 'Subject created' : 'Subject saved');
      closeSidebar();
      if (isNew) {
        /* New node: need the server-assigned JID, so a full refresh is required */
        refreshGraph({ focusName: payload.name });
      } else {
        /* Existing node: patch the DataSet in-place, no graph redraw */
        const type = payload.subject_type;
        const meta = TYPE_META[type] || TYPE_META.other;
        const updatedSubject = { ...payload, jid };
        nodes.update({
          id: jid,
          label: payload.name,
          title: buildTooltip(updatedSubject),
          color: {
            background: meta.bg,
            border: meta.border,
            highlight: { background: meta.bg, border: '#c9a84c' },
            hover: { background: meta.bg, border: meta.border },
          },
          // shadow disabled globally for performance
          subject: updatedSubject,
        });
        setLoading(false);
      }
    } else {
      const err = await res.json();
      showToast('Error: ' + err.detail);
      setLoading(false);
    }
  } catch (err) {
    showToast('Request failed: ' + err.message);
    setLoading(false);
  }
}

async function apiDeleteSubject(jid, callback) {
  setLoading(true);
  try {
    const res = await fetch(
      `/display/api/memory/subjects/${encodeURIComponent(jid)}`,
      { method: 'DELETE' }
    );
    if (res.ok) {
      showToast('Subject removed');
      callback();
    } else {
      const err = await res.json();
      showToast('Delete failed: ' + err.detail);
    }
  } catch (err) {
    showToast('Delete failed: ' + err.message);
  } finally {
    setLoading(false);
  }
}

async function saveRelation(edgeData, kind, callback) {
  const srcNode = nodes.get(edgeData.from);
  const tgtNode = nodes.get(edgeData.to);

  if (!srcNode || !tgtNode) {
    showToast('Error: node context lost');
    callback(null);
    return;
  }

  const payload = {
    source: srcNode.subject?.name || srcNode.label,
    kind,
    target: tgtNode.subject?.name || tgtNode.label,
  };

  setLoading(true);
  try {
    const res = await fetch('/display/api/memory/relations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (res.ok) {
      showToast(`Relation established: ${kind}`);
      callback(edgeData);
      setTimeout(() => refreshGraph(), 500);
    } else {
      showToast('Failed to save relation');
      callback(null);
    }
  } catch (err) {
    showToast('Relation request failed');
    callback(null);
  } finally {
    setLoading(false);
  }
}

async function apiDeleteRelation(edge, callback) {
  const srcNode = nodes.get(edge.from);
  const tgtNode = nodes.get(edge.to);
  const kind = edge.kind || edge.label;

  setLoading(true);
  try {
    const url = `/display/api/memory/relations?source=${encodeURIComponent(srcNode?.subject?.name || srcNode?.label || '')}&kind=${encodeURIComponent(kind)}&target=${encodeURIComponent(tgtNode?.subject?.name || tgtNode?.label || '')}`;
    const res = await fetch(url, { method: 'DELETE' });
    if (res.ok) {
      showToast('Relation removed');
      callback();
    } else {
      showToast('Failed to delete relation');
    }
  } catch (err) {
    showToast('Delete relation failed');
  } finally {
    setLoading(false);
  }
}

/* ═══════════════════════════════════════════════════════════
   SIDEBAR
   ═══════════════════════════════════════════════════════════ */
function showDetails(jid) {
  const node = nodes.get(jid);
  if (!node) return;

  selectedNodeJid = jid;
  const s = node.subject || {};

  document.getElementById('edit-jid').value = jid;
  document.getElementById('edit-name').value = s.name || '';
  document.getElementById('edit-summary').value = s.summary || '';
  document.getElementById('edit-description').value = s.description || '';
  document.getElementById('edit-type').value = s.subject_type?.toLowerCase() || 'other';

  document.getElementById('sb-mode').textContent = 'Editing Subject';
  document.getElementById('sb-title').textContent = s.name || 'Subject';
  document.getElementById('save-btn').textContent = 'Save Changes';
  document.getElementById('delete-btn').textContent = 'Delete Subject';
  document.getElementById('delete-btn').style.display = '';

  document.getElementById('node-fields').style.display = '';
  document.getElementById('edge-fields').style.display = 'none';
  currentSidebarMode = 'node';

  document.getElementById('sidebar').classList.add('open');
}

function createNewSubject() {
  closeFab();
  selectedNodeJid = null;

  document.getElementById('edit-jid').value = '';
  document.getElementById('edit-name').value = '';
  document.getElementById('edit-summary').value = '';
  document.getElementById('edit-description').value = '';
  document.getElementById('edit-type').value = 'person';

  document.getElementById('sb-mode').textContent = 'New Subject';
  document.getElementById('sb-title').textContent = 'Untitled';
  document.getElementById('save-btn').textContent = 'Create Subject';
  document.getElementById('delete-btn').style.display = 'none';

  document.getElementById('node-fields').style.display = '';
  document.getElementById('edge-fields').style.display = 'none';
  currentSidebarMode = 'node';

  document.getElementById('sidebar').classList.add('open');
  if (network) network.unselectAll();

  /* Focus the name field after the slide-in animation */
  setTimeout(() => document.getElementById('edit-name').focus(), 380);
}

function closeSidebar() {
  document.getElementById('sidebar').classList.remove('open');
  selectedNodeJid = null;
  selectedEdgeId = null;
  currentSidebarMode = 'node';
  if (network) network.unselectAll();
}

/* ── Dispatch helpers ─────────────────────────────────────── */
function saveDispatch() {
  if (currentSidebarMode === 'edge') saveEdge();
  else if (currentSidebarMode === 'new-edge') saveNewRelation();
  else saveSubject();
}

function deleteDispatch() {
  if (currentSidebarMode === 'edge') deleteEdgeFromSidebar();
  else deleteSubject();
}

/* ── Edge sidebar ─────────────────────────────────────────── */
function showEdgeDetails(edgeId) {
  const edge = edges.get(edgeId);
  if (!edge) return;

  const srcNode = nodes.get(edge.from);
  const tgtNode = nodes.get(edge.to);
  const srcName = srcNode?.subject?.name || srcNode?.label || '?';
  const tgtName = tgtNode?.subject?.name || tgtNode?.label || '?';
  const kind = edge.kind || edge.label || '';

  selectedEdgeId = edgeId;
  selectedNodeJid = null;
  currentSidebarMode = 'edge';

  document.getElementById('edit-edge-id').value = edgeId;
  document.getElementById('edge-from-name').textContent = srcName;
  document.getElementById('edge-to-name').textContent = tgtName;

  /* Pre-select the dropdown; fall back to 'other' for custom kinds */
  const select = document.getElementById('edge-kind');
  const knownOpts = Array.from(select.options).map(o => o.value);
  if (knownOpts.includes(kind)) {
    select.value = kind;
    document.getElementById('edge-custom-container').style.display = 'none';
  } else {
    select.value = 'other';
    document.getElementById('edge-custom-container').style.display = 'block';
    document.getElementById('edge-kind-custom').value = kind;
  }

  document.getElementById('sb-mode').textContent = 'Editing Relation';
  document.getElementById('sb-title').textContent = `${srcName} → ${tgtName}`;
  document.getElementById('save-btn').textContent = 'Save Changes';
  document.getElementById('delete-btn').textContent = 'Delete Relation';
  document.getElementById('delete-btn').style.display = '';

  /* Swap visible panels */
  document.getElementById('node-fields').style.display = 'none';
  document.getElementById('edge-fields').style.display = '';

  document.getElementById('sidebar').classList.add('open');
}

function toggleEdgeCustomKind(value) {
  document.getElementById('edge-custom-container').style.display =
    value === 'other' ? 'block' : 'none';
}

async function saveEdge() {
  const edgeId = document.getElementById('edit-edge-id').value;
  const edge = edges.get(edgeId);
  if (!edge) return;

  let newKind = document.getElementById('edge-kind').value;
  if (newKind === 'other') {
    newKind = document.getElementById('edge-kind-custom').value.trim();
  }
  if (!newKind) { showToast('Relationship type is required'); return; }

  const oldKind = edge.kind || edge.label;
  if (newKind === oldKind) { closeSidebar(); return; }

  setLoading(true);

  /* Delete old relation then create the new one */
  const srcNode = nodes.get(edge.from);
  const tgtNode = nodes.get(edge.to);
  const source = srcNode?.subject?.name || srcNode?.label || '';
  const target = tgtNode?.subject?.name || tgtNode?.label || '';

  try {
    const delUrl = `/display/api/memory/relations?source=${encodeURIComponent(source)}&kind=${encodeURIComponent(oldKind)}&target=${encodeURIComponent(target)}`;
    await fetch(delUrl, { method: 'DELETE' });

    const res = await fetch('/display/api/memory/relations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source, kind: newKind, target }),
    });

    if (res.ok) {
      showToast('Relation updated');
      closeSidebar();
      refreshGraph();
    } else {
      showToast('Failed to update relation');
      setLoading(false);
    }
  } catch (err) {
    showToast('Update failed: ' + err.message);
    setLoading(false);
  }
}

function deleteEdgeFromSidebar() {
  const edgeId = document.getElementById('edit-edge-id').value;
  const edge = edges.get(edgeId);
  if (!edge) return;

  if (confirm('Delete this relationship?')) {
    apiDeleteRelation(edge, () => {
      edges.remove(edgeId);
      closeSidebar();
      refreshGraph();
    });
  }
}

function deleteSubject() {
  if (selectedNodeJid && confirm('Permanently remove this subject from memory?')) {
    apiDeleteSubject(selectedNodeJid, () => {
      nodes.remove(selectedNodeJid);
      closeSidebar();
      refreshGraph();
    });
  }
}

/* ═══════════════════════════════════════════════════════════
   FAB
   ═══════════════════════════════════════════════════════════ */
function togglePhysics() {
  physicsEnabled = !physicsEnabled;
  network.setOptions({ physics: { enabled: physicsEnabled } });
  const btn = document.getElementById('physics-btn');
  btn.textContent = physicsEnabled ? '⏸' : '▶';
  btn.title = physicsEnabled ? 'Pause physics' : 'Resume physics';
}

function toggleFab() {
  document.getElementById('fab').classList.toggle('open');
}

function closeFab() {
  document.getElementById('fab').classList.remove('open');
}

function startAddEdgeFlow() {
  closeFab();
  showNewRelationSidebar();
}

function showNewRelationSidebar(prefillSource = '') {
  selectedNodeJid = null;
  selectedEdgeId = null;
  currentSidebarMode = 'new-edge';

  document.getElementById('new-rel-source').value = prefillSource;
  document.getElementById('new-rel-target').value = '';
  document.getElementById('new-rel-kind').value = 'relates_to';
  document.getElementById('new-rel-kind-custom').value = '';
  document.getElementById('new-rel-custom-container').style.display = 'none';

  document.getElementById('sb-mode').textContent = 'New Relation';
  document.getElementById('sb-title').textContent = 'Connect Subjects';
  document.getElementById('save-btn').textContent = 'Establish Relation';
  document.getElementById('delete-btn').style.display = 'none';

  document.getElementById('node-fields').style.display = 'none';
  document.getElementById('edge-fields').style.display = 'none';
  document.getElementById('new-edge-fields').style.display = '';

  document.getElementById('sidebar').classList.add('open');
  if (network) network.unselectAll();
  setTimeout(() => document.getElementById('new-rel-source').focus(), 380);
}

async function saveNewRelation() {
  const source = document.getElementById('new-rel-source').value.trim();
  const target = document.getElementById('new-rel-target').value.trim();
  let kind = document.getElementById('new-rel-kind').value;
  if (kind === 'other') {
    kind = document.getElementById('new-rel-kind-custom').value.trim();
  }

  if (!source || !target) { showToast('Source and target are required'); return; }
  if (!kind) { showToast('Relationship type is required'); return; }

  setLoading(true);
  try {
    const res = await fetch('/display/api/memory/relations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source, kind, target }),
    });
    if (res.ok) {
      showToast('Relation established');
      closeSidebar();
      refreshGraph();
    } else {
      showToast('Failed to create relation');
      setLoading(false);
    }
  } catch (err) {
    showToast('Request failed: ' + err.message);
    setLoading(false);
  }
}

function toggleNewRelCustomKind(value) {
  document.getElementById('new-rel-custom-container').style.display =
    value === 'other' ? 'block' : 'none';
}

/* ═══════════════════════════════════════════════════════════
   RELATION MODAL
   ═══════════════════════════════════════════════════════════ */
function showRelationModal(edgeData, callback) {
  pendingEdgeData = edgeData;
  pendingEdgeCallback = callback;

  document.getElementById('rel-kind-select').value = 'relates_to';
  document.getElementById('rel-kind-custom').value = '';
  document.getElementById('custom-rel-container').style.display = 'none';

  document.getElementById('relation-modal').style.display = 'flex';
}

function toggleCustomRel(value) {
  document.getElementById('custom-rel-container').style.display =
    value === 'other' ? 'block' : 'none';
}

function closeRelationModal(success) {
  document.getElementById('relation-modal').style.display = 'none';

  if (success && pendingEdgeData && pendingEdgeCallback) {
    let kind = document.getElementById('rel-kind-select').value;
    if (kind === 'other') {
      kind = document.getElementById('rel-kind-custom').value.trim();
    }

    if (kind) {
      pendingEdgeData.label = kind;
      saveRelation(pendingEdgeData, kind, pendingEdgeCallback);
    } else {
      showToast('Relation type is required');
      pendingEdgeCallback(null);
    }
  } else if (pendingEdgeCallback) {
    pendingEdgeCallback(null);
  }

  pendingEdgeData = null;
  pendingEdgeCallback = null;
}

/* ═══════════════════════════════════════════════════════════
   FILTER PANEL
   ═══════════════════════════════════════════════════════════ */
let hiddenTypes = new Set();
let hiddenKinds = new Set();

const TYPE_COLORS = {
  person: '#e87c8a',
  concept: '#7cb4e8',
  goal: '#7ce8a8',
  event: '#e8c87c',
  place: '#b47ce8',
  object: '#e87cb4',
  other: '#7090a4',
};

function toggleFilterPanel() {
  const panel = document.getElementById('filter-panel');
  panel.classList.toggle('open');
}

function populateFilterPanel() {
  /* ── Subject types ── */
  const typeCounts = {};
  nodes.get().forEach(n => {
    const t = n.subject?.subject_type?.toLowerCase() || 'other';
    typeCounts[t] = (typeCounts[t] || 0) + 1;
  });

  const typesEl = document.getElementById('filter-types');
  typesEl.innerHTML = '';
  Object.entries(TYPE_COLORS).forEach(([type, color]) => {
    const count = typeCounts[type] || 0;
    const isOff = hiddenTypes.has(type);
    const item = document.createElement('div');
    item.className = `fi${isOff ? ' off' : ''}`;
    item.dataset.type = type;
    item.innerHTML = `
      <div class="fi-check">✓</div>
      <div class="fi-dot" style="background:${color};box-shadow:0 0 4px ${color}"></div>
      <span class="fi-label">${type}</span>
      <span class="fi-count">${count}</span>`;
    item.addEventListener('click', () => toggleTypeFilter(type));
    typesEl.appendChild(item);
  });

  /* ── Relation kinds ── */
  const kindCounts = {};
  edges.get().forEach(e => {
    const k = (e.kind || e.label || 'unknown').toLowerCase();
    kindCounts[k] = (kindCounts[k] || 0) + 1;
  });

  const kindsEl = document.getElementById('filter-kinds');
  const kindsSection = document.getElementById('filter-kinds-section');
  kindsEl.innerHTML = '';

  const kindEntries = Object.entries(kindCounts);
  kindsSection.style.display = kindEntries.length > 0 ? '' : 'none';

  kindEntries.sort((a, b) => b[1] - a[1]).forEach(([kind, count]) => {
    const isOff = hiddenKinds.has(kind);
    const item = document.createElement('div');
    item.className = `fi${isOff ? ' off' : ''}`;
    item.dataset.kind = kind;
    item.innerHTML = `
      <div class="fi-check">✓</div>
      <span class="fi-label">${kind.replace(/_/g, ' ')}</span>
      <span class="fi-count">${count}</span>`;
    item.addEventListener('click', () => toggleKindFilter(kind));
    kindsEl.appendChild(item);
  });
}

function toggleTypeFilter(type) {
  if (hiddenTypes.has(type)) hiddenTypes.delete(type);
  else hiddenTypes.add(type);
  applyFilter();
  populateFilterPanel();
  updateFilterBtn();
}

function toggleKindFilter(kind) {
  if (hiddenKinds.has(kind)) hiddenKinds.delete(kind);
  else hiddenKinds.add(kind);
  applyFilter();
  populateFilterPanel();
  updateFilterBtn();
}

function applyFilter() {
  const re = getSearchRegex();

  /* Nodes: hide if type-filtered OR doesn't match search */
  nodes.update(nodes.get().map(n => {
    const type = n.subject?.subject_type?.toLowerCase() || 'other';
    const typeHidden = hiddenTypes.has(type);
    const srchHidden = re ? !matchesSearch(n.subject, re) : false;
    return { id: n.id, hidden: typeHidden || srchHidden };
  }));

  /* Edges: hide if connected node is hidden OR relation kind is hidden */
  edges.update(edges.get().map(e => ({
    id: e.id,
    hidden: nodes.get(e.from)?.hidden
      || nodes.get(e.to)?.hidden
      || hiddenKinds.has((e.kind || e.label || '').toLowerCase()),
  })));
}

/* ── Search helpers ───────────────────────────────────────── */
function getSearchRegex() {
  const val = document.getElementById('search-input')?.value?.trim();
  if (!val) return null;
  try { return new RegExp(val, 'i'); }
  catch { return null; }
}

function matchesSearch(subject, re) {
  return re.test(subject?.name || '')
    || re.test(subject?.summary || '')
    || re.test(subject?.description || '');
}

function onSearchInput() {
  const val = document.getElementById('search-input').value;
  const clearBtn = document.getElementById('search-clear');
  const statusEl = document.getElementById('search-status');
  const wrap = document.getElementById('search-wrap');

  clearBtn.style.display = val.trim() ? '' : 'none';

  if (!val.trim()) {
    wrap.classList.remove('invalid');
    statusEl.textContent = '';
    statusEl.className = 'search-status';
    applyFilter();
    updateFilterBtn();
    return;
  }

  /* Validate regex first */
  try {
    new RegExp(val, 'i');
    wrap.classList.remove('invalid');
  } catch {
    wrap.classList.add('invalid');
    statusEl.textContent = 'invalid regex';
    statusEl.className = 'search-status error';
    return;
  }

  applyFilter();
  updateFilterBtn();

  /* Show match count after filter is applied */
  const all = nodes.get();
  const matched = all.filter(n => !n.hidden).length;
  if (matched === 0) {
    statusEl.textContent = 'no matches';
    statusEl.className = 'search-status no-match';
  } else {
    statusEl.textContent = `${matched} of ${all.length}`;
    statusEl.className = 'search-status has-match';
  }
}

function clearSearch() {
  const input = document.getElementById('search-input');
  const clearBtn = document.getElementById('search-clear');
  const statusEl = document.getElementById('search-status');
  const wrap = document.getElementById('search-wrap');

  input.value = '';
  clearBtn.style.display = 'none';
  statusEl.textContent = '';
  statusEl.className = 'search-status';
  wrap.classList.remove('invalid');

  applyFilter();
  updateFilterBtn();
}

function clearFilters() {
  hiddenTypes.clear();
  hiddenKinds.clear();
  clearSearch();        // also resets search input + re-applies
  populateFilterPanel();
  updateFilterBtn();
}

function updateFilterBtn() {
  const searchActive = !!document.getElementById('search-input')?.value?.trim();
  const active = hiddenTypes.size > 0 || hiddenKinds.size > 0 || searchActive;
  document.getElementById('filter-btn').classList.toggle('filter-active', active);
}

/* ═══════════════════════════════════════════════════════════
   UI UTILITIES
   ═══════════════════════════════════════════════════════════ */
function setLoading(active) {
  document.getElementById('loading-overlay').style.display = active ? 'flex' : 'none';
}

function showToast(message) {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.textContent = message;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.transition = 'opacity 0.25s';
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 280);
  }, 3000);
}

function buildTooltip(subject) {
  const type = subject.subject_type?.toLowerCase() || 'other';
  const meta = TYPE_META[type] || TYPE_META.other;

  const el = document.createElement('div');
  el.style.cssText = 'padding:4px 2px;min-width:140px;max-width:220px;';

  const name = document.createElement('div');
  name.textContent = subject.name;
  name.style.cssText = `color:${meta.border};font-weight:500;margin-bottom:5px;font-size:0.85rem;`;
  el.appendChild(name);

  const typeTag = document.createElement('div');
  typeTag.textContent = type.toUpperCase();
  typeTag.style.cssText = `font-size:0.55rem;letter-spacing:0.12em;color:rgba(236,228,212,0.35);margin-bottom:6px;`;
  el.appendChild(typeTag);

  if (subject.summary) {
    const summary = document.createElement('div');
    summary.textContent = subject.summary;
    summary.style.cssText = 'font-size:0.72rem;color:rgba(236,228,212,0.6);line-height:1.45;';
    el.appendChild(summary);
  }

  return el;
}
