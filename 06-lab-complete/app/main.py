"""
Production AI Agent — Part 6 Final Project.

Kiểm tra:  python check_production_ready.py
"""
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import redis
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import redis_healthy
from utils.mock_llm import ask as llm_ask


class JsonFormatter(logging.Formatter):
    """Mỗi dòng log = 1 JSON object. Field thêm truyền qua extra={"fields": {...}}."""

    def format(self, record):
        entry = {"ts": datetime.now(timezone.utc).isoformat(), "lvl": record.levelname,
                 "event": record.getMessage(), **getattr(record, "fields", {})}
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logger = logging.getLogger("agent")
logger.handlers = [handler]
logger.setLevel(settings.log_level)
logger.propagate = False


def log(event: str, **fields):
    logger.info(event, extra={"fields": fields})


@asynccontextmanager
async def lifespan(app: FastAPI):
    log("startup", environment=settings.environment)
    yield
    # Uvicorn tự xử lý SIGTERM: ngừng nhận request mới, chờ request đang chạy xong rồi mới tới đây
    log("shutdown")


app = FastAPI(title="Production AI Agent", lifespan=lifespan)


@app.middleware("http")
async def access_log(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    log("request", method=request.method, path=request.url.path, status=response.status_code,
        ms=round((time.perf_counter() - start) * 1000, 1))
    return response


@app.exception_handler(redis.RedisError)
async def redis_down(request: Request, exc: redis.RedisError):
    logger.error("redis_error", extra={"fields": {"path": request.url.path, "error": str(exc)}})
    return JSONResponse(status_code=503, content={"detail": "Service temporarily unavailable"})


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)


@app.get("/health")
def health():
    """Liveness: process còn sống là 200, không phụ thuộc Redis."""
    return {"status": "ok"}


@app.get("/ready")
def ready():
    """Readiness: chỉ nhận traffic khi Redis kết nối được."""
    if not redis_healthy():
        return JSONResponse(status_code=503, content={"status": "not ready", "redis": "down"})
    return {"status": "ready"}


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)
    check_budget()
    answer = llm_ask(body.question)
    # shortcut: ước lượng token ≈ số ký tự / 4 vì mock LLM không trả usage; dùng usage thật khi gọi LLM thật
    cost = record_cost(len(body.question) // 4 + 1, len(answer) // 4 + 1)
    return {"question": body.question, "answer": answer, "cost_usd": round(cost, 8)}
