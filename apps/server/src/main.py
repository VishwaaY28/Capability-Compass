import sys
import os
from pathlib import Path


src_path = Path(__file__).parent
sys.path.insert(0, str(src_path))
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes import router
from env import env
from tortoise.contrib.fastapi import register_tortoise
import sqlite3
from pathlib import Path
import logging
from config.azure_clients import initialize_azure_clients

app = FastAPI(
    title="Compass Master API",
    description="API for Compass Master application",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix="/api")


register_tortoise(
    app,
    db_url="sqlite://db.sqlite3",
    modules={"models": ["database.models"]},
    generate_schemas=True,
    add_exception_handlers=True,
)

# Import seed function
from database.seed import run_seed


# Ensure DB schema compatibility on startup (add missing columns when safe)
logger = logging.getLogger(__name__)

def _ensure_process_capability_column():
    """Synchronous helper: check sqlite process table for capability_id column and add it if missing.

    This uses sqlite3 directly because altering an existing sqlite table is simpler
    than attempting to programmatically migrate via Tortoise here. If your DB is
    stored elsewhere or you prefer proper migrations, use a migration tool or
    drop+recreate the DB after backing up.
    """
    # candidate paths where db.sqlite3 may live
    candidates = [
        Path("db.sqlite3"),
        Path(__file__).parent / "db.sqlite3",
        Path(__file__).parent.parent / "db.sqlite3",
    ]

    for db_path in candidates:
        try:
            if not db_path.exists():
                continue
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            cur.execute("PRAGMA table_info(process);")
            rows = cur.fetchall()
            cols = [r[1] for r in rows]
            if "capability_id" not in cols:
                logger.info(f"Adding missing column 'capability_id' to process table in {db_path}")
                cur.execute("ALTER TABLE process ADD COLUMN capability_id INTEGER;")
                conn.commit()
            cur.close()
            conn.close()
            # stop after first existing db handled
            return
        except Exception as e:
            logger.warning(f"Failed to ensure process.capability_id on {db_path}: {e}")
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass


@app.on_event("startup")
def _on_startup_initialize_azure_clients():
    """Initialize all Azure OpenAI clients at server startup"""
    try:
        logger.info("Initializing Azure OpenAI clients...")
        initialize_azure_clients()
        logger.info("✓ Azure OpenAI clients initialized successfully")
    except Exception as e:
        logger.error(f"Startup Azure clients initialization failed: {e}", exc_info=True)
        raise

@app.on_event("startup")
def _on_startup_check_db():
    # run sync DB compatibility check
    try:
        _ensure_process_capability_column()
    except Exception as e:
        logger.warning(f"Startup DB compatibility check failed: {e}")

@app.on_event("startup")
async def _on_startup_seed_db():
    """Run database seeding on startup"""
    try:
        logger.info("Starting database seeding...")
        await run_seed()
    except Exception as e:
        logger.error(f"Startup database seeding failed: {e}", exc_info=True)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host='0.0.0.0',
        port=8005,
        log_level=env["LOG_LEVEL"].lower(),
        reload=True,
    )