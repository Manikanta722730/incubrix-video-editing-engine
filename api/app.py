"""Main FastAPI application entry point.

Integration Standard 1: Runs via docker compose or direct python command.
Integration Standard 2: OpenAPI 3.1 contract matching running service under /api/v1/.
"""

from __future__ import annotations
import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router, make_error_response
from api.logging_config import logger

app = FastAPI(
    title="IncuBrix Prompt-Based Video Editing Engine",
    description="Deterministic, content-anchored prompt video editing engine API.",
    version="1.0.0",
    openapi_url="/api/v1/openapi.json",
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    corr_id = request.headers.get("X-Correlation-Id") or f"corr_{os.urandom(6).hex()}"
    response = await call_next(request)
    response.headers["X-Correlation-Id"] = corr_id
    return response


# Include all API routes
app.include_router(router)


# Root endpoint serves interactive Live Demo UI
@app.get("/", response_class=HTMLResponse)
def serve_index():
    index_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web", "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>IncuBrix Video Editing Engine API Running</h1><p><a href='/api/v1/docs'>API Docs</a></p>")


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled server error: {exc}")
    return make_error_response("INTERNAL_SERVER_ERROR", f"An internal error occurred: {str(exc)}", 500)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    uvicorn.run("api.app:app", host=host, port=port, reload=False)

