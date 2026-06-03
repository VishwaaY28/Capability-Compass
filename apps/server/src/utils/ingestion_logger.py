"""
Ingestion run logger for Compass.

Every Compass document ingestion produces one JSONL record describing:
  * the source document (filename + content hash),
  * the configuration used (vertical, subvertical, extraction depth),
  * the FIBO ontology metadata that was applied,
  * the per-process guardrail outcome (candidates, accepted, rejected),
  * the resulting capability/process payload that was kept,
  * timing information and any error.

Records are appended to ``ingestion_logs/compass_ingestion.jsonl`` (path is
configurable via the ``COMPASS_INGESTION_LOG_DIR`` /
``COMPASS_INGESTION_LOG_FILE`` environment variables). The file is JSONL
(one JSON document per line) so it is easy to ``tail`` / grep / load into
DataFrames for review.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

ENV_LOG_DIR = "COMPASS_INGESTION_LOG_DIR"
ENV_LOG_FILE = "COMPASS_INGESTION_LOG_FILE"

DEFAULT_LOG_DIR = Path(os.getenv(ENV_LOG_DIR, "ingestion_logs"))
DEFAULT_LOG_FILE = os.getenv(ENV_LOG_FILE, "compass_ingestion.jsonl")

_write_lock = threading.Lock()


def _resolve_log_path(
    log_dir: Optional[str] = None, log_file: Optional[str] = None
) -> Path:
    base = Path(log_dir) if log_dir else DEFAULT_LOG_DIR
    base.mkdir(parents=True, exist_ok=True)
    return base / (log_file or DEFAULT_LOG_FILE)


def _safe_status_slug(status: Optional[str]) -> str:
    """Return a filesystem-friendly slug for a run status."""
    if not status:
        return "unknown"
    return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in str(status))[:32]


def _per_run_filename(timestamp_iso: str, run_id: str, status: Optional[str]) -> str:
    """Build a deterministic, sortable filename for a single run.

    Example: ``run_2026-05-28T11-39-10Z_ontology_rejected_c7eda2da.json``
    """
    safe_ts = (
        timestamp_iso.replace(":", "-")
        .replace(".", "-")
        .replace("+", "p")
    )
    short_id = (run_id or "")[:8] or "unknown"
    return f"run_{safe_ts}_{_safe_status_slug(status)}_{short_id}.json"


def write_ingestion_log(
    entry: Dict[str, Any],
    log_dir: Optional[str] = None,
    log_file: Optional[str] = None,
) -> Dict[str, str]:
    """Persist a single ingestion run entry.

    Two artefacts are produced for each run:

      * **Per-run file** ``ingestion_logs/run_<UTC-ISO>_<status>_<run_id>.json``
        — one JSON document per run, easy to open / share / diff.
      * **Aggregate JSONL** ``ingestion_logs/compass_ingestion.jsonl`` —
        appended to so callers can ``tail -f`` or grep across runs.

    Returns a dict with both paths.
    """
    aggregate_path = _resolve_log_path(log_dir, log_file)

    enriched = dict(entry)
    enriched.setdefault("run_id", uuid.uuid4().hex)
    enriched.setdefault("timestamp", datetime.utcnow().isoformat() + "Z")

    per_run_path = aggregate_path.parent / _per_run_filename(
        enriched["timestamp"], enriched["run_id"], enriched.get("status")
    )

    with _write_lock:
        with aggregate_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(enriched, ensure_ascii=False, default=str) + "\n")

        with per_run_path.open("w", encoding="utf-8") as fh:
            json.dump(enriched, fh, ensure_ascii=False, indent=2, default=str)

    logger.info(
        "[INGESTION_LOG] run_id=%s status=%s -> %s | %s",
        enriched.get("run_id"),
        enriched.get("status"),
        per_run_path,
        aggregate_path,
    )
    return {"per_run": str(per_run_path), "aggregate": str(aggregate_path)}


def read_ingestion_logs(
    limit: int = 50,
    log_dir: Optional[str] = None,
    log_file: Optional[str] = None,
) -> Dict[str, Any]:
    """Return up to ``limit`` most-recent ingestion log entries (newest first)."""
    path = _resolve_log_path(log_dir, log_file)
    if not path.exists():
        return {"path": str(path), "total": 0, "returned": 0, "entries": []}

    entries: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError as exc:
                logger.warning("Skipping malformed ingestion log line: %s", exc)

    total = len(entries)
    if limit and limit > 0:
        entries = entries[-limit:]
    entries.reverse()  # newest first

    return {
        "path": str(path),
        "total": total,
        "returned": len(entries),
        "entries": entries,
    }


def build_run_entry(
    *,
    run_id: Optional[str] = None,
    source_file: str,
    file_hash: Optional[str],
    config: Dict[str, Any],
    status: str,
    ontology: Dict[str, Any],
    guardrail: Dict[str, Any],
    accepted_processes: Optional[List[Dict[str, Any]]] = None,
    rejected_processes: Optional[List[Dict[str, Any]]] = None,
    capability_name: Optional[str] = None,
    duration_ms: Optional[float] = None,
    cached: bool = False,
    neo4j_synced: Optional[bool] = None,
    error: Optional[str] = None,
    extras: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Construct a normalised ingestion log entry.

    Parameters
    ----------
    status:
        One of ``"success"``, ``"ontology_rejected"``, ``"cache_hit"``,
        ``"error"``. Free-form values are also tolerated; ``"success"``
        denotes that at least one process passed the ontology guardrail.
    ontology:
        Snapshot of :meth:`FIBOOntologyService.metadata` so future readers
        know which ontology version was used at the time of the run.
    guardrail:
        Per-run guardrail summary including candidates / accepted /
        rejected lists. This is the primary record of "how the ontology
        was used for this run".
    """
    entry: Dict[str, Any] = {
        "run_id": run_id or uuid.uuid4().hex,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "status": status,
        "cached": bool(cached),
        "source_file": source_file,
        "file_hash": file_hash,
        "capability_name": capability_name,
        "config": config,
        "ontology": ontology,
        "guardrail": guardrail,
        "accepted_processes": accepted_processes or [],
        "rejected_processes": rejected_processes or [],
        "duration_ms": duration_ms,
    }
    if neo4j_synced is not None:
        entry["neo4j_synced"] = bool(neo4j_synced)
    if error:
        entry["error"] = error
    if extras:
        entry["extras"] = extras
    return entry
