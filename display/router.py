from pathlib import Path
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Body
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from display.websocket import manager
from memory import bridge

router = APIRouter(prefix="/display", tags=["display"])
STATIC_DIR = Path(__file__).parent / "static"


@router.get("/")
async def display_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@router.get("/static/{filename}")
async def static_file(filename: str) -> FileResponse:
    return FileResponse(STATIC_DIR / filename)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# --- Memory UI & API ---

@router.get("/memory", response_class=HTMLResponse)
async def memory_ui():
    """Serves the full-screen Vis.js graph UI."""
    memory_html = STATIC_DIR / "memory.html"
    if not memory_html.exists():
        # Temporary fallback if file doesn't exist yet during development
        return "<h1>Memory UI coming soon... please ensure display/static/memory.html exists.</h1>"
    with open(memory_html, "r") as f:
        return f.read()


@router.get("/api/memory/graph")
async def get_memory_graph(user_id: str = "default_user"):
    """Fetch the full graph topology for Vis.js."""
    try:
        return bridge.get_full_graph(user_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class SubjectUpdate(BaseModel):
    name: str
    summary: str
    description: str
    subject_type: str


@router.post("/api/memory/subjects")
async def create_subject(data: SubjectUpdate, user_id: str = "default_user"):
    """Create a new subject."""
    try:
        # bridge.ingest_subjects handles merging/creating
        result = bridge.ingest_subjects(
            user_id=user_id,
            subjects=[{
                "name": data.name,
                "summary": data.summary,
                "description_delta": data.description,
                "subject_type": data.subject_type
            }],
            relations=[]
        )
        return {"status": "success", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/memory/subjects/{jid}")
async def update_subject(jid: str, data: SubjectUpdate, user_id: str = "default_user"):
    """Update a subject in the graph, SQLite, and Vector store."""
    try:
        return bridge.update_subject(
            user_id=user_id,
            jid=jid,
            name=data.name,
            summary=data.summary,
            description=data.description,
            subject_type=data.subject_type
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/memory/subjects/{jid}/consolidate")
async def force_consolidate(jid: str, user_id: str = "default_user"):
    """Manually trigger async consolidation/rewrite for a given subject."""
    import asyncio
    from memory.rewriter import rewrite_subject
    
    try:
        # Resolve JID to Subject Name via SQLite store to save a Jac call
        from memory.store import subject_store
        subjects = subject_store.get_subjects(user_id, limit=1000)
        subject_name = None
        for s in subjects:
            if s.get("jid") == jid:
                subject_name = s.get("name")
                break
                
        if not subject_name:
            raise HTTPException(status_code=404, detail="Subject not found")

        # Launch the rewriter task
        asyncio.create_task(rewrite_subject(user_id, subject_name))
        return {"status": "success", "message": "Consolidation task triggered"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/memory/subjects/{jid}/similar")
async def find_similar_subjects(jid: str, user_id: str = "default_user"):
    """Find semantically similar subjects using the vector store."""
    try:
        from memory.store import subject_store
        from memory.vector import vector_store
        
        subjects = subject_store.get_subjects(user_id, limit=1000)
        subject_data = None
        for s in subjects:
            if s.get("jid") == jid:
                subject_data = s
                break
                
        if not subject_data:
            # Gracefully handle stale or disconnected nodes
            return {"status": "success", "similar_jids": []}
            
        query_text = f"{subject_data['name']}\n{subject_data.get('summary', '')}\n{subject_data.get('description', '')}"
        
        results = vector_store.search_with_payload(user_id, query_text, k=6)
        similar_jids = [r["node_id"] for r in results if str(r["node_id"]) != str(jid)]
        
        return {"status": "success", "similar_jids": similar_jids}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/memory/subjects/{jid}")
async def delete_subject(jid: str, user_id: str = "default_user"):
    """Delete a subject across all layers."""
    try:
        return bridge.delete_subject(user_id, jid)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class RelationCreate(BaseModel):
    source: str
    kind: str
    target: str


@router.post("/api/memory/relations")
async def add_relation(data: RelationCreate, user_id: str = "default_user"):
    """Add a new relation between two subjects."""
    try:
        return bridge.add_relation(user_id, data.source, data.kind, data.target)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/memory/relations")
async def delete_relation(
    source: str, 
    kind: str, 
    target: str, 
    user_id: str = "default_user"
):
    """Delete a relation between two subjects."""
    try:
        return bridge.delete_relation(user_id, source, kind, target)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
