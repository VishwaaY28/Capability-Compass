import os
import json
import datetime
from pathlib import Path

import spacy
from spacy.cli import download as spacy_download
from unstructured.partition.pdf import partition_pdf


# -------- spaCy loader with fallbacks --------
def get_nlp():
    model = "en_core_web_sm"
    try:
        return spacy.load(model)
    except OSError:
        try:
            spacy_download(model)
            return spacy.load(model)
        except Exception as e:
            print(f"[WARN] Could not load '{model}'. Using blank('en'). Error: {e}")
            nlp_blank = spacy.blank("en")
            if "sentencizer" not in nlp_blank.pipe_names:
                nlp_blank.add_pipe("sentencizer")
            return nlp_blank

nlp = get_nlp()
if "sentencizer" not in nlp.pipe_names and "parser" not in nlp.pipe_names and "senter" not in nlp.pipe_names:
    # Ensure sentence boundaries even if model lacks parser/senter
    nlp.add_pipe("sentencizer")


# -------- Robust PDF extraction with fallbacks --------
def extract_text_from_pdf(pdf_path: str) -> str:
    """
    Try multiple strategies with `unstructured` to maximize text extraction.
    Saves raw text alongside the PDF for inspection.
    """
    pdf_path = str(pdf_path)
    strategies = [
        # Fast path for digital PDFs
        dict(strategy="fast", include_page_breaks=True, infer_table_structure=True),
        # Hi-res layout (requires unstructured-inference)
        dict(strategy="hi_res", include_page_breaks=True, infer_table_structure=True),
        # OCR fallback (requires Tesseract + layoutparser[ocr])
        dict(strategy="ocr_only", include_page_breaks=True, infer_table_structure=True, ocr_languages="eng"),
    ]

    all_texts = []
    last_err = None

    for i, kw in enumerate(strategies, start=1):
        try:
            print(f"[INFO] partition_pdf attempt {i}: {kw}")
            elements = partition_pdf(pdf_path, **kw)
            texts = [getattr(el, "text", "") for el in elements if getattr(el, "text", None)]
            combined = "\n".join(texts).strip()
            if combined:
                all_texts.append(combined)
                print(f"[INFO] Strategy {kw['strategy']} extracted {len(combined)} chars.")
                break
            else:
                print(f"[WARN] Strategy {kw['strategy']} returned no text.")
        except Exception as e:
            last_err = e
            print(f"[ERROR] Strategy {kw.get('strategy')} failed: {e}")

    if not all_texts:
        if last_err:
            print(f"[ERROR] All strategies failed. Last error: {last_err}")
        return ""

    final_text = all_texts[0]
    # Save raw text next to the PDF for inspection
    raw_out = Path(pdf_path).with_suffix(".txt")
    try:
        raw_out.write_text(final_text, encoding="utf-8")
        print(f"[INFO] Wrote raw extracted text to: {raw_out}")
    except Exception as e:
        print(f"[WARN] Could not write raw text file: {e}")

    return final_text


# -------- Tolerant rule-based extraction --------
def rule_based_extraction(text: str) -> dict:
    """
    Extract "capabilities", "processes", "subprocesses", "entities" using:
    - Keyword matches (original behavior)
    - Additional tolerant patterns (e.g., 'capabilities:', numbered sections)
    - Simple noun-chunk & NER heuristics as fallback
    """
    doc = nlp(text)
    capabilities = []
    processes = []
    subprocesses = []
    entities = []

    # 1) Keyword & pattern-based
    for sent in doc.sents:
        s = sent.text.strip()
        low = s.lower()

        # Original keywords
        if "capability" in low or "capabilities:" in low:
            capabilities.append(s)
            continue
        if "process" in low or low.startswith("process:") or "processes:" in low:
            processes.append(s)
            continue
        if "subprocess" in low or "sub-process" in low or "sub-processes" in low:
            subprocesses.append(s)
            continue
        if "entity" in low or "entities:" in low or "data entity" in low or "data:" in low:
            entities.append(s)
            continue

        # Section-like patterns (e.g., "1. Capability Name", "2. Process Name")
        if any(
            low.startswith(prefix) for prefix in [
                "capabilities -", "capability -", "capabilities –", "capability –",
                "process -", "process –", "processes -", "processes –",
                "subprocess -", "sub-process -", "subprocess –", "sub-process –",
                "entities -", "entities –", "entity -", "entity –",
            ]
        ):
            # crude classifier by keyword presence
            if "capab" in low:
                capabilities.append(s)
            elif "subprocess" in low or "sub-process" in low:
                subprocesses.append(s)
            elif "process" in low:
                processes.append(s)
            elif "entit" in low or "data" in low:
                entities.append(s)

    # 2) Fallback heuristics if too sparse
    def uniq(seq):
        seen = set()
        out = []
        for x in seq:
            if x not in seen:
                out.append(x)
                seen.add(x)
        return out

    # If we found nothing, try noun chunks & named entities as last resort
    if not any([capabilities, processes, subprocesses, entities]):
        # Noun chunks as "entities"
        if hasattr(doc, "noun_chunks"):
            entities = [nc.text.strip() for nc in doc.noun_chunks if 2 <= len(nc.text.split()) <= 6]
        # Named entities
        if hasattr(doc, "ents") and doc.ents:
            entities.extend({e.text.strip() for e in doc.ents})

    return {
        "capabilities": uniq(capabilities),
        "processes": uniq(processes),
        "subprocesses": uniq(subprocesses),
        "entities": uniq(entities),
    }


# -------- Build hierarchical model --------
def build_json_model(extracted: dict) -> dict:
    """
    Creates a hierarchical JSON. If capabilities are empty, we'll still
    produce a non-empty structure by grouping under a synthetic capability.
    """
    caps = extracted.get("capabilities", [])
    procs = extracted.get("processes", [])
    subs = extracted.get("subprocesses", [])
    ents = extracted.get("entities", [])

    # If no explicit capabilities found, create a synthetic one to hold content
    if not caps and (procs or subs or ents):
        caps = ["(Auto) Capability"]

    model = {
        "capabilities": [
            {
                "id": idx + 1,
                "name": cap,
                "processes": [
                    {
                        "id": pidx + 1,
                        "name": proc,
                        "subprocesses": [{"id": sidx + 1, "name": sub} for sidx, sub in enumerate(subs)],
                        "data_entities": [{"id": eidx + 1, "name": ent} for eidx, ent in enumerate(ents)],
                    }
                    for pidx, proc in enumerate(procs or ["(Auto) Process"])
                ],
            }
            for idx, cap in enumerate(caps)
        ],
        "counts": {k: len(v) for k, v in extracted.items()},
        "timestamp": datetime.datetime.now().isoformat(),
    }
    return model


# -------- Timestamped JSON writer --------
def write_timestamped_json(data: dict, base_path: str = "response.json") -> str:
    abs_path = Path(base_path).resolve()
    base = abs_path.stem
    ext = abs_path.suffix or ".json"
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    candidate = abs_path.with_name(f"{base}_{timestamp}{ext}")

    counter = 2
    while candidate.exists():
        candidate = abs_path.with_name(f"{base}_{timestamp}_{counter}{ext}")
        counter += 1

    candidate.parent.mkdir(parents=True, exist_ok=True)
    with open(candidate, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"[INFO] Saved JSON to: {candidate}")
    return str(candidate)


# -------- Main --------
def main():
    pdf_path = "policy.pdf"  # Replace with your input PDF path
    if not Path(pdf_path).exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    text = extract_text_from_pdf(pdf_path)
    print(f"[DEBUG] Extracted chars: {len(text)}")

    if not text.strip():
        print("[ERROR] No text extracted. Check OCR/Tesseract installation and PDF content.")
        # Still write a minimal JSON for traceability
        write_timestamped_json({"error": "No text extracted", "timestamp": datetime.datetime.now().isoformat()})
        return

    extracted = rule_based_extraction(text)
    print(f"[DEBUG] Extracted counts: { {k: len(v) for k, v in extracted.items()} }")

    model_json = build_json_model(extracted)
    write_timestamped_json(model_json, "response.json")


if __name__ == "__main__":
    main()