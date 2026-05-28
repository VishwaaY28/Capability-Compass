"""
LLM-based research endpoint - returns a SINGLE most relevant result.

The match can land at any level of the hierarchy:
  - capability
  - process (under a capability)
  - subprocess (under a process under a capability)

Whatever level the LLM picks, the response is shaped as a single capability
(with only the matched process/subprocess kept) so the existing UI renders it
unchanged. A `match_level` field is added so the client can highlight what
was actually matched if needed.
"""
import logging
import json
import re
import copy
from fastapi.responses import JSONResponse

from neo4j_graph.services.capability_service import CapabilityService

logger = logging.getLogger(__name__)

MAX_CANDIDATES = 60
DESCRIPTION_PREVIEW_CHARS = 280


async def llm_research_capabilities(query: str):
    """Search across capabilities/processes/subprocesses and let the LLM pick ONE."""
    try:
        logger.info(f"[Research] Query: {query}")

        keywords = extract_keywords(query)
        logger.info(f"[Research] Keywords: {keywords}")

        if not keywords:
            return JSONResponse({"results": []})

        cap_results = CapabilityService.search_by_concepts(keywords, limit=30)
        logger.info(f"[Research] Found {len(cap_results)} candidate capabilities")

        if not cap_results:
            return JSONResponse({"results": []})

        candidates = build_flat_candidates(cap_results, keywords)
        logger.info(f"[Research] Flattened to {len(candidates)} ranked candidates across all levels")

        if not candidates:
            return JSONResponse({"results": []})

        best = await pick_best_with_llm(query, candidates)
        if not best:
            best = candidates[0]

        result = shape_result(best)
        logger.info(
            f"[Research] Returning 1 result at level={result.get('match_level')} "
            f"name={result.get('name')}"
        )
        return JSONResponse({"results": [result]})

    except Exception as e:
        logger.error(f"[Research] Error: {e}", exc_info=True)
        return fallback_keyword_search(query)


def extract_keywords(query: str) -> list:
    stop_words = {
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
        'of', 'with', 'by', 'from', 'as', 'is', 'are', 'was', 'were', 'what',
        'show', 'me', 'all', 'give', 'how', 'can', 'do', 'does', 'will',
        'would', 'should', 'could', 'my', 'your', 'their', 'our', 'this',
        'that', 'these', 'those', 'used', 'involved',
        # Generic terms that exist in almost every node and only add noise
        'process', 'processes', 'subprocess', 'subprocesses',
        'capability', 'capabilities', 'data', 'entity', 'entities',
    }
    return [
        word.strip('.,!?;:"\'')
        for word in query.lower().split()
        if len(word) > 2 and word.lower() not in stop_words
    ][:10]


def _score_text(text: str, keywords: list, name_field: bool) -> int:
    """Score a single text field. Name matches are weighted higher than descriptions."""
    if not text or not keywords:
        return 0
    text_lower = text.lower()
    score = 0
    for kw in keywords:
        if not kw:
            continue
        kw_lower = kw.lower()
        if kw_lower in text_lower:
            score += 5 if name_field else 1
            # Whole-word bonus
            if re.search(rf'\b{re.escape(kw_lower)}\b', text_lower):
                score += 3 if name_field else 1
    return score


def _score_candidate(name: str, description: str, keywords: list,
                     extra_texts: list = None) -> int:
    """Compute a relevance score for a node based on its own + optional child text."""
    score = _score_text(name, keywords, name_field=True)
    score += _score_text(description, keywords, name_field=False)
    for txt in extra_texts or []:
        score += _score_text(txt, keywords, name_field=False)
    return score


def build_flat_candidates(capabilities: list, keywords: list) -> list:
    """Flatten capabilities/processes/subprocesses into a ranked candidate list.

    Every node from a matched capability is included so the LLM can still pick
    a node that doesn't textually contain any keyword (e.g. semantic match), but
    nodes are sorted by keyword-match score so the strongest candidates always
    sit at the top of the list and never get cut off by MAX_CANDIDATES.
    """
    candidates: list = []
    for cap in capabilities:
        cap_score = _score_candidate(cap.get("name"), cap.get("description"), keywords)
        candidates.append({
            "level": "capability",
            "id": cap.get("id"),
            "name": cap.get("name"),
            "description": cap.get("description", ""),
            "_score": cap_score,
            "_capability": cap,
        })

        for proc in cap.get("processes", []) or []:
            if not proc.get("id"):
                continue
            proc_score = _score_candidate(proc.get("name"), proc.get("description"), keywords)
            candidates.append({
                "level": "process",
                "id": proc.get("id"),
                "name": proc.get("name"),
                "description": proc.get("description", ""),
                "_score": proc_score,
                "_capability": cap,
                "_process": proc,
            })

            for sp in proc.get("subprocesses", []) or []:
                if not sp.get("id"):
                    continue
                # Pull text from the subprocess's data entities/elements so a
                # subprocess matched purely on its data assets still scores well.
                extra_texts = []
                for de in sp.get("data_entities", []) or []:
                    extra_texts.append(de.get("data_entity_name", ""))
                    extra_texts.append(de.get("data_entity_description", ""))
                    for el in de.get("data_elements", []) or []:
                        extra_texts.append(el.get("data_element_name", ""))
                sp_score = _score_candidate(
                    sp.get("name"), sp.get("description"), keywords,
                    extra_texts=extra_texts
                )
                candidates.append({
                    "level": "subprocess",
                    "id": sp.get("id"),
                    "name": sp.get("name"),
                    "description": sp.get("description", ""),
                    "_score": sp_score,
                    "_capability": cap,
                    "_process": proc,
                    "_subprocess": sp,
                })

    # Sort by score desc; keep level priority (subprocess > process > capability)
    # as a tie-breaker so specific matches win when scores are equal.
    level_priority = {"subprocess": 2, "process": 1, "capability": 0}
    candidates.sort(
        key=lambda c: (c["_score"], level_priority.get(c["level"], 0)),
        reverse=True,
    )
    return candidates[:MAX_CANDIDATES]


def _format_candidate_block(idx: int, c: dict) -> str:
    """Render one candidate as a multi-line block the LLM can reason over."""
    cap_name = c["_capability"].get("name", "")
    lines = [f"{idx}. <{c['level'].upper()}> {c['name']}  (score={c['_score']})"]

    if c["level"] == "process":
        lines.append(f"   parent capability: {cap_name}")
    elif c["level"] == "subprocess":
        proc_name = c["_process"].get("name", "")
        lines.append(f"   parent process: {proc_name}")
        lines.append(f"   parent capability: {cap_name}")

    desc = (c.get("description") or "").strip()
    if desc:
        lines.append(f"   description: {desc[:DESCRIPTION_PREVIEW_CHARS]}")

    if c["level"] == "subprocess":
        sp = c["_subprocess"]
        de_names = [
            de.get("data_entity_name")
            for de in (sp.get("data_entities") or [])
            if de.get("data_entity_name")
        ]
        if de_names:
            lines.append(f"   data entities: {', '.join(de_names[:10])}")

    if c["level"] == "process":
        proc = c["_process"]
        sp_names = [
            sp.get("name")
            for sp in (proc.get("subprocesses") or [])
            if sp.get("name")
        ]
        if sp_names:
            lines.append(f"   subprocesses: {', '.join(sp_names[:8])}")

    if c["level"] == "capability":
        cap = c["_capability"]
        proc_names = [
            p.get("name")
            for p in (cap.get("processes") or [])
            if p.get("name")
        ]
        if proc_names:
            lines.append(f"   processes: {', '.join(proc_names[:8])}")

    return "\n".join(lines)


async def pick_best_with_llm(query: str, candidates: list) -> dict | None:
    """Ask the LLM to pick the single most relevant candidate across all levels."""
    try:
        from config.azure_clients import get_azure_openai_client, get_azure_config

        client = get_azure_openai_client()
        config = get_azure_config()

        summary_lines = "\n\n".join(
            _format_candidate_block(i, c) for i, c in enumerate(candidates, 1)
        )

        prompt = f"""User query:
"{query}"

Below is a ranked list of candidate matches at three levels of the business
architecture hierarchy. Each candidate carries a coarse keyword-match `score`
(higher = more textual overlap with the query); use it as a hint, not a rule.

- CAPABILITY (broad business capability)
- PROCESS    (a process realizing a capability)
- SUBPROCESS (a step inside a process; usually the most specific match)

Selection rules (apply in order):
1. Pick the candidate that most directly answers the user's intent — read the
   description, parent context, and listed children carefully before deciding.
2. When multiple candidates equally answer the query, prefer the MOST SPECIFIC
   level: SUBPROCESS > PROCESS > CAPABILITY.
3. A higher score is a useful signal, but a lower-score candidate may still be
   the best answer if its description/data-entities semantically match the
   intent better than higher-score ones.
4. Never pick a parent (capability/process) when one of its children precisely
   answers the query.

Return ONLY a JSON object with the 1-based index of the best match:
{{"best_index": 7}}

Candidates:

{summary_lines}"""

        logger.info(f"[Research] Calling LLM to pick 1 of {len(candidates)} candidates")

        response = client.chat.completions.create(
            model=config["deployment"],
            messages=[
                {"role": "system", "content": (
                    "You are a precise search ranking expert for a business "
                    "architecture knowledge graph. You read every candidate "
                    "carefully (including its parent context, description, and "
                    "children) before making a decision. You return only valid "
                    "JSON of the form {\"best_index\": <int>}."
                )},
                {"role": "user", "content": prompt}
            ],
        )

        response_text = response.choices[0].message.content.strip()
        logger.info(f"[Research] LLM response: {response_text[:200]}")

        json_match = re.search(r'\{.*?\}', response_text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            idx = data.get("best_index")
            if isinstance(idx, int) and 1 <= idx <= len(candidates):
                picked = candidates[idx - 1]
                logger.info(
                    f"[Research] LLM picked index {idx} "
                    f"(level={picked['level']}, score={picked['_score']}, name={picked['name']})"
                )
                return picked

        logger.warning("[Research] LLM parse failed, falling back to top-scored candidate")
        return None

    except Exception as e:
        logger.warning(f"[Research] LLM ranking error: {e}")
        return None


def shape_result(candidate: dict) -> dict:
    """Build the single-capability response, trimmed to just the matched branch.

    The frontend always renders results as capabilities with nested processes
    and subprocesses, so we package every match level into that shape.
    """
    cap = copy.deepcopy(candidate["_capability"])
    level = candidate["level"]

    if level == "capability":
        cap["match_level"] = "capability"
        cap["matched_id"] = cap.get("id")
        return cap

    if level == "process":
        proc = copy.deepcopy(candidate["_process"])
        cap["processes"] = [proc]
        cap["match_level"] = "process"
        cap["matched_id"] = proc.get("id")
        return cap

    # subprocess
    proc = copy.deepcopy(candidate["_process"])
    sp = copy.deepcopy(candidate["_subprocess"])
    proc["subprocesses"] = [sp]
    cap["processes"] = [proc]
    cap["match_level"] = "subprocess"
    cap["matched_id"] = sp.get("id")
    return cap


def fallback_keyword_search(query: str):
    """Pure keyword fallback when the LLM path fails. Returns at most 1 result."""
    logger.warning(f"[Research Fallback] Using keyword search for: {query}")
    try:
        keywords = extract_keywords(query)
        if not keywords:
            return JSONResponse({"results": []})

        caps = CapabilityService.search_by_concepts(keywords, limit=1)
        if not caps:
            return JSONResponse({"results": []})

        cap = caps[0]
        result = {
            "id": cap["id"],
            "name": cap["name"],
            "description": cap.get("description", ""),
            "vertical": cap.get("vertical"),
            "subvertical": cap.get("subvertical"),
            "processes": cap.get("processes", []),
            "match_level": "capability",
            "matched_id": cap["id"],
        }
        logger.info("[Research Fallback] Returning 1 result")
        return JSONResponse({"results": [result]})
    except Exception as e:
        logger.error(f"[Research Fallback] Error: {e}", exc_info=True)
        return JSONResponse({"results": []})
