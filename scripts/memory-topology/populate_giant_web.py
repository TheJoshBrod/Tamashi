import random
import requests

def create_giant_web(user_id="default_user", node_count=200, edge_count=400):
    print(f"🕸️ Generating a web of {node_count} nodes and {edge_count} edges for {user_id}...")
    
    subjects = []
    subject_types = ["person", "concept", "goal", "event", "place", "object", "other"]
    
    for i in range(node_count):
        name = f"Node_{i:03d}"
        s_type = random.choice(subject_types)
        subjects.append({
            "name": name,
            "summary": f"A synthetic node representing item {i}.",
            "description": f"Detailed data for node {i}. Created for load testing the giant web UI.",
            "subject_type": s_type
        })
    
    relations = []
    relation_kinds = ["relates_to", "is_part_of", "knows", "located_at", "wants", "contains"]
    
    for _ in range(edge_count):
        src = random.randint(0, node_count - 1)
        tgt = random.randint(0, node_count - 1)
        while src == tgt:
            tgt = random.randint(0, node_count - 1)
            
        relations.append({
            "source": f"Node_{src:03d}",
            "kind": random.choice(relation_kinds),
            "target": f"Node_{tgt:03d}"
        })
        
    print("🚀 Ingesting into memory graph via REST API (this ensures UI syncs)...")
    base_url = "http://localhost:8000/display/api/memory"
    
    for s in subjects:
        requests.post(f"{base_url}/subjects", json=s)
        
    for r in relations:
        requests.post(f"{base_url}/relations", json=r)

    print(f"✅ Ingested {len(subjects)} subjects and {len(relations)} relations.")
    print("🔄 You can now refresh the graph UI.")

if __name__ == "__main__":
    create_giant_web()
