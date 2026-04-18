import random
import requests

def create_cluster_topology(user_id="default_user", num_clusters=4, nodes_per_cluster=25):
    total_nodes = num_clusters * nodes_per_cluster
    print(f"🏝️ Generating Cluster layout ({num_clusters} islands, {total_nodes} nodes) for {user_id}...")
    
    subjects = []
    relations = []
    types = ["person", "concept", "goal", "event", "place", "object", "other"]
    node_counter = 0

    for cluster_idx in range(num_clusters):
        cluster_nodes = []
        cluster_theme = random.choice(types)
        
        for i in range(nodes_per_cluster):
            node_counter += 1
            node_name = f"Node_Cluster{cluster_idx}_{node_counter:03d}"
            s_type = cluster_theme if random.random() > 0.2 else random.choice(types)
            
            subjects.append({
                "name": node_name,
                "summary": f"Node {i} belonging to Island {cluster_idx}",
                "description": "Synthetic cluster node.",
                "subject_type": s_type
            })
            cluster_nodes.append(node_name)
            
        for i in range(nodes_per_cluster):
            relations.append({
                "source": cluster_nodes[i],
                "kind": "next_to",
                "target": cluster_nodes[(i + 1) % nodes_per_cluster]
            })
            
            if random.random() > 0.5:
                for _ in range(random.randint(1, 2)):
                    random_target = random.choice(cluster_nodes)
                    if random_target != cluster_nodes[i]:
                        relations.append({
                            "source": cluster_nodes[i],
                            "kind": "associated_with",
                            "target": random_target
                        })

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
    create_cluster_topology()
