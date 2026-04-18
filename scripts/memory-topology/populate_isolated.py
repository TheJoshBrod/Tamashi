import random
import requests

def create_isolated_topology(user_id="default_user", node_count=100):
    print(f"🪐 Generating {node_count} completely isolated nodes for {user_id}...")
    
    subjects = []
    types = ["person", "concept", "goal", "event", "place", "object", "other"]
    
    for i in range(node_count):
        subjects.append({
            "name": f"Node_Isolated_{i:03d}",
            "summary": f"An isolated node {i}.",
            "description": "Synthetic node with zero edges.",
            "subject_type": random.choice(types)
        })

    print(f"📦 Prepared {len(subjects)} nodes with 0 edges.")
    print("🚀 Ingesting into memory graph via REST API...")
    
    base_url = "http://localhost:8000/display/api/memory"
    for s in subjects:
        requests.post(f"{base_url}/subjects", json=s)

    print(f"✅ Ingested {len(subjects)} new isolated nodes.")
    print("🔄 You can now refresh the graph UI.")

if __name__ == "__main__":
    create_isolated_topology()
