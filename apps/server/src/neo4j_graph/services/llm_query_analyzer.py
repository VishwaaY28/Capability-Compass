"""
LLM-based query analyzer for intelligent search
"""
import logging
from dataclasses import dataclass
from typing import List, Dict
from utils.llm import azure_openai_client

logger = logging.getLogger(__name__)

@dataclass
class QueryAnalysis:
    concepts: List[str]
    expanded_terms: Dict[str, str]
    confidence: float

class LLMQueryAnalyzer:
    def __init__(self):
        self.llm_client = azure_openai_client
    
    async def analyze_query(self, query: str) -> QueryAnalysis:
        logger.info(f"[Query Analysis] Query: {query}")
        try:
            concepts = await self._extract_concepts(query)
            expanded_terms = self._expand_abbreviations(query, concepts)
            return QueryAnalysis(concepts, expanded_terms, 0.85)
        except Exception as e:
            logger.error(f"[Query Analysis] Failed: {e}", exc_info=True)
            return self._fallback_analysis(query)
    
    async def _extract_intent(self, query: str) -> str:
        try:
            prompt = f"""Analyze this search query 

Query: "{query}"

Return ONLY the intent classification (one word)."""
            
            result = await self.llm_client.generate_json(
                prompt_text=prompt,
                purpose="intent_extraction"
            )
            
            if result.get("status") == "success":
                data = result.get("data", {})
                intent = data.get("intent", "Exploratory")
                if isinstance(intent, str):
                    return intent
            return "Exploratory"
        except:
            return "Exploratory"
    
    async def _infer_persona(self, query: str) -> str:
        try:
            prompt = f"""Infer the user persona from this query. Choose ONE of: Executive, Portfolio Manager, Investment Analyst, or Technical User.

Query: "{query}"

Return ONLY the persona (e.g., "Portfolio Manager")."""
            
            result = await self.llm_client.generate_json(
                prompt_text=prompt,
                purpose="persona_inference"
            )
            
            if result.get("status") == "success":
                data = result.get("data", {})
                persona = data.get("persona", "Portfolio Manager")
                if isinstance(persona, str):
                    return persona
            return "Portfolio Manager"
        except:
            return "Portfolio Manager"
    
    async def _extract_concepts(self, query: str) -> List[str]:
        try:
            prompt = f"""Extract 3-5 key concepts from this query. Return as a JSON array.

Query: "{query}"

Return format: {{"concepts": ["concept1", "concept2", ...]}}"""
            
            result = await self.llm_client.generate_json(
                prompt_text=prompt,
                purpose="concept_extraction"
            )
            
            if result.get("status") == "success":
                data = result.get("data", {})
                concepts = data.get("concepts", [])
                if isinstance(concepts, list) and concepts:
                    return concepts[:5]
            return self._extract_keywords(query)
        except:
            return self._extract_keywords(query)
    
    def _extract_keywords(self, query: str) -> List[str]:
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'from', 'as', 'is', 'are', 'was', 'were', 'what', 'show', 'me', 'all', 'give', 'how', 'can', 'do', 'does', 'will', 'would', 'should', 'could', 'my', 'your', 'their', 'our', 'this', 'that', 'these', 'those', 'used', 'involved'}
        return [w.strip('.,!?;:') for w in query.lower().split() if len(w) > 2 and w.lower() not in stop_words][:5]
    
    def _expand_abbreviations(self, query: str, concepts: List[str]) -> Dict[str, str]:
        abbrevs = {'kyc': 'know your customer', 'aml': 'anti money laundering', 'esg': 'environmental social governance', 'roi': 'return on investment', 'kpi': 'key performance indicator'}
        expanded = {}
        for abbrev, full in abbrevs.items():
            if abbrev in query.lower():
                expanded[abbrev] = full
        return expanded
    
    def _determine_focus_level(self, intent: str, persona: str) -> List[str]:
        if 'strategic' in intent.lower():
            return ['capability', 'process']
        elif 'technical' in intent.lower():
            return ['subprocess', 'data_entity', 'data_element']
        elif 'operational' in intent.lower():
            return ['process', 'subprocess']
        return ['capability', 'process', 'subprocess']
    
    def _fallback_analysis(self, query: str) -> QueryAnalysis:
        keywords = self._extract_keywords(query)
        q = query.lower()
        if 'data' in q or 'element' in q:
            return QueryAnalysis("Technical", "Portfolio Manager", keywords, {}, ['subprocess', 'data_entity', 'data_element'], 0.5)
        elif 'process' in q:
            return QueryAnalysis("Operational", "Portfolio Manager", keywords, {}, ['process', 'subprocess'], 0.5)
        return QueryAnalysis("Exploratory", "Portfolio Manager", keywords, {}, ['capability', 'process', 'subprocess'], 0.5)
