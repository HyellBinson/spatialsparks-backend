
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.database import init_database, UPLOAD_DIR
from app.api.routes import health, media, copilot, auth
from app.api.v1 import sam


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_database()
    yield


app = FastAPI(
    title="SpatialSparks API",
    description="AI-powered visual inspection and intelligent assistance.",
    version="1.0.0",
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://spatialsparks.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Authentication
app.include_router(
    auth.router,
    prefix="/api/v1/auth",
    tags=["Authentication"],
)

# System health
app.include_router(
    health.router,
    prefix="/api/v1",
    tags=["System"],
)

# Image uploads
app.include_router(
    media.router,
    prefix="/api/v1/uploads",
    tags=["Image Uploads"],
)

# AI Copilot
app.include_router(
    copilot.router,
    prefix="/api/v1/copilot",
    tags=["Copilot"],
)

# SAM 3 image segmentation
app.include_router(sam.router)


# Static uploaded files
app.mount(
    "/uploads",
    StaticFiles(directory=str(UPLOAD_DIR)),
    name="uploads",
)


@app.get("/")
async def root():
    return {
        "application": "SpatialSparks",
        "status": "running",
        "version": "1.0.0",
        "docs": "/docs",
    }
