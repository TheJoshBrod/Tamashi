/* ═══════════════════════════════════════════════════════════
   Tamashi | Memory Cartography
   ═══════════════════════════════════════════════════════════ */

let network = null;
let nodes = new vis.DataSet([]);
let edges = new vis.DataSet([]);
let selectedNodeJid = null;
let selectedEdgeId = null;
let currentSidebarMode = 'node'; // 'node' | 'edge' | 'new-edge'
let pendingEdgeData = null;
let pendingEdgeCallback = null;
let physicsEnabled = true;
let _stabilizeTimeout = null;
let hiddenTypes = new Set();
let hiddenKinds = new Set();
let showEdgeWeights = false;
let isHoveringNode = false;
let focusedNodeId = null;

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

const REL_KIND_OPTIONS = [
  ['relates_to', 'Relates to'],
  ['is_a', 'Is a (category / type)'],
  ['works_at', 'Works at'],
  ['lives_in', 'Lives in'],
  ['member_of', 'Member of'],
  ['loves', 'Loves / Likes'],
  ['uses', 'Uses'],
  ['owned_by', 'Owned by'],
  ['other', 'Other (Custom)'],
];

/* ── Shared helpers ───────────────────────────────────────── */
function nodeColorFromType(type) {
  const meta = TYPE_META[type] || TYPE_META.other;
  return {
    background: meta.bg,
    border: meta.border,
    highlight: { background: meta.bg, border: '#c9a84c' },
    hover: { background: meta.bg, border: meta.border },
  };
}

function nodeName(node) {
  return node?.subject?.name || node?.label || '';
}

function toggleCustomKind(containerId, value) {
  document.getElementById(containerId).style.display = value === 'other' ? 'block' : 'none';
}

/* ── Bootstrap ────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  const relKindHtml = REL_KIND_OPTIONS.map(([v, t]) => `<option value="${v}">${t}</option>`).join('');
  ['rel-kind-select', 'new-rel-kind', 'edge-kind'].forEach(id => {
    document.getElementById(id).innerHTML = relKindHtml;
  });

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
  const CONNECT_DIST_SQ = CONNECT_DIST * CONNECT_DIST;
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

    for (let i = 0; i < COUNT; i++) {
      for (let j = i + 1; j < COUNT; j++) {
        const dx = particles[i].x - particles[j].x;
        const dy = particles[i].y - particles[j].y;
        const distSq = dx * dx + dy * dy;
        if (distSq < CONNECT_DIST_SQ) {
          const a = (1 - Math.sqrt(distSq) / CONNECT_DIST) * 0.07;
          ctx.beginPath();
          ctx.moveTo(particles[i].x, particles[i].y);
          ctx.lineTo(particles[j].x, particles[j].y);
          ctx.strokeStyle = `rgba(201,168,76,${a})`;
          ctx.lineWidth = 0.5;
          ctx.stroke();
        }
      }
    }

    particles.forEach(p => {
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(201,168,76,${p.o})`;
      ctx.fill();

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
    if (_stabilizeTimeout) clearTimeout(_stabilizeTimeout);
  });

  network.on('selectNode', (params) => {
    const nodeId = params.nodes[0];
    if (network.isCluster(nodeId)) {
      network.openCluster(nodeId);
      network.unselectAll();
      return;
    }
    focusedNodeId = nodeId;
    updateIsolation();
  });

  network.on('deselectNode', (params) => {
    focusedNodeId = null;
    updateIsolation();
  });

  network.on('hoverNode', (params) => {
    if (!focusedNodeId) {
      isHoveringNode = true;
      updateIsolation(params.node);
    }
  });

  network.on('blurNode', (params) => {
    if (!focusedNodeId) {
      isHoveringNode = false;
      updateIsolation();
    }
  });
}

function updateIsolation(hoverId = null) {
  const focusCenter = focusedNodeId || hoverId;
  if (!focusCenter) {
    const nodeUpdates = [];
    nodes.get().forEach(n => {
      if (n.isolatedOpacity !== undefined) {
        nodeUpdates.push({
          id: n.id,
          isolatedOpacity: undefined,
          color: nodeColorFromType(n.subject?.subject_type?.toLowerCase() || 'other'),
          font: { color: '#ece4d4' }
        });
      }
    });
    if (nodeUpdates.length) nodes.update(nodeUpdates);

    const edgeUpdates = [];
    edges.get().forEach(e => {
      if (e.isolatedOpacity !== undefined) {
        edgeUpdates.push({
          id: e.id,
          isolatedOpacity: undefined,
          color: { color: 'rgba(201,168,76,0.18)' },
          font: { color: 'rgba(201,168,76,0.55)' }
        });
      }
    });
    if (edgeUpdates.length) edges.update(edgeUpdates);
    return;
  }

  const neighbors = network.getConnectedNodes(focusCenter);
  const focusSet = new Set(neighbors);
  focusSet.add(focusCenter);

  const nodeUpdates = [];
  nodes.get().forEach(n => {
    const isFocused = focusSet.has(n.id);
    const opacity = isFocused ? 1.0 : 0.15;
    if (n.isolatedOpacity !== opacity) {
      const type = n.subject?.subject_type?.toLowerCase() || 'other';
      const c = nodeColorFromType(type);
      c.opacity = opacity; // fallback if vis natively supports it

      // also construct rgba colors to assure vis dims it
      const rgbBg = hexToRgb(TYPE_META[type]?.bg || '#0c0e14');
      const rgbBorder = hexToRgb(TYPE_META[type]?.border || '#7090a4');
      if (rgbBg && rgbBorder) {
        c.background = `rgba(${rgbBg.r}, ${rgbBg.g}, ${rgbBg.b}, ${opacity})`;
        c.border = `rgba(${rgbBorder.r}, ${rgbBorder.g}, ${rgbBorder.b}, ${opacity})`;
        c.hover = { background: c.background, border: c.border };
        c.highlight = { background: c.background, border: c.border };
      }

      nodeUpdates.push({
        id: n.id,
        isolatedOpacity: opacity,
        color: c,
        font: { color: `rgba(236,228,212,${opacity})` }
      });
    }
  });
  if (nodeUpdates.length) nodes.update(nodeUpdates);

  const edgeUpdates = [];
  edges.get().forEach(e => {
    const isFocused = (e.from === focusCenter || e.to === focusCenter);
    const opacity = isFocused ? 1.0 : 0.05;
    if (e.isolatedOpacity !== opacity) {
      const c = isFocused ? 'rgba(201,168,76,0.75)' : 'rgba(201,168,76,0.05)';
      const fontC = isFocused ? 'rgba(201,168,76,0.55)' : 'rgba(201,168,76,0.05)';
      edgeUpdates.push({
        id: e.id,
        isolatedOpacity: opacity,
        color: { color: c, opacity: opacity },
        font: { color: fontC }
      });
    }
  });
  if (edgeUpdates.length) edges.update(edgeUpdates);
}

function hexToRgb(hex) {
  const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
  return result ? {
    r: parseInt(result[1], 16),
    g: parseInt(result[2], 16),
    b: parseInt(result[3], 16)
  } : null;
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
      return {
        id: subject.jid,
        label: subject.name,
        title: buildTooltip(subject),
        color: nodeColorFromType(type),
        // shadow disabled globally for performance
        subject,
      };
    });

    nodes.clear();
    edges.clear();

    const sEl = document.getElementById('stat-subjects');
    const rEl = document.getElementById('stat-relations');
    sEl.textContent = formattedNodes.length;
    rEl.textContent = data.edges.length;
    sEl.classList.toggle('loaded', formattedNodes.length > 0);
    rEl.classList.toggle('loaded', data.edges.length > 0);

    // subjects-list has no separate refresh path — must be kept in sync during data load
    const datalist = document.getElementById('subjects-list');
    datalist.innerHTML = '';
    formattedNodes.forEach(n => {
      const opt = document.createElement('option');
      opt.value = n.label;
      datalist.appendChild(opt);
    });

    if (formattedNodes.length > 0) {
      // barnesHut scales better past 500 nodes; forceAtlas2Based gives better aesthetics below that
      if (formattedNodes.length > 500) {
        network.setOptions({ physics: { solver: 'barnesHut' } });
      } else {
        network.setOptions({ physics: { solver: 'forceAtlas2Based' } });
      }

      const formattedEdges = [];
      const edgeMap = new Map();

      data.edges.forEach(e => {
        const minNode = e.from < e.to ? e.from : e.to;
        const maxNode = e.from < e.to ? e.to : e.from;
        const key = `${minNode}|${maxNode}|${e.kind}`;

        if (edgeMap.has(key)) {
          const existing = edgeMap.get(key);
          existing.isBidirectional = true;
          existing.arrows = 'to, from';
          existing.width = (existing.width || 1.4) * 1.5;
        } else {
          edgeMap.set(key, {
            ...e,
            width: showEdgeWeights ? Math.max(1.0, (e.weight || 1.0) * 1.8) : 1.4
          });
        }
      });

      edgeMap.forEach(e => formattedEdges.push(e));

      nodes.add(formattedNodes);
      edges.add(formattedEdges);
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
      if (_stabilizeTimeout) clearTimeout(_stabilizeTimeout);
      _stabilizeTimeout = setTimeout(() => setLoading(false), 2500);

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
        const updatedSubject = { ...payload, jid };
        nodes.update({
          id: jid,
          label: payload.name,
          title: buildTooltip(updatedSubject),
          color: nodeColorFromType(payload.subject_type),
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
    source: nodeName(srcNode),
    kind,
    target: nodeName(tgtNode),
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
    const url = `/display/api/memory/relations?source=${encodeURIComponent(nodeName(srcNode))}&kind=${encodeURIComponent(kind)}&target=${encodeURIComponent(nodeName(tgtNode))}`;
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

async function forceConsolidate() {
  const jid = document.getElementById('edit-jid').value;
  if (!jid) return;
  setLoading(true);
  try {
    const res = await fetch(`/display/api/memory/subjects/${encodeURIComponent(jid)}/consolidate`, { method: 'POST' });
    if (res.ok) {
      showToast('Consolidation triggered!');
      setTimeout(() => refreshGraph({ focusName: document.getElementById('edit-name').value }), 2500);
    } else {
      const err = await res.json();
      showToast('Consolidation failed: ' + (err.detail || ''));
    }
  } catch (e) {
    showToast('Consolidation error: ' + e.message);
  } finally {
    setLoading(false);
  }
}

/* ── Find Similar ─────────────────────────────────────────── */
let suggestedEdgeIds = [];

async function findSimilar() {
  const jid = document.getElementById('edit-jid').value;
  if (!jid) return;

  const btn = document.getElementById('find-similar-btn');
  const orgText = btn.textContent;
  btn.textContent = 'Searching...';
  btn.disabled = true;

  try {
    const res = await fetch(`/display/api/memory/subjects/${encodeURIComponent(jid)}/similar`);
    if (res.ok) {
      const data = await res.json();
      renderSuggestedRelations(jid, data.similar_jids);
    } else {
      showToast('Failed to find similar subjects');
    }
  } catch (err) {
    showToast('Search error: ' + err.message);
  } finally {
    btn.textContent = orgText;
    btn.disabled = false;
  }
}

function renderSuggestedRelations(sourceJid, similarJids) {
  clearSuggestedRelations();

  const container = document.getElementById('suggested-relations-container');
  const list = document.getElementById('suggested-relations-list');
  container.style.display = 'block';

  if (!similarJids || similarJids.length === 0) {
    list.innerHTML = '<div style="padding: 4px">No similar subjects found.</div>';
    return;
  }

  const newEdges = [];
  const htmlParts = [];

  similarJids.forEach(tgtJid => {
    const tgtNode = nodes.get(tgtJid);
    if (!tgtNode) return;

    // Check if edge already exists
    const existingEdges = network.getConnectedEdges(sourceJid);
    let alreadyConnected = false;
    existingEdges.forEach(eid => {
      const e = edges.get(eid);
      if (e && ((e.from === sourceJid && e.to === tgtJid) || (e.from === tgtJid && e.to === sourceJid))) {
        alreadyConnected = true;
      }
    });

    if (alreadyConnected) return;

    const edgeId = `suggest_${sourceJid}_${tgtJid}`;
    suggestedEdgeIds.push(edgeId);

    newEdges.push({
      id: edgeId,
      from: sourceJid,
      to: tgtJid,
      label: 'similar_to',
      kind: 'similar_to',
      dashes: true,
      color: { color: 'rgba(124, 232, 168, 0.6)' },
      font: { color: 'rgba(124, 232, 168, 0.8)' },
      isSuggestion: true
    });

    htmlParts.push(`
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px; padding-bottom:6px; border-bottom:1px solid rgba(201,168,76,0.1)">
        <span style="font-size:0.75rem; color:var(--text);">${nodeName(tgtNode)}</span>
        <div style="display:flex; gap: 4px;">
          <button class="btn btn-ghost" style="padding:4px 8px; font-size:0.55rem; color:var(--success); border-color:rgba(124,232,168,0.3)" onclick="approveSuggestion(event, '${edgeId}', '${sourceJid}', '${tgtJid}')">Approve</button>
          <button class="btn btn-ghost" style="padding:4px 8px; font-size:0.55rem; color:var(--danger); border-color:rgba(232,124,124,0.3)" onclick="dismissSuggestion(event, '${edgeId}')">Dismiss</button>
        </div>
      </div>
    `);
  });

  if (htmlParts.length === 0) {
    list.innerHTML = '<div style="padding: 4px">All similar subjects are already connected.</div>';
    return;
  }

  edges.add(newEdges);
  list.innerHTML = htmlParts.join('');
}

function clearSuggestedRelations() {
  if (suggestedEdgeIds.length > 0) {
    const toRemove = suggestedEdgeIds.filter(id => edges.get(id));
    if (toRemove.length > 0) edges.remove(toRemove);
    suggestedEdgeIds = [];
  }
  document.getElementById('suggested-relations-container').style.display = 'none';
  document.getElementById('suggested-relations-list').innerHTML = '';
}

function dismissSuggestion(event, edgeId) {
  if (edges.get(edgeId)) edges.remove(edgeId);
  const row = event.target.closest('div').parentElement;
  row.style.opacity = '0.3';
  row.style.pointerEvents = 'none';
}

function approveSuggestion(event, edgeId, srcJid, tgtJid) {
  const edgeData = edges.get(edgeId);
  if (!edgeData) return;

  const row = event.target.closest('div').parentElement;
  row.style.opacity = '0.3';
  row.style.pointerEvents = 'none';

  // Create permanent relation via API
  saveRelation({ from: srcJid, to: tgtJid }, 'similar_to', () => {
    // The callback logic triggers a graph refresh!
    // Just clear the overlay state
    clearSuggestedRelations();
  });
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

  const evts = s.recent_events || [];
  if (evts.length > 0) {
    document.getElementById('wal-container').style.display = 'block';
    const container = document.getElementById('wal-events');
    container.innerHTML = evts.map(e => `<div style="margin-bottom:8px; padding-bottom:8px; border-bottom:1px solid rgba(201,168,76,0.18)">${e}</div>`).join('');
  } else {
    document.getElementById('wal-container').style.display = 'none';
  }

  // Clear suggestions on load
  clearSuggestedRelations();

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

  document.getElementById('wal-container').style.display = 'none';

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
  clearSuggestedRelations();
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
  const srcName = nodeName(srcNode) || '?';
  const tgtName = nodeName(tgtNode) || '?';
  const kind = edge.kind || edge.label || '';

  selectedEdgeId = edgeId;
  selectedNodeJid = null;
  currentSidebarMode = 'edge';

  document.getElementById('edit-edge-id').value = edgeId;
  document.getElementById('edge-from-name').textContent = srcName;
  document.getElementById('edge-to-name').textContent = tgtName;

  // custom kinds not in the option list fall back to 'other' + free-text
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

  document.getElementById('node-fields').style.display = 'none';
  document.getElementById('edge-fields').style.display = '';

  document.getElementById('sidebar').classList.add('open');
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

  // API lacks an update endpoint — delete then recreate
  const source = nodeName(nodes.get(edge.from));
  const target = nodeName(nodes.get(edge.to));

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
      closeSidebar();
      refreshGraph();
    });
  }
}

function deleteSubject() {
  if (selectedNodeJid && confirm('Permanently remove this subject from memory?')) {
    apiDeleteSubject(selectedNodeJid, () => {
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

function toggleWeights() {
  showEdgeWeights = !showEdgeWeights;
  const btn = document.getElementById('weight-btn');
  if (btn) btn.style.color = showEdgeWeights ? 'var(--gold)' : '';

  const edgeUpdates = [];
  edges.get().forEach(e => {
    const rawWeight = e.weight || 1.0;
    const w = showEdgeWeights ? Math.max(1.0, rawWeight * 1.8) : 1.4;
    if (e.width !== w) {
      edgeUpdates.push({ id: e.id, width: w });
    }
  });
  if (edgeUpdates.length) edges.update(edgeUpdates);
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
function toggleFilterPanel() {
  const panel = document.getElementById('filter-panel');
  panel.classList.toggle('open');
}

function populateFilterPanel() {
  const typeCounts = {};
  nodes.get().forEach(n => {
    const t = n.subject?.subject_type?.toLowerCase() || 'other';
    typeCounts[t] = (typeCounts[t] || 0) + 1;
  });

  const typesEl = document.getElementById('filter-types');
  typesEl.innerHTML = '';
  Object.entries(TYPE_META).forEach(([type, meta]) => {
    const count = typeCounts[type] || 0;
    const isOff = hiddenTypes.has(type);
    const item = document.createElement('div');
    item.className = `fi subject-fi${isOff ? ' off' : ''}`;
    item.dataset.type = type;

    const isClustered = clusteredTypes.has(type);
    const clusterBtnStyle = isClustered ? 'color: var(--gold); border-color: var(--gold); background: rgba(201,168,76,0.1);' : 'color: var(--text-muted); opacity: 0.6;';

    item.innerHTML = `
      <div class="fi-check" onclick="toggleTypeFilter('${type}'); event.stopPropagation();">✓</div>
      <div class="fi-dot" style="background:${meta.border};box-shadow:0 0 4px ${meta.border}"></div>
      <span class="fi-label">${type}</span>
      <span class="fi-count">${count}</span>
      <button class="btn btn-ghost cluster-mini-btn" onclick="toggleSingleTypeCluster(event, '${type}')" title="Collapse/expand nodes of this type" style="padding: 2px 4px; font-size: 0.48rem; flex: 0 0 56px; text-align: center; margin-left: 0; box-sizing: border-box; ${clusterBtnStyle}">${isClustered ? 'Uncluster' : 'Cluster'}</button>
    `;
    item.addEventListener('click', (e) => {
      if (e.target.closest('button')) return;
      toggleTypeFilter(type);
    });
    typesEl.appendChild(item);
  });

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
    item.className = `fi relation-fi${isOff ? ' off' : ''}`;
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
  const allNodes = nodes.get();
  const nodeUpdates = [];
  const hiddenMap = new Map();
  let matchCount = 0;

  for (const n of allNodes) {
    const type = n.subject?.subject_type?.toLowerCase() || 'other';
    const hidden = hiddenTypes.has(type) || (re ? !matchesSearch(n.subject, re) : false);
    hiddenMap.set(n.id, hidden);
    if (n.hidden !== hidden) nodeUpdates.push({ id: n.id, hidden });
    if (!hidden) matchCount++;
  }
  if (nodeUpdates.length) nodes.update(nodeUpdates);

  const edgeUpdates = [];
  for (const e of edges.get()) {
    const hidden = !!hiddenMap.get(e.from) || !!hiddenMap.get(e.to)
      || hiddenKinds.has((e.kind || e.label || '').toLowerCase());
    if (e.hidden !== hidden) edgeUpdates.push({ id: e.id, hidden });
  }
  if (edgeUpdates.length) edges.update(edgeUpdates);

  return { matched: matchCount, total: allNodes.length };
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

  try {
    new RegExp(val, 'i');
    wrap.classList.remove('invalid');
  } catch {
    wrap.classList.add('invalid');
    statusEl.textContent = 'invalid regex';
    statusEl.className = 'search-status error';
    return;
  }

  const { matched, total } = applyFilter();
  updateFilterBtn();

  if (matched === 0) {
    statusEl.textContent = 'no matches';
    statusEl.className = 'search-status no-match';
  } else {
    statusEl.textContent = `${matched} of ${total}`;
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
  clearSearch(); // resets search input, calls applyFilter() + updateFilterBtn()
  populateFilterPanel();
}

function updateFilterBtn() {
  const searchActive = !!document.getElementById('search-input')?.value?.trim();
  const active = hiddenTypes.size > 0 || hiddenKinds.size > 0 || searchActive;
  document.getElementById('filter-btn').classList.toggle('filter-active', active);
}

/* ── Clustering ───────────────────────────────────────────── */
let clusteredTypes = new Set();

function toggleSingleTypeCluster(event, type) {
  event.stopPropagation();
  const btn = event.target.closest('button');

  if (clusteredTypes.has(type)) {
    clusteredTypes.delete(type);
    if (btn) {
      btn.style.color = 'var(--text-muted)';
      btn.style.borderColor = 'transparent';
      btn.style.background = 'transparent';
      btn.style.opacity = '0.6';
      btn.textContent = 'Cluster';
    }
    try {
      if (network.isCluster(`cluster_${type}`)) {
        network.openCluster(`cluster_${type}`);
      }
    } catch (e) { }
  } else {
    clusteredTypes.add(type);
    if (btn) {
      btn.style.color = 'var(--gold)';
      btn.style.borderColor = 'var(--gold)';
      btn.style.background = 'rgba(201,168,76,0.1)';
      btn.style.opacity = '1';
      btn.textContent = 'Uncluster';
    }
    network.cluster({
      joinCondition: function (nodeOptions) {
        if (!nodeOptions.subject) return false;
        return (nodeOptions.subject.subject_type || 'other').toLowerCase() === type;
      },
      clusterNodeProperties: {
        id: `cluster_${type}`,
        shape: 'hexagon',
        size: 38,
        font: { size: 14, color: '#ece4d4', face: '"JetBrains Mono", monospace' },
        color: nodeColorFromType(type),
      },
      processProperties: function (clusterOptions, childNodes) {
        clusterOptions.label = `[${type.toUpperCase()}]\n(${childNodes.length})`;
        return clusterOptions;
      }
    });
  }
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

/* ═══════════════════════════════════════════════════════════
   FILTER PANEL RESIZER
   ═══════════════════════════════════════════════════════════ */
document.addEventListener('DOMContentLoaded', () => {
  const resizer = document.getElementById('filter-resizer');
  const panel = document.getElementById('filter-panel');
  let isResizing = false;

  if (resizer && panel) {
    resizer.addEventListener('mousedown', (e) => {
      isResizing = true;
      resizer.classList.add('active');
      document.body.style.cursor = 'ew-resize';
      panel.style.transition = 'none';
      e.preventDefault();
    });

    document.addEventListener('mousemove', (e) => {
      if (!isResizing) return;
      let newWidth = e.clientX;
      if (newWidth < 220) newWidth = 220;
      if (newWidth > 600) newWidth = 600;
      panel.style.width = newWidth + 'px';
    });

    document.addEventListener('mouseup', () => {
      if (isResizing) {
        isResizing = false;
        resizer.classList.remove('active');
        document.body.style.cursor = '';
        panel.style.transition = '';
      }
    });
  }
});
