import requests

def create_tree_topology(user_id="default_user", depth=3, branching_factor=4):
    print(f"🌳 Generating hierarchical tree (depth={depth}, factor={branching_factor}) for {user_id}...")
    
    subjects = []
    relations = []
    node_counter = 0

    def recursive_build(parent_name, current_depth):
        nonlocal node_counter
        if current_depth > depth: return

        for _ in range(branching_factor):
            node_counter += 1
            child_name = f"Node_Tree_{node_counter:03d}"
            types = ["goal", "concept", "person", "event", "object"]
            s_type = types[current_depth % len(types)]
            
            subjects.append({
                "name": child_name,
                "summary": f"Tree node at depth {current_depth}",
                "description": f"Synthetic hierarchy node {node_counter}.",
                "subject_type": s_type
            })
            relations.append({"source": parent_name, "kind": "is_parent_of", "target": child_name})
            recursive_build(child_name, current_depth + 1)

    root_name = f"Node_Tree_Root"
    subjects.append({
        "name": root_name,
        "summary": "The root of the tree.",
        "description": "Synthetic root node for tree topology.",
        "subject_type": "place"
    })
    
    recursive_build(root_name, 1)

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
    create_tree_topology()
