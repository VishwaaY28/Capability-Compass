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
    root_path="/Capability-Compass"
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
    """Configure neomodel connection to Neo4j.

    neomodel requires the connection string in the form
    ``bolt://<user>:<password>@<host>:<port>``. We construct that from the
    individual ``NEO4J_*`` env vars (with credentials URL-encoded so special
    characters in the password don't break the parser), and also set
    ``DATABASE_NAME`` separately because neomodel does not read the database
    name from the URL path.
    """
    try:
        from urllib.parse import quote, urlsplit
        from neomodel import config as neomodel_config

        neo4j_url = os.getenv("NEO4J_DATABASE_URL1")
        if not neo4j_url:
            uri = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687").strip()
            username = os.getenv("NEO4J_USERNAME", "neo4j")
            password = os.getenv("NEO4J_PASSWORD", "12345678")
            database = os.getenv("NEO4J_DATABASE", "neo4j")

            parsed = urlsplit(uri if "://" in uri else f"bolt://{uri}")
            host_port = parsed.netloc or parsed.path  # fallback if no scheme was given
            if not host_port:
                host_port = "127.0.0.1:7687"

            neo4j_url = (
                f"bolt://{quote(username, safe='')}:{quote(password, safe='')}"
                f"@{host_port}"
            )
            neomodel_config.DATABASE_NAME = database
            logger.info(
                "Constructed Neo4j URL from components: bolt://%s@%s (database=%s)",
                username, host_port, database,
            )

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


@app.on_event("startup")
def _on_startup_load_fibo_ontology():
    """
    Pre-load the FIBO ontology used by the Compass ingestion guardrail and,
    on a best-effort basis, project it into Neo4j as `:OntologyConcept`
    nodes so it is browseable alongside ingested capabilities.

    Failures are logged but never abort startup — ingestion will continue
    without the guardrail and ingestion logs will mark the run accordingly.
    """
    try:
        from utils.ontology import get_ontology_service
        ontology = get_ontology_service()
        meta = ontology.metadata()
        logger.info(
            "FIBO ontology ready: %s (%d concepts, threshold=%.2f, max_processes=%d)",
            meta.get("ontology_label") or meta.get("ontology_iri"),
            meta.get("concept_count", 0),
            meta.get("threshold", 0.0),
            meta.get("max_processes", 1),
        )

        # Best-effort Neo4j sync — only if the graph is reachable.
        try:
            from neo4j_graph.services.query_execution_service import Neo4jQueryService
            svc = Neo4jQueryService()
            try:
                rows = svc.execute_cypher(
                    "MATCH (n:OntologyConcept) RETURN count(n) AS n"
                )
                concept_count = rows[0]["n"] if rows else 0
            finally:
                svc.close()

            if concept_count == 0:
                summary = ontology.sync_to_neo4j(replace_existing=False)
                logger.info(
                    "FIBO ontology synced to Neo4j on startup: %s", summary
                )
            else:
                logger.info(
                    "FIBO ontology already present in Neo4j (%d concepts) — skipping startup sync",
                    concept_count,
                )
        except Exception as e:
            logger.warning(f"FIBO ontology Neo4j sync skipped on startup: {e}")
    except Exception as e:
        logger.error(f"FIBO ontology preload failed: {e}", exc_info=True)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host='0.0.0.0',
        port=8010,
        log_level=env["LOG_LEVEL"].lower(),
        reload=True,
    )