import os
import sys
from uuid import uuid4
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, UploadFile, File, HTTPException, Body
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from typing import List, Optional

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core import config
from core.logger import logger
from generation.rag_service import RagService
from ingestion.ingest_service import KnowledgeBaseService
from ingestion.pdf_parser import parse_pdf_to_md
from memory.history_store import (
    delete_history,
    get_history,
    is_session_pinned,
    list_session_ids,
    toggle_session_pinned,
)
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Legal RAG API", description="FastAPI Backend for Legal QA")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.exception(f"Unhandled exception during request {request.method} {request.url}")
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": "服务器内部发生未知错误，请联系管理员或查看日志。"},
    )

# Global instances
rag_service = RagService()
kb_service = KnowledgeBaseService()

# Global state for upload progress tracking
upload_progress_store = {}

# Models
class ChatRequest(BaseModel):
    session_id: str
    message: str

class SessionResponse(BaseModel):
    session_id: str
    label: str
    pinned: bool

class MessageResponse(BaseModel):
    role: str
    content: str

def get_session_label(session_id: str) -> str:
    history = get_history(session_id)
    first_user_message = ""
    for msg in history.messages:
        if msg.type == "human" and isinstance(msg.content, str):
            first_user_message = msg.content.strip()
            break
    return first_user_message[:15] if first_user_message else "新会话"

@app.post("/api/upload")
def upload_document(file: UploadFile = File(...)):
    filename = file.filename
    try:
        logger.info(f"Receiving file upload: {filename}")
        # Initialize progress
        upload_progress_store[filename] = {"progress": 0, "status": "接收文件中..."}
        
        def update_progress(progress: int, status: str):
            upload_progress_store[filename] = {"progress": progress, "status": status}
            
        # Use sync file reading so we don't need await
        content = file.file.read()

        update_progress(5, "读取文件完成，开始处理...")

        # PDF 文件走 MinerU 解析
        if filename.lower().endswith(".pdf"):
            text = parse_pdf_to_md(content, filename, progress_callback=update_progress)
        else:
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                text = content.decode("gbk", errors="ignore")

        result = kb_service.upload_by_str(text, filename, progress_callback=update_progress)
        logger.info(f"Upload and ingestion successful for: {filename}")
        
        # Cleanup progress after a delay if needed, but for now just set to 100
        update_progress(100, "入库完成")
        return {"status": "success", "message": result}
    except Exception as e:
        logger.exception(f"Error during file upload: {filename}")
        upload_progress_store[filename] = {"progress": -1, "status": f"错误: {str(e)}"}
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/upload/progress/{filename:path}")
def get_upload_progress(filename: str):
    if filename not in upload_progress_store:
        return {"progress": 0, "status": "等待上传..."}
    return upload_progress_store[filename]

@app.get("/api/knowledge-base/files")
def get_kb_files():
    try:
        files = kb_service.get_all_sources()
        return {"status": "success", "files": files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/knowledge-base/files/{filename:path}")
def delete_kb_file(filename: str):
    try:
        deleted_count = kb_service.delete_source(filename)
        if deleted_count == 0:
            raise HTTPException(status_code=404, detail=f"文档 '{filename}' 未找到")
        logger.info(f"Deleted document '{filename}': {deleted_count} chunks removed")
        return {"status": "success", "message": f"已删除 '{filename}'（{deleted_count} 个文档块）"}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error deleting document: {filename}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat")
async def chat(request: ChatRequest):
    logger.info(f"Chat request received - Session: {request.session_id}, Message: {request.message[:50]}...")
    session_config = config.build_session_config(request.session_id)
    
    def generate():
        try:
            res_stream = rag_service.chain.stream({"input": request.message}, session_config)
            for chunk in res_stream:
                if isinstance(chunk, str):
                    yield chunk
                else:
                    yield str(chunk)
            logger.info(f"Chat stream completed for session: {request.session_id}")
        except Exception as e:
            logger.exception(f"Error during chat generation for session: {request.session_id}")
            yield f"\n\nError: {str(e)}"

    return StreamingResponse(generate(), media_type="text/event-stream")

@app.get("/api/sessions", response_model=List[SessionResponse])
def get_sessions():
    sessions = list_session_ids()
    result = []
    for sid in sessions:
        result.append(SessionResponse(
            session_id=sid,
            label=get_session_label(sid),
            pinned=is_session_pinned(sid)
        ))
    return result

@app.post("/api/sessions")
def create_session():
    new_sid = f"chat_{uuid4().hex[:12]}"
    return {"session_id": new_sid}

@app.get("/api/sessions/{session_id}/messages", response_model=List[MessageResponse])
def get_session_messages(session_id: str):
    history = get_history(session_id)
    messages = []
    for msg in history.messages:
        summary_tag = config.memory_summary_tag
        if msg.type == "system" and str(msg.content).startswith(summary_tag):
            continue
        role = "user" if msg.type == "human" else "assistant"
        messages.append(MessageResponse(role=role, content=msg.content))
    
    if not messages:
        messages.append(MessageResponse(role="assistant", content="你好，我是一个法律问答助手，我有什么可以帮助你？"))
    return messages

@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str):
    delete_history(session_id)
    return {"status": "success"}

@app.post("/api/sessions/{session_id}/pin")
def pin_session(session_id: str):
    toggle_session_pinned(session_id)
    return {"status": "success", "pinned": is_session_pinned(session_id)}
