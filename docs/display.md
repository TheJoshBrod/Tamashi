# Display & Dashboard

Tamashi ships a built-in web dashboard served under `/display/`. It has two views: the live emotion dashboard and the memory graph editor.

---

## Routes

| Route | Description |
|-------|-------------|
| `GET /display/` | Emotion dashboard — real-time animated face driven by the EventBus |
| `GET /display/memory` | Memory graph editor — full-screen interactive graph of all Subjects and Relations |

---

## Memory Graph UI

A full-screen, immersive visualization of the user's long-term memory graph. Features specialized controls for managing complex knowledge structures.

### Top Bar & Stats

The top bar displays real-time health metrics of the memory system:
- **Subjects**: Total entity nodes in the graph.
- **Relations**: Total semantic edges connecting them.
- **Physics Control (▶/⏸)**: Toggle graph simulation. Pausing is recommended when editing large graphs.
- **Refresh**: Force-synchronize the UI with the backend (useful after manual Jac edits).

### Navigation & Perspective

- **Zoom (Bottom-left)**: Use the `+` / `-` buttons or your mouse wheel.
- **Pan**: Click and drag the canvas background.
- **Focus**: Click a node to center and zoom in on it while opening details.
- **Aesthetics**: An interactive particle background provides visual depth and feedback.

### Knowledge Navigation (Filters)

The **Filter Panel** (left side) allows you to declutter the graph by toggling visibility of specific data types:
- **Subject Types**: Hide/show entire categories of entities.
- **Relation Kinds**: Hide/show specific edge types (e.g., hide all "works_at" links).

### Subject Categorization (Legend)

The persistent **Legend** (bottom-left) visualizes the color-coding for Subject types:

| Type | Color | Description |
|------|-------|-------------|
| **Person** | Rose | Social entities and individuals |
| **Concept** | Cerulean | Abstract ideas and semantic clusters |
| **Goal** | Jade | Desires, objectives, and intents |
| **Event** | Amber | Temporal occurrences |
| **Place** | Violet | Geographical or logical locations |
| **Object** | Coral | Tangible artifacts |
| **Other** | Steel | General or unclassified nodes |

### Interacting with Knowledge

**Click a node** to open the detail sidebar. From there you can:
- Edit the subject's name, type, summary, and description
- Delete the subject (removes it from the Jac graph, SQLite, and Qdrant)

**Click empty space** to close the sidebar.

### Interacting with Relations

**Click an edge** to open the relation sidebar. From there you can:
- Change the relationship type via dropdown (or enter a custom kind)
- Delete the relation

### Creating Subjects

Press the **+** FAB (bottom-right) → **New Subject** to open a blank creation form in the sidebar. Fill in the name, type, summary, and description, then click **Create Subject**.

### Creating Relations

Press the **+** FAB → **New Relation** to open the relation creation sidebar. Type the **From** and **To** subject names (autocomplete suggestions are drawn from existing subjects), select a relationship type, and click **Establish Relation**.

Alternatively, relations can be drawn directly on the graph:
1. Enable the **Manipulation Toolbar** (if not already visible, though usually hidden in favor of FAB).
2. Use the **Add Edge** tool and drag between nodes.

> Press **Esc** at any time to cancel an in-progress action, close sidebars, or collapse the FAB.

### API Endpoints

The UI is backed by REST endpoints under `/display/api/memory/`:

| Method | Path | Action |
|--------|------|--------|
| `GET` | `/display/api/memory/graph?user_id=` | Fetch full graph (nodes + edges) |
| `POST` | `/display/api/memory/subjects` | Create a new Subject |
| `PUT` | `/display/api/memory/subjects/{jid}` | Update an existing Subject |
| `DELETE` | `/display/api/memory/subjects/{jid}` | Delete a Subject |
| `POST` | `/display/api/memory/relations` | Create a Relation |
| `DELETE` | `/display/api/memory/relations?source=&kind=&target=` | Delete a Relation |

All endpoints accept an optional `user_id` query parameter (default: `"default_user"`).

### Performance Notes
The Memory Graph uses `vis.js` and is highly optimized to handle up to 500 nodes smoothly:
- **Canvas Drop Shadows**: Disabled globally to drastically reduce GPU jitter when zoomed deeply into the graph.
- **Edge Physics**: `dynamic` smoothing is applied, meaning curves are only calculated when the physics engine rests, rendering as inexpensive straight lines when nodes are dragged.
- **Interaction Hiding**: Edges disappear temporarily while dragging a node to maintain high 60fps framerates during heavy interaction.
- **Initial Load**: To prevent rendering freezes when a massive overlapping node cluster spawns at `(0,0)`, the camera intentionally zooms out (`scale: 0.15`) immediately upon refresh.
- **Loading Spinner**: A fallback 2.5s maximum timeout ensures the UI safely drops the loading spinner if the physics engine never fully stabilizes (e.g., when forces are perfectly balanced).

---

## Topology Testing Scripts

There are several helper scripts included in the `scripts/` directory to stress-test layout generation, rendering metrics, and UI interactivity. Each script interacts directly with the running REST API (`http://localhost:8000/display/api/memory`), ensuring real-time graphical updates without a backend restart.

| Script | Purpose | Description |
|--------|---------|-------------|
| `delete_temp_nodes.py` | Graph Cleanup | Purges all nodes prefixed with `Node_` in both the Active API and databases. |
| `populate_giant_web.py`| Load Testing | Generates 200 nodes and 400 random connections. |
| `populate_tree.py`     | Determinism   | Generates a deeply nested, multi-branch hierarchical topography. |
| `populate_clusters.py` | Gravity Testing | Generates completely disconnected islands to test force repulsion without cross-edges. |
| `populate_hub.py`      | Bottlenecks   | Generates 3 massive "star" nodes connected to hundreds of isolated leaf nodes to test gravitational pull. |
| `populate_isolated.py` | Unconnected   | Generates 100 perfectly isolated nodes with 0 edges to test standalone float behavior. |

---

## Emotion Dashboard

`localhost:8000/display/`

Displays an animated avatar face whose state is driven by the `EmotionManager` via WebSocket. For details on how emotions map to UI states and how to add new ones, see the [Extension Guide](extending_tamashi.md) and [Implementation Details](implementation.md).

---

[← Back to Documentation Hub](README.md)
