"""
Azure OpenAI LLM Thinking Module
Handles AI reasoning and query processing using Azure OpenAI LLM provider with chain-of-thought capability.
This module provides LLM thinking capabilities for analyzing user queries against vertical data
and returning both the agent's reasoning process and final results.
"""
import logging
import json
import os
import re
from typing import Dict, Any, Optional, List, Tuple, Callable
import uuid
from datetime import datetime
try:
    import pandas as pd
except Exception:
    pd = None

try:
    from thefuzz import process as fuzzy_process
except Exception:
    fuzzy_process = None
try:
    import requests
except Exception:
    requests = None
try:
    from neo4j_graphrag.retrievers import HybridCypherRetriever
except Exception:
    HybridCypherRetriever = None
try:
    from neo4j import GraphDatabase
except Exception:
    GraphDatabase = None
from env import env
from openai import AzureOpenAI
from openai import OpenAI
from config.azure_clients import get_azure_openai_thinking_client, get_azure_config


logger = logging.getLogger(__name__)

try:
    _has_azure = True
except ImportError:
    _has_azure = False
    logger.warning("Azure libraries not installed. Install them to use Azure OpenAI provider.")


class AzureOpenAIWrapper:
    """
    Wrapper for Azure OpenAI client to provide LangChain-compatible interface.
    HybridCypherRetriever expects an LLM with an 'invoke' method that returns
    an object with a .content attribute (like AIMessage from langchain).
    """
    def __init__(self, client: AzureOpenAI, config: Dict[str, Any]):
        self.client = client
        self.config = config
        self.model = config.get("deployment", "gpt-4")
    
    def invoke(self, prompt: str):
        """
        Call the Azure OpenAI API with the given prompt.
        
        Returns an object with a .content attribute to match LangChain's AIMessage interface.
        
        Args:
            prompt: The prompt/input to send to the LLM
            
        Returns:
            Object with .content attribute containing the LLM's text response
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "user", "content": prompt}
                ],
            )
            # Extract the text content
            content = response.choices[0].message.content
            if isinstance(content, str):
                # Return an object with .content attribute (like langchain's AIMessage)
                return AIMessageLike(content)
            else:
                return AIMessageLike(str(content))
        except Exception as e:
            logger.error(f"Error calling Azure OpenAI in wrapper: {e}")
            # Return empty message instead of raising to allow graceful degradation
            return AIMessageLike("")


class AIMessageLike:
    """
    Minimal object that mimics langchain's AIMessage with a .content attribute.
    This is used to make our Azure OpenAI response compatible with HybridCypherRetriever.
    """
    def __init__(self, content: str):
        self.content = content
    
    def __str__(self):
        return self.content
    
    def __repr__(self):
        return f"AIMessageLike(content={self.content[:100]}...)"



class AzureOpenAIThinkingClient:
    """
    Azure OpenAI Client for chain-of-thought reasoning and analysis.
    Provides thinking capability to reason through queries and data analysis using Azure credentials.
    """

    def __init__(self):
        self._client = None
        self._config = None
        self._last_system_prompt = None
        self._last_user_prompt = None
        self._last_vmo_meta: Dict[str, Any] = {}
        # Store VMO metadata per-request to avoid global overwrite and support lookup by id
        self._vmo_meta_store: Dict[str, Dict[str, Any]] = {}
        # Initialize HybridCypherRetriever for knowledge chunks
        self._knowledge_retriever = None
        self._neo4j_driver = None
        # Load elements_fixed.csv as DF_KNOWLEDGE for persona-aware enrichment
        self.df_knowledge = None

        # Initialize HybridCypherRetriever if available
        try:
            if HybridCypherRetriever is not None and GraphDatabase is not None:
                # Will be initialized lazily when needed to avoid connection errors during startup
                logger.info("HybridCypherRetriever and Neo4j GraphDatabase are available and will be initialized on first use")
            else:
                if HybridCypherRetriever is None:
                    logger.warning("neo4j_graphrag.retrievers.HybridCypherRetriever not available; knowledge chunk retrieval will be skipped")
                if GraphDatabase is None:
                    logger.warning("neo4j.GraphDatabase not available; Neo4j driver cannot be created")
        except Exception as e:
            logger.warning(f"Failed to check HybridCypherRetriever availability: {e}")

        try:
            if pd is not None:
                csv_path = os.path.abspath(os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "elements_fixed.csv")))
                if os.path.exists(csv_path):
                    # Try utf-8 first, then fall back to common encodings on decode errors
                    tried_encodings = []
                    df = None
                    for enc in ("latin-1", "cp1252"):
                        try:
                            df = pd.read_csv(csv_path, encoding=enc, low_memory=False)
                            tried_encodings.append(enc)
                            logger.info(f"Loaded DF_KNOWLEDGE from {csv_path} using encoding={enc} (rows={len(df)})")
                            break
                        except UnicodeDecodeError as ude:
                            tried_encodings.append(enc)
                            logger.warning(f"Encoding {enc} failed for {csv_path}: {ude}")
                        except Exception as e:
                            # Some parsers may raise ParserError or others; keep trying
                            tried_encodings.append(enc)
                            logger.warning(f"Reading with encoding {enc} raised: {e}")

                    if df is None:
                        try:
                            # As last resort use replacement to avoid decode errors
                            df = pd.read_csv(csv_path, encoding="utf-8", encoding_errors="replace", low_memory=False)
                            logger.info(f"Loaded DF_KNOWLEDGE from {csv_path} using utf-8 with replacement (rows={len(df)})")
                        except Exception as e:
                            logger.warning(f"Failed to load DF_KNOWLEDGE after trying encodings {tried_encodings}: {e}")
                            df = None

                    if df is not None:
                        # Normalize column names and strip whitespace from key columns
                        df.columns = [c.strip() if isinstance(c, str) else c for c in df.columns]
                        for col in ("Capability Name", "Process", "Data Entity", "Data Element", "Process Description"):
                            if col in df.columns:
                                # ensure strings and strip
                                df[col] = df[col].astype(str).str.strip()
                        self.df_knowledge = df
                    else:
                        logger.warning(f"elements_fixed.csv could not be read at: {csv_path}")
                else:
                    logger.warning(f"elements_fixed.csv not found at expected path: {csv_path}")
            else:
                logger.warning("pandas not available; DF_KNOWLEDGE will be unavailable")
        except Exception as e:
            logger.warning(f"Failed to load DF_KNOWLEDGE: {e}")

        # Build a dynamic official catalog from Neo4j (live DB), fall back to CSV
        self.official_catalog = []
        self._catalog_loaded_from_db = False
        try:
            self._load_catalog_from_db()
        except Exception as e:
            logger.warning(f"Could not load catalog from DB at init: {e}")

        # If DB catalog is empty, fall back to CSV
        if not self.official_catalog and self.df_knowledge is not None:
            try:
                caps = []
                if 'Capability Name' in self.df_knowledge.columns:
                    caps = list(self.df_knowledge['Capability Name'].dropna().unique())
                procs = []
                if 'Process' in self.df_knowledge.columns:
                    procs = list(self.df_knowledge['Process'].dropna().unique())
                self.official_catalog = list(dict.fromkeys(caps + procs))
                logger.info(f"Built official catalog from CSV fallback with {len(self.official_catalog)} items")
            except Exception:
                self.official_catalog = []

    def _load_config(self) -> Dict[str, Any]:
        """Get cached Azure OpenAI configuration (loaded at server startup)"""
        if self._config is None:
            self._config = {
                "api_key": get_azure_config().get("api_key"),
                "endpoint": get_azure_config().get("endpoint"),
                "deployment": get_azure_config().get("deployment"),
                "api_version": get_azure_config().get("api_version"),
            }
        return self._config

    def _load_catalog_from_db(self):
        """
        Load capability and process names directly from Neo4j so the catalog
        always reflects the live graph — not a stale CSV snapshot.
        Falls back silently; caller handles the empty-catalog case.
        """
        try:
            from neo4j_graph.services.query_execution_service import Neo4jQueryService
            svc = Neo4jQueryService()
            try:
                query = """
                MATCH (c:Capability)
                OPTIONAL MATCH (c)-[:REALIZED_BY]->(p:Process)
                RETURN DISTINCT c.name AS cap_name, p.name AS proc_name
                """
                rows = svc.execute_cypher(query)
            finally:
                svc.close()

            caps, procs = [], []
            for row in rows:
                if row.get("cap_name"):
                    caps.append(row["cap_name"])
                if row.get("proc_name"):
                    procs.append(row["proc_name"])

            catalog = list(dict.fromkeys(caps + procs))  # deduplicate, preserve order
            if catalog:
                self.official_catalog = catalog
                self._catalog_loaded_from_db = True
                logger.info(f"[CATALOG] Loaded {len(catalog)} items from Neo4j ({len(caps)} capabilities, {len(procs)} processes)")
            else:
                logger.warning("[CATALOG] Neo4j returned no capability/process names — catalog will be empty until data is imported")
        except Exception as e:
            logger.warning(f"[CATALOG] Failed to load catalog from Neo4j: {e}")

    def refresh_catalog(self):
        """Force-reload the catalog from Neo4j. Call this after CSV/document imports."""
        self._catalog_loaded_from_db = False
        self.official_catalog = []
        self._load_catalog_from_db()
        logger.info(f"[CATALOG] Refreshed — {len(self.official_catalog)} items")

    def _get_client(self) -> AzureOpenAI:
        """Get Azure OpenAI client instance (initialized at server startup)"""
        if self._client is None:
            if not _has_azure:
                raise ImportError(
                    "Azure libraries are not installed. Install them with: pip install azure-identity azure-keyvault-secrets openai"
                )
            self._client = get_azure_openai_thinking_client()
            logger.info(f"Using pre-initialized Azure OpenAI client")

        return self._client

    def get_last_system_prompt(self) -> Optional[str]:
        """Get the last system prompt used"""
        return self._last_system_prompt

    def get_last_user_prompt(self) -> Optional[str]:
        """Get the last user prompt used"""
        return self._last_user_prompt

    def get_last_vmo_meta(self) -> Dict[str, Any]:
        """Return the last VMO metadata (persona, tone, intent, primary_anchors)."""
        return self._last_vmo_meta or {}

    def get_vmo_meta(self, request_id: Optional[str] = None) -> Dict[str, Any]:
        """Get stored VMO metadata by request_id. If no request_id provided, return empty dict.

        This prevents unscoped polling of a global meta object. Frontend should use the
        `request_id` returned in the LLM response to fetch metadata for that specific request.
        """
        # If no request_id is provided, return the last stored VMO meta for convenience
        # (useful for debugging or when the frontend hasn't yet persisted the request_id).
        if not request_id:
            return self._last_vmo_meta or {}
        return self._vmo_meta_store.get(request_id, {})

    def _default_db_fetch(self, cypher: str) -> Any:
        """Execute a Cypher query directly via Neo4jQueryService (no HTTP hop)."""
        try:
            from neo4j_graph.services.query_execution_service import Neo4jQueryService
            svc = Neo4jQueryService()
            result = svc.execute_cypher(cypher)
            svc.close()
            return result
        except Exception as e:
            logger.warning(f"Default DB fetch via Neo4jQueryService failed: {e}")
            return []

    def _get_neo4j_driver(self):
        """Get or create a Neo4j driver instance for HybridCypherRetriever."""
        if self._neo4j_driver is not None:
            return self._neo4j_driver
        
        if GraphDatabase is None:
            logger.warning("Neo4j GraphDatabase not available, cannot create driver")
            return None
        
        try:
            neo4j_uri = os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687").strip()
            neo4j_user = os.getenv("NEO4J_USERNAME", "neo4j").strip()
            neo4j_password = os.getenv("NEO4J_PASSWORD", "12345678").strip()
            
            if not neo4j_uri or not neo4j_user or not neo4j_password:
                logger.debug(
                    "Neo4j connection parameters not fully configured. "
                    "Set NEO4J_URI, NEO4J_USER, and NEO4J_PASSWORD environment variables to enable knowledge chunk retrieval. "
                    "Proceeding without knowledge chunk retrieval."
                )
                return None
            
            # Create and test the driver connection
            logger.info(f"Creating Neo4j driver connection to {neo4j_uri}")
            driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
            
            # Test the connection with a simple query
            try:
                with driver.session() as session:
                    session.run("RETURN 1")
                logger.info("Neo4j driver connection established and authenticated successfully")
                self._neo4j_driver = driver
                return driver
            except Exception as connection_error:
                # Distinguish between different types of errors
                error_msg = str(connection_error)
                if "Unauthorized" in error_msg or "authentication" in error_msg.lower():
                    logger.error(
                        f"Neo4j Authentication Failed: Invalid credentials for user '{neo4j_user}'. "
                        f"Please verify NEO4J_USER and NEO4J_PASSWORD are correct. "
                        f"Error: {connection_error}"
                    )
                elif "Connection refused" in error_msg or "unable to connect" in error_msg.lower():
                    logger.error(
                        f"Neo4j Connection Failed: Cannot reach Neo4j server at {neo4j_uri}. "
                        f"Verify the server is running and NEO4J_URI is correct. "
                        f"Error: {connection_error}"
                    )
                else:
                    logger.error(f"Neo4j Connection Error: {connection_error}")
                
                driver.close()
                return None
            
        except Exception as e:
            logger.warning(f"Failed to create Neo4j driver: {e}")
            return None

    def _ensure_vector_indexes(self, driver):
        """
        Ensure vector and full-text indexes exist for knowledge chunk retrieval.
        Creates indexes if they don't already exist.
        
        Args:
            driver: Neo4j driver instance
        """
        try:
            with driver.session() as session:
                # Check and create vector index for embeddings
                try:
                    logger.info("[KNOWLEDGE RETRIEVAL] Checking for vector index: chunk_embedding_idx")
                    result = session.run("SHOW INDEXES WHERE name = 'chunk_embedding_idx'")
                    indexes = list(result)
                    if not indexes:
                        logger.info("[KNOWLEDGE RETRIEVAL] Vector index not found, attempting to create...")
                        session.run("""
                            CREATE VECTOR INDEX chunk_embedding_idx IF NOT EXISTS
                            FOR (c:Chunk) ON (c.embedding)
                            OPTIONS {
                                indexConfig: {
                                    `vector.dimensions`: 1536,
                                    `vector.similarity_function`: 'cosine'
                                }
                            }
                        """)
                        logger.info("[KNOWLEDGE RETRIEVAL] Vector index created successfully")
                    else:
                        logger.info("[KNOWLEDGE RETRIEVAL] Vector index already exists")
                except Exception as vec_error:
                    logger.warning(f"[KNOWLEDGE RETRIEVAL] Could not create vector index: {vec_error}")
                    # Vector index creation may fail on some Neo4j versions - continue anyway
                
                # Check and create full-text index for text search
                try:
                    logger.info("[KNOWLEDGE RETRIEVAL] Checking for full-text index: chunk_fulltext_idx")
                    result = session.run("SHOW INDEXES WHERE name = 'chunk_fulltext_idx'")
                    indexes = list(result)
                    if not indexes:
                        logger.info("[KNOWLEDGE RETRIEVAL] Full-text index not found, attempting to create...")
                        session.run("""
                            CREATE FULLTEXT INDEX chunk_fulltext_idx IF NOT EXISTS
                            FOR (c:Chunk) ON EACH [c.text]
                        """)
                        logger.info("[KNOWLEDGE RETRIEVAL] Full-text index created successfully")
                    else:
                        logger.info("[KNOWLEDGE RETRIEVAL] Full-text index already exists")
                except Exception as ft_error:
                    logger.warning(f"[KNOWLEDGE RETRIEVAL] Could not create full-text index: {ft_error}")
                    # Full-text index creation may fail - continue anyway
        except Exception as e:
            logger.warning(f"[KNOWLEDGE RETRIEVAL] Error ensuring indexes: {e}")
            raise

    def _retrieve_knowledge_chunks(self, query: str, top_k: int = 5) -> str:
        """
        Retrieve top K knowledge chunks from the knowledge nodes in the graph database
        using HybridCypherRetriever with vector embeddings.
        
        HybridCypherRetriever combines vector similarity search with full-text search
        to retrieve the most relevant knowledge chunks based on embeddings.
        
        Args:
            query: The user's query to retrieve relevant knowledge chunks for
            top_k: Number of top chunks to retrieve (default: 5)
            
        Returns:
            Formatted string containing the retrieved knowledge chunks, or empty string if retrieval fails
        """
        try:
            logger.info(f"[KNOWLEDGE RETRIEVAL] _retrieve_knowledge_chunks START: query={query[:50]}, _knowledge_retriever={self._knowledge_retriever}, HybridCypherRetriever={HybridCypherRetriever}")
            
            if HybridCypherRetriever is None:
                logger.warning("[KNOWLEDGE RETRIEVAL] HybridCypherRetriever not available, skipping knowledge chunk retrieval")
                return ""
            
            # Initialize retriever lazily if not already done
            if self._knowledge_retriever is None:
                logger.info("[KNOWLEDGE RETRIEVAL] Initializing retriever (first call)...")
                try:
                    # Get or create Neo4j driver connection
                    driver = self._get_neo4j_driver()
                    logger.info(f"[KNOWLEDGE RETRIEVAL] Got Neo4j driver: {driver}")
                    if driver is None:
                        logger.warning("[KNOWLEDGE RETRIEVAL] Neo4j driver connection not configured, skipping knowledge retrieval")
                        return ""
                    
                    # Ensure vector indexes exist before initializing retriever
                    try:
                        self._ensure_vector_indexes(driver)
                    except Exception as idx_error:
                        logger.warning(f"[KNOWLEDGE RETRIEVAL] Could not ensure indexes: {idx_error}")
                    
                    # Create embedder for vector search
                    from utils.deepagent_extractor import _get_azure_llm
                    _, llm_embedd = _get_azure_llm()
                    
                    class SimpleEmbedder:
                        def __init__(self, embedding_client):
                            self.client = embedding_client
                        
                        def embed_query(self, text: str) -> List[float]:
                            resp = self.client.embeddings.create(
                                model="text-embedding-ada-002",
                                input=[text]
                            )
                            return resp.data[0].embedding
                    
                    embedder = SimpleEmbedder(llm_embedd)
                    logger.info("[KNOWLEDGE RETRIEVAL] Created embedder for vector search")
                    
                    logger.info("[KNOWLEDGE RETRIEVAL] Initializing HybridCypherRetriever...")
                    # Initialize HybridCypherRetriever with vector index and full-text index
                    # Retrieval query returns the chunk node and similarity score
                    retrieval_query = "RETURN node, score"
                    self._knowledge_retriever = HybridCypherRetriever(
                        driver=driver,
                        vector_index_name="chunk_embedding_idx",
                        fulltext_index_name="chunk_fulltext_idx",
                        retrieval_query=retrieval_query,
                        embedder=embedder,
                    )
                    logger.info(f"[KNOWLEDGE RETRIEVAL] HybridCypherRetriever initialized successfully: {self._knowledge_retriever}")
                except Exception as init_error:
                    logger.error(f"[KNOWLEDGE RETRIEVAL] Failed to initialize HybridCypherRetriever: {init_error}", exc_info=True)
                    import traceback
                    logger.error(f"[KNOWLEDGE RETRIEVAL] Initialization error details:\n{traceback.format_exc()}")
                    return ""
            
            # If retriever is still None at this point (initialization skipped or failed), skip retrieval
            if self._knowledge_retriever is None:
                logger.warning("[KNOWLEDGE RETRIEVAL] Retriever is None, skipping knowledge retrieval")
                return ""
            
            logger.info(f"[KNOWLEDGE RETRIEVAL] Using initialized retriever: {self._knowledge_retriever}")
            
            # Retrieve chunks using the query with vector similarity
            logger.info(f"[KNOWLEDGE RETRIEVAL] Retrieving knowledge chunks for query: {query[:50]}...")
            try:
                logger.info(f"[KNOWLEDGE RETRIEVAL] About to call get_search_results on retriever: {self._knowledge_retriever}")
                logger.info(f"[KNOWLEDGE RETRIEVAL] Calling get_search_results with query: {query}")
                # HybridCypherRetriever uses get_search_results() method for vector + full-text hybrid search
                result = self._knowledge_retriever.get_search_results(query_text=query, top_k=top_k)
                logger.info(f"[KNOWLEDGE RETRIEVAL] get_search_results returned successfully")
                # Log raw result for diagnostics
                try:
                    raw_repr = repr(result)
                except Exception:
                    raw_repr = str(type(result))
                logger.info(f"[KNOWLEDGE RETRIEVAL] Raw retriever result type={type(result)} repr={raw_repr[:1000]}")

                # If result is a string that contains JSON, attempt to parse it
                if isinstance(result, str):
                    stripped = result.strip()
                    if (stripped.startswith('{') or stripped.startswith('[')):
                        try:
                            result = json.loads(stripped)
                        except Exception:
                            pass
                    else:
                        if stripped:
                            logger.info(f"[KNOWLEDGE RETRIEVAL] Retrieved string result (length={len(stripped)} chars)")
                            return stripped
                        else:
                            logger.info("[KNOWLEDGE RETRIEVAL] Retrieved empty string result")
                            return ""

                # If result is now a list of items
                if isinstance(result, list):
                    logger.info(f"[KNOWLEDGE RETRIEVAL] Result is a list with {len(result)} items")
                    formatted_chunks = []
                    for idx, chunk in enumerate(result, 1):
                        chunk_text = None
                        chunk_score = None
                        try:
                            if isinstance(chunk, dict):
                                node = chunk.get("node", {})
                                chunk_score = chunk.get("score", 0)
                                if isinstance(node, dict):
                                    chunk_text = node.get("text") or node.get("content")
                                else:
                                    chunk_text = getattr(node, "text", None) or getattr(node, "content", None)
                            else:
                                chunk_text = getattr(chunk, "text", None) or getattr(chunk, "content", None)
                        except Exception as chunk_error:
                            logger.warning(f"[KNOWLEDGE RETRIEVAL] Error extracting chunk {idx}: {chunk_error}")

                        if chunk_text and chunk_text.strip():
                            score_str = f" (score: {chunk_score:.4f})" if chunk_score else ""
                            formatted_chunks.append(f"[Chunk {idx}{score_str}]\n{chunk_text}")

                    if formatted_chunks:
                        knowledge_context = "\n---\n".join(formatted_chunks)
                        logger.info(f"[KNOWLEDGE RETRIEVAL] Successfully retrieved {len(formatted_chunks)} knowledge chunks")
                        return knowledge_context
                    else:
                        logger.info("[KNOWLEDGE RETRIEVAL] No chunks had valid text content")
                        return ""

                # If result is a dict-like structure, pretty-print and return
                if isinstance(result, dict):
                    try:
                        result_str = json.dumps(result, default=str)
                    except Exception:
                        result_str = str(result)
                    if result_str and result_str.strip():
                        logger.info(f"[KNOWLEDGE RETRIEVAL] Retrieved dict-like result (length={len(result_str)} chars)")
                        return result_str

                # Fallback: convert to string
                result_str = str(result)
                if result_str and result_str.strip():
                    logger.info(f"[KNOWLEDGE RETRIEVAL] Successfully retrieved knowledge (converted to string, length: {len(result_str)} chars)")
                    return result_str

                logger.info("[KNOWLEDGE RETRIEVAL] No knowledge chunks retrieved")
                return ""
                
            except AttributeError as attr_error:
                logger.warning(f"[KNOWLEDGE RETRIEVAL] AttributeError during retrieval: {attr_error}", exc_info=True)
                return ""
            except Exception as retrieval_error:
                logger.warning(f"[KNOWLEDGE RETRIEVAL] Error retrieving knowledge chunks: {retrieval_error}", exc_info=True)
                import traceback
                logger.debug(f"[KNOWLEDGE RETRIEVAL] Traceback: {traceback.format_exc()}")
                return ""
            
        except Exception as e:
            logger.warning(f"[KNOWLEDGE RETRIEVAL] Outer exception in knowledge retrieval: {e}", exc_info=True)
            return ""

    # --- Entity resolution and NLU helpers that leverage DF_KNOWLEDGE ---
    def _resolve_entity(self, extracted_name: str, threshold: int = 85) -> Optional[str]:
        """Resolve an extracted name to the official catalog using fuzzy matching."""
        try:
            catalog = self.official_catalog or OFFICIAL_CATALOG
            if not catalog or fuzzy_process is None:
                return None
            best = fuzzy_process.extractOne(extracted_name, catalog)
            if best and best[1] >= threshold:
                return best[0]
        except Exception as e:
            logger.warning(f"Error resolving entity '{extracted_name}': {e}")
        return None

    def think_and_analyze(
        self,
        query: str,
        vertical: str,
        vertical_data: Dict[str, Any],
        db_fetch_function: Optional[Callable[[str], Any]] = None,
        user_profile: Optional[Dict[str, str]] = None,
    ) -> Tuple[str, str, Optional[str]]:
        """
        Use Azure OpenAI LLM to think through a query and analyze vertical data.

        Args:
            query: User's query/question
            vertical: Selected vertical/domain
            vertical_data: Data structure containing capabilities, processes, etc.

        Returns:
            Tuple of (thinking_process, final_result)
        """
        try:
            client = self._get_client()
            config = self._load_config()
            plan = self._create_query_plan(query, user_profile, vertical)  # Pass vertical to plan

            # 2) Generate cypher using plan (VMO-driven flow only)
            cypher = self._generate_enterprise_query(plan)
            logger.info(f"Generated Cypher: {cypher}")
            
            # Log query firing
            logger.info(f"[PROCESS START] Firing database query for vertical: {vertical}")
            db_records = []
            if db_fetch_function and callable(db_fetch_function):
                try:
                    logger.info("[DB FETCH] Using provided db_fetch_function to execute query")
                    db_records = db_fetch_function(cypher)
                    logger.info(f"[DB FETCH RESULT] Received {db_records if isinstance(db_records, list) else 'unknown'} records from db_fetch_function")
                except Exception as e:
                    logger.warning(f"DB fetch function raised an error: {e}")
                    db_records = []
            else:
                # Prefer the default endpoint fetcher as the primary source of truth
                if callable(getattr(self, "_default_db_fetch", None)):
                    try:
                        logger.info("[DB FETCH] Using default endpoint fetcher to execute query")
                        db_records = self._default_db_fetch(cypher)
                        logger.info(f"[DB FETCH RESULT] Received {db_records if isinstance(db_records, (list, dict)) else 'unknown'} records from default endpoint")
                        logger.debug("Default DB fetch returned %s items", (len(db_records) if isinstance(db_records, (list, dict)) else 1))
                    except Exception as e:
                        logger.warning(f"Default DB fetch failed: {e}")
                        db_records = []

                # If default fetch returned nothing meaningful, fall back to provided vertical_data
                if (not db_records) and isinstance(vertical_data, (list, dict)) and vertical_data:
                    db_records = vertical_data
                    logger.info("[DB FETCH] Falling back to provided vertical_data (caller pre-fetched result)")
                    logger.debug("Falling back to provided vertical_data as db_records (caller pre-fetched result)")

                # Ensure we have something (db_records may still be empty)
            
            # Add 2-second delay to allow database to settle and complete any pending operations
            logger.info("[DELAY COMPLETE] Proceeding with result processing")

            # 4) Normalize and serialize only the retrieved graph context (small, persona-aware) and build VMO prompt
            try:
                normalized = self._normalize_db_response(db_records)
                logger.info(f"normalized data inside try block 325: {normalized}")
            except Exception as e:
                logger.warning(f"Error normalizing DB response: {e}")
                normalized = db_records
                logger.info(f"normalized data inside except block 329: {normalized}")


            serialized = self._serialize_db_records(normalized, plan)
            if len(serialized)>500:
                retrieved_context=serialized
            else:
                retrieved_context=normalized

            # retrieved_context = normalized
            logger.info(f"serialized data : {retrieved_context}")
            logger.info(f"Serialized retrieved_context length={len(retrieved_context)} snippet={retrieved_context}")
            if not retrieved_context:
                logger.warning("No meaningful retrieved graph context was serialized — LLM will receive an empty context block.")
            
            # 4a) Retrieve knowledge chunks from the knowledge nodes in the graph database
            logger.info("[KNOWLEDGE INTEGRATION] Retrieving knowledge chunks to enrich context...")
            knowledge_chunks = self._retrieve_knowledge_chunks(query, top_k=5)
            
            # Append knowledge chunks to the retrieved context if available
            if knowledge_chunks:
                retrieved_context = f"{retrieved_context}\n\n### SUPPLEMENTARY KNOWLEDGE FROM KNOWLEDGE BASE:\n{knowledge_chunks}"
                logger.info(f"[KNOWLEDGE INTEGRATION] Successfully appended knowledge chunks to context (new length: {len(retrieved_context)} chars)")
            else:
                logger.info("[KNOWLEDGE INTEGRATION] No additional knowledge chunks were retrieved")
            
            vmo_prompt = self._create_vmo_prompt(query, plan, retrieved_context, vertical)
            self._last_system_prompt = vmo_prompt
            
            # Log context being sent to LLM
            logger.info(f"[CONTEXT SERIALIZATION] Successfully serialized retrieved context (length={len(retrieved_context)} chars)")
            logger.info(f"[CONTEXT SUMMARY] Preparing VMO prompt with persona={plan.get('persona_tone')}, intent={plan.get('intent')}, anchors={plan.get('primary_anchors')}, context={plan.get('retrieved_context')}")
            logger.info(f"[CONTEXT TO LLM] System prompt prepared and ready to send to LLM (prompt length={len(vmo_prompt)} chars)")

            # Create and store VMO metadata for this request so frontend can fetch it by id
            try:
                request_id = str(uuid.uuid4())
                persona_tone = plan.get("persona_tone") if isinstance(plan, dict) else None
                intent_val = plan.get("intent") if isinstance(plan, dict) else None
                primary_anchors = plan.get("primary_anchors") if isinstance(plan, dict) else []
                meta = {
                    "request_id": request_id,
                    "persona": persona_tone,
                    "tone": persona_tone,
                    "intent": intent_val,
                    "primary_anchors": primary_anchors,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "system_prompt": vmo_prompt[:10000],
                }
                # store both as last and in store
                self._last_vmo_meta = meta
                self._vmo_meta_store[request_id] = meta
            except Exception:
                request_id = None

            # 5) Call Azure OpenAI with VMO prompt and user prompt message
            deployment = config["deployment"]
            logger.info(f"Calling Azure OpenAI API with VMO prompt for query: {query[:50]}... (Deployment: {deployment})")
            
            # Create user prompt with context
            user_prompt = self._create_user_message(query, plan, retrieved_context, vertical)
            self._last_user_prompt = user_prompt

            try:
                response = client.chat.completions.create(
                    model=deployment,
                    messages=[
                        {"role": "system", "content": vmo_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                )
            except Exception as api_error:
                logger.error(f"Azure API Error - Deployment: {deployment}, Error: {str(api_error)}")
                raise

            # Extract thinking and result from response
            response_text = response.choices[0].message.content
            logger.info("[LLM RESPONSE RECEIVED] Successfully received response from Azure OpenAI LLM")
            logger.info(f"[LLM RESPONSE DETAILS] Response length={len(response_text)} chars, model={deployment}")
            
            # Extract reasoning_content if available (Kimi model native thinking)
            reasoning_content = getattr(response.choices[0].message, 'reasoning_content', None)
            thinking, result = self._parse_response(response_text, reasoning_content)
            logger.info(f"[LLM RESPONSE PARSED] Thinking section length={len(thinking)} chars, Result section length={len(result)} chars")
            logger.info(f"Successfully processed query with VMO prompt: {query[:50]}...")
            return thinking, result, request_id

        except Exception as e:
            logger.error(f"Error in think_and_analyze: {e}")
            raise

    def stream_think_and_analyze(
        self,
        query: str,
        vertical: str,
        vertical_data: Dict[str, Any],
    ):
        """
        Stream the thinking process and analysis result progressively.
        This allows the frontend to see thinking as it happens.

        Args:
            query: User's query/question
            vertical: Selected vertical/domain
            vertical_data: Data structure containing capabilities, processes, etc.

        Yields:
            Tuple of (chunk_type, content) where chunk_type is 'thinking' or 'result'
        """
        try:
            client = self._get_client()
            config = self._load_config()

            # VMO flow: create QueryPlan-like dict, generate cypher and fetch via default endpoint if possible
            plan = self._create_query_plan(query, None, vertical)  # Pass vertical to plan

            cypher = self._generate_enterprise_query(plan)
            # Prefer the default endpoint fetcher as primary. If it returns nothing,
            # fall back to provided vertical_data (caller pre-fetched result).

            db_records = []
            if callable(getattr(self, "_default_db_fetch", None)):
                try:
                    db_records = self._default_db_fetch(cypher)
                except Exception as e:
                    db_records = []

            if (not db_records) and isinstance(vertical_data, (list, dict)) and vertical_data:
                db_records = vertical_data
            try:
                normalized = self._normalize_db_response(db_records)
            except Exception as e:
                normalized = db_records

            retrieved_context = self._serialize_db_records(normalized, plan)
            
            # Retrieve knowledge chunks from the knowledge nodes in the graph database
            logger.info("[KNOWLEDGE INTEGRATION] Retrieving knowledge chunks to enrich context...")
            knowledge_chunks = self._retrieve_knowledge_chunks(query, top_k=5)
            
            # Append knowledge chunks to the retrieved context if available
            if knowledge_chunks:
                retrieved_context = f"{retrieved_context}\n\n### SUPPLEMENTARY KNOWLEDGE FROM KNOWLEDGE BASE:\n{knowledge_chunks}"
                logger.info(f"[KNOWLEDGE INTEGRATION] Successfully appended knowledge chunks to context (new length: {len(retrieved_context)} chars)")
            else:
                logger.info("[KNOWLEDGE INTEGRATION] No additional knowledge chunks were retrieved")
            
            system_prompt = self._create_vmo_prompt(query, plan, retrieved_context, vertical)
            user_prompt = self._create_user_message(query, plan, retrieved_context, vertical)

            # Store the system and user prompts for logging
            self._last_system_prompt = system_prompt
            self._last_user_prompt = user_prompt
            if not retrieved_context or retrieved_context.strip().lower().startswith("no retrieved graph context"):
                logger.warning("No meaningful retrieved graph context was serialized for stream — LLM will receive an empty context block.")
            try:
                request_id = str(uuid.uuid4())
                persona_tone = plan.get("persona_tone") if isinstance(plan, dict) else None
                intent_val = plan.get("intent") if isinstance(plan, dict) else None
                primary_anchors = plan.get("primary_anchors") if isinstance(plan, dict) else []
                meta = {
                    "request_id": request_id,
                    "persona": persona_tone,
                    "tone": persona_tone,
                    "intent": intent_val,
                    "primary_anchors": primary_anchors,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "system_prompt": system_prompt[:10000],
                    "user_prompt": user_prompt[:10000],
                }
                self._last_vmo_meta = meta
                self._vmo_meta_store[request_id] = meta
            except Exception:
                self._last_vmo_meta = {}

            deployment = config["deployment"]
            logger.info(f"Starting stream for query: {query[:50]}... (Deployment: {deployment})")

            try:
                stream = client.chat.completions.create(
                    model=deployment,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt },
                    ],
                    stream=True,
                )
            except Exception as api_error:
                logger.error(f"Azure API Error - Deployment: {deployment}, Error: {str(api_error)}")
                raise

            buffer = ""
            in_thinking = False
            thinking_started = False
            chunk_count = 0
            reasoning_chunks = []  # Collect reasoning chunks for Kimi native reasoning
            has_reasoning_field = False  # Track if the response has native reasoning

            for chunk in stream:
                # Check for native reasoning_content in the response (Kimi model)
                if chunk.choices[0].delta and hasattr(chunk.choices[0].delta, 'reasoning_content'):
                    reasoning_text = chunk.choices[0].delta.reasoning_content
                    if reasoning_text:
                        has_reasoning_field = True
                        reasoning_chunks.append(reasoning_text)
                
                # Handle regular content
                if chunk.choices[0].delta.content:
                    text = chunk.choices[0].delta.content
                    buffer += text

                    # Only parse for thinking tags if no native reasoning field exists
                    if not has_reasoning_field:
                        # Check for thinking section markers
                        if "<thinking>" in buffer:
                            in_thinking = True
                            thinking_started = True
                            before, after = buffer.split("<thinking>", 1)
                            
                            # Yield any text before thinking tags
                            if before.strip():
                                yield ("text", before)
                            
                            buffer = after

                        if "</thinking>" in buffer and in_thinking:
                            thinking_text, after = buffer.split("</thinking>", 1)
                            
                            # Yield the complete thinking section
                            if thinking_text.strip():
                                yield ("thinking", thinking_text.strip())
                            
                            in_thinking = False
                            buffer = after

                        # Yield buffered result content periodically (when not in thinking)
                        if not in_thinking and len(buffer) > 100:
                            yield ("result", buffer)
                            buffer = ""
                    else:
                        # If we have native reasoning, stream result content
                        if len(buffer) > 100:
                            yield ("result", buffer)
                            buffer = ""

            # Yield any accumulated reasoning from native field
            if reasoning_chunks:
                reasoning_content = "".join(reasoning_chunks).strip()
                if reasoning_content:
                    logger.info(f"Yielding native reasoning from Kimi model (length={len(reasoning_content)} chars)")
                    yield ("thinking", reasoning_content)

            # Yield remaining content
            if buffer:
                if in_thinking and not has_reasoning_field:
                    # If we're still in thinking mode, yield as thinking
                    yield ("thinking", buffer.strip())
                else:
                    # Otherwise yield as result
                    if buffer.strip():
                        yield ("result", buffer.strip())
            
            logger.info(f"Stream completed for query: {query[:50]}... (native_reasoning={has_reasoning_field})")

        except Exception as e:
            logger.error(f"Error in stream_think_and_analyze: {e}")
            raise

    pass

    def _create_user_message(self, user_query: str, plan: Dict[str, Any], retrieved_graph_context: str, vertical: str) -> str:
        persona_tone = plan.get("persona_tone", "portfolio manager")
        display_anchor = ", ".join(plan.get("primary_anchors", []))
        intent = plan.get("intent", "Informational")
        """Create the user message with query and context"""
        user_prompt =  f"""
Please analyze this user query: {user_query} based on the provided enterprise data 
### INPUT CONTEXT
- TARGET PERSONA: {persona_tone}
- PRIMARY ANCHOR: {display_anchor}
- INTENT: {intent}
### RETRIEVED ENTERPRISE GRAPH DATA:
{retrieved_graph_context}
### GRAPH RELATIONSHIPS (Lineage): 
Please synthesize the procedure based on the graph lineage above.
Provide both your thinking process and final analysis."""
        return user_prompt

    # --- Local NLU and serialization helpers ---
    def _extract_intent(self, user_query: str) -> str:
        q = user_query.lower()
        for intent, keys in INTENT_KEYWORDS.items():
            if any(k in q for k in keys):
                return intent.capitalize()
        return "Informational"

    def _infer_persona(self, user_query: str) -> Tuple[str, int]:
        """
        Infer persona and depth from the user query when user_profile.role is absent.
        Returns (persona, depth_scope) where persona is one of Executive|portfolio manager|Investment Analyst
        and depth_scope is 1,2,3 respectively.
        Uses explicit persona keywords, DF_KNOWLEDGE presence, and intent heuristics.
        """
        q = (user_query or "").lower()

        exec_keys = [
            "executive", "ceo", "cfo", "director", "vp", "vision",
            "objective", "board", "stakeholder", "value", "kpi", "roi", "business value",
            "investment committee", "fund strategy", "performance objectives",
            "portfolio construction", "compliance", "regulatory", "risk appetite",
            "governance", "mandate", "disclosure"
        ]

        mgr_keys = [
            "portfolio manager", "supervisor", "team lead", "owner", "process", "workflow", "steps",
            "how", "implement", "procedure", "operational", "policy", "deployment",
            "performance targets", "tracking error", "information ratio", "investor profile",
            "distribution policy", "fund accounting", "portfolio management",
            "risk management", "compliance department", "client reporting"
        ]

        spec_keys = [
            "analyst", "investment analyst", "engineer", "developer", "architect",
            "api", "data entity", "data element", "attribute", "schema", "lineage",
            "id", "technical", "aladdin", "blackrock", "performance measurement team",
            "portfolio analytics", "fund valuation", "data element description",
            "prospectus", "objective statement", "strategy", "goal"
        ]

        # 1) explicit role / seniority words
        for k in exec_keys:
            if k in q:
                return "Executive", 2
        for k in spec_keys:
            if k in q:
                return "Investment Analyst", 4
        for k in mgr_keys:
            if k in q:
                return "portfolio manager", 3

        # 2) check DF_KNOWLEDGE for technical artifact mentions — bias to Investment Analyst
        try:
            if self.df_knowledge is not None:
                cols = [c for c in ("Data Element", "Data Entity", "Capability Name", "Process") if c in self.df_knowledge.columns]
                for col in cols:
                    names = [str(x).lower() for x in self.df_knowledge[col].dropna().unique()]
                    for name in names:
                        if name and name in q:
                            if "data" in col.lower() or "element" in col.lower():
                                return "Investment Analyst", 3
                            if "capability" in col.lower():
                                return "portfolio manager", 2
                            return "portfolio manager", 2
        except Exception:
            pass

        # 3) fallback to intent heuristics
        intent = self._extract_intent(user_query).lower()
        logger.info("Using intents to find persona")
        if intent == "technical":
            return "Investment Analyst", 4
        if intent == "strategic":
            return "Executive", 2
        if intent == "operational":
            return "portfolio manager", 3
        
        # 4) Ultimate fallback: return portfolio manager as default
        logger.info("No persona keywords found, defaulting to portfolio manager")
        return "portfolio manager", 2

    def _extract_all_anchors(self, user_query: str) -> List[str]:
        # Lazily refresh catalog from DB if it hasn't been loaded yet or is empty
        if not self.official_catalog or not self._catalog_loaded_from_db:
            try:
                self._load_catalog_from_db()
            except Exception:
                pass

        found: List[str] = []
        temp = user_query
        catalog = self.official_catalog or OFFICIAL_CATALOG
        for term in sorted(catalog, key=len, reverse=True):
            try:
                pattern = rf"\b{re.escape(term)}\b"
                if re.search(pattern, temp, re.IGNORECASE):
                    found.append(term)
                    # remove matched portion so we can find other distinct anchors
                    temp = re.sub(pattern, "", temp, flags=re.IGNORECASE)
            except re.error:
                continue

        # 2) If no direct catalog matches, attempt fuzzy resolution for capitalized phrases
        if not found:
            matches = re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b", user_query)
            if matches:
                logger.info("No direct catalog matches — attempting fuzzy resolution for capitalized phrases")
                for candidate in matches:
                    try:
                        resolved = None
                        if fuzzy_process and catalog:
                            best = fuzzy_process.extractOne(candidate, catalog)
                            if best and best[1] >= 80:
                                resolved = best[0]
                        if resolved:
                            found.append(resolved)
                    except Exception:
                        continue

        # 3) As an additional fallback, scan n-grams (4..1) of the query tokens and fuzzy match them to the catalog
        if not found and fuzzy_process and catalog:
            words = re.findall(r"\w+", user_query)
            seen = set()
            for n in range(4, 0, -1):
                for i in range(0, max(0, len(words) - n + 1)):
                    ngram = " ".join(words[i : i + n])
                    try:
                        best = fuzzy_process.extractOne(ngram, catalog)
                        if best and best[1] >= 90 and best[0] not in seen:
                            found.append(best[0])
                            seen.add(best[0])
                    except Exception:
                        continue

        # 4) Canonicalize and preserve order, deduplicate while preserving first occurrence
        resolved_list: List[str] = []
        for item in found:
            if not item:
                continue
            # prefer a canonical resolution but fall back to the raw item
            canonical = self._resolve_entity(item) or item
            if canonical not in resolved_list:
                resolved_list.append(canonical)

        return resolved_list

    def _create_query_plan(self, user_query: str, user_profile: Optional[Dict[str, str]] = None, vertical: Optional[str] = None) -> Optional[Dict[str, Any]]:
        anchors = self._extract_all_anchors(user_query)
        # allow empty anchors list — proceed with an empty plan rather than falling back to legacy behavior
        if not anchors:
            anchors = []

        # Prefer explicit role from user_profile when provided; otherwise infer from the query text
        role = (user_profile.get("role", "") if user_profile else "").strip().lower()
        if role:
            if "Investment Analyst" in role or "architect" in role:
                persona = "Investment Analyst"
                depth = 4
            elif "executive" in role:
                persona = "Executive"
                depth = 2
            else:
                persona = "portfolio manager"
                depth = 3
        else:
            # Infer persona and depth from the query using DF_KNOWLEDGE and heuristics
            persona, depth = self._infer_persona(user_query)

        intent = self._extract_intent(user_query)
        is_comp = len(anchors) > 1

        return {
            "primary_anchors": anchors,
            "intent": intent,
            "persona_tone": persona,
            "depth_scope": depth,
            "is_comparison": is_comp,
            "vertical": vertical,  # Include vertical filter in plan
        }

    def _generate_enterprise_query(self, plan: Dict[str, Any]) -> str:
        queries: List[str] = []
        depth = plan.get("depth_scope") or 2
        vertical = plan.get("vertical")  # Get vertical filter from plan
        
        # Get primary anchors
        primary_anchors = plan.get("primary_anchors", [])
        
        # If no anchors found, create a general query to fetch vertical data
        if not primary_anchors:
            logger.warning("[QUERY GENERATION] No primary anchors found - generating general vertical query")
            if vertical:
                safe_vertical = vertical.replace("'", "''")
                # Query to get all capabilities and their processes for the vertical
                general_query = f"""
                MATCH (v:Vertical {{name: '{safe_vertical}'}})-[:HAS_SUBVERTICAL]->(sv:SubVertical)-[:HAS_CAPABILITY]->(c:Capability)
                OPTIONAL MATCH (c)-[:REALIZED_BY]->(p:Process)
                OPTIONAL MATCH (p)-[:DECOMPOSES]->(sp:Subprocess)
                WITH c, collect(DISTINCT p) as processes, collect(DISTINCT sp) as subprocesses
                RETURN c.name as capability_name, c.description as capability_description,
                       [proc IN processes | {{name: proc.name, description: proc.description}}] as processes,
                       [sp IN subprocesses | {{name: sp.name, description: sp.description}}] as subprocesses
                LIMIT 10
                """
                return general_query.strip()
            else:
                # No vertical specified - return a very general query
                logger.warning("[QUERY GENERATION] No vertical specified - returning minimal query")
                general_query = """
                MATCH (c:Capability)
                OPTIONAL MATCH (c)-[:REALIZED_BY]->(p:Process)
                WITH c, collect(DISTINCT p) as processes
                RETURN c.name as capability_name, c.description as capability_description,
                       [proc IN processes | {{name: proc.name, description: proc.description}}] as processes
                LIMIT 10
                """
                return general_query.strip()

        for anchor in primary_anchors:
            # Escape single quotes in anchor to avoid Cypher injection/syntax errors
            safe_anchor = anchor.replace("'", "''") if isinstance(anchor, str) else anchor
            
            # Build WHERE clause to filter by vertical if provided
            vertical_filter = ""
            if vertical:
                safe_vertical = vertical.replace("'", "''")
                vertical_filter = f"""
                OPTIONAL MATCH (v:Vertical {{name: '{safe_vertical}'}})-[:HAS_SUBVERTICAL]->(sv:SubVertical)-[:HAS_CAPABILITY]->(cap)
                WITH root, cap, v, sv
                WHERE v IS NOT NULL AND (root:Capability OR cap = root OR (root)-[:REALIZED_BY*0..2]-(cap))
                """
                logger.debug(f"[VERTICAL FILTER] Applied vertical filter for: {vertical}")
            else:
                logger.debug(f"[VERTICAL FILTER] No vertical filter applied - querying all verticals")
            
            # Build comprehensive query that works for Capability, Process, or Subprocess anchors
            # This query traverses both upward (to parent Capability) and downward (to child nodes)
            q = f"""
            MATCH (root)
            WHERE root.name = '{safe_anchor}' AND (root:Capability OR root:Process OR root:Subprocess)
            {vertical_filter}
            
            // Get parent capability if root is Process or Subprocess
            OPTIONAL MATCH (parent_cap:Capability)-[:REALIZED_BY]->(root)
            OPTIONAL MATCH (parent_proc:Process)-[:DECOMPOSES]->(root)
            OPTIONAL MATCH (parent_cap2:Capability)-[:REALIZED_BY]->(parent_proc)
            
            // Get child processes if root is Capability
            OPTIONAL MATCH (root)-[:REALIZED_BY]->(child_proc:Process)
            
            // Get child subprocesses if root is Capability or Process
            OPTIONAL MATCH (root)-[:REALIZED_BY|DECOMPOSES*1..2]->(child_sp:Subprocess)
            
            // Get data entities and elements from subprocesses
            OPTIONAL MATCH (all_sp:Subprocess)-[:USES_DATA]->(de:DataEntity)
            WHERE all_sp = root OR all_sp = child_sp OR (parent_proc)-[:DECOMPOSES]->(all_sp)
            OPTIONAL MATCH (de)-[:HAS_ELEMENT]->(elem:DataElements)
            
            // Get org units and applications
            OPTIONAL MATCH (all_sp2:Subprocess)-[:OWNED_BY]->(org:OrgUnit)
            WHERE all_sp2 = root OR all_sp2 = child_sp OR (parent_proc)-[:DECOMPOSES]->(all_sp2)
            OPTIONAL MATCH (all_sp3:Subprocess)-[:USES_APPLICATION]->(app:ApplicationCatalog)
            WHERE all_sp3 = root OR all_sp3 = child_sp OR (parent_proc)-[:DECOMPOSES]->(all_sp3)
            
            WITH root,
                 COALESCE(parent_cap, parent_cap2) as parent_capability,
                 parent_proc,
                 collect(DISTINCT child_proc) as child_processes,
                 collect(DISTINCT child_sp) as child_subprocesses,
                 collect(DISTINCT de) as data_entities,
                 collect(DISTINCT elem) as data_elements,
                 collect(DISTINCT org) as org_units,
                 collect(DISTINCT app) as applications
            
            RETURN 
                root.name as root_name,
                root.description as root_description,
                labels(root) as root_labels,
                parent_capability.name as parent_capability_name,
                parent_capability.description as parent_capability_description,
                parent_proc.name as parent_process_name,
                parent_proc.description as parent_process_description,
                [proc IN child_processes | {{name: proc.name, description: proc.description, uid: proc.uid}}] as processes,
                [sub IN child_subprocesses | {{name: sub.name, description: sub.description, uid: sub.uid}}] as subprocesses,
                [de IN data_entities | {{name: de.name, description: de.data_entity_description, uid: de.uid}}] as data_entities,
                [elem IN data_elements | {{name: elem.name, description: elem.data_element_description, uid: elem.uid}}] as data_elements,
                [o IN org_units | {{name: o.name, uid: o.uid}}] as org_units,
                [a IN applications | {{name: a.name, uid: a.uid}}] as applications
            """
            queries.append(q.strip())

        return " UNION ".join(queries)

    def _serialize_db_records(self, records: Any, plan: Dict[str, Any]) -> str:
        """Serialize DB records with persona-aware hydration and proper metadata extraction."""
        
        try:
            persona = plan.get("persona_tone", "portfolio manager") if isinstance(plan, dict) else "portfolio manager"
            lines = []
            
            # Handle hierarchical vertical context (capabilities structure)
            if isinstance(records, dict) and "capabilities" in records and isinstance(records["capabilities"], list):
                if records.get("vertical_name"):
                    lines.append(f"Vertical: {records.get('vertical_name')}")

                for cap in records.get("capabilities", [])[:10]:
                    cap_name = cap.get("name") or "<unnamed capability>"
                    cap_desc = (cap.get("description") or "").strip()
                    if persona == "Executive":
                        lines.append(f"- Capability: {cap_name}{(' - ' + cap_desc) if cap_desc else ''}")
                    else:
                        lines.append(f"- Capability: {cap_name} - {cap_desc}")

                    # portfolio manager and Investment Analyst see processes
                    for proc in cap.get("processes", [])[:5]:
                        proc_name = proc.get("name") or "<unnamed process>"
                        proc_desc = (proc.get("description") or "").strip()
                        if persona == "portfolio manager":
                            lines.append(f"  - Process: {proc_name} - {proc_desc}")
                        else:  # Investment Analyst
                            lines.append(f"  - Process: {proc_name} - {proc_desc}")
                            for sub in proc.get("subprocesses", [])[:5]:
                                sub_name = sub.get("name") or "<unnamed subprocess>"
                                app = sub.get("application") or ""
                                api = sub.get("api") or ""
                                lines.append(f"    - SubProcess: {sub_name} (App: {app} API: {api})")
                                for ent in sub.get("data_entities", [])[:5]:
                                    ent_name = ent.get("data_entity_name") or "<unnamed entity>"
                                    ent_desc = ent.get("data_entity_description") or ""
                                    lines.append(f"      - DataEntity: {ent_name} - {ent_desc}")

                return "\n".join(lines) if lines else "No retrieved graph context available."
            
            # Handle new Cypher response structure from updated query
            if isinstance(records, dict):
                records_iter = [records]
            elif isinstance(records, list):
                records_iter = records
            else:
                return str(records)[:5000]

            # Process each record from the Cypher query response
            for idx, rec in enumerate(records_iter[:50]):
                if not isinstance(rec, dict):
                    lines.append(f"- {str(rec)}")
                    continue

                # Extract components from new Cypher response format
                root_name = rec.get("root_name")
                root_desc = rec.get("root_description", "")
                root_labels = rec.get("root_labels", [])
                
                # Extract parent context (for when anchor is Process or Subprocess)
                parent_cap_name = rec.get("parent_capability_name")
                parent_cap_desc = rec.get("parent_capability_description", "")
                parent_proc_name = rec.get("parent_process_name")
                parent_proc_desc = rec.get("parent_process_description", "")
                
                # Extract child nodes
                processes = rec.get("processes", [])
                subprocesses = rec.get("subprocesses", [])
                data_entities = rec.get("data_entities", [])
                data_elements = rec.get("data_elements", [])
                org_units = rec.get("org_units", [])
                applications = rec.get("applications", [])
                
                if not root_name:
                    continue
                
                # Determine root type from labels
                root_type = "Entity"
                if "Capability" in root_labels:
                    root_type = "Capability"
                elif "Process" in root_labels:
                    root_type = "Process"
                elif "Subprocess" in root_labels:
                    root_type = "Subprocess"
                
                # Build context based on persona
                if persona == "Executive":
                    # Executive: Show hierarchy context + root node, minimal detail
                    if parent_cap_name:
                        lines.append(f"- Parent Capability: {parent_cap_name}")
                    if parent_proc_name and root_type == "Subprocess":
                        lines.append(f"  - Parent Process: {parent_proc_name}")
                    
                    lines.append(f"  - {root_type}: {root_name}")
                    if root_desc:
                        lines.append(f"    Description: {root_desc}")
                
                elif persona == "portfolio manager":
                    # portfolio manager: Show hierarchy + root + child processes/subprocesses with descriptions
                    if parent_cap_name:
                        lines.append(f"- Parent Capability: {parent_cap_name}")
                        if parent_cap_desc:
                            lines.append(f"  Description: {parent_cap_desc}")
                    
                    if parent_proc_name and root_type == "Subprocess":
                        lines.append(f"  - Parent Process: {parent_proc_name}")
                        if parent_proc_desc:
                            lines.append(f"    Description: {parent_proc_desc}")
                    
                    lines.append(f"  - {root_type}: {root_name}")
                    if root_desc:
                        lines.append(f"    Description: {root_desc}")
                    
                    # Show child processes
                    if processes:
                        lines.append("    Child Processes:")
                        for proc in processes[:10]:
                            proc_name = proc.get("name", "")
                            proc_desc = proc.get("description", "")
                            if proc_name:
                                lines.append(f"      - {proc_name}: {proc_desc}")
                    
                    # Show child subprocesses
                    if subprocesses:
                        lines.append("    Child Subprocesses:")
                        for sub in subprocesses[:10]:
                            sub_name = sub.get("name", "")
                            sub_desc = sub.get("description", "")
                            if sub_name:
                                lines.append(f"      - {sub_name}: {sub_desc}")
                
                else:  # Investment Analyst
                    # Investment Analyst: Comprehensive detail with full hierarchy and all metadata
                    if parent_cap_name:
                        lines.append(f"- Parent Capability: {parent_cap_name}")
                        if parent_cap_desc:
                            lines.append(f"  Description: {parent_cap_desc}")
                    
                    if parent_proc_name and root_type == "Subprocess":
                        lines.append(f"  - Parent Process: {parent_proc_name}")
                        if parent_proc_desc:
                            lines.append(f"    Description: {parent_proc_desc}")
                    
                    lines.append(f"  - {root_type}: {root_name}")
                    if root_desc:
                        lines.append(f"    Description: {root_desc}")
                    
                    # Show child processes with full detail
                    if processes:
                        lines.append("    Child Processes:")
                        for proc in processes[:20]:
                            proc_name = proc.get("name", "")
                            proc_desc = proc.get("description", "")
                            proc_uid = proc.get("uid", "")
                            if proc_name:
                                lines.append(f"      - {proc_name} (UID: {proc_uid})")
                                if proc_desc:
                                    lines.append(f"        Description: {proc_desc}")
                    
                    # Show child subprocesses with full detail
                    if subprocesses:
                        lines.append("    Child Subprocesses:")
                        for sub in subprocesses[:20]:
                            sub_name = sub.get("name", "")
                            sub_desc = sub.get("description", "")
                            sub_uid = sub.get("uid", "")
                            if sub_name:
                                lines.append(f"      - {sub_name} (UID: {sub_uid})")
                                if sub_desc:
                                    lines.append(f"        Description: {sub_desc}")
                    
                    # Show org units
                    if org_units:
                        lines.append("    Organizational Units:")
                        for org in org_units[:20]:
                            org_name = org.get("name", "")
                            org_uid = org.get("uid", "")
                            if org_name:
                                lines.append(f"      - {org_name} (UID: {org_uid})")
                    
                    # Show applications
                    if applications:
                        lines.append("    Applications:")
                        for app in applications[:20]:
                            app_name = app.get("name", "")
                            app_uid = app.get("uid", "")
                            if app_name:
                                lines.append(f"      - {app_name} (UID: {app_uid})")
                    
                    # Show data entities
                    if data_entities:
                        lines.append("    Data Entities:")
                        for de in data_entities[:20]:
                            de_name = de.get("name", "")
                            de_desc = de.get("description", "")
                            de_uid = de.get("uid", "")
                            if de_name:
                                lines.append(f"      - {de_name} (UID: {de_uid})")
                                if de_desc:
                                    lines.append(f"        Description: {de_desc}")
                    
                    # Show data elements
                    if data_elements:
                        lines.append("    Data Elements:")
                        for elem in data_elements[:20]:
                            elem_name = elem.get("name", "")
                            elem_desc = elem.get("description", "")
                            elem_uid = elem.get("uid", "")
                            if elem_name:
                                lines.append(f"      - {elem_name} (UID: {elem_uid})")
                                if elem_desc:
                                    lines.append(f"        Description: {elem_desc}")

            return "\n".join(lines) if lines else "No retrieved graph context available."
        
        except Exception as e:
            logger.warning(f"Error serializing DB records: {e}")
            return "Error serializing DB records."

    def _normalize_db_response(self, resp: Any) -> Any:
        """
        Normalize common /execute-cypher response shapes into a friendlier Python
        structure for serialization. Handles Neo4j HTTP shapes like:
          - {'results': [{'data': [{'row': [...]}, ...]}, ...]}
          - {'data': [{'row': [...]}, ...]}
          - {'columns': [...], 'rows': [[...], ...]}
        Preserves hierarchical shapes that already include 'capabilities'.
        Returns either a list of dicts, a dict (hierarchical), or the original value as fallback.
        """
        try:
            if resp is None:
                return []

            # Preserve already-hierarchical vertical context
            if isinstance(resp, dict) and "capabilities" in resp and isinstance(resp["capabilities"], list):
                return resp

            # If it's already a list of dicts, assume it's normalized
            if isinstance(resp, list):
                if all(isinstance(r, dict) for r in resp):
                    return resp
                # Mixed lists: try to extract inner dicts
                out = []
                for item in resp:
                    if isinstance(item, dict):
                        out.append(item)
                if out:
                    return out

            if isinstance(resp, dict):
                # Neo4j HTTP response with 'results' -> 'data' -> 'row'
                if "results" in resp and isinstance(resp["results"], list):
                    out = []
                    for result in resp["results"]:
                        for d in result.get("data", []):
                            row = d.get("row", [])
                            for item in row:
                                if isinstance(item, dict):
                                    out.append(item)
                                elif isinstance(item, list):
                                    for it in item:
                                        if isinstance(it, dict):
                                            out.append(it)
                                        else:
                                            out.append({"value": it})
                                else:
                                    out.append({"value": item})
                    if out:
                        return out

                # Top-level 'data' array with 'row'
                if "data" in resp and isinstance(resp["data"], list):
                    out = []
                    for d in resp["data"]:
                        if isinstance(d, dict) and "row" in d:
                            for item in d.get("row", []):
                                if isinstance(item, dict):
                                    out.append(item)
                                else:
                                    out.append({"value": item})
                        elif isinstance(d, dict):
                            out.append(d)
                    if out:
                        return out

                # 'columns' + 'rows' shape -> map columns to row values
                if "columns" in resp and "rows" in resp and isinstance(resp.get("rows"), list):
                    cols = resp.get("columns", [])
                    mapped = []
                    for r in resp.get("rows", []):
                        if isinstance(r, list):
                            mapped.append({cols[i]: (r[i] if i < len(r) else None) for i in range(len(cols))})
                    if mapped:
                        return mapped

                # Some endpoints return a top-level key that is a list of dicts; return first such list
                for k, v in resp.items():
                    if isinstance(v, list) and v and isinstance(v[0], dict):
                        return v

            # Fallback: return as-is
            return resp
        except Exception as e:
            logger.warning(f"_normalize_db_response error: {e}")
            return resp

    def _create_vmo_prompt(self, user_query: str, plan: Dict[str, Any], retrieved_graph_context: str, vertical: str) -> str:
        system_message = f"""
### ROLE
You are an expert Enterprise Architecture Consultant for the Capital Markets Virtual Model Office. You specialize in synthesizing complex GraphDB data into actionable insights.
 
### OPERATIONAL GUARDRAILS (THE NORTH STAR)
1. GROUNDING: Use ONLY the provided 'RETRIEVED CONTEXT'. If a relationship or entity is not in the graph, state: "Information not available in the current enterprise model."
2. NO FABRICATION: Do not invent processes, IDs, or lineage.
3. LINEAGE ADHERENCE: Follow the hierarchy: Capability -> Process -> Sub-process -> Data Entity.
4. CITATION: Reference specific entities from the context (e.g., "Per the [Process Name]...") to maintain integrity.
 
### PERSONA GUIDELINES
- EXECUTIVE: "Bottom Line Up Front." Focus on business value and high-level capabilities.
- portfolio manager: Focus on the "How." Detail process relationships, workflows, and dependencies.
- Investment Analyst: Maximum fidelity. Include technical IDs, Data Element definitions, and exhaustive lineage mapping.
 
### RESPONSE STRUCTURE
1. Give your thinking inside the thinking tag: <thinking> [Your step-by-step reasoning process - reference external sources] </thinking>
2. TARGET ENTITY: [Target Entity: Name]
3. ANALYSIS: Map the query to the meta-model and justify your response "altitude" based on the Persona.
4. TAILORED RESPONSE: The persona-specific synthesis.
"""
        return system_message

    pass

    def _parse_response(self, response_text: str, reasoning_content: Optional[str] = None) -> Tuple[str, str]:
        """
        Parse the LLM response into thinking and result sections.
        
        Prioritizes native reasoning_content from Kimi model over parsing explicit tags.
        
        Args:
            response_text: The main response content from the LLM
            reasoning_content: Native reasoning output from Kimi model (optional)
            
        Returns:
            Tuple of (thinking, result)
        """
        thinking = ""
        result = ""

        try:
            # Priority 1: Use native reasoning_content from Kimi model if available
            if reasoning_content:
                thinking = reasoning_content.strip()
                result = response_text.strip()
                logger.debug(f"Using native reasoning_content from Kimi model (length={len(thinking)} chars)")
                return thinking, result
            
            # Priority 2: Parse explicit thinking tags if no native reasoning available
            if "<thinking>" in response_text and "</thinking>" in response_text:
                parts = response_text.split("<thinking>")
                thinking = parts[1].split("</thinking>")[0].strip()
                result = parts[1].split("</thinking>")[1].strip()
                logger.debug(f"Extracted thinking from explicit tags (length={len(thinking)} chars)")
                return thinking, result
            
            # Fallback: If no explicit thinking tags, treat all as result
            result = response_text.strip()
            thinking = "Analysis in progress..."
            logger.debug("No explicit thinking tags found, using fallback response format")

        except Exception as e:
            logger.warning(f"Error parsing response: {e}")
            result = response_text
            thinking = "Analysis completed"

        return thinking, result

    def extract_keywords(
        self, query: str, max_keywords: int = 5
    ) -> List[str]:
        """Extract key concepts from a query using Azure OpenAI"""
        try:
            client = self._get_client()
            config = self._load_config()

            response = client.chat.completions.create(
                model=config["deployment"],
                messages=[
                    {
                        "role": "user",
                        "content": f"Extract the top {max_keywords} key concepts/keywords from this query. Return only the keywords as a comma-separated list:\n{query}",
                    }
                ],
            )

            keywords_text = response.choices[0].message.content
            keywords = [
                k.strip() for k in keywords_text.split(",")
            ]
            return keywords[:max_keywords]

        except Exception as e:
            logger.error(f"Error extracting keywords: {e}")
            return []


# Global instance
azure_openai_thinking_client = AzureOpenAIThinkingClient()

# --- Lightweight NLU / QueryPlan helpers (kept local to this module) ---
INTENT_KEYWORDS = {
    "strategic": ["strategy", "goal", "objective", "plan", "vision"],
    "operational": ["process", "steps", "workflow", "procedure", "operation"],
    "informational": ["what", "how", "describe", "information", "details", "differences"],
    "impact": ["impact", "effect", "influence", "consequence"],
    "technical": ["api", "data entity", "technical", "attribute", "lineage", "id"],
}

OFFICIAL_CATALOG = [
    # Capabilities
    "Fund Performance",
    "Performance Attribution",
]


