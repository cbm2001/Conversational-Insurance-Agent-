from __future__ import annotations

import uuid
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from openai import APIConnectionError, APIStatusError, OpenAIError

from harness.openai_client import configure_ssl
from harness.orchestrator import Orchestrator
from harness.state import SessionState

APP_DIR = Path(__file__).resolve().parent
load_dotenv(APP_DIR / ".env")
configure_ssl()
STATIC_DIR = APP_DIR / "static"

app = FastAPI(title="Insurance SOP Conversational Agent")
orchestrator = Orchestrator()
sessions: dict[str, SessionState] = {}


class ChatRequest(BaseModel):
    session_id: str = Field(default="")
    message: str = Field(min_length=1)


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    phase: str
    verified: bool
    case_id: str = ""


@app.get("/")
def index() -> FileResponse:
    index_path = STATIC_DIR / "index.html"
    if not index_path.is_file():
        raise HTTPException(status_code=500, detail="static/index.html not found")
    return FileResponse(index_path)


@app.post("/api/chat", response_model=ChatResponse)
def chat(body: ChatRequest) -> ChatResponse:
    session_id = body.session_id.strip() or str(uuid.uuid4())
    if session_id not in sessions:
        sessions[session_id] = SessionState(session_id=session_id)

    state = sessions[session_id]
    try:
        reply = orchestrator.handle_turn(state, body.message.strip())
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except APIConnectionError as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "Could not reach OpenAI (network or SSL). On Windows/Anaconda, run "
                "'pip install certifi' and restart the server. Underlying: "
                f"{exc.__cause__ or exc}"
            ),
        ) from exc
    except APIStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"OpenAI API error ({exc.status_code}): {exc.message}",
        ) from exc
    except OpenAIError as exc:
        raise HTTPException(status_code=502, detail=f"OpenAI error: {exc}") from exc

    return ChatResponse(
        session_id=state.session_id,
        reply=reply,
        phase=state.phase,
        verified=state.verified_party_id is not None,
        case_id=state.active_case_id or "—",
    )


@app.post("/api/session")
def new_session() -> dict[str, str]:
    session_id = str(uuid.uuid4())
    sessions[session_id] = SessionState(session_id=session_id)
    return {"session_id": session_id}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
