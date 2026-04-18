# Topology Testing Scripts

There are several helper scripts included in the `scripts/memory-topology/` directory to stress-test layout generation, rendering metrics, and UI interactivity. Each script interacts directly with the running REST API (`http://localhost:8000/display/api/memory`), ensuring real-time graphical updates without a backend restart.

| Script | Purpose | Description |
|--------|---------|-------------|
| `delete_temp_nodes.py` | Graph Cleanup | Purges all nodes prefixed with `Node_` in both the Active API and databases. |
| `populate_giant_web.py`| Load Testing | Generates 200 nodes and 400 random connections. |
| `populate_tree.py`     | Determinism   | Generates a deeply nested, multi-branch hierarchical topography. |
| `populate_clusters.py` | Gravity Testing | Generates completely disconnected islands to test force repulsion without cross-edges. |
| `populate_hub.py`      | Bottlenecks   | Generates 3 massive "star" nodes connected to hundreds of isolated leaf nodes to test gravitational pull. |
| `populate_isolated.py` | Unconnected   | Generates 100 perfectly isolated nodes with 0 edges to test standalone float behavior. |

---

[← Back to Documentation Hub](../README.md)
