"""
LLM Result Ranker Service

Scores and ranks search results using LLM reasoning for semantic relevance.
Applies persona-based boosting and filters to top 5-15 results.
"""
import logging
import time
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

from neo4j_graph.services.llm_query_analyzer import QueryAnalysis

logger = logging.getLogger(__name__)


@dataclass
class SearchCandidate:
    """A candidate search result from Neo4j."""
    entity_type: str  # capability, process, subprocess, data_entity, data_element
    entity_id: int
    name: str
    description: str
    hierarchy_level: int  # 1=Vertical, 2=SubVertical, 3=Capability, etc.
    parent_info: Dict[str, Any]  # Parent entity information
    metadata: Dict[str, Any]  # Additional entity-specific metadata


@dataclass
class RankedResult:
    """A search result with relevance score and ranking reason."""
    candidate: SearchCandidate
    relevance_score: float  # 0-100
    ranking_reason: str  # Brief explanation of why this result is relevant


class LLMResultRanker:
    """
    Ranks search results using Azure OpenAI LLM to score semantic relevance.
    Applies persona-based boosting and filters by relevance threshold.
    """
    
    def __init__(self):
        """Initialize the ranker with LLM client."""
        self.llm_client = None
        self.min_relevance_score = 30
        self.max_results = 15
        self._initialize_client()
    
    def _initialize_client(self):
        """Lazily initialize the LLM client."""
        try:
            from utils.llmthinking import AzureOpenAIThinkingClient
            self.llm_client = AzureOpenAIThinkingClient()
            logger.info("[Result Ranker] Initialized with AzureOpenAIThinkingClient")
        except Exception as e:
            logger.warning(f"[Result Ranker] Failed to initialize LLM client: {e}")
            self.llm_client = None
    
    def rank_results(
        self,
        query: str,
        candidates: List[SearchCandidate],
        analysis: QueryAnalysis
    ) -> List[RankedResult]:
        """
        Rank search candidates by relevance using LLM scoring.
        
        Args:
            query: Original user query
            candidates: List of candidate entities from Neo4j
            analysis: Query analysis from LLMQueryAnalyzer
            
        Returns:
            List of RankedResult objects, sorted by score (descending),
            filtered to top 15 results with score >= 30
        """
        if not candidates:
            logger.info("[Result Ranker] No candidates to rank")
            return []
        
        logger.info(f"[Result Ranker] Ranking {len(candidates)} candidates")
        start_time = time.time()
        
        try:
            # Score all candidates (batch scoring for efficiency)
            scores = self._batch_score_candidates(query, candidates, analysis)
            
            # Apply persona-based boosting
            boosted_scores = []
            for i, candidate in enumerate(candidates):
                base_score = scores[i]
                boosted_score = self._apply_persona_boost(
                    base_score,
                    candidate.entity_type,
                    analysis.persona
                )
                boosted_scores.append(boosted_score)
            
            # Create ranked results
            ranked_results = []
            for i, candidate in enumerate(candidates):
                ranked_results.append(RankedResult(
                    candidate=candidate,
                    relevance_score=boosted_scores[i],
                    ranking_reason=self._generate_ranking_reason(
                        candidate, boosted_scores[i], analysis
                    )
                ))
            
            # Filter and limit
            filtered_results = self._filter_and_limit(ranked_results)
            
            elapsed = time.time() - start_time
            logger.info(
                f"[Result Ranker] Ranked {len(candidates)} candidates to "
                f"{len(filtered_results)} results in {elapsed:.2f}s"
            )
            logger.info(
                f"[Result Ranker] Top scores: "
                f"{[r.relevance_score for r in filtered_results[:5]]}"
            )
            
            return filtered_results
            
        except Exception as e:
            logger.error(f"[Result Ranker] Error ranking results: {e}", exc_info=True)
            # Fallback to simple text similarity scoring
            return self._fallback_ranking(query, candidates, analysis)
    
    def _batch_score_candidates(
        self,
        query: str,
        candidates: List[SearchCandidate],
        analysis: QueryAnalysis
    ) -> List[float]:
        """
        Score multiple candidates in a single LLM call for efficiency.
        
        Returns: List of relevance scores (0-100) matching candidate order
        """
        if not self.llm_client:
            return self._fallback_scores(query, candidates, analysis)
        
        try:
            # Build prompt for batch scoring
            prompt = self._build_scoring_prompt(query, candidates, analysis)
            
            # Call LLM (using the client's invoke method)
            client = self.llm_client._get_client()
            config = self.llm_client._load_config()
            
            response = client.chat.completions.create(
                model=config["deployment"],
                messages=[
                    {"role": "system", "content": "You are an expert at evaluating search result relevance."},
                    {"role": "user", "content": prompt}
                ],
            )
            
            response_text = response.choices[0].message.content
            
            # Parse scores from response
            scores = self._parse_scores(response_text, len(candidates))
            
            return scores
            
        except Exception as e:
            logger.warning(f"[Result Ranker] Batch scoring failed: {e}")
            return self._fallback_scores(query, candidates, analysis)
    
    def _build_scoring_prompt(
        self,
        query: str,
        candidates: List[SearchCandidate],
        analysis: QueryAnalysis
    ) -> str:
        """Build prompt for LLM to score candidates."""
        prompt = f"""Score the relevance of these search results to the user's query.
For each result, provide a score from 0-100 based on how well it matches the query intent and concepts.

Query: "{query}"
Intent: {analysis.intent}
Persona: {analysis.persona}
Key Concepts: {', '.join(analysis.concepts)}

Results to score:
"""
        
        for i, candidate in enumerate(candidates, 1):
            prompt += f"\n{i}. {candidate.name} ({candidate.entity_type})"
            if candidate.description:
                # Truncate long descriptions
                desc = candidate.description[:150]
                if len(candidate.description) > 150:
                    desc += "..."
                prompt += f"\n   Description: {desc}"
        
        prompt += "\n\nProvide scores as a JSON array: [score1, score2, score3, ...]"
        prompt += "\nConsider:"
        prompt += "\n- Exact concept matches = higher scores"
        prompt += "\n- Partial matches = moderate scores"
        prompt += "\n- Unrelated results = low scores"
        prompt += f"\n- {analysis.persona} perspective"
        
        return prompt
    
    def _parse_scores(self, response_text: str, expected_count: int) -> List[float]:
        """Parse scores from LLM response."""
        import json
        import re
        
        try:
            # Try to find JSON array in response
            json_match = re.search(r'\[[\d\s,\.]+\]', response_text)
            if json_match:
                scores = json.loads(json_match.group())
                
                # Validate and normalize scores
                scores = [float(s) for s in scores]
                scores = [max(0.0, min(100.0, s)) for s in scores]
                
                # Ensure we have the right number of scores
                if len(scores) == expected_count:
                    return scores
                elif len(scores) > expected_count:
                    return scores[:expected_count]
                else:
                    # Pad with default scores
                    while len(scores) < expected_count:
                        scores.append(50.0)
                    return scores
            
            # Fallback: try to extract numbers
            numbers = re.findall(r'\b\d+(?:\.\d+)?\b', response_text)
            if numbers:
                scores = [float(n) for n in numbers[:expected_count]]
                scores = [max(0.0, min(100.0, s)) for s in scores]
                
                # Pad if needed
                while len(scores) < expected_count:
                    scores.append(50.0)
                
                return scores[:expected_count]
            
        except Exception as e:
            logger.warning(f"[Result Ranker] Failed to parse scores: {e}")
        
        # Ultimate fallback: return default scores
        return [50.0] * expected_count
    
    def _apply_persona_boost(
        self,
        score: float,
        entity_type: str,
        persona: str
    ) -> float:
        """
        Apply persona-based score boosting.
        
        Boost percentages:
        - Executive: +20% for Capability/Vertical
        - Portfolio Manager: +20% for Capability/Process
        - Investment Analyst: +20% for Process/Subprocess
        - Technical User: +20% for Subprocess/DataEntity/DataElements
        """
        boost_factor = 1.0
        
        if persona == "Executive":
            if entity_type in ["capability", "vertical"]:
                boost_factor = 1.2
        
        elif persona == "Portfolio Manager":
            if entity_type in ["capability", "process"]:
                boost_factor = 1.2
        
        elif persona == "Investment Analyst":
            if entity_type in ["process", "subprocess"]:
                boost_factor = 1.2
        
        elif persona == "Technical User":
            if entity_type in ["subprocess", "data_entity", "data_element"]:
                boost_factor = 1.2
        
        boosted_score = min(100.0, score * boost_factor)
        
        return boosted_score
    
    def _filter_and_limit(
        self,
        ranked_results: List[RankedResult]
    ) -> List[RankedResult]:
        """
        Filter results by min_relevance_score and limit to max_results.
        """
        # Sort by score descending
        sorted_results = sorted(
            ranked_results,
            key=lambda r: r.relevance_score,
            reverse=True
        )
        
        # Filter by minimum score
        filtered = [
            r for r in sorted_results
            if r.relevance_score >= self.min_relevance_score
        ]
        
        # Limit to max results
        limited = filtered[:self.max_results]
        
        logger.info(
            f"[Result Ranker] Filtered {len(ranked_results)} -> "
            f"{len(filtered)} (score >= {self.min_relevance_score}) -> "
            f"{len(limited)} (top {self.max_results})"
        )
        
        return limited
    
    def _generate_ranking_reason(
        self,
        candidate: SearchCandidate,
        score: float,
        analysis: QueryAnalysis
    ) -> str:
        """Generate a brief explanation of why this result is relevant."""
        reasons = []
        
        # Check for concept matches in name
        name_lower = candidate.name.lower()
        for concept in analysis.concepts:
            if concept.lower() in name_lower:
                reasons.append(f"matches '{concept}'")
        
        # Check entity type alignment with focus levels
        if candidate.entity_type in analysis.focus_levels:
            reasons.append(f"{candidate.entity_type} level match")
        
        # Score-based reason
        if score >= 80:
            reasons.append("highly relevant")
        elif score >= 60:
            reasons.append("relevant")
        elif score >= 40:
            reasons.append("partially relevant")
        
        if reasons:
            return "; ".join(reasons)
        else:
            return "general match"
    
    def _fallback_scores(
        self,
        query: str,
        candidates: List[SearchCandidate],
        analysis: QueryAnalysis
    ) -> List[float]:
        """
        Fallback scoring using simple text similarity.
        """
        logger.warning("[Result Ranker] Using fallback scoring")
        
        query_lower = query.lower()
        concepts_lower = [c.lower() for c in analysis.concepts]
        
        scores = []
        for candidate in candidates:
            score = 0.0
            name_lower = candidate.name.lower()
            desc_lower = (candidate.description or "").lower()
            
            # Exact name match with query
            if query_lower in name_lower:
                score += 40
            
            # Concept matches in name
            for concept in concepts_lower:
                if concept in name_lower:
                    score += 20
            
            # Concept matches in description
            for concept in concepts_lower:
                if concept in desc_lower:
                    score += 10
            
            # Entity type in focus levels
            if candidate.entity_type in analysis.focus_levels:
                score += 15
            
            # Ensure score is in valid range
            score = max(0.0, min(100.0, score))
            scores.append(score)
        
        return scores
    
    def _fallback_ranking(
        self,
        query: str,
        candidates: List[SearchCandidate],
        analysis: QueryAnalysis
    ) -> List[RankedResult]:
        """
        Fallback ranking when LLM fails.
        """
        logger.warning("[Result Ranker] Using fallback ranking")
        
        scores = self._fallback_scores(query, candidates, analysis)
        
        # Apply persona boost
        boosted_scores = []
        for i, candidate in enumerate(candidates):
            boosted_score = self._apply_persona_boost(
                scores[i],
                candidate.entity_type,
                analysis.persona
            )
            boosted_scores.append(boosted_score)
        
        # Create ranked results
        ranked_results = []
        for i, candidate in enumerate(candidates):
            ranked_results.append(RankedResult(
                candidate=candidate,
                relevance_score=boosted_scores[i],
                ranking_reason=self._generate_ranking_reason(
                    candidate, boosted_scores[i], analysis
                )
            ))
        
        # Filter and limit
        return self._filter_and_limit(ranked_results)
