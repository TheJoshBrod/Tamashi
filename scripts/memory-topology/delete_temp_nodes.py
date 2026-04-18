import requests

def delete_temp_nodes():
    """
    Finds all subjects with the 'Node_' prefix and deletes them
    by making REST API calls to the running backend Server.
    
    This ensures that the running server's in-memory Jac graph, 
    SQLite store, and Vector store are all synchronized correctly, 
    and the UI will reflect the changes immediately on refresh.
    """
    base_url = "http://localhost:8000/display/api/memory"
    print(f"🧹 Scanning for temporary nodes via API...")
    
    try:
        # Get the full graph from the backend
        res = requests.get(f"{base_url}/graph")
        res.raise_for_status()
        graph_data = res.json()
    except Exception as e:
        print(f"❌ Failed to reach backend API. Is the server running? ({e})")
        return

    nodes = graph_data.get("nodes", [])
    temp_nodes = [n for n in nodes if n["label"].startswith("Node_")]

    if not temp_nodes:
        print("✅ No temporary nodes found in the active graph.")
        return

    print(f"⚠️ Found {len(temp_nodes)} temporary nodes. Deleting via backend API...")
    deleted_count = 0
    failed_count = 0

    for node in temp_nodes:
        node_jid = node["id"]
        node_name = node["label"]
        try:
            del_res = requests.delete(f"{base_url}/subjects/{node_jid}")
            if del_res.status_code == 200:
                deleted_count += 1
            else:
                print(f"❌ Failed to delete {node_name}: {del_res.text}")
                failed_count += 1
        except Exception as e:
            print(f"❌ Error deleting {node_name}: {e}")
            failed_count += 1

    print(f"\n🎉 Cleanup complete! Deleted: {deleted_count}, Failed: {failed_count}")
    print("🔄 You can now refresh the graph UI.")

if __name__ == "__main__":
    delete_temp_nodes()
