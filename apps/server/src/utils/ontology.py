
from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from lxml import etree
from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Files shipped alongside this module
# ---------------------------------------------------------------------------

DEFAULT_RDF_PATH = Path(__file__).parent / "FinancialContextAndProcess.rdf"
DEFAULT_FIBO_LOCAL_DIR = Path(__file__).parent / "fibo"


DEFAULT_SYNONYM_LEXICON_PATH: Optional[Path] = None

# ---------------------------------------------------------------------------
# Tunables — overridable via environment variables
# ---------------------------------------------------------------------------

ENV_RDF_PATH = "COMPASS_FIBO_RDF"
ENV_FIBO_LOCAL_DIR = "COMPASS_FIBO_LOCAL_DIR"
ENV_SYNONYM_LEXICON_PATH = "COMPASS_FIBO_SYNONYMS"
ENV_FOLLOW_IMPORTS = "COMPASS_FIBO_FOLLOW_IMPORTS"
ENV_THRESHOLD = "COMPASS_GUARDRAIL_THRESHOLD"
ENV_MAX_PROCESSES = "COMPASS_GUARDRAIL_MAX_PROCESSES"

# Document-level (pre-LLM) gate
ENV_DOC_THRESHOLD = "COMPASS_DOC_RELEVANCE_THRESHOLD"
ENV_CHUNK_THRESHOLD = "COMPASS_CHUNK_MATCH_THRESHOLD"
ENV_DOC_TOP_K = "COMPASS_DOC_TOP_K"

# Semantic (embedding) layer
ENV_SEMANTIC_ENABLED = "COMPASS_SEMANTIC_ENABLED"
ENV_SEMANTIC_TRUST = "COMPASS_SEMANTIC_TRUST"
ENV_SEMANTIC_FLOOR = "COMPASS_SEMANTIC_COSINE_FLOOR"
ENV_SEMANTIC_CEIL = "COMPASS_SEMANTIC_COSINE_CEIL"
ENV_ANCESTOR_DISCOUNT = "COMPASS_ANCESTOR_ROLLUP_DISCOUNT"

DEFAULT_THRESHOLD = float(os.getenv(ENV_THRESHOLD, "0.45"))
# Number of guardrail-accepted processes per document. Set to a generous
# default (10) so a single document can map to several FIBO concepts when
# its content genuinely covers multiple capability areas. Override with
# ``COMPASS_GUARDRAIL_MAX_PROCESSES`` (e.g. ``=1`` to restore the old
# single-process behaviour, ``=0`` is treated as "no extra cap").
DEFAULT_MAX_PROCESSES = int(os.getenv(ENV_MAX_PROCESSES, "10"))

DEFAULT_DOC_THRESHOLD = float(os.getenv(ENV_DOC_THRESHOLD, "0.45"))
DEFAULT_CHUNK_THRESHOLD = float(os.getenv(ENV_CHUNK_THRESHOLD, "0.35"))
DEFAULT_DOC_TOP_K = int(os.getenv(ENV_DOC_TOP_K, "5"))

 
DEFAULT_SEMANTIC_ENABLED = os.getenv(ENV_SEMANTIC_ENABLED, "1") not in ("0", "false", "False", "")
DEFAULT_SEMANTIC_TRUST = float(os.getenv(ENV_SEMANTIC_TRUST, "0.85"))
DEFAULT_SEMANTIC_FLOOR = float(os.getenv(ENV_SEMANTIC_FLOOR, "0.72"))
DEFAULT_SEMANTIC_CEIL = float(os.getenv(ENV_SEMANTIC_CEIL, "0.90"))
DEFAULT_ANCESTOR_DISCOUNT = float(os.getenv(ENV_ANCESTOR_DISCOUNT, "0.70"))
DEFAULT_FOLLOW_IMPORTS = os.getenv(ENV_FOLLOW_IMPORTS, "1") not in ("0", "false", "False", "")

# Stop-words removed during token-level matching so they cannot create
# spurious overlap between unrelated short labels (e.g. "and").
_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has",
        "have", "in", "into", "is", "it", "its", "of", "on", "or", "that",
        "the", "to", "via", "with", "within", "without",
    }
)
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z\-]+")


def _content_tokens(text: str, min_len: int = 3) -> List[str]:
    """Lower-cased content tokens (stop-words and very short tokens removed)."""
    if not text:
        return []
    return [
        tok.lower()
        for tok in _TOKEN_RE.findall(text)
        if tok.lower() not in _STOPWORDS and len(tok) >= min_len
    ]


def _token_set_overlap(needle_tokens: List[str], haystack_tokens: List[str]) -> float:
    """Fraction of *unique* needle tokens present in the haystack token set."""
    if not needle_tokens:
        return 0.0
    needle_set = set(needle_tokens)
    haystack_set = set(haystack_tokens)
    return len(needle_set & haystack_set) / len(needle_set)


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Plain cosine similarity (no numpy dependency)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / math.sqrt(na * nb)


def _normalise_cosine(cos: float, floor: float, ceil: float) -> float:
    """Map raw ada-002 cosine into the comparable ``[0, 1]`` band.

    Ada-002 has a high baseline similarity for any English text (random
    pairs sit around ``0.70-0.74``), so raw cosine isn't directly
    comparable to the lexical signal that lives in ``[0, 1]``. We linearly
    rescale ``[floor, ceil]`` → ``[0, 1]`` and clip outside that range.
    """
    if ceil <= floor:
        return 0.0
    if cos <= floor:
        return 0.0
    if cos >= ceil:
        return 1.0
    return (cos - floor) / (ceil - floor)


# XML namespaces used by FIBO RDF/XML.
# ``cmns-av`` is the OMG **Commons Annotation Vocabulary** which the
# production FIBO modules use heavily for ``synonym``, ``abbreviation``
# and ``explanatoryNote`` annotations. Picking these up is what closes
# the gap once a richer FIBO module is loaded.
_NS = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "owl": "http://www.w3.org/2002/07/owl#",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "dct": "http://purl.org/dc/terms/",
    "cmns-av": "https://www.omg.org/spec/Commons/AnnotationVocabulary/",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class OntologyConcept:
    """A single OWL class extracted from the FIBO ontology.

    Beyond the basic ``label`` / ``definition`` / ``parents`` triple we also
    track:

    * ``synonyms``         — combined ``skos:altLabel`` + ``skos:prefLabel``
      from the RDF and any curated entries from ``fibo_synonyms.json``.
    * ``ancestors``        — *transitive* sub-class closure restricted to
      concepts that are themselves part of the loaded ontology (used for
      Stage 1 ancestor roll-up and Stage 3 hierarchy validation).
    * ``disjoint_with``    — IRIs of concepts declared ``owl:disjointWith``
      this concept. Currently empty for the shipped FIBO module but the
      framework is wired so disjointness validation works the moment a
      richer module is dropped in.
    * ``restrictions``     — flattened ``owl:Restriction`` axioms attached
      to this class (``onProperty``, ``someValuesFrom``, ...). Recorded for
      traceability — not currently enforced by the validator.
    * ``surface_forms``    — pre-built lower-cased list ``[label, *synonyms]``
      used as the set of "needles" the lexical scorer searches for.
    """

    iri: str
    label: str
    definition: str = ""
    parents: List[str] = field(default_factory=list)
    source: str = "FIBO"
    # Which RDF module this concept was loaded from (relative path or
    # filename of the file containing its ``<owl:Class>`` declaration).
    # Useful for distinguishing concepts that came in via ``owl:imports``.
    source_module: str = ""

    # Pre-computed lower-cased content tokens for fast scoring
    label_tokens: List[str] = field(default_factory=list, repr=False)
    definition_tokens: List[str] = field(default_factory=list, repr=False)

    # Synonyms — union of FIBO RDF annotations (``skos:altLabel``,
    # ``skos:prefLabel``, ``cmns-av:synonym``, ``cmns-av:abbreviation``)
    # and any optional external lexicon the operator opts into.
    synonyms: List[str] = field(default_factory=list)
    synonyms_from_rdf: List[str] = field(default_factory=list, repr=False)
    synonyms_from_lexicon: List[str] = field(default_factory=list, repr=False)
    surface_forms: List[str] = field(default_factory=list, repr=False)
    surface_form_tokens: List[List[str]] = field(default_factory=list, repr=False)

    # OWL semantics
    ancestors: List[str] = field(default_factory=list)
    disjoint_with: List[str] = field(default_factory=list)
    restrictions: List[Dict[str, str]] = field(default_factory=list)

    # Pre-computed text used for embedding (label + definition + synonyms)
    embedding_text: str = field(default="", repr=False)

    @property
    def short_name(self) -> str:
        """Last URI path / fragment segment, used as a friendly identifier."""
        tail = self.iri.rsplit("/", 1)[-1]
        return tail.rsplit("#", 1)[-1]

    def all_label_tokens(self) -> Set[str]:
        """Union of label and synonym tokens — the *needle set* for scoring."""
        merged: Set[str] = set(self.label_tokens or [])
        for toks in self.surface_form_tokens or []:
            merged.update(toks)
        return merged

    def to_dict(self) -> Dict[str, Any]:
        return {
            "iri": self.iri,
            "short_name": self.short_name,
            "label": self.label,
            "definition": self.definition,
            "parents": list(self.parents),
            "ancestors": list(self.ancestors),
            "synonyms": list(self.synonyms),
            "synonyms_from_rdf": list(self.synonyms_from_rdf),
            "synonyms_from_lexicon": list(self.synonyms_from_lexicon),
            "disjoint_with": list(self.disjoint_with),
            "restrictions": list(self.restrictions),
            "source": self.source,
            "source_module": self.source_module,
        }


@dataclass
class ConceptHit:
    """One concept's strongest match against a document chunk.

    The ``breakdown`` dict is now nested into ``lexical`` / ``semantic`` /
    ``combined`` so callers can see exactly which signal carried the score
    (and the per-component sub-signals within each).
    """

    concept_iri: str
    concept_label: str
    concept_short_name: str
    concept_definition: str
    best_chunk_index: int
    best_chunk_score: float
    best_chunk_excerpt: str
    matching_chunk_count: int
    breakdown: Dict[str, Any]
    matched_via: str = "direct"           # "direct" | "ancestor_rollup"
    matched_synonym: Optional[str] = None
    ancestor_chain: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "concept_iri": self.concept_iri,
            "concept_label": self.concept_label,
            "concept_short_name": self.concept_short_name,
            "concept_definition": self.concept_definition,
            "best_chunk_index": self.best_chunk_index,
            "best_chunk_score": self.best_chunk_score,
            "best_chunk_excerpt": self.best_chunk_excerpt,
            "matching_chunk_count": self.matching_chunk_count,
            "breakdown": self.breakdown,
            "matched_via": self.matched_via,
            "matched_synonym": self.matched_synonym,
            "ancestor_chain": list(self.ancestor_chain),
        }


@dataclass
class DocumentRelevance:
    """Outcome of the pre-LLM document-vs-ontology gate."""

    is_relevant: bool
    aggregate_score: float
    top_concepts: List[ConceptHit]
    chunk_count: int
    chunk_threshold: float
    doc_threshold: float
    rejection_reason: Optional[str]
    ontology_meta: Dict[str, Any]
    semantic_used: bool = False
    coherence: Dict[str, Any] = field(default_factory=dict)

    def top_concept_iris(self) -> List[str]:
        return [c.concept_iri for c in self.top_concepts]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_relevant": self.is_relevant,
            "aggregate_score": self.aggregate_score,
            "top_concepts": [c.to_dict() for c in self.top_concepts],
            "chunk_count": self.chunk_count,
            "chunk_threshold": self.chunk_threshold,
            "doc_threshold": self.doc_threshold,
            "rejection_reason": self.rejection_reason,
            "ontology_meta": self.ontology_meta,
            "semantic_used": self.semantic_used,
            "coherence": self.coherence,
        }


@dataclass
class GuardrailMatch:
    """Per-process scoring + accept/reject outcome from the guardrail."""

    process_index: int
    process_name: str
    process_description: str
    best_concept_iri: Optional[str]
    best_concept_label: Optional[str]
    score: float
    breakdown: Dict[str, Any]
    accepted: bool
    reason: str
    # NEW — validation metadata
    ancestor_chain: List[str] = field(default_factory=list)
    matched_synonym: Optional[str] = None
    hierarchy_consistent: Optional[bool] = None
    disjointness_violations: List[str] = field(default_factory=list)
    validation_notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "process_index": self.process_index,
            "process_name": self.process_name,
            "process_description": self.process_description,
            "best_concept_iri": self.best_concept_iri,
            "best_concept_label": self.best_concept_label,
            "score": self.score,
            "breakdown": self.breakdown,
            "accepted": self.accepted,
            "reason": self.reason,
            "ancestor_chain": list(self.ancestor_chain),
            "matched_synonym": self.matched_synonym,
            "hierarchy_consistent": self.hierarchy_consistent,
            "disjointness_violations": list(self.disjointness_violations),
            "validation_notes": list(self.validation_notes),
        }


@dataclass
class GuardrailResult:
    """Aggregate outcome of running the guardrail over a list of processes."""

    threshold: float
    max_processes: int
    candidates: List[GuardrailMatch]
    accepted: List[GuardrailMatch]
    rejected: List[GuardrailMatch]
    ontology_meta: Dict[str, Any]
    semantic_used: bool = False
    document_top_concept_iris: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "threshold": self.threshold,
            "max_processes": self.max_processes,
            "candidates": [c.to_dict() for c in self.candidates],
            "accepted": [a.to_dict() for a in self.accepted],
            "rejected": [r.to_dict() for r in self.rejected],
            "ontology_meta": self.ontology_meta,
            "semantic_used": self.semantic_used,
            "document_top_concept_iris": list(self.document_top_concept_iris),
        }


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class FIBOOntologyService:
    """Loads the FIBO RDF file and exposes guardrail / Neo4j operations."""

    def __init__(
        self,
        rdf_path: Optional[str] = None,
        threshold: float = DEFAULT_THRESHOLD,
        max_processes: int = DEFAULT_MAX_PROCESSES,
        doc_threshold: float = DEFAULT_DOC_THRESHOLD,
        chunk_threshold: float = DEFAULT_CHUNK_THRESHOLD,
        doc_top_k: int = DEFAULT_DOC_TOP_K,
        synonym_lexicon_path: Optional[str] = None,
        fibo_local_dir: Optional[str] = None,
        follow_imports: bool = DEFAULT_FOLLOW_IMPORTS,
        semantic_enabled: bool = DEFAULT_SEMANTIC_ENABLED,
        semantic_trust: float = DEFAULT_SEMANTIC_TRUST,
        semantic_floor: float = DEFAULT_SEMANTIC_FLOOR,
        semantic_ceil: float = DEFAULT_SEMANTIC_CEIL,
        ancestor_discount: float = DEFAULT_ANCESTOR_DISCOUNT,
    ) -> None:
        self.rdf_path = Path(rdf_path) if rdf_path else DEFAULT_RDF_PATH
        # Curated lexicon: opt-in only. ``synonym_lexicon_path`` is taken
        # *only* from the explicit constructor argument or env var; the
        # module no longer ships a default JSON. ``Path("")`` evaluates
        # truthy, so we guard against that explicitly.
        self.synonym_lexicon_path: Optional[Path]
        if synonym_lexicon_path:
            self.synonym_lexicon_path = Path(synonym_lexicon_path)
        else:
            self.synonym_lexicon_path = DEFAULT_SYNONYM_LEXICON_PATH

        self.fibo_local_dir = (
            Path(fibo_local_dir) if fibo_local_dir else DEFAULT_FIBO_LOCAL_DIR
        )
        self.follow_imports = bool(follow_imports)

        self.threshold = float(threshold)
        self.max_processes = int(max_processes)
        self.doc_threshold = float(doc_threshold)
        self.chunk_threshold = float(chunk_threshold)
        self.doc_top_k = int(doc_top_k)

        # Semantic layer config
        self.semantic_enabled = bool(semantic_enabled)
        self.semantic_trust = float(semantic_trust)
        self.semantic_floor = float(semantic_floor)
        self.semantic_ceil = float(semantic_ceil)
        self.ancestor_discount = float(ancestor_discount)

        self.concepts: Dict[str, OntologyConcept] = {}
        self.ontology_iri: str = ""
        self.ontology_label: str = ""
        self.ontology_abstract: str = ""
        self.loaded_at: Optional[str] = None

        # Module / import bookkeeping. ``modules_loaded`` is the ordered
        # list of RDF files the parser actually parsed; ``imports_*``
        # describe the resolution outcome of every ``owl:imports`` edge
        # encountered (resolved → loaded, unresolved → skipped).
        self.modules_loaded: List[Dict[str, Any]] = []
        self.imports_resolved: List[Dict[str, str]] = []
        self.imports_unresolved: List[Dict[str, str]] = []

        # Lazy embedding cache: iri -> List[float]
        self._concept_vectors: Dict[str, List[float]] = {}
        self._concept_vectors_ready: bool = False
        self._semantic_disabled_reason: Optional[str] = None
        self._embedding_lock = threading.Lock()
        self._curated_synonyms: Dict[str, List[str]] = {}
        self._loaded_paths: Set[str] = set()  # for cycle detection

        self._load()

    # ------------------------------------------------------------------ load

    def _load(self) -> None:
        """Top-level loader: parse the entry RDF and recurse into imports.

        Pipeline:

        1. Optional curated lexicon read once up front (opt-in only).
        2. Parse the entry RDF — extracts ontology metadata, classes,
           and queues any ``owl:imports`` for resolution.
        3. Resolve imports against ``fibo_local_dir``. Each resolved
           import is parsed by the same ``_load_module`` so its
           classes are merged into ``self.concepts``. Unresolved
           imports are recorded with a clear advisory message.
        4. Compute the transitive sub-class closure across **all**
           merged concepts.
        """
        if not self.rdf_path.exists():
            raise FileNotFoundError(f"FIBO RDF file not found: {self.rdf_path}")

        self._curated_synonyms = self._load_curated_synonyms()

        self._load_module(self.rdf_path, is_entry=True)

        self._compute_ancestor_closure()

        self.loaded_at = datetime.utcnow().isoformat() + "Z"

        synonym_rdf_total = sum(len(c.synonyms_from_rdf) for c in self.concepts.values())
        synonym_lex_total = sum(len(c.synonyms_from_lexicon) for c in self.concepts.values())
        logger.info(
            "Loaded FIBO ontology '%s' (%d concepts across %d modules, "
            "%d synonyms from RDF + %d from lexicon, %d imports resolved, "
            "%d unresolved, semantic_enabled=%s)",
            self.ontology_label or self.ontology_iri,
            len(self.concepts),
            len(self.modules_loaded),
            synonym_rdf_total,
            synonym_lex_total,
            len(self.imports_resolved),
            len(self.imports_unresolved),
            self.semantic_enabled,
        )

        if self.imports_unresolved:
            logger.warning(
                "[Ontology] %d FIBO import(s) declared but not resolved locally. "
                "To enable them, drop the matching .rdf files into %s using the "
                "FIBO release directory layout (FBC/FinancialInstruments/"
                "FinancialInstruments.rdf, etc.). Unresolved imports: %s",
                len(self.imports_unresolved),
                self.fibo_local_dir,
                ", ".join(u["iri"] for u in self.imports_unresolved),
            )

        if synonym_rdf_total == 0 and not self.synonym_lexicon_path:
            logger.warning(
                "[Ontology] FIBO module '%s' declared 0 synonyms (no skos:altLabel, "
                "skos:prefLabel, cmns-av:synonym, or cmns-av:abbreviation). "
                "Lexical recall will rely on labels + definitions only; semantic "
                "(embedding) recall is unaffected. Drop a richer FIBO module into "
                "%s, or use a richer FIBO release, to enrich synonym coverage.",
                self.rdf_path.name,
                self.fibo_local_dir,
            )

    def _load_module(self, rdf_path: Path, *, is_entry: bool = False) -> None:
        """Parse one RDF file and merge its concepts into the catalog.

        Imports declared inside this module are queued for resolution and
        recursively loaded after the local classes are parsed. Cycle
        detection uses the resolved file path.
        """
        resolved = str(rdf_path.resolve())
        if resolved in self._loaded_paths:
            logger.debug("[Ontology] Skipping already-loaded module: %s", rdf_path)
            return
        self._loaded_paths.add(resolved)

        # ``load_dtd`` + ``resolve_entities`` are required because FIBO RDF
        # files use entity references declared in their inline DOCTYPE
        # (e.g. ``&fibo-bp-prc-fcp;Clearing``) that must be expanded.
        parser = etree.XMLParser(load_dtd=True, resolve_entities=True, no_network=True)
        try:
            tree = etree.parse(str(rdf_path), parser)
        except etree.XMLSyntaxError as exc:
            raise ValueError(f"Failed to parse FIBO RDF '{rdf_path}': {exc}") from exc

        root = tree.getroot()

        module_iri = ""
        module_label = ""
        module_imports: List[str] = []

        ontology = root.find("owl:Ontology", _NS)
        if ontology is not None:
            module_iri = ontology.get(f"{{{_NS['rdf']}}}about", "") or ""
            label_el = ontology.find("rdfs:label", _NS)
            if label_el is not None and label_el.text:
                module_label = label_el.text.strip()
                if is_entry:
                    self.ontology_label = module_label
            abstract_el = ontology.find("dct:abstract", _NS)
            if is_entry and abstract_el is not None and abstract_el.text:
                self.ontology_abstract = abstract_el.text.strip()
            if is_entry:
                self.ontology_iri = module_iri
            for imp_el in ontology.findall("owl:imports", _NS):
                imp_iri = imp_el.get(f"{{{_NS['rdf']}}}resource")
                if imp_iri:
                    module_imports.append(imp_iri)

        # Module identifier used to tag every concept declared in this RDF.
        try:
            source_module = str(rdf_path.relative_to(self.fibo_local_dir.parent))
        except (ValueError, OSError):
            source_module = rdf_path.name

        classes_added = 0
        for cls in root.findall("owl:Class", _NS):
            iri = cls.get(f"{{{_NS['rdf']}}}about")
            if not iri:
                continue

            # If a richer module redeclares a concept already loaded, keep
            # the first definition (entry RDF wins, then imports in order).
            # We still let later modules contribute *additional synonyms*
            # below if needed — but for this v1 we simply skip.
            if iri in self.concepts:
                continue

            self.concepts[iri] = self._build_concept_from_xml(
                cls, iri, source_module=source_module
            )
            classes_added += 1

        self.modules_loaded.append(
            {
                "path": str(rdf_path),
                "module_iri": module_iri,
                "module_label": module_label,
                "is_entry": is_entry,
                "classes_added": classes_added,
                "imports_declared": list(module_imports),
            }
        )

        # Recurse into imports.
        if self.follow_imports:
            for imp_iri in module_imports:
                self._resolve_and_load_import(imp_iri, importer_path=rdf_path)

    def _build_concept_from_xml(
        self,
        cls: "etree._Element",
        iri: str,
        source_module: str,
    ) -> OntologyConcept:
        """Turn one ``<owl:Class>`` element into an ``OntologyConcept``.

        Pulls the full set of FIBO annotations:

          * ``rdfs:label``               → primary label
          * ``skos:definition``          → definition (with optional
                                            ``cmns-av:explanatoryNote``
                                            appended)
          * ``skos:altLabel`` /
            ``skos:prefLabel``           → synonyms
          * ``cmns-av:synonym``          → synonyms
          * ``cmns-av:abbreviation``     → synonyms (acronym entries)
          * ``rdfs:subClassOf``          → parents (resource form) and
                                            inline ``owl:Restriction``
                                            axioms (axiom form)
          * ``owl:disjointWith``         → disjointness edges
        """
        label_el = cls.find("rdfs:label", _NS)
        label = (label_el.text or "").strip() if label_el is not None else ""

        def_el = cls.find("skos:definition", _NS)
        definition = (def_el.text or "").strip() if def_el is not None else ""

        # Append any explanatoryNote so the embedding picks it up. We keep
        # the SKOS definition as-is on the concept (single source of truth
        # for users) and concatenate explanatoryNote into the embedding
        # text only.
        explanatory_notes: List[str] = []
        for ex_el in cls.findall("cmns-av:explanatoryNote", _NS):
            if ex_el is not None and ex_el.text:
                txt = ex_el.text.strip()
                if txt:
                    explanatory_notes.append(txt)

        parents: List[str] = []
        restrictions: List[Dict[str, str]] = []
        for sub in cls.findall("rdfs:subClassOf", _NS):
            resource = sub.get(f"{{{_NS['rdf']}}}resource")
            if resource:
                parents.append(resource)
                continue
            restr_el = sub.find("owl:Restriction", _NS)
            if restr_el is not None:
                flat: Dict[str, str] = {"type": "Restriction"}
                on_prop = restr_el.find("owl:onProperty", _NS)
                if on_prop is not None:
                    on_prop_res = on_prop.get(f"{{{_NS['rdf']}}}resource")
                    if on_prop_res:
                        flat["onProperty"] = on_prop_res
                for axiom_tag in (
                    "someValuesFrom",
                    "allValuesFrom",
                    "hasValue",
                    "onClass",
                ):
                    ax_el = restr_el.find(f"owl:{axiom_tag}", _NS)
                    if ax_el is not None:
                        ax_res = ax_el.get(f"{{{_NS['rdf']}}}resource")
                        if ax_res:
                            flat[axiom_tag] = ax_res
                restrictions.append(flat)

        # Synonyms — pull from every annotation FIBO uses.
        rdf_synonyms: List[str] = []
        for ns_tag in (
            "skos:altLabel",
            "skos:prefLabel",
            "cmns-av:synonym",
            "cmns-av:abbreviation",
        ):
            for syn_el in cls.findall(ns_tag, _NS):
                if syn_el.text:
                    text = syn_el.text.strip()
                    if text:
                        rdf_synonyms.append(text)

        # owl:disjointWith
        disjoint: List[str] = []
        for dj_el in cls.findall("owl:disjointWith", _NS):
            dj_res = dj_el.get(f"{{{_NS['rdf']}}}resource")
            if dj_res:
                disjoint.append(dj_res)

        effective_label = label or iri.rsplit("/", 1)[-1]
        short_name = iri.rsplit("/", 1)[-1].rsplit("#", 1)[-1]

        curated = self._curated_synonyms.get(short_name, [])

        # De-duplicate, preserve order, drop anything that exactly matches
        # the primary label. Track RDF and lexicon contributions
        # separately so logs and metadata can attribute each synonym
        # to its source.
        seen_lc: Set[str] = {effective_label.lower()}
        rdf_clean: List[str] = []
        for syn in rdf_synonyms:
            key = syn.lower()
            if not key or key in seen_lc:
                continue
            seen_lc.add(key)
            rdf_clean.append(syn)
        lexicon_clean: List[str] = []
        for syn in curated:
            key = syn.lower()
            if not key or key in seen_lc:
                continue
            seen_lc.add(key)
            lexicon_clean.append(syn)

        merged_synonyms = [*rdf_clean, *lexicon_clean]
        surface_forms = [effective_label, *merged_synonyms]
        surface_form_tokens = [_content_tokens(sf) for sf in surface_forms]

        # Embedding text: label + definition + explanatoryNotes + synonyms
        full_definition = definition
        if explanatory_notes:
            full_definition = (
                full_definition + " " + " ".join(explanatory_notes)
            ).strip()
        embedding_text = self._build_embedding_text(
            effective_label, full_definition, merged_synonyms
        )

        return OntologyConcept(
            iri=iri,
            label=effective_label,
            definition=definition,
            parents=parents,
            source_module=source_module,
            label_tokens=_content_tokens(effective_label),
            definition_tokens=_content_tokens(full_definition),
            synonyms=merged_synonyms,
            synonyms_from_rdf=rdf_clean,
            synonyms_from_lexicon=lexicon_clean,
            surface_forms=surface_forms,
            surface_form_tokens=surface_form_tokens,
            disjoint_with=disjoint,
            restrictions=restrictions,
            embedding_text=embedding_text,
        )

    def _resolve_and_load_import(self, imp_iri: str, importer_path: Path) -> None:
        """Try to resolve a FIBO ``owl:imports`` IRI to a local RDF file.

        FIBO and OMG IRIs follow a stable directory layout, e.g.

          ``https://spec.edmcouncil.org/fibo/ontology/FBC/FinancialInstruments/FinancialInstruments/``
            → ``<fibo_local_dir>/FBC/FinancialInstruments/FinancialInstruments.rdf``

          ``https://www.omg.org/spec/Commons/AnnotationVocabulary/``
            → ``<fibo_local_dir>/Commons/AnnotationVocabulary.rdf``

        The resolver also falls back to a flat search by basename, so
        users who don't want to mirror the directory layout can drop
        files alongside the entry RDF.
        """
        candidates = self._candidate_paths_for_iri(imp_iri, importer_path)
        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                self.imports_resolved.append(
                    {"iri": imp_iri, "path": str(candidate)}
                )
                self._load_module(candidate, is_entry=False)
                return

        self.imports_unresolved.append(
            {
                "iri": imp_iri,
                "tried_paths": "; ".join(str(c) for c in candidates),
            }
        )

    def _candidate_paths_for_iri(
        self, imp_iri: str, importer_path: Path
    ) -> List[Path]:
        """Generate the local paths the resolver should try for an import IRI."""
        # Strip well-known prefixes to recover the relative path.
        stripped: Optional[str] = None
        for prefix in (
            "https://spec.edmcouncil.org/fibo/ontology/",
            "http://spec.edmcouncil.org/fibo/ontology/",
            "https://www.omg.org/spec/",
            "http://www.omg.org/spec/",
        ):
            if imp_iri.startswith(prefix):
                stripped = imp_iri[len(prefix):]
                break
        if stripped is None:
            # Generic fallback: take the last two path segments.
            parts = [p for p in imp_iri.rstrip("/").split("/") if p]
            stripped = "/".join(parts[-2:]) if len(parts) >= 2 else (parts[-1] if parts else "")
        stripped = stripped.rstrip("/")
        if not stripped:
            return []

        candidates: List[Path] = []
        # 1. Mirrored layout under the FIBO local dir.
        candidates.append(self.fibo_local_dir / f"{stripped}.rdf")
        candidates.append(self.fibo_local_dir / stripped / f"{Path(stripped).name}.rdf")
        # 2. Flat layout under the FIBO local dir, by basename.
        basename = Path(stripped).name
        candidates.append(self.fibo_local_dir / f"{basename}.rdf")
        # 3. Beside the importer file (handy for ad-hoc setups).
        candidates.append(importer_path.parent / f"{basename}.rdf")
        # De-duplicate while preserving order.
        seen: Set[str] = set()
        unique: List[Path] = []
        for c in candidates:
            key = str(c)
            if key in seen:
                continue
            seen.add(key)
            unique.append(c)
        return unique

    @staticmethod
    def _build_embedding_text(label: str, definition: str, synonyms: List[str]) -> str:
        """Compose the text we'll embed for each concept.

        Putting label + definition + ``Aliases:`` synonyms in one string
        lets a single ada-002 vector capture the concept *and* its synonym
        cloud simultaneously, so a chunk that uses any synonym surfaces a
        higher cosine without needing per-synonym embeddings.
        """
        parts: List[str] = []
        if label:
            parts.append(label.strip())
        if definition:
            parts.append(definition.strip())
        if synonyms:
            parts.append("Aliases: " + "; ".join(s.strip() for s in synonyms if s.strip()))
        return ". ".join(p for p in parts if p)

    def _load_curated_synonyms(self) -> Dict[str, List[str]]:
        """Read an *opt-in* synonym JSON, returning ``{short_name: [syn, ...]}``.

        The system is FIBO-driven by default — no synonym JSON is auto-loaded
        from disk. To opt into a manual lexicon override, point the
        ``COMPASS_FIBO_SYNONYMS`` env var (or ``synonym_lexicon_path``
        constructor arg) at a JSON file with shape
        ``{"synonyms": {"ConceptShortName": ["alt one", "alt two"], ...}}``.

        A non-existent or malformed file is tolerated: we log and continue
        with an empty lexicon, so all synonyms come from the FIBO RDF.
        """
        path = self.synonym_lexicon_path
        if path is None:
            logger.info(
                "[Ontology] FIBO-only mode: no external synonym lexicon configured "
                "(COMPASS_FIBO_SYNONYMS unset). All synonyms will come from the RDF "
                "(skos:altLabel, skos:prefLabel, cmns-av:synonym, cmns-av:abbreviation)."
            )
            return {}
        if not Path(path).exists():
            logger.warning(
                "[Ontology] Configured synonym lexicon not found at %s — "
                "continuing in FIBO-only mode (no external synonyms applied).",
                path,
            )
            return {}
        try:
            with Path(path).open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:
            logger.warning("[Ontology] Failed to load synonym lexicon %s: %s", path, exc)
            return {}

        raw = data.get("synonyms") if isinstance(data, dict) else None
        if not isinstance(raw, dict):
            logger.warning(
                "[Ontology] Synonym lexicon %s missing top-level 'synonyms' object",
                path,
            )
            return {}

        cleaned: Dict[str, List[str]] = {}
        for key, value in raw.items():
            if not isinstance(value, list):
                continue
            cleaned[str(key)] = [str(v).strip() for v in value if str(v).strip()]
        logger.warning(
            "[Ontology] External synonym lexicon active (NOT pure FIBO): %d concepts, "
            "%d synonyms loaded from %s. Unset COMPASS_FIBO_SYNONYMS to return to "
            "FIBO-only mode.",
            len(cleaned),
            sum(len(v) for v in cleaned.values()),
            path,
        )
        return cleaned

    def _compute_ancestor_closure(self) -> None:
        """Populate ``concept.ancestors`` with the transitive sub-class set."""

        def walk(iri: str, seen: Set[str]) -> List[str]:
            concept = self.concepts.get(iri)
            if not concept:
                return []
            chain: List[str] = []
            for parent_iri in concept.parents:
                if parent_iri in seen or parent_iri not in self.concepts:
                    continue
                seen.add(parent_iri)
                chain.append(parent_iri)
                chain.extend(walk(parent_iri, seen))
            return chain

        for iri, concept in self.concepts.items():
            concept.ancestors = walk(iri, {iri})

    # -------------------------------------------------------------- metadata

    def metadata(self) -> Dict[str, Any]:
        """Lightweight ontology descriptor suitable for embedding in logs."""
        synonym_rdf_total = sum(len(c.synonyms_from_rdf) for c in self.concepts.values())
        synonym_lex_total = sum(len(c.synonyms_from_lexicon) for c in self.concepts.values())
        disjoint_total = sum(len(c.disjoint_with) for c in self.concepts.values())
        restriction_total = sum(len(c.restrictions) for c in self.concepts.values())

        # Per-module concept counts so the operator can see which RDF
        # contributed how many concepts (entry vs each import).
        per_module: Dict[str, int] = {}
        for c in self.concepts.values():
            per_module[c.source_module] = per_module.get(c.source_module, 0) + 1

        synonym_mode = (
            "fibo_only"
            if self.synonym_lexicon_path is None or synonym_lex_total == 0
            else "fibo_plus_external_lexicon"
        )

        return {
            "ontology_iri": self.ontology_iri,
            "ontology_label": self.ontology_label,
            "ontology_abstract": self.ontology_abstract,
            "rdf_file": self.rdf_path.name,
            "rdf_path": str(self.rdf_path),
            "fibo_local_dir": str(self.fibo_local_dir),
            "follow_imports": self.follow_imports,
            "synonym_lexicon": str(self.synonym_lexicon_path)
            if self.synonym_lexicon_path
            else None,
            "synonym_mode": synonym_mode,
            "concept_count": len(self.concepts),
            "concept_count_per_module": per_module,
            "modules_loaded": list(self.modules_loaded),
            "imports_resolved": list(self.imports_resolved),
            "imports_unresolved": list(self.imports_unresolved),
            "synonym_count_from_rdf": synonym_rdf_total,
            "synonym_count_from_lexicon": synonym_lex_total,
            "synonym_count": synonym_rdf_total + synonym_lex_total,
            "disjointness_axiom_count": disjoint_total,
            "restriction_axiom_count": restriction_total,
            "loaded_at": self.loaded_at,
            "threshold": self.threshold,
            "max_processes": self.max_processes,
            "doc_threshold": self.doc_threshold,
            "chunk_threshold": self.chunk_threshold,
            "doc_top_k": self.doc_top_k,
            "semantic": {
                "enabled": self.semantic_enabled,
                "ready": self._concept_vectors_ready,
                "trust": self.semantic_trust,
                "cosine_floor": self.semantic_floor,
                "cosine_ceil": self.semantic_ceil,
                "disabled_reason": self._semantic_disabled_reason,
            },
            "ancestor_rollup_discount": self.ancestor_discount,
            "source": "FIBO",
        }

    def get_concepts(self) -> List[Dict[str, Any]]:
        return [c.to_dict() for c in self.concepts.values()]

    # ---------------------------------------------------------------- scorer

    # ---------------- lexical signal (synonym-aware) ----------------

    @staticmethod
    def _lexical_score(
        text: str, concept: OntologyConcept
    ) -> Tuple[float, Dict[str, Any]]:
        """Synonym-aware lexical score for ``text`` against ``concept``.

        Each of the concept's *surface forms* (label + every synonym) is
        independently treated as a needle, and we keep the strongest signal
        across all of them. This means a chunk that says *"asset
        allocation"* still scores highly against ``Portfolio Management``
        because ``asset allocation`` is one of that concept's curated
        synonyms — without it we'd see zero token overlap.

        Per-needle components:

          * ``label_overlap``      — fraction of the needle's content tokens
            present in the text.
          * ``substring``          — *graded* signal in ``[0, 0.85]`` based on
            (a) whether the full needle string appears verbatim, (b) how
            many times it appears (cap of 3), and (c) how many words the
            needle has (multi-word phrases are more discriminating than
            single tokens). A single passing reference therefore can no
            longer saturate the score on its own — definition overlap is
            required to push the chunk to 1.0.
          * ``partial_ratio``      — RapidFuzz ``partial_ratio(needle, text)``
            in ``[0, 1]``.
          * ``definition_overlap`` — fraction of the concept's definition
            tokens present in the text (computed once per concept).

        Per-needle aggregation uses a noise-suppressed
        ``max``-of-strongest-signal + small additive definition boost.
        We then take the **max across all needles** as the final lexical
        score for the concept.
        """
        text_lower = (text or "").lower()
        if not text_lower or not concept.surface_forms:
            return 0.0, {
                "label_overlap": 0.0,
                "substring": 0.0,
                "partial_ratio": 0.0,
                "definition_overlap": 0.0,
                "matched_surface_form": None,
            }

        text_tokens = _content_tokens(text_lower)
        def_tokens = concept.definition_tokens
        def_overlap = _token_set_overlap(def_tokens, text_tokens) if def_tokens else 0.0

        best_final = 0.0
        best_breakdown: Dict[str, Any] = {
            "label_overlap": 0.0,
            "substring": 0.0,
            "partial_ratio": 0.0,
            "definition_overlap": round(def_overlap, 4),
            "matched_surface_form": None,
        }

        for surface, surface_tokens in zip(
            concept.surface_forms, concept.surface_form_tokens
        ):
            needle = (surface or "").lower().strip()
            if not needle:
                continue

            # If the surface form has no content tokens (e.g. a single
            # stop-word), fall back to the full needle as a single token so
            # we still get a meaningful overlap measurement.
            n_tokens = surface_tokens or _content_tokens(needle) or [needle]
            label_overlap = _token_set_overlap(n_tokens, text_tokens)

            # Graded substring signal — a single occurrence of a concept
            # name (e.g. "portfolio management") in a paragraph is weak
            # evidence that the *document* is about that concept; it could
            # easily be a passing reference. We grade the signal by
            # frequency (capped at 3 occurrences) and by how many words
            # the needle has, and we cap the substring contribution at
            # 0.85 so definition-token overlap is required to push the
            # final score to 1.0.
            occurrences = text_lower.count(needle) if needle else 0
            if occurrences == 0:
                substring = 0.0
            else:
                # Anchor at 0.50 for first occurrence, +0.10 per extra
                # match up to 3 (=> 0.50, 0.60, 0.70).
                freq_score = 0.50 + 0.10 * min(occurrences - 1, 2)
                # Multi-word phrases are more discriminating — bump them.
                phrase_bonus = 0.15 if len(n_tokens) >= 2 else 0.0
                substring = min(freq_score + phrase_bonus, 0.85)
            partial = fuzz.partial_ratio(needle, text_lower) / 100.0

            has_label_token_hit = label_overlap > 0.0
            has_typo_match = partial >= 0.85
            has_substring = substring > 0.0

            if not (has_label_token_hit or has_substring or has_typo_match):
                continue

            base = max(
                substring,
                label_overlap,
                partial * 0.85 if has_label_token_hit else 0.0,
                partial if has_typo_match else 0.0,
            )
            final = base + 0.20 * def_overlap
            final = max(0.0, min(1.0, final))

            if final > best_final:
                best_final = final
                best_breakdown = {
                    "label_overlap": round(label_overlap, 4),
                    "substring": round(substring, 4),
                    "substring_occurrences": occurrences,
                    "needle_word_count": len(n_tokens),
                    "partial_ratio": round(partial, 4),
                    "definition_overlap": round(def_overlap, 4),
                    "matched_surface_form": surface,
                }

        return round(best_final, 4), best_breakdown

    # ---------------- semantic signal (embeddings) ----------------

    def _ensure_concept_embeddings(self) -> bool:
        """Lazily compute one embedding per concept. Returns True on success.

        Failure (Azure unavailable, key vault down, etc.) flips
        ``self._semantic_disabled_reason`` and returns ``False``. The rest
        of the pipeline then transparently falls back to lexical-only
        scoring, so an embedding outage never blocks ingestion.
        """
        if not self.semantic_enabled:
            return False
        if self._concept_vectors_ready:
            return True
        if self._semantic_disabled_reason is not None:
            return False

        with self._embedding_lock:
            if self._concept_vectors_ready:
                return True
            if self._semantic_disabled_reason is not None:
                return False

            try:
                # Imported lazily so this module stays importable in
                # environments where Azure clients aren't initialised
                # (e.g. unit tests, CLI tooling).
                from config.azure_clients import get_azure_embedding_client

                client = get_azure_embedding_client()
            except Exception as exc:
                self._semantic_disabled_reason = f"client_unavailable: {exc}"
                logger.warning(
                    "[Ontology] Semantic scoring disabled — embedding client "
                    "unavailable: %s",
                    exc,
                )
                return False

            iris = list(self.concepts.keys())
            texts = [self.concepts[i].embedding_text for i in iris]
            try:
                resp = client.embeddings.create(
                    model="text-embedding-ada-002",
                    input=texts,
                )
                vectors = [d.embedding for d in resp.data]
            except Exception as exc:
                self._semantic_disabled_reason = f"embedding_call_failed: {exc}"
                logger.warning(
                    "[Ontology] Semantic scoring disabled — embedding call "
                    "failed: %s",
                    exc,
                )
                return False

            for iri, vec in zip(iris, vectors):
                self._concept_vectors[iri] = vec
            self._concept_vectors_ready = True
            logger.info(
                "[Ontology] Computed concept embeddings: %d vectors of "
                "dim=%d (model=text-embedding-ada-002)",
                len(vectors),
                len(vectors[0]) if vectors else 0,
            )
            return True

    def _embed_texts(self, texts: List[str]) -> Optional[List[List[float]]]:
        """Embed an arbitrary list of strings. Returns ``None`` on failure."""
        if not texts or not self.semantic_enabled:
            return None
        if not self._ensure_concept_embeddings():
            return None
        try:
            from config.azure_clients import get_azure_embedding_client

            client = get_azure_embedding_client()
            # The embeddings endpoint can fail on empty strings; replace
            # them with a single space to keep the batch shape stable.
            safe_inputs = [(t if (t or "").strip() else " ") for t in texts]
            resp = client.embeddings.create(
                model="text-embedding-ada-002",
                input=safe_inputs,
            )
            return [d.embedding for d in resp.data]
        except Exception as exc:
            logger.warning(
                "[Ontology] Inline embedding call failed (%s) — falling back "
                "to lexical-only for this batch",
                exc,
            )
            return None

    def _semantic_score(
        self,
        text_vector: Optional[Sequence[float]],
        concept: OntologyConcept,
    ) -> Tuple[float, Dict[str, float]]:
        """Map ``cosine(text_vector, concept_vector)`` into ``[0, 1]``."""
        if text_vector is None:
            return 0.0, {"cosine": 0.0, "normalised": 0.0, "available": 0.0}
        cv = self._concept_vectors.get(concept.iri)
        if cv is None:
            return 0.0, {"cosine": 0.0, "normalised": 0.0, "available": 0.0}
        cos = _cosine(text_vector, cv)
        norm = _normalise_cosine(cos, self.semantic_floor, self.semantic_ceil)
        return round(norm, 4), {
            "cosine": round(cos, 4),
            "normalised": round(norm, 4),
            "floor": self.semantic_floor,
            "ceil": self.semantic_ceil,
            "available": 1.0,
        }

    # ---------------- fused scorer ----------------

    def _combine_scores(
        self,
        lexical: float,
        semantic: float,
    ) -> Tuple[float, Dict[str, float]]:
        """Fuse lexical and semantic into one ``[0, 1]`` score.

        Ontology guardrail is meant to capture *meaning*, not surface
        keyword overlap, so we don't take ``max(lexical, semantic*trust)``
        any more — a strong lexical match would otherwise win even when
        the embedding actively disagrees ("the chunk mentions the
        concept's name in passing but is talking about something else").

        Instead, when the semantic signal is available we use it as a
        *confidence gate* on the lexical signal:

          * ``confidence`` rises with semantic agreement, from ``0.4``
            (embedding sees no semantic similarity) to ``1.0`` (embedding
            fully agrees). A passing keyword reference therefore gets its
            lexical score multiplied by ``0.4`` and falls below the
            threshold, while a chunk that's genuinely about the concept
            keeps full lexical credit.
          * The semantic-only arm (``weighted_semantic``) is preserved as
            an alternative path so synonym / paraphrase matches that
            score zero on lexical can still drive acceptance through the
            embedding alone.

        When the semantic layer is disabled or its embeddings haven't
        been initialised, we fall back to the old lexical-only behaviour
        so the rest of the pipeline keeps working in degraded mode.
        """
        weighted_semantic = semantic * self.semantic_trust if self.semantic_enabled else 0.0
        sem_active = self.semantic_enabled and self._concept_vectors_ready

        if sem_active:
            confidence = 0.4 + 0.6 * max(0.0, min(semantic, 1.0))
            gated_lexical = lexical * confidence
            combined = max(gated_lexical, weighted_semantic)
        else:
            confidence = 1.0
            gated_lexical = lexical
            combined = lexical

        combined = max(0.0, min(combined, 1.0))
        return round(combined, 4), {
            "lexical": round(lexical, 4),
            "semantic_normalised": round(semantic, 4),
            "semantic_weighted": round(weighted_semantic, 4),
            "trust": self.semantic_trust,
            "lexical_confidence": round(confidence, 4),
            "lexical_gated": round(gated_lexical, 4),
            "semantic_active": 1.0 if sem_active else 0.0,
            "final": round(combined, 4),
        }

    def _score(
        self,
        text: str,
        concept: OntologyConcept,
        text_vector: Optional[Sequence[float]] = None,
    ) -> Tuple[float, Dict[str, Any]]:
        """Public scoring primitive: returns ``(combined_score, breakdown)``.

        ``breakdown`` is now a nested dict::

            {
              "lexical":  { label_overlap, substring, partial_ratio,
                            definition_overlap, matched_surface_form },
              "semantic": { cosine, normalised, floor, ceil, available },
              "combined": { lexical, semantic_normalised,
                            semantic_weighted, trust, final },
            }
        """
        lex_score, lex_breakdown = self._lexical_score(text, concept)
        sem_score, sem_breakdown = self._semantic_score(text_vector, concept)
        combined, combo_breakdown = self._combine_scores(lex_score, sem_score)
        return combined, {
            "lexical": lex_breakdown,
            "semantic": sem_breakdown,
            "combined": combo_breakdown,
        }

    def find_best_match(
        self,
        name: str,
        description: str = "",
        context: str = "",
    ) -> Tuple[Optional[OntologyConcept], float, Dict[str, Any]]:
        """Return the highest-scoring concept for the given process text.

        ``context`` is optional surrounding text (e.g. the parent capability's
        name) that will be folded into the candidate text used for scoring.
        This lets a process inherit its capability's theme — so a process
        named *"Close-Out and Auction Management"* inside a capability
        *"Securities Clearing and Settlement"* picks up the *settlement*
        token and is scored against the right FIBO concept.
        """
        candidate_text = " ".join(
            part for part in (context, name, description) if part
        ).strip()

        # Best-effort embedding for the candidate; falls back to lexical-only
        # if Azure is unavailable.
        text_vector: Optional[List[float]] = None
        if candidate_text and self.semantic_enabled:
            embeds = self._embed_texts([candidate_text])
            if embeds:
                text_vector = embeds[0]

        best: Optional[OntologyConcept] = None
        best_score = 0.0
        best_breakdown: Dict[str, Any] = {}

        for concept in self.concepts.values():
            score, breakdown = self._score(candidate_text, concept, text_vector)
            if score > best_score:
                best, best_score, best_breakdown = concept, score, breakdown

        return best, round(best_score, 4), best_breakdown

    # ------------------------------------------------------ document gate

    def score_document(
        self,
        chunks: List[Dict[str, Any]],
        top_k: Optional[int] = None,
        chunk_threshold: Optional[float] = None,
        doc_threshold: Optional[float] = None,
    ) -> DocumentRelevance:
        """Pre-LLM gate: decide whether a document is relevant to the ontology.

        Pipeline:

        1. **Lexical + semantic scoring** of every chunk against every
           concept. ``_score`` already fuses the two signals.
        2. **Ancestor roll-up**: for each concept that scored ``> 0`` against
           a chunk, propagate ``ancestor_discount * direct_score`` to every
           in-ontology ancestor (taking the max with the ancestor's own
           direct score). This ensures specific evidence credits more
           general parents — a chunk about *"trade matching"* boosts the
           ancestor *"securities post trade"* and ultimately the document
           gate's relevance score.
        3. **Top-K** by post-roll-up best score.
        4. **Coherence**: report whether the top-K share a common ancestor
           (a soft signal that the document has a single dominant theme).
        """
        top_k = self.doc_top_k if top_k is None else int(top_k)
        chunk_threshold = (
            self.chunk_threshold if chunk_threshold is None else float(chunk_threshold)
        )
        doc_threshold = (
            self.doc_threshold if doc_threshold is None else float(doc_threshold)
        )

        chunk_count = len(chunks or [])
        if chunk_count == 0:
            return DocumentRelevance(
                is_relevant=False,
                aggregate_score=0.0,
                top_concepts=[],
                chunk_count=0,
                chunk_threshold=chunk_threshold,
                doc_threshold=doc_threshold,
                rejection_reason="empty_document",
                ontology_meta=self.metadata(),
                semantic_used=False,
                coherence={},
            )

        chunk_texts = [
            (c.get("text") if isinstance(c, dict) else str(c)) or ""
            for c in chunks
        ]

        # One-shot batch embed of the chunks. Embeddings might be disabled
        # or fail — in either case _semantic_score gracefully returns 0 for
        # all concepts and we end up with lexical-only scoring.
        chunk_vectors: List[Optional[List[float]]] = [None] * len(chunks)
        semantic_used = False
        if self.semantic_enabled and any(t.strip() for t in chunk_texts):
            embeds = self._embed_texts(chunk_texts)
            if embeds:
                chunk_vectors = embeds  # type: ignore[assignment]
                semantic_used = True

        # Per-concept best direct score / chunk / breakdown
        direct_scores: Dict[str, float] = {}
        direct_chunk_idx: Dict[str, int] = {}
        direct_breakdowns: Dict[str, Dict[str, Any]] = {}
        matching_counts: Dict[str, int] = {}

        for concept in self.concepts.values():
            best_score = 0.0
            best_idx = -1
            best_breakdown: Dict[str, Any] = {}
            matching = 0

            for idx, text in enumerate(chunk_texts):
                if not text:
                    continue
                score, breakdown = self._score(text, concept, chunk_vectors[idx])
                if score > best_score:
                    best_score = score
                    best_idx = idx
                    best_breakdown = breakdown
                if score >= chunk_threshold:
                    matching += 1

            if best_score > 0.0 and best_idx >= 0:
                direct_scores[concept.iri] = best_score
                direct_chunk_idx[concept.iri] = best_idx
                direct_breakdowns[concept.iri] = best_breakdown
                matching_counts[concept.iri] = matching

        # Ancestor roll-up — credit each direct hit's ancestors at a
        # discount. We track which ancestors picked up score from where so
        # downstream consumers can tell direct vs rolled-up matches apart.
        rollup_scores: Dict[str, float] = dict(direct_scores)
        rollup_source: Dict[str, str] = {iri: iri for iri in direct_scores}
        for child_iri, score in direct_scores.items():
            child = self.concepts.get(child_iri)
            if not child:
                continue
            credit = score * self.ancestor_discount
            for anc_iri in child.ancestors:
                if anc_iri not in self.concepts:
                    continue
                if credit > rollup_scores.get(anc_iri, 0.0):
                    rollup_scores[anc_iri] = credit
                    rollup_source[anc_iri] = child_iri

        concept_hits: List[ConceptHit] = []
        for iri, score in rollup_scores.items():
            concept = self.concepts.get(iri)
            if not concept:
                continue
            source_iri = rollup_source.get(iri, iri)
            is_direct = source_iri == iri

            if is_direct:
                best_idx = direct_chunk_idx.get(iri, -1)
                breakdown = direct_breakdowns.get(iri, {})
                ancestor_chain: List[str] = []
            else:
                # Borrow the chunk + breakdown from the descendant whose
                # direct score generated the credit so the user has
                # something concrete to point at.
                best_idx = direct_chunk_idx.get(source_iri, -1)
                breakdown = dict(direct_breakdowns.get(source_iri, {}))
                breakdown["rolled_up_from"] = self.concepts[source_iri].label
                breakdown["ancestor_discount"] = self.ancestor_discount
                ancestor_chain = [self.concepts[source_iri].label]

            if best_idx < 0:
                continue

            best_chunk_text = chunk_texts[best_idx]
            excerpt = (best_chunk_text or "").strip().replace("\n", " ")
            if len(excerpt) > 280:
                excerpt = excerpt[:277] + "..."

            matched_synonym: Optional[str] = None
            lex = breakdown.get("lexical") if isinstance(breakdown, dict) else None
            if isinstance(lex, dict):
                matched_synonym = lex.get("matched_surface_form")

            concept_hits.append(
                ConceptHit(
                    concept_iri=concept.iri,
                    concept_label=concept.label,
                    concept_short_name=concept.short_name,
                    concept_definition=concept.definition,
                    best_chunk_index=best_idx,
                    best_chunk_score=round(score, 4),
                    best_chunk_excerpt=excerpt,
                    matching_chunk_count=matching_counts.get(source_iri, 0),
                    breakdown=breakdown,
                    matched_via="direct" if is_direct else "ancestor_rollup",
                    matched_synonym=matched_synonym,
                    ancestor_chain=ancestor_chain,
                )
            )

        concept_hits.sort(key=lambda c: c.best_chunk_score, reverse=True)
        top_concepts = concept_hits[:top_k]

        aggregate = top_concepts[0].best_chunk_score if top_concepts else 0.0
        is_relevant = bool(top_concepts) and aggregate >= doc_threshold
        rejection_reason: Optional[str] = None
        if not is_relevant:
            if not top_concepts:
                rejection_reason = "no_concept_signal"
            else:
                rejection_reason = (
                    f"top_concept_score_below_threshold "
                    f"(top='{top_concepts[0].concept_label}', "
                    f"score={aggregate:.3f}, threshold={doc_threshold:.3f})"
                )

        coherence = self._compute_coherence(top_concepts)

        return DocumentRelevance(
            is_relevant=is_relevant,
            aggregate_score=round(aggregate, 4),
            top_concepts=top_concepts,
            chunk_count=chunk_count,
            chunk_threshold=chunk_threshold,
            doc_threshold=doc_threshold,
            rejection_reason=rejection_reason,
            ontology_meta=self.metadata(),
            semantic_used=semantic_used,
            coherence=coherence,
        )

    def _compute_coherence(self, top_concepts: List[ConceptHit]) -> Dict[str, Any]:
        """Soft check: do the top-K concepts share a common ancestor?

        A document with a single dominant theme will have all its top
        concepts converge on one ancestor (e.g. *Securities Post Trade*).
        A multi-theme document won't. We surface this as metadata so log
        readers can spot dispersed/noisy documents.
        """
        if not top_concepts:
            return {"shared_ancestor": None, "concepts_in_subtree": 0, "is_coherent": False}

        ancestor_sets: List[Set[str]] = []
        for hit in top_concepts:
            concept = self.concepts.get(hit.concept_iri)
            if not concept:
                ancestor_sets.append(set())
                continue
            # Each concept counts itself in the "subtree" calculation.
            ancestor_sets.append({concept.iri, *concept.ancestors})

        if not ancestor_sets:
            return {"shared_ancestor": None, "concepts_in_subtree": 0, "is_coherent": False}

        common = set.intersection(*ancestor_sets) if len(ancestor_sets) > 1 else ancestor_sets[0]
        if not common:
            return {
                "shared_ancestor": None,
                "concepts_in_subtree": 0,
                "is_coherent": False,
            }

        # Pick the *deepest* common ancestor (largest ancestor list = closest
        # to a leaf), which is the most informative one.
        deepest_iri = max(
            common,
            key=lambda iri: len(self.concepts[iri].ancestors) if iri in self.concepts else -1,
        )
        deepest = self.concepts.get(deepest_iri)
        return {
            "shared_ancestor": deepest.label if deepest else None,
            "shared_ancestor_iri": deepest_iri if deepest else None,
            "concepts_in_subtree": len(top_concepts),
            "is_coherent": True,
        }

    def build_extraction_focus(self, top_concepts: List[ConceptHit]) -> str:
        """Return a system-prompt fragment that constrains extraction to FIBO.

        Listing only the concepts that *actually* appear in the document
        prevents the LLM from inventing alignments and gives it a small,
        relevant vocabulary to choose from. The LLM is allowed to extract
        **one Process per genuinely-evidenced concept** — i.e. up to
        ``len(top_concepts)`` processes — so a multi-theme document
        (e.g. one that covers both portfolio management *and* trade
        settlement) doesn't get artificially clamped to a single process.

        Each concept's curated synonyms are surfaced so the LLM
        understands the alias cloud (e.g. *Portfolio Management* also
        covers *asset allocation*, *portfolio construction*, etc.).
        """
        if not top_concepts:
            return ""

        max_processes = len(top_concepts)

        lines = [
            "",
            "═════ ONTOLOGY-GUIDED EXTRACTION (FIBO) ═════",
            (
                f"This document was screened against the FIBO ontology "
                f"({self.ontology_label or self.ontology_iri})."
            ),
            "The FIBO concepts most strongly evidenced by the document text are:",
            "",
        ]
        for i, hit in enumerate(top_concepts, 1):
            line = f"{i}. {hit.concept_label} (score={hit.best_chunk_score:.3f}"
            if hit.matched_via == "ancestor_rollup":
                line += ", via ancestor roll-up"
            elif hit.matched_synonym and hit.matched_synonym.lower() != hit.concept_label.lower():
                line += f", matched synonym '{hit.matched_synonym}'"
            line += ")"
            if hit.concept_definition:
                line += f"\n   Definition: {hit.concept_definition}"
            concept = self.concepts.get(hit.concept_iri)
            if concept and concept.synonyms:
                line += "\n   Aliases: " + ", ".join(concept.synonyms[:6])
                if len(concept.synonyms) > 6:
                    line += f", ... ({len(concept.synonyms) - 6} more)"
            line += f"\n   Concept IRI: {hit.concept_iri}"
            lines.append(line)

        lines += [
            "",
            "EXTRACTION CONSTRAINTS — MUST be followed:",
            (
                f"- Extract UP TO {max_processes} Process(es). Each extracted Process MUST"
            ),
            "  semantically align with ONE of the FIBO concepts listed above",
            "  (or one of its aliases).",
            "- Each extracted Process should align with a DIFFERENT FIBO concept —",
            "  do NOT produce multiple Processes that all map to the same concept.",
            "- Only emit a Process for a concept if the document content GENUINELY",
            "  describes that concept (its activities, inputs, outputs, or",
            "  governance). A passing reference to the concept's name is NOT",
            "  enough — the chunk text must actually discuss what the concept does.",
            "- Use the matched FIBO concept's label or one of its aliases as",
            "  guidance for naming and scoping each Process — do NOT invent",
            "  process names that have no basis in either the document text",
            "  or the listed FIBO concepts.",
            "- If NONE of the concepts truly fit the document content, return",
            "  processes: [] — do NOT fabricate alignment.",
            "═══════════════════════════════════════════════",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------- guardrail

    def apply_guardrail(
        self,
        processes: List[Dict[str, Any]],
        threshold: Optional[float] = None,
        max_processes: Optional[int] = None,
        capability_context: Optional[str] = None,
        document_top_concept_iris: Optional[List[str]] = None,
    ) -> GuardrailResult:
        """Score every candidate process and select at most ``max_processes``.

        Processes whose best match scores below ``threshold`` are rejected
        with reason ``below_threshold``. Among those that pass, only the top
        ``max_processes`` (by score) are accepted; surplus passes are
        rejected with reason ``exceeded_max_processes``.

        Validation
        ----------
        For every process scored we now also run two validation checks:

        * **Hierarchy consistency** — when ``document_top_concept_iris`` is
          provided (Stage 1's output), we check that the process's matched
          concept either *is* one of those IRIs or has one of them as an
          ancestor / descendant. If neither holds, the process is flagged
          ``hierarchy_consistent=False``. We do not auto-reject on this —
          downstream consumers can choose to escalate or just record it.
        * **Disjointness** — if the matched concept (or any ancestor) is
          declared ``owl:disjointWith`` a concept that *also* has strong
          evidence elsewhere in the candidate set, we reject the process
          with reason ``disjointness_violation``. (The shipped FIBO module
          currently declares no ``disjointWith`` axioms, so this is a
          framework hook that becomes active automatically when richer
          modules are loaded.)

        ``capability_context`` (typically the capability's name) is folded
        into each process's scored text so processes inherit the document's
        dominant theme.
        """
        threshold = self.threshold if threshold is None else float(threshold)
        max_processes = self.max_processes if max_processes is None else int(max_processes)
        ctx = (capability_context or "").strip()
        doc_top_iris = list(document_top_concept_iris or [])

        # Build the candidate text set first, then batch-embed everything in
        # one round-trip so each process doesn't pay its own embedding call.
        prepared: List[Tuple[int, str, str, str]] = []
        for idx, proc in enumerate(processes or []):
            name = (proc.get("name") or "").strip()
            desc = (proc.get("description") or "").strip()
            text = " ".join(part for part in (ctx, name, desc) if part).strip()
            prepared.append((idx, name, desc, text))

        process_vectors: List[Optional[List[float]]] = [None] * len(prepared)
        semantic_used = False
        if self.semantic_enabled and any(t for _, _, _, t in prepared):
            embeds = self._embed_texts([t for _, _, _, t in prepared])
            if embeds:
                process_vectors = embeds  # type: ignore[assignment]
                semantic_used = True

        candidates: List[GuardrailMatch] = []
        for slot, (idx, name, desc, text) in enumerate(prepared):
            best_concept: Optional[OntologyConcept] = None
            best_score = 0.0
            best_breakdown: Dict[str, Any] = {}

            for concept in self.concepts.values():
                score, breakdown = self._score(text, concept, process_vectors[slot])
                if score > best_score:
                    best_concept = concept
                    best_score = score
                    best_breakdown = breakdown

            ancestor_chain: List[str] = []
            matched_synonym: Optional[str] = None
            hierarchy_consistent: Optional[bool] = None
            disjointness_violations: List[str] = []
            validation_notes: List[str] = []

            if best_concept is not None:
                ancestor_chain = [
                    self.concepts[a].label
                    for a in best_concept.ancestors
                    if a in self.concepts
                ]
                lex = best_breakdown.get("lexical") if isinstance(best_breakdown, dict) else None
                if isinstance(lex, dict):
                    matched_synonym = lex.get("matched_surface_form")

                if doc_top_iris:
                    hierarchy_consistent = self._check_hierarchy_consistency(
                        best_concept, doc_top_iris
                    )
                    if hierarchy_consistent is False:
                        validation_notes.append(
                            "matched concept is not in or under any of the "
                            "document gate's top concepts"
                        )

                disjointness_violations = self._check_disjointness(
                    best_concept,
                    other_iris=[c.iri for c in self.concepts.values()],
                )
                if disjointness_violations:
                    validation_notes.append(
                        f"disjoint with: {', '.join(disjointness_violations)}"
                    )

            passes_threshold = bool(best_concept) and best_score >= threshold
            disjoint_block = bool(disjointness_violations)
            accepted = passes_threshold and not disjoint_block
            if disjoint_block:
                reason = "disjointness_violation"
            elif passes_threshold:
                reason = "passes_threshold"
            else:
                reason = "below_threshold"

            candidates.append(
                GuardrailMatch(
                    process_index=idx,
                    process_name=name,
                    process_description=desc,
                    best_concept_iri=best_concept.iri if best_concept else None,
                    best_concept_label=best_concept.label if best_concept else None,
                    score=round(best_score, 4),
                    breakdown=best_breakdown,
                    accepted=accepted,
                    reason=reason,
                    ancestor_chain=ancestor_chain,
                    matched_synonym=matched_synonym,
                    hierarchy_consistent=hierarchy_consistent,
                    disjointness_violations=disjointness_violations,
                    validation_notes=validation_notes,
                )
            )

        # Pick top-N from those that cleared every gate (threshold + no
        # disjointness violation).
        passed = sorted(
            (c for c in candidates if c.accepted),
            key=lambda c: c.score,
            reverse=True,
        )
        accepted = passed[:max_processes]
        accepted_indices = {a.process_index for a in accepted}

        rejected: List[GuardrailMatch] = []
        for match in candidates:
            if match.process_index in accepted_indices:
                continue
            if match.accepted:
                # Passed threshold but didn't make the top-N cut
                rejected.append(
                    GuardrailMatch(
                        process_index=match.process_index,
                        process_name=match.process_name,
                        process_description=match.process_description,
                        best_concept_iri=match.best_concept_iri,
                        best_concept_label=match.best_concept_label,
                        score=match.score,
                        breakdown=match.breakdown,
                        accepted=False,
                        reason="exceeded_max_processes",
                        ancestor_chain=match.ancestor_chain,
                        matched_synonym=match.matched_synonym,
                        hierarchy_consistent=match.hierarchy_consistent,
                        disjointness_violations=match.disjointness_violations,
                        validation_notes=match.validation_notes,
                    )
                )
            else:
                rejected.append(match)

        return GuardrailResult(
            threshold=threshold,
            max_processes=max_processes,
            candidates=candidates,
            accepted=accepted,
            rejected=rejected,
            ontology_meta=self.metadata(),
            semantic_used=semantic_used,
            document_top_concept_iris=doc_top_iris,
        )

    # --------------------------------------------------------- validation

    def _check_hierarchy_consistency(
        self,
        concept: OntologyConcept,
        document_top_iris: List[str],
    ) -> bool:
        """Is ``concept`` in the same sub-tree as any document-top concept?

        We treat the relation symmetrically: the matched concept may be an
        ancestor or descendant of one of the doc-top concepts, or be one of
        them outright. This avoids penalising legitimate sub-class /
        super-class refinements (e.g. doc gate flags
        *Securities Post Trade* and the LLM extracts the more specific
        *Securities Trades Matching*).
        """
        if not document_top_iris:
            return True
        own_set: Set[str] = {concept.iri, *concept.ancestors}
        for top_iri in document_top_iris:
            if top_iri in own_set:
                return True
            top = self.concepts.get(top_iri)
            if top and concept.iri in {top.iri, *top.ancestors}:
                return True
        return False

    def _check_disjointness(
        self,
        concept: OntologyConcept,
        other_iris: List[str],
    ) -> List[str]:
        """Return labels of concepts in ``other_iris`` that are disjoint with
        ``concept`` or any of its ancestors. Empty list when no violation.
        """
        if not concept.disjoint_with and not any(
            self.concepts.get(a) and self.concepts[a].disjoint_with
            for a in concept.ancestors
        ):
            return []

        forbidden: Set[str] = set(concept.disjoint_with)
        for anc_iri in concept.ancestors:
            anc = self.concepts.get(anc_iri)
            if anc:
                forbidden.update(anc.disjoint_with)
        if not forbidden:
            return []

        violations: List[str] = []
        for iri in other_iris:
            if iri in forbidden:
                target = self.concepts.get(iri)
                violations.append(target.label if target else iri)
        return violations

    def annotate_model(self, model: Dict[str, Any], result: GuardrailResult) -> Dict[str, Any]:
        """Return a copy of ``model`` trimmed to the accepted processes only.

        The returned dict carries:
          * ``processes``          — only the guardrail-accepted entries, each
            with an ``ontology_alignment`` block describing the matched concept.
          * ``ontology_guardrail`` — full guardrail outcome for traceability.
        """
        accepted_map = {a.process_index: a for a in result.accepted}

        annotated_processes: List[Dict[str, Any]] = []
        for idx, proc in enumerate(model.get("processes", []) or []):
            if idx not in accepted_map:
                continue
            match = accepted_map[idx]
            proc_copy = dict(proc)
            proc_copy["ontology_alignment"] = {
                "concept_iri": match.best_concept_iri,
                "concept_label": match.best_concept_label,
                "score": match.score,
                "score_breakdown": match.breakdown,
                "matched_synonym": match.matched_synonym,
                "ancestor_chain": list(match.ancestor_chain),
                "validation": {
                    "hierarchy_consistent": match.hierarchy_consistent,
                    "disjointness_violations": list(match.disjointness_violations),
                    "notes": list(match.validation_notes),
                },
                "threshold": result.threshold,
                "source": "FIBO",
            }
            annotated_processes.append(proc_copy)

        annotated = dict(model)
        annotated["processes"] = annotated_processes
        annotated["ontology_guardrail"] = {
            "applied": True,
            "threshold": result.threshold,
            "max_processes": result.max_processes,
            "ontology": result.ontology_meta,
            "semantic_used": result.semantic_used,
            "document_top_concept_iris": list(result.document_top_concept_iris),
            "accepted_count": len(result.accepted),
            "rejected_count": len(result.rejected),
            "candidate_count": len(result.candidates),
            "candidates": [c.to_dict() for c in result.candidates],
        }
        return annotated

    # ------------------------------------------------------------------ neo4j

    def sync_to_neo4j(self, replace_existing: bool = True) -> Dict[str, Any]:
        """Project the ontology into Neo4j as ``:OntologyConcept`` nodes.

        Edges:
          ``(child:OntologyConcept)-[:SUBCLASS_OF]->(parent:OntologyConcept)``

        Only parents that are themselves part of the loaded ontology are
        materialised as edges; external references (e.g. into other FIBO
        modules not present in the local file) are kept on the node as a
        ``external_parents`` property for traceability.
        """
        from neo4j_graph.services.query_execution_service import Neo4jQueryService

        svc = Neo4jQueryService()
        try:
            if replace_existing:
                svc.execute_cypher(
                    "MATCH (n:OntologyConcept) DETACH DELETE n"
                )

            now = datetime.utcnow().isoformat() + "Z"

            for concept in self.concepts.values():
                external_parents = [p for p in concept.parents if p not in self.concepts]
                svc.execute_cypher(
                    """
                    MERGE (c:OntologyConcept {iri: $iri})
                    SET c.label = $label,
                        c.short_name = $short_name,
                        c.definition = $definition,
                        c.source = $source,
                        c.source_module = $source_module,
                        c.ontology_iri = $ontology_iri,
                        c.external_parents = $external_parents,
                        c.synonyms = $synonyms,
                        c.synonyms_from_rdf = $synonyms_from_rdf,
                        c.synonyms_from_lexicon = $synonyms_from_lexicon,
                        c.disjoint_with = $disjoint_with,
                        c.ancestor_count = $ancestor_count,
                        c.updated_at = $updated_at
                    """,
                    {
                        "iri": concept.iri,
                        "label": concept.label,
                        "short_name": concept.short_name,
                        "definition": concept.definition,
                        "source": concept.source,
                        "source_module": concept.source_module,
                        "ontology_iri": self.ontology_iri,
                        "external_parents": external_parents,
                        "synonyms": list(concept.synonyms),
                        "synonyms_from_rdf": list(concept.synonyms_from_rdf),
                        "synonyms_from_lexicon": list(concept.synonyms_from_lexicon),
                        "disjoint_with": list(concept.disjoint_with),
                        "ancestor_count": len(concept.ancestors),
                        "updated_at": now,
                    },
                )

            edges_created = 0
            for concept in self.concepts.values():
                for parent_iri in concept.parents:
                    if parent_iri not in self.concepts:
                        continue
                    svc.execute_cypher(
                        """
                        MATCH (child:OntologyConcept {iri: $child_iri})
                        MATCH (parent:OntologyConcept {iri: $parent_iri})
                        MERGE (child)-[r:SUBCLASS_OF]->(parent)
                        SET r.updated_at = $updated_at
                        """,
                        {
                            "child_iri": concept.iri,
                            "parent_iri": parent_iri,
                            "updated_at": now,
                        },
                    )
                    edges_created += 1

            summary = {
                "concepts_synced": len(self.concepts),
                "edges_created": edges_created,
                "ontology_iri": self.ontology_iri,
                "synced_at": now,
                "replace_existing": replace_existing,
            }
            logger.info("FIBO ontology synced to Neo4j: %s", summary)
            return summary
        finally:
            svc.close()


# ---------------------------------------------------------------------------
# Module-level singleton accessor
# ---------------------------------------------------------------------------

_ontology_singleton: Optional[FIBOOntologyService] = None
_singleton_lock = threading.Lock()


def get_ontology_service(
    rdf_path: Optional[str] = None,
    threshold: Optional[float] = None,
    max_processes: Optional[int] = None,
    doc_threshold: Optional[float] = None,
    chunk_threshold: Optional[float] = None,
    doc_top_k: Optional[int] = None,
    synonym_lexicon_path: Optional[str] = None,
    fibo_local_dir: Optional[str] = None,
    follow_imports: Optional[bool] = None,
    semantic_enabled: Optional[bool] = None,
    semantic_trust: Optional[float] = None,
    reload: bool = False,
) -> FIBOOntologyService:
    """Return the process-wide :class:`FIBOOntologyService`, building it lazily.

    Pass ``reload=True`` to force a fresh load — useful when the underlying
    RDF file has been replaced on disk.
    """
    global _ontology_singleton
    with _singleton_lock:
        if _ontology_singleton is None or reload:
            resolved_path = rdf_path or os.getenv(ENV_RDF_PATH) or str(DEFAULT_RDF_PATH)
            # Curated lexicon is opt-in only: caller arg first, then env
            # var. Empty string from the env var is treated as unset so
            # users can disable it at runtime.
            env_lex = os.getenv(ENV_SYNONYM_LEXICON_PATH) or ""
            resolved_lex: Optional[str]
            if synonym_lexicon_path:
                resolved_lex = synonym_lexicon_path
            elif env_lex:
                resolved_lex = env_lex
            else:
                resolved_lex = None

            resolved_fibo_dir = (
                fibo_local_dir
                or os.getenv(ENV_FIBO_LOCAL_DIR)
                or str(DEFAULT_FIBO_LOCAL_DIR)
            )

            _ontology_singleton = FIBOOntologyService(
                rdf_path=resolved_path,
                synonym_lexicon_path=resolved_lex,
                fibo_local_dir=resolved_fibo_dir,
                follow_imports=(
                    follow_imports if follow_imports is not None else DEFAULT_FOLLOW_IMPORTS
                ),
                threshold=threshold if threshold is not None else DEFAULT_THRESHOLD,
                max_processes=max_processes if max_processes is not None else DEFAULT_MAX_PROCESSES,
                doc_threshold=doc_threshold if doc_threshold is not None else DEFAULT_DOC_THRESHOLD,
                chunk_threshold=chunk_threshold if chunk_threshold is not None else DEFAULT_CHUNK_THRESHOLD,
                doc_top_k=doc_top_k if doc_top_k is not None else DEFAULT_DOC_TOP_K,
                semantic_enabled=(
                    semantic_enabled if semantic_enabled is not None else DEFAULT_SEMANTIC_ENABLED
                ),
                semantic_trust=(
                    semantic_trust if semantic_trust is not None else DEFAULT_SEMANTIC_TRUST
                ),
            )
        return _ontology_singleton
