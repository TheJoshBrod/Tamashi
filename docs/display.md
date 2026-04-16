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

`localhost:8000/display/memory`

A full-screen, interactive visualization of the user's long-term memory graph. Built on [vis.js Network](https://visjs.github.io/vis-network/docs/network/).

### Node Types

Each Subject type is rendered with a distinct glow color:

| Type | Color |
|------|-------|
| Person | Rose |
| Concept | Cerulean |
| Goal | Jade |
| Event | Amber |
| Place | Violet |
| Object | Coral |
| Other | Steel |

### Interacting with Subjects

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

Alternatively, relations can be drawn directly on the graph using vis.js's built-in drag mode (enabled via the manipulation toolbar).

> Press **Esc** at any time to cancel an in-progress action and close the sidebar.

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

---

## Emotion Dashboard

`localhost:8000/display/`

Displays an animated avatar face whose state is driven by the `EmotionManager` via WebSocket. For details on how emotions map to UI states and how to add new ones, see the [Extension Guide](extending_tamashi.md) and [Implementation Details](implementation.md).

---

[← Back to Documentation Hub](README.md)
