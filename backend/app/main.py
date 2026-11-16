from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import get_settings
from app.db.session import SessionLocal, create_schema
from app.services.default_fields import seed_default_fields
from app.services.recovery import recover_interrupted_processing


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_schema()
    settings = get_settings()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        seed_default_fields(db)
        recover_interrupted_processing(db)
    yield


settings = get_settings()
app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
