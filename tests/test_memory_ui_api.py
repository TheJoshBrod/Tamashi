import sys
import os
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent))

from memory import bridge
from memory.store import subject_store

def test_memory_api():
    user_id = "test_ui_user"
    
    # 1. Clear existing data for test user
    subject_store.delete_subject(user_id, "Apple")
    subject_store.delete_subject(user_id, "Banana")
    
    # 2. Ingest some subjects
    print("Ingesting subjects...")
    bridge.ingest_subjects(
        user_id=user_id,
        subjects=[
            {"name": "Apple", "description_delta": "A red fruit.", "summary": "Red fruit", "subject_type": "object"},
            {"name": "Banana", "description_delta": "A yellow fruit.", "summary": "Yellow fruit", "subject_type": "object"}
        ],
        relations=[
            {"source": "Apple", "kind": "differs_from", "target": "Banana"}
        ]
    )
    
    # 3. Test get_full_graph
    print("Testing get_full_graph...")
    graph = bridge.get_full_graph(user_id)
    print(f"Nodes: {len(graph['nodes'])}")
    print(f"Edges: {len(graph['edges'])}")
    
    apple_jid = next(n["id"] for n in graph["nodes"] if n["name"] == "Apple")
    print(f"Apple JID: {apple_jid}")
    
    # 4. Test update_subject
    print("Testing update_subject...")
    res = bridge.update_subject(
        user_id=user_id,
        jid=apple_jid,
        name="Red Apple",
        summary="A very red apple",
        description="Updated description",
        subject_type="object"
    )
    print(f"Update Result: {res}")
    
    # 5. Verify update
    graph2 = bridge.get_full_graph(user_id)
    updated_apple = next(n for n in graph2["nodes"] if n["id"] == apple_jid)
    print(f"Updated Name: {updated_apple['name']}")
    
    # 6. Test delete_subject
    print("Testing delete_subject...")
    res = bridge.delete_subject(user_id, apple_jid)
    print(f"Delete Result: {res}")
    
    # 7. Final Verify
    graph3 = bridge.get_full_graph(user_id)
    print(f"Final Node Count: {len(graph3['nodes'])}")

if __name__ == "__main__":
    try:
        test_memory_api()
        print("\nSUCCESS: All API tests passed!")
    except Exception as e:
        print(f"\nFAILURE: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
