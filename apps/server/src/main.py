import sys
import os
from pathlib import Path


src_path = Path(__file__).parent
sys.path.insert(0, str(src_path))
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from env import env
import logging
from config.azure_clients import initialize_azure_clients
from neo4j_graph.routes.subtree_routes import router as neo4j_subtree_router
from neo4j_graph.routes.capability_routes import router as neo4j_capability_router
from neo4j_graph.routes.query_routes import router as neo4j_query_router
from neo4j_graph.routes.neo4j_api_routes import router as neo4j_api_router
from neo4j_graph.routes.upload_routes import router as upload_router
from neo4j_graph.routes.chat_routes import router as chat_router
from neo4j_pmo.routes.pmo_subtree_routes import router as pmo_subtree_router
from neo4j_graph.routes.workspace_routes import router as workspace_router
from database import init_db, close_db

# Configure logging BEFORE creating FastAPI app
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Compass Master API",
    description="API for Compass Master application - Neo4j Backend",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:8500", "http://127.0.0.1:5173", "http://127.0.0.1:8500"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Neo4j API routes
app.include_router(neo4j_api_router, prefix="/api")
app.include_router(neo4j_subtree_router, prefix="/api")
app.include_router(neo4j_capability_router, prefix="/api")
app.include_router(neo4j_query_router, prefix="/api")
app.include_router(upload_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(pmo_subtree_router, prefix="/api")
app.include_router(workspace_router, prefix="/api")


@app.on_event("startup")
async def _on_startup_init_sqlite():
    """Initialize Tortoise ORM SQLite connection"""
    try:
        await init_db()
    except Exception as e:
        logger.error(f"SQLite initialization failed: {e}", exc_info=True)
        raise


@app.on_event("shutdown")
async def _on_shutdown_close_sqlite():
    """Close Tortoise ORM SQLite connections"""
    try:
        await close_db()
    except Exception as e:
        logger.warning(f"SQLite shutdown failed: {e}")


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
def _on_startup_configure_neo4j():
    """Configure neomodel connection to Neo4j"""
    try:
        from neomodel import config as neomodel_config
        # Try NEO4J_DATABASE_URL1 first, fallback to constructing from components
        neo4j_url = os.getenv("NEO4J_DATABASE_URL1")
        if not neo4j_url:
            # Construct from individual components
            uri = os.getenv("NEO4J_URI", "neo4j://127.0.0.1")
            username = os.getenv("NEO4J_USERNAME", "neo4j")
            password = os.getenv("NEO4J_PASSWORD", "12345678")
            database = os.getenv("NEO4J_DATABASE", "neo4j")
            # Convert neo4j:// to bolt:// for neomodel
            if uri.startswith("neo4j://"):
                uri = uri.replace("neo4j://", "bolt://")
            neo4j_url = f"{uri.rstrip('/')}/{database}?auth={username}:{password}"
            logger.info(f"Constructed Neo4j URL from components: {uri}/{database}")
        
        if neo4j_url:
            neomodel_config.DATABASE_URL = neo4j_url
            logger.info("✓ Neo4j neomodel configured successfully")
        else:
            logger.warning("Neo4j connection details not set — Neo4j routes will not function")
    except Exception as e:
        logger.warning(f"Neo4j configuration failed: {e}")


@app.on_event("startup")
def _on_startup_seed_neo4j():
    """
    Startup hook - no longer seeds static data.
    Use CSV upload to populate Verticals, SubVerticals, and Capabilities.
    """
    logger.info("Server started - use CSV upload to populate data")
    # No static seeding - all data comes from CSV


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host='0.0.0.0',
        port=8005,
        log_level=env["LOG_LEVEL"].lower(),
        reload=True,
    )
