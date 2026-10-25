"""FastAPI application entry point."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.db.connection import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Meeting-to-Action Agent",
    description="Turn meeting transcripts into verified, human-approved follow-ups.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)
