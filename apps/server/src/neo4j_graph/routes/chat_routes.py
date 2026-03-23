"""
Compass Chat routes for conversational AI interface.

Provides endpoints for chatting with the Compass system using LLM with graph context.
"""

import logging
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["Chat"])


class CompassChatRequest(BaseModel):
    """Request model for compass chat"""
    query: str
    vertical: str


class DualChatLogRequest(BaseModel):
    """Request model for logging dual chat responses"""
    query: str
    vertical: str
    system_prompt_compass: str
    thinking_compass: str
    response_compass: str
    system_prompt_independent: str
    thinking_independent: str
    response_independent: str
    context_data: str


@router.post("/compass")
async def compass_chat(payload: CompassChatRequest):
    """
    Chat with Compass using graph database context.
    
    This endpoint uses the graph database to retrieve relevant context
    and generates a response using the LLM with VMO (Vertical, Metadata, Orchestration) prompting.
    
    Request Body:
    {
        "query": "User's question",
        "vertical": "Selected vertical/domain",
    }
    
    Returns:
    {
        "thinking": "LLM's reasoning process",
        "result": "Final answer",
        "vmo_meta": {...metadata about the query processing...},
        "system_prompt_compass": "System prompt used",
        "context_data": "Retrieved graph context"
    }
    """
    try:
        from utils.llmthinking import AzureOpenAIThinkingClient
        from neo4j_graph.services.query_execution_service import Neo4jQueryService
        
        # Initialize the thinking client
        thinking_client = AzureOpenAIThinkingClient()
        
        # Create Neo4j service instance for database queries
        neo4j_service = Neo4jQueryService()
        
        try:
            # Execute query with graph context
            thinking, result, request_id = thinking_client.think_and_analyze(
                query=payload.query,
                vertical=payload.vertical,
                vertical_data={},  # Will be fetched by the client
                db_fetch_function=neo4j_service.execute_cypher,
                user_profile=None
            )
            
            # Get metadata about the query processing
            vmo_meta = thinking_client.get_vmo_meta(request_id)
            system_prompt = thinking_client.get_last_system_prompt() or ""
            
            # Get the context that was sent to the LLM (from system prompt)
            context_data = ""
            if system_prompt:
                # Extract context from system prompt (it's embedded in the VMO prompt)
                import re
                context_match = re.search(r'### RETRIEVED GRAPH CONTEXT:(.*?)(?:###|$)', system_prompt, re.DOTALL)
                if context_match:
                    context_data = context_match.group(1).strip()
            
            return JSONResponse({
                "thinking": thinking,
                "result": result,
                "vmo_meta": vmo_meta,
                "system_prompt_compass": system_prompt[:5000],  # Truncate for response size
                "context_data": context_data[:5000]  # Truncate for response size
            })
        finally:
            # Always close the Neo4j connection
            neo4j_service.close()
        
    except Exception as e:
        logger.error(f"Compass chat failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/compass/independent")
async def compass_chat_independent(payload: CompassChatRequest):
    """
    Chat with Compass WITHOUT graph database context (independent LLM response).
    
    This endpoint generates a response using only the LLM's knowledge,
    without retrieving any context from the graph database.
    
    Request Body:
    {
        "query": "User's question",
        "vertical": "Selected vertical/domain",
    }
    
    Returns:
    {
        "thinking": "LLM's reasoning process",
        "result": "Final answer",
        "system_prompt_independent": "System prompt used"
    }
    """
    try:
        from config.azure_clients import get_azure_openai_client, get_azure_config
        
        # Get Azure OpenAI client
        client = get_azure_openai_client()
        config = get_azure_config()
        
        # Create a simple system prompt without graph context
        system_prompt = f"""You are an expert Enterprise Architecture consultant specializing in the {payload.vertical} domain.

Your role is to provide insightful, accurate answers to questions about business capabilities, processes, and enterprise architecture.

Guidelines:
- Provide clear, structured responses
- Use your knowledge of industry best practices
- Be specific and actionable
- If you're uncertain, acknowledge it

User Query: {payload.query}

Provide your response in two sections:
1. THINKING: Your reasoning process (brief)
2. RESULT: Your final answer (detailed)

Format your response as:
### THINKING
[Your reasoning here]

### RESULT
[Your answer here]
"""
        
        # Call Azure OpenAI
        response = client.chat.completions.create(
            model=config["deployment"],
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": payload.query}
            ],
        )
        
        response_text = response.choices[0].message.content
        
        # Parse thinking and result
        thinking = ""
        result = response_text
        
        if "### THINKING" in response_text and "### RESULT" in response_text:
            parts = response_text.split("### RESULT")
            thinking_part = parts[0].replace("### THINKING", "").strip()
            result_part = parts[1].strip() if len(parts) > 1 else ""
            thinking = thinking_part
            result = result_part
        
        return JSONResponse({
            "thinking": thinking,
            "result": result,
            "system_prompt_independent": system_prompt[:5000]  # Truncate for response size
        })
        
    except Exception as e:
        logger.error(f"Independent compass chat failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/compass/log-dual")
async def log_dual_chat(payload: DualChatLogRequest):
    """
    Log dual chat responses for analysis and comparison.
    
    This endpoint logs both the graph-context response and independent response
    for later analysis of how context affects LLM responses.
    
    Request Body:
    {
        "query": "User's question",
        "vertical": "Selected vertical",
        "system_prompt_compass": "System prompt with context",
        "thinking_compass": "Thinking with context",
        "response_compass": "Response with context",
        "system_prompt_independent": "System prompt without context",
        "thinking_independent": "Thinking without context",
        "response_independent": "Response without context",
        "context_data": "Graph context used"
    }
    
    Returns:
    {
        "status": "success",
        "message": "Dual chat logged successfully"
    }
    """
    try:
        from utils.llm_call_logger import get_llm_call_logger
        from datetime import datetime
        
        # Get logger instance
        llm_logger = get_llm_call_logger()
        
        # Log the dual chat comparison
        llm_logger.log_call(
            model_name="dual_chat_comparison",
            domain=payload.vertical,
            capability_name=payload.query[:100],
            user_prompt=payload.query,
            status="success"
        )
        
        logger.info(f"Logged dual chat comparison for query: {payload.query[:50]}...")
        
        return JSONResponse({
            "status": "success",
            "message": "Dual chat logged successfully"
        })
        
    except Exception as e:
        logger.error(f"Failed to log dual chat: {e}", exc_info=True)
        # Don't fail the request if logging fails
        return JSONResponse({
            "status": "warning",
            "message": f"Logging failed but chat completed: {str(e)}"
        })
