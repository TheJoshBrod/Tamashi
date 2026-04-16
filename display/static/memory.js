let network = null;
let nodes = new vis.DataSet([]);
let edges = new vis.DataSet([]);
let selectedNodeJid = null;
let pendingEdgeData = null;
let pendingEdgeCallback = null;

const TYPE_COLORS = {
    person: '#ef4444',
    concept: '#38bdf8',
    goal: '#22c55e',
    event: '#f59e0b',
    place: '#8b5cf6',
    object: '#ec4899',
    other: '#94a3b8'
};

document.addEventListener('DOMContentLoaded', () => {
    initGraph();
    refreshGraph();

    // Global ESC key listener for dismissing overlays
    window.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeSidebar();
            closeRelationModal(false);
        }
    });
});

function initGraph() {
    const container = document.getElementById('graph-container');
    const data = { nodes, edges };
    const options = {
        nodes: {
            shape: 'dot',
            size: 25,
            font: { color: '#f8fafc', size: 14, strokeWidth: 2, strokeColor: '#0f172a' },
            borderWidth: 2,
            shadow: true,
            scaling: { label: { enabled: true, min: 14, max: 24 } }
        },
        edges: {
            width: 2,
            color: { color: '#445566', highlight: '#38bdf8' },
            arrows: { to: { enabled: true, scaleFactor: 0.5 } },
            font: { size: 12, color: '#94a3b8', align: 'middle' },
            smooth: { type: 'continuous' }
        },
        physics: {
            forceAtlas2Based: {
                gravitationalConstant: -100,
                centralGravity: 0.01,
                springLength: 150,
                springConstant: 0.08
            },
            maxVelocity: 50,
            solver: 'forceAtlas2Based',
            stabilization: { iterations: 150 }
        },
        interaction: {
            hover: true,
            multiselect: false,
            navigationButtons: false // Using custom zoom controls
        },
        manipulation: {
            enabled: true,
            addNode: false,
            // Vis.js standalone expects a function for editNode if manipulation is enabled
            editNode: function (data, callback) { callback(data); },
            addEdge: function (edgeData, callback) {
                showRelationModal(edgeData, callback);
            },
            deleteNode: function (data, callback) {
                const jid = data.nodes[0];
                if (confirm("Permanently delete this memory subject?")) {
                    apiDeleteSubject(jid, () => callback(data));
                } else {
                    callback(null);
                }
            },
            deleteEdge: function (data, callback) {
                const edgeId = data.edges[0];
                const edge = edges.get(edgeId);
                if (confirm("Delete this relationship?")) {
                    apiDeleteRelation(edge, () => callback(data));
                } else {
                    callback(null);
                }
            }
        }
    };

    network = new vis.Network(container, data, options);

    // Reliable Selection
    network.on("click", (params) => {
        if (params.nodes.length > 0) {
            const nodeJid = params.nodes[0];
            showDetails(nodeJid);
        } else {
            // Check if we clicked "nothing" (close sidebar)
            if (params.nodes.length === 0 && params.edges.length === 0) {
                closeSidebar();
            }
        }
    });

    network.on("stabilized", () => {
        setLoading(false);
    });
}

function setLoading(active) {
    document.getElementById('loading-overlay').style.display = active ? 'flex' : 'none';
}

function showToast(message) {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.innerText = message;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

async function refreshGraph() {
    setLoading(true);
    try {
        const response = await fetch('/display/api/memory/graph');
        const data = await response.json();

        const formattedNodes = data.nodes.map(subject => ({
            id: subject.jid,
            label: subject.name,
            title: createNodeTooltip(subject),
            color: subject.subject_type ? TYPE_COLORS[subject.subject_type.toLowerCase()] || TYPE_COLORS.other : TYPE_COLORS.other,
            subject: subject // Keep full subject data for later
        }));

        nodes.clear();
        edges.clear();

        if (formattedNodes.length > 0) {
            nodes.add(formattedNodes);
            edges.add(data.edges);
            document.getElementById('empty-state').style.display = 'none';
        } else {
            document.getElementById('empty-state').style.display = 'block';
            setLoading(false);
        }
    } catch (err) {
        console.error("Failed to refresh graph:", err);
        showToast("Error: " + err.message);
        setLoading(false);
    }
}

function showDetails(jid) {
    const node = nodes.get(jid);
    if (!node) return;

    selectedNodeJid = jid;
    const subject = node.subject || {};

    document.getElementById('edit-jid').value = jid;
    document.getElementById('edit-name').value = subject.name || '';
    document.getElementById('edit-summary').value = subject.summary || '';
    document.getElementById('edit-description').value = subject.description || '';
    document.getElementById('edit-type').value = subject.subject_type?.toLowerCase() || 'other';

    document.getElementById('detail-title').innerText = "Details: " + (subject.name || "Subject");
    document.getElementById('sidebar').classList.remove('sidebar-hidden');

    document.getElementById('save-btn').innerText = "Save Changes";
}

function closeSidebar() {
    document.getElementById('sidebar').classList.add('sidebar-hidden');
    selectedNodeJid = null;
    if (network) network.unselectAll();
}

async function saveSubject() {
    const jid = document.getElementById('edit-jid').value;
    const isNew = !jid;

    const payload = {
        name: document.getElementById('edit-name').value,
        summary: document.getElementById('edit-summary').value,
        description: document.getElementById('edit-description').value,
        subject_type: document.getElementById('edit-type').value
    };

    if (!payload.name) {
        showToast("Name is required");
        return;
    }

    setLoading(true);
    const encodedJid = encodeURIComponent(jid);
    const url = isNew ? '/display/api/memory/subjects' : `/display/api/memory/subjects/${encodedJid}`;
    const method = isNew ? 'POST' : 'PUT';

    try {
        const res = await fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (res.ok) {
            showToast(isNew ? "Created new subject" : "Saved changes");
            refreshGraph();
            closeSidebar();
        } else {
            const err = await res.json();
            showToast("Error saving: " + err.detail);
            setLoading(false);
        }
    } catch (err) {
        showToast("Request failed: " + err.message);
        setLoading(false);
    }
}

async function apiDeleteSubject(jid, callback) {
    setLoading(true);
    try {
        const encodedJid = encodeURIComponent(jid);
        const res = await fetch(`/display/api/memory/subjects/${encodedJid}`, { method: 'DELETE' });
        if (res.ok) {
            showToast("Subject deleted");
            callback();
        } else {
            const err = await res.json();
            showToast("Delete failed: " + err.detail);
        }
    } catch (err) {
        showToast("Delete failed: " + err.message);
    } finally {
        setLoading(false);
    }
}

async function saveRelation(edgeData, kind, callback) {
    const srcNode = nodes.get(edgeData.from);
    const tgtNode = nodes.get(edgeData.to);

    if (!srcNode || !tgtNode) {
        showToast("Error: Node context lost");
        callback(null);
        return;
    }

    const payload = {
        source: srcNode.subject?.name || srcNode.label,
        kind: kind,
        target: tgtNode.subject?.name || tgtNode.label
    };

    setLoading(true);
    try {
        const res = await fetch('/display/api/memory/relations', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (res.ok) {
            showToast(`Link created: ${payload.kind || kind}`);
            callback(edgeData);
            // Wait a moment for backend sync before refreshing
            setTimeout(() => refreshGraph(), 500);
        } else {
            showToast("Failed to save relation");
            callback(null);
        }
    } catch (err) {
        showToast("Relation request failed");
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
        const url = `/display/api/memory/relations?source=${encodeURIComponent(srcNode.name)}&kind=${encodeURIComponent(kind)}&target=${encodeURIComponent(tgtNode.name)}`;
        const res = await fetch(url, {
            method: 'DELETE'
        });
        if (res.ok) {
            showToast("Relation deleted");
            callback();
        } else {
            showToast("Failed to delete relation");
        }
    } catch (err) {
        showToast("Delete relation failed");
    } finally {
        setLoading(false);
    }
}

function createNewSubject() {
    selectedNodeJid = null;
    document.getElementById('edit-jid').value = '';
    document.getElementById('edit-name').value = '';
    document.getElementById('edit-summary').value = '';
    document.getElementById('edit-description').value = '';
    document.getElementById('edit-type').value = 'person';

    document.getElementById('detail-title').innerText = "Create New Subject";
    document.getElementById('sidebar').classList.remove('sidebar-hidden');
    document.getElementById('save-btn').innerText = "Create Subject";

    if (network) network.unselectAll();
}

// --- Helpers ---

function createNodeTooltip(subject) {
    const container = document.createElement("div");
    container.style.padding = "5px";

    const nameEl = document.createElement("strong");
    nameEl.textContent = subject.name;
    nameEl.style.color = TYPE_COLORS[subject.subject_type?.toLowerCase()] || TYPE_COLORS.other;
    container.appendChild(nameEl);

    if (subject.summary) {
        container.appendChild(document.createElement("br"));
        const summaryEl = document.createElement("span");
        summaryEl.textContent = subject.summary;
        summaryEl.style.fontSize = "0.85rem";
        summaryEl.style.color = "#94a3b8";
        container.appendChild(summaryEl);
    }

    return container;
}

function deleteSubject() {
    if (selectedNodeJid && confirm("Are you sure?")) {
        apiDeleteSubject(selectedNodeJid, () => {
            nodes.remove(selectedNodeJid);
            closeSidebar();
            refreshGraph();
        });
    }
}

// --- FAB Logic ---

function toggleFab() {
    const container = document.getElementById('fab-container');
    const mainBtn = document.getElementById('fab-main-btn');
    container.classList.toggle('active');
    mainBtn.classList.toggle('active');
}

function startAddEdgeFlow() {
    toggleFab(); // Close menu
    if (network) {
        network.addEdgeMode();
        showToast("Drag between nodes to link them");
    }
}

// --- Relation Modal ---

function showRelationModal(edgeData, callback) {
    pendingEdgeData = edgeData;
    pendingEdgeCallback = callback;

    // Reset modal
    document.getElementById('rel-kind-select').value = 'relates_to';
    document.getElementById('rel-kind-custom').value = '';
    document.getElementById('custom-rel-container').style.display = 'none';

    document.getElementById('relation-modal').style.display = 'flex';
}

function toggleCustomRel(value) {
    const customContainer = document.getElementById('custom-rel-container');
    customContainer.style.display = (value === 'other') ? 'block' : 'none';
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
            showToast("Relation type required");
            pendingEdgeCallback(null);
        }
    } else if (pendingEdgeCallback) {
        pendingEdgeCallback(null);
    }

    pendingEdgeData = null;
    pendingEdgeCallback = null;
}
