"""
LLM-based research endpoint - capability-first, full depth
Fetches capabilities with complete hierarchy, LLM picks top 3 most relevant.
"""
import logging
import json
import re
from fastapi.responses import JSONResponse

from neo4j_graph.services.capability_service import CapabilityService

logger = logging.getLogger(__name__)

MAX_RESULTS = 3


async def llm_research_capabilities(query: str):
    """Search capabilities with full depth, let LLM pick top 3"""
    try:
        logger.info(f"[Research] Query: {query}")

        keywords = extract_keywords(query)
        logger.info(f"[Research] Keywords: {keywords}")

        if not keywords:
            return JSONResponse({"results": []})

        # Fetch capabilities with full hierarchy (processes → subprocesses → data entities)
        cap_results = CapabilityService.search_by_concepts(keywords, limit=20)
        logger.info(f"[Research] Found {len(cap_results)} candidate capabilities")

        if not cap_results:
            return JSONResponse({"results": []})

        # Format all candidates for LLM ranking
        candidates = [
            {
                "type": "capability",
                "id": cap["id"],
                "name": cap["name"],
                "description": cap.get("description", ""),
                "vertical": cap.get("vertical"),
                "subvertical": cap.get("subvertical"),
                "processes": cap.get("processes", []),
            }
            for cap in cap_results
        ]

        ranked = await rank_results_with_llm(query, candidates)
        logger.info(f"[Research] Returning {len(ranked)} results")
        return JSONResponse({"results": ranked})

    except Exception as e:
        logger.error(f"[Research] Error: {e}", exc_info=True)
        return fallback_keyword_search(query)


def extract_keywords(query: str) -> list:
    stop_words = {
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
        'of', 'with', 'by', 'from', 'as', 'is', 'are', 'was', 'were', 'what',
        'show', 'me', 'all', 'give', 'how', 'can', 'do', 'does', 'will',
        'would', 'should', 'could', 'my', 'your', 'their', 'our', 'this',
        'that', 'these', 'those', 'used', 'involved'
    }
    return [
        word.strip('.,!?;:')
        for word in query.lower().split()
        if len(word) > 2 and word.lower() not in stop_words
    ][:10]


async def rank_results_with_llm(query: str, candidates: list) -> list:
    """Use LLM to pick the top MAX_RESULTS most relevant capabilities"""
    try:
        from config.azure_clients import get_azure_openai_client, get_azure_config

        client = get_azure_openai_client()
        config = get_azure_config()

        # Build a compact summary of each candidate for the LLM
        summary_lines = ""
        for i, cap in enumerate(candidates[:20], 1):
            proc_names = ", ".join(p["name"] for p in cap.get("processes", [])[:8] if p.get("name"))
            # Collect subprocess names for extra context
            sp_names = []
            for p in cap.get("processes", [])[:5]:
                for sp in p.get("subprocesses", [])[:3]:
                    if sp.get("name"):
                        sp_names.append(sp["name"])
            summary_lines += f"\n{i}. [{cap['name']}]"
            if cap.get("description"):
                summary_lines += f" - {cap['description'][:120]}"
            if proc_names:
                summary_lines += f"\n   Processes: {proc_names}"
            if sp_names:
                summary_lines += f"\n   Subprocesses: {', '.join(sp_names[:6])}"

        prompt = f"""User query: "{query}"

Below are business capabilities (with their key processes). 
Pick the {MAX_RESULTS} MOST RELEVANT capabilities that best answer the query.
Return ONLY a JSON object with the indices (1-based) in order of relevance:
{{"relevant_results": [2, 5, 1]}}

Capabilities:
{summary_lines}"""

        logger.info(f"[Research] Calling LLM to rank {len(candidates[:20])} capabilities")

        response = client.chat.completions.create(
            model=config["deployment"],
            messages=[
                {"role": "system", "content": "You are a search ranking expert. Return only valid JSON."},
                {"role": "user", "content": prompt}
            ],
        )

        response_text = response.choices[0].message.content.strip()
        logger.info(f"[Research] LLM response: {response_text[:200]}")

        # Extract JSON - handle code blocks too
        json_match = re.search(r'\{.*?\}', response_text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            indices = data.get("relevant_results", [])
            ranked = []
            for idx in indices[:MAX_RESULTS]:
                if 1 <= idx <= len(candidates[:20]):
                    ranked.append(candidates[idx - 1])
            if ranked:
                logger.info(f"[Research] LLM selected {len(ranked)} capabilities")
                return ranked

        logger.warning("[Research] LLM parse failed, returning top candidates")
        return candidates[:MAX_RESULTS]

    except Exception as e:
        logger.warning(f"[Research] LLM ranking error: {e}")
        return candidates[:MAX_RESULTS]


def fallback_keyword_search(query: str):
    logger.warning(f"[Research Fallback] Using keyword search for: {query}")
    try:
        keywords = extract_keywords(query)
        if not keywords:
            return JSONResponse({"results": []})

        caps = CapabilityService.search_by_concepts(keywords, limit=MAX_RESULTS)
        results = [
            {
                "type": "capability",
                "id": cap["id"],
                "name": cap["name"],
                "description": cap.get("description", ""),
                "vertical": cap.get("vertical"),
                "subvertical": cap.get("subvertical"),
                "processes": cap.get("processes", []),
            }
            for cap in caps
        ]
        logger.info(f"[Research Fallback] Returning {len(results)} results")
        return JSONResponse({"results": results})
    except Exception as e:
        logger.error(f"[Research Fallback] Error: {e}", exc_info=True)
        return JSONResponse({"results": []})
