import random
import requests

def create_hub_topology(user_id="default_user", num_hubs=3, nodes_per_hub=40):
    total_nodes = num_hubs + (num_hubs * nodes_per_hub)
    print(f"⭐ Generating Star/Hub layout ({num_hubs} hubs, {total_nodes} total nodes) for {user_id}...")
    
    subjects = []
    relations = []
    
    hubs = []
    for h in range(num_hubs):
        hub_name = f"Node_Hub_{h}"
        subjects.append({
            "name": hub_name,
            "summary": f"Central Hub {h}",
            "description": "A massive synthetic bottleneck node.",
            "subject_type": "event"
        })
        hubs.append(hub_name)
    
    for i in range(len(hubs) - 1):
        relations.append({"source": hubs[i], "kind": "core_link", "target": hubs[i+1]})

    node_counter = 0
    types = ["person", "concept", "goal", "place", "object", "other"]
    
    for hub in hubs:
        for _ in range(nodes_per_hub):
            node_counter += 1
            leaf_name = f"Node_Leaf_{node_counter:03d}"
            
            subjects.append({
                "name": leaf_name,
                "summary": f"A peripheral leaf node for {hub}.",
                "description": "Synthetic leaf.",
                "subject_type": random.choice(types)
            })
            
            relations.append({"source": leaf_name, "kind": "orbits", "target": hub})

    print(f"📦 Prepared {len(subjects)} nodes and {len(relations)} edges.")
    print("🚀 Ingesting into memory graph via REST API...")
    
    base_url = "http://localhost:8000/display/api/memory"
    for s in subjects:
        requests.post(f"{base_url}/subjects", json=s)
        
    for r in relations:
        requests.post(f"{base_url}/relations", json=r)

    print(f"✅ Ingested {len(subjects)} new nodes.")
    print("🔄 You can now refresh the graph UI.")

if __name__ == "__main__":
    create_hub_topology()
