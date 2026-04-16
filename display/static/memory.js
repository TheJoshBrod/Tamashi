let network = null;
let nodes = new vis.DataSet([]);
let edges = new vis.DataSet([]);
let selectedNodeJid = null;

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
});

function initGraph() {
    const container = document.getElementById('graph-container');
    const data = { nodes, edges };
    const options = {
        nodes: {
            shape: 'dot',
            size: 20,
            font: { color: '#f8fafc', size: 14, strokeWidth: 2, strokeColor: '#0f172a' },
            borderWidth: 2,
            shadow: true
        },
        edges: {
            width: 2,
            color: { color: '#475569', highlight: '#38bdf8' },
            arrows: { to: { enabled: true, scaleFactor: 0.5 } },
            font: { size: 12, color: '#94a3b8', align: 'middle' },
            smooth: { type: 'continuous' }
        },
        physics: {
            forceAtlas2Based: {
                gravitationalConstant: -50,
                centralGravity: 0.01,
                springLength: 100,
                springConstant: 0.08
            },
            maxVelocity: 50,
            solver: 'forceAtlas2Based',
            stabilization: { iterations: 150 }
        },
        interaction: {
            hover: true,
            multiselect: false,
            navigationButtons: true
        },
        manipulation: {
            enabled: true,
            addEdge: function (edgeData, callback) {
                const kind = prompt("Enter relation kind (e.g., wants, enjoys, works_at):", "relates_to");
                if (kind) {
                    edgeData.label = kind;
                    saveRelation(edgeData, callback);
                }
            },
            deleteNode: function (data, callback) {
                const jid = data.nodes[0];
                if (confirm("Are you sure you want to delete this subject?")) {
                    apiDeleteSubject(jid, () => callback(data));
                }
            },
            deleteEdge: function (data, callback) {
                const edgeId = data.edges[0];
                const edge = edges.get(edgeId);
                if (confirm("Delete this relation?")) {
                    apiDeleteRelation(edge, () => callback(data));
                }
            }
        }
    };

    network = new vis.Network(container, data, options);

    network.on("selectNode", (params) => {
        showDetails(params.nodes[0]);
    });

    network.on("deselectNode", () => {
        closeSidebar();
    });
}

async function refreshGraph() {
    try {
        const response = await fetch('/display/api/memory/graph');
        const data = await response.json();

        // Update nodes with colors
        const formattedNodes = data.nodes.map(n => ({
            ...n,
            color: TYPE_COLORS[n.subject_type] || TYPE_COLORS.other,
            title: n.summary // Tooltip
        }));

        nodes.clear();
        edges.clear();
        nodes.add(formattedNodes);
        edges.add(data.edges);
    } catch (err) {
        console.error("Failed to refresh graph:", err);
    }
}

function showDetails(jid) {
    const node = nodes.get(jid);
    if (!node) return;

    selectedNodeJid = jid;
    document.getElementById('edit-jid').value = jid;
    document.getElementById('edit-name').value = node.name || '';
    document.getElementById('edit-summary').value = node.summary || '';
    document.getElementById('edit-description').value = node.description || '';
    document.getElementById('edit-type').value = node.subject_type || 'other';

    document.getElementById('detail-title').innerText = "Edit " + node.label;
    document.getElementById('sidebar').classList.remove('sidebar-hidden');
}

function closeSidebar() {
    document.getElementById('sidebar').classList.add('sidebar-hidden');
    selectedNodeJid = null;
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

    const url = isNew ? '/display/api/memory/subjects' : `/display/api/memory/subjects/${jid}`;
    const method = isNew ? 'POST' : 'PUT';

    try {
        const res = await fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (res.ok) {
            refreshGraph();
            closeSidebar();
        } else {
            const err = await res.json();
            alert("Error saving: " + err.detail);
        }
    } catch (err) {
        alert("Request failed: " + err.message);
    }
}

async function apiDeleteSubject(jid, callback) {
    try {
        const res = await fetch(`/display/api/memory/subjects/${jid}`, { method: 'DELETE' });
        if (res.ok) {
            callback();
        } else {
            const err = await res.json();
            alert("Delete failed: " + err.detail);
        }
    } catch (err) {
        alert("Delete failed: " + err.message);
    }
}

async function saveRelation(edgeData, callback) {
    const srcNode = nodes.get(edgeData.from);
    const tgtNode = nodes.get(edgeData.to);

    const payload = {
        source: srcNode.name,
        kind: edgeData.label,
        target: tgtNode.name
    };

    try {
        const res = await fetch('/display/api/memory/relations', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (res.ok) {
            callback(edgeData);
        } else {
            alert("Failed to save relation");
        }
    } catch (err) {
        alert("Relation request failed");
    }
}

async function apiDeleteRelation(edge, callback) {
    const srcNode = nodes.get(edge.from);
    const tgtNode = nodes.get(edge.to);

    try {
        const res = await fetch(`/display/api/memory/relations?source=${srcNode.name}&kind=${edge.kind}&target=${tgtNode.name}`, {
            method: 'DELETE'
        });
        if (res.ok) {
            callback();
        } else {
            alert("Failed to delete relation");
        }
    } catch (err) {
        alert("Delete relation failed");
    }
}

function createNewSubject() {
    selectedNodeJid = null;
    document.getElementById('edit-jid').value = '';
    document.getElementById('edit-name').value = 'New Subject';
    document.getElementById('edit-summary').value = '';
    document.getElementById('edit-description').value = '';
    document.getElementById('edit-type').value = 'other';

    document.getElementById('detail-title').innerText = "Create New Subject";
    document.getElementById('sidebar').classList.remove('sidebar-hidden');
}

function deleteSubject() {
    if (selectedNodeJid && confirm("Are you sure?")) {
        apiDeleteSubject(selectedNodeJid, () => {
            nodes.remove(selectedNodeJid);
            closeSidebar();
        });
    }
}
