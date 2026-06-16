// Module-level extraction state manager — survives component unmount/remount
import { API_BASE } from './apiBase';

interface ExtractedCapabilityModel {
  id?: number;
  name: string;
  description: string;
  vertical: string;
  subvertical?: string;
  processes: any[];
  // Carried over by the backend after the FIBO guardrail runs
  ontology_guardrail?: OntologyGuardrailSummary;
}

/**
 * Snapshot of the FIBO ontology that was used for a given run.
 * Mirrors the backend `FIBOOntologyService.metadata()` payload.
 */
export interface OntologyMeta {
  ontology_iri?: string;
  ontology_label?: string;
  ontology_abstract?: string;
  rdf_file?: string;
  concept_count?: number;
  loaded_at?: string;
  threshold?: number;
  max_processes?: number;
  doc_threshold?: number;
  chunk_threshold?: number;
  doc_top_k?: number;
  source?: string;
}

export interface ConceptHit {
  concept_iri: string;
  concept_label: string;
  concept_short_name?: string;
  concept_definition?: string;
  best_chunk_index: number;
  best_chunk_score: number;
  best_chunk_excerpt?: string;
  matching_chunk_count?: number;
  breakdown?: Record<string, number>;
}

export interface DocumentRelevance {
  is_relevant: boolean;
  aggregate_score: number;
  top_concepts: ConceptHit[];
  chunk_count: number;
  chunk_threshold: number;
  doc_threshold: number;
  rejection_reason: string | null;
  ontology_meta?: OntologyMeta;
}

export interface OntologyGuardrailSummary {
  applied: boolean;
  threshold?: number;
  max_processes?: number;
  candidate_count?: number;
  accepted_count?: number;
  rejected_count?: number;
  candidates?: any[];
  accepted?: any[];
  rejected?: any[];
  reason?: string;
}

/**
 * Logical UI status for a file in the ingestion list.
 *  - rejected: a *terminal* state meaning the document failed the FIBO
 *    ontology guardrail (either the pre-LLM document gate or the
 *    post-LLM process guardrail).
 *  - awaiting_review: the HITL flow is paused at a wizard step waiting
 *    for the user to review a stage's output and click "Next".
 */
export type FileStatus =
  | 'pending'
  | 'uploading'
  | 'extracting'
  | 'validating'
  | 'awaiting_review'
  | 'success'
  | 'rejected'
  | 'error';

/**
 * Logical wizard step inside the HITL ingestion flow. The four stages
 * correspond 1:1 to the backend `/upload/session/...` endpoints:
 *  - doc_gate     → POST /session/start  (FIBO document gate output)
 *  - extraction   → POST /session/{id}/extract (raw LLM processes)
 *  - guardrail    → POST /session/{id}/guardrail (post-LLM ontology trim)
 *  - import       → POST /session/{id}/import (writes Neo4j)
 */
export type IngestionStep = 'doc_gate' | 'extraction' | 'guardrail' | 'import';

/**
 * One chunk that contributed evidence to a top FIBO concept during the
 * pre-LLM document gate. Surfaced to the user in step 1 so they can
 * see *why* the document was accepted.
 */
export interface EvidenceChunk {
  chunk_index: number;
  concept_iri?: string;
  concept_label?: string;
  concept_definition?: string;
  score?: number;
  matched_via?: string;
  matched_synonym?: string | null;
  passes_chunk_threshold?: boolean;
  chunk_threshold?: number;
  page?: number | string | null;
  text: string;
  excerpt?: string;
}

/**
 * Distinguishes a free-form `document` (PDF/DOCX/TXT — needs LLM + FIBO
 * guardrail) from a `tabular` source (CSV/XLSX — already structured, so we
 * parse + display only, skipping ontology and LLM extraction).
 *
 * Both flows produce the same `ExtractedCapabilityModel` shape; this flag
 * only governs which import endpoint to call when the user clicks
 * "Import to Graph".
 */
export type SourceType = 'document' | 'tabular';

interface UploadedFile {
  id: string;
  name: string;
  size: number;
  type: string;
  status: FileStatus;
  progress: number;
  error?: string;
  extractedData?: ExtractedCapabilityModel;
  sourceType?: SourceType;
  chunks_path?: string;
  // FIBO ontology metadata captured during this run
  ontology?: OntologyMeta;
  document_relevance?: DocumentRelevance;
  guardrail?: OntologyGuardrailSummary;
  ontology_status?: 'success' | 'document_rejected' | 'ontology_rejected';
  rejection_reason?: string;

  // ---- Human-in-the-Loop wizard state ----
  /** Backend session id, set the moment step 1 returns. */
  session_id?: string;
  /** Which wizard step the file is currently parked at. */
  current_step?: IngestionStep;
  /** Document chunks that drove the top FIBO concepts (step 1 evidence). */
  evidence_chunks?: EvidenceChunk[];
  /** Number of chunks the document was split into (step 1). */
  chunk_count?: number;
  /** Raw LLM output before the FIBO guardrail is applied (step 2). */
  rawExtractedData?: ExtractedCapabilityModel;
}

const TABULAR_EXTENSIONS = ['.csv', '.xlsx', '.xls'];

export function detectSourceType(fileName: string): SourceType {
  const lower = fileName.toLowerCase();
  return TABULAR_EXTENSIONS.some((ext) => lower.endsWith(ext)) ? 'tabular' : 'document';
}

const INGESTION_STORAGE_KEY = 'compass_ingestion_files';

// Module-level state
let activeExtractions = new Map<string, AbortController>();
let cachedFiles: UploadedFile[] = [];
let thinkingState = { isThinking: false, message: '' };
let pendingModalData: { data: ExtractedCapabilityModel; fileId: string } | null = null;
// Notifications surface info about rejected documents to the page so it can toast
let pendingRejection: { fileId: string; fileName: string; reason: string } | null = null;

/**
 * In-memory cache of the actual `File` objects keyed by upload id. Required
 * because (a) drag-and-drop never populates the hidden `<input>`, and
 * (b) tabular uploads need to re-send the same file when the user clicks
 * "Import to Graph" after previewing.
 */
const fileObjectCache = new Map<string, File>();

export function registerFileObject(id: string, file: File) {
  fileObjectCache.set(id, file);
}

export function getFileObject(id: string): File | undefined {
  return fileObjectCache.get(id);
}

export function dropFileObject(id: string) {
  fileObjectCache.delete(id);
}

// Subscribers for state updates
type Subscriber = (files: UploadedFile[], thinking: { isThinking: boolean; message: string }) => void;
const subscribers = new Set<Subscriber>();

function notifySubscribers() {
  subscribers.forEach((sub) => sub([...cachedFiles], { ...thinkingState }));
}

export function subscribeToExtractions(callback: Subscriber) {
  subscribers.add(callback);
  // Immediately call with current state
  callback([...cachedFiles], { ...thinkingState });
  return () => subscribers.delete(callback);
}

export function loadPersistedFiles(): UploadedFile[] {
  try {
    const raw = sessionStorage.getItem(INGESTION_STORAGE_KEY);
    if (!raw) return [];
    const parsed: UploadedFile[] = JSON.parse(raw);
    return parsed;
  } catch {
    return [];
  }
}

function saveFiles(files: UploadedFile[]) {
  try {
    sessionStorage.setItem(INGESTION_STORAGE_KEY, JSON.stringify(files));
  } catch {
    // Quota exceeded
  }
}

export function initializeFiles(files: UploadedFile[]) {
  cachedFiles = files;
  saveFiles(files);
}

export function getFiles(): UploadedFile[] {
  return [...cachedFiles];
}

export function addFiles(newFiles: UploadedFile[]) {
  cachedFiles = [...newFiles, ...cachedFiles];
  saveFiles(cachedFiles);
  notifySubscribers();
}

export function removeFile(id: string) {
  const target = cachedFiles.find((f) => f.id === id);
  if (target?.session_id) {
    void cancelSession(target.session_id);
  }
  cachedFiles = cachedFiles.filter((f) => f.id !== id);
  saveFiles(cachedFiles);
  dropFileObject(id);
  notifySubscribers();
}

export function clearAllFiles() {
  // Best-effort cancel for every in-flight ingestion session. We still
  // wipe local state immediately even if the network calls fail — the
  // server's TTL-based janitor will clean up abandoned sessions.
  for (const f of cachedFiles) {
    if (f.session_id) {
      void cancelSession(f.session_id);
    }
  }
  cachedFiles = [];
  saveFiles(cachedFiles);
  fileObjectCache.clear();
  notifySubscribers();
}

function updateFile(id: string, updates: Partial<UploadedFile>) {
  cachedFiles = cachedFiles.map((f) => (f.id === id ? { ...f, ...updates } : f));
  saveFiles(cachedFiles);
  notifySubscribers();
}

function setThinking(isThinking: boolean, message: string = '') {
  thinkingState = { isThinking, message };
  notifySubscribers();
}

/**
 * Callback fired the moment a HITL step completes and the wizard should
 * (re-)open. The page passes one of these in to `startExtraction` so the
 * modal can react to step transitions even if the user navigated away
 * mid-run.
 */
export type WizardStepCallback = (
  fileId: string,
  step: IngestionStep,
) => void;

/**
 * Public entry point: dispatches to either the document-driven HITL flow
 * (PDF/DOCX/TXT — kicks off step 1: document chunking + FIBO doc gate)
 * or the tabular flow (CSV/XLSX, parsed directly via the CSV import
 * service — no LLM, no ontology, no wizard).
 *
 * Both flows ultimately populate `extractedData` so the popup can render
 * results uniformly. For the document flow the wizard handles steps 2-4
 * via {@link runExtractionStep}, {@link runGuardrailStep}, and
 * {@link runImportStep}.
 */
export async function startExtraction(
  file: UploadedFile,
  actualFile: File,
  vertical: string,
  subVertical: string,
  capability: string,
  depth: string,
  onWizardStep: WizardStepCallback,
) {
  registerFileObject(file.id, actualFile);

  const sourceType = detectSourceType(file.name);
  if (sourceType === 'tabular') {
    return startTabularExtraction(file, actualFile, (_data, fileId) => {
      // Tabular files skip the wizard entirely — open the modal at the
      // import step so the user can review and click "Import to Graph".
      onWizardStep(fileId, 'import');
    });
  }
  return startHitlDocumentSession(
    file,
    actualFile,
    vertical,
    subVertical,
    capability,
    depth,
    onWizardStep,
  );
}

/**
 * CSV/XLSX flow: a single POST to `/upload/tabular-preview` returns an
 * `ExtractedCapabilityModel` (capabilities in the file are aggregated
 * server-side). No streaming, no guardrail.
 */
async function startTabularExtraction(
  file: UploadedFile,
  actualFile: File,
  onModalOpen: (data: ExtractedCapabilityModel, fileId: string) => void,
) {
  const controller = new AbortController();
  activeExtractions.set(file.id, controller);

  updateFile(file.id, {
    status: 'uploading',
    progress: 20,
    sourceType: 'tabular',
  });
  setThinking(true, 'Parsing tabular file...');

  const formData = new FormData();
  formData.append('file', actualFile);

  try {
    const response = await fetch(`${API_BASE}/upload/tabular-preview`, {
      method: 'POST',
      body: formData,
      signal: controller.signal,
    });

    if (!response.ok) {
      let detail = `Preview failed: ${response.statusText}`;
      try {
        const errorPayload = await response.json();
        if (errorPayload?.detail) detail = errorPayload.detail;
      } catch {
        // body was not JSON
      }
      throw new Error(detail);
    }

    const payload = await response.json();
    const model: ExtractedCapabilityModel | undefined = payload.model;

    if (!model) {
      throw new Error('File parsed successfully but no capability data was returned.');
    }

    updateFile(file.id, {
      status: 'success',
      progress: 100,
      sourceType: 'tabular',
      extractedData: model,
      ontology_status: 'success',
      current_step: 'import',
    });
    setThinking(false);

    try {
      onModalOpen(model, file.id);
    } catch {
      pendingModalData = { data: model, fileId: file.id };
    }
  } catch (error: any) {
    if (error?.name === 'AbortError') {
      console.log('Tabular extraction aborted for', file.id);
      return;
    }
    console.error('Tabular preview error:', error);
    const errorMsg = error instanceof Error ? error.message : 'Unknown error occurred';
    updateFile(file.id, { status: 'error', error: errorMsg, sourceType: 'tabular' });
    // Stash the failure so the page can surface it as a toast even if the
    // user navigated away during the upload.
    pendingRejection = {
      fileId: file.id,
      fileName: file.name,
      reason: errorMsg,
    };
    setThinking(false);
  } finally {
    activeExtractions.delete(file.id);
    if (activeExtractions.size === 0) {
      setThinking(false);
    }
  }
}

// ---------------------------------------------------------------------------
// Human-in-the-Loop ingestion flow (PDF / DOCX / TXT)
//
// The document flow is split into 4 wizard steps backed by the new
// `/upload/session/...` endpoints. Each step is a stand-alone async
// function so the page can drive it from a "Next" button:
//
//   1. startHitlDocumentSession   → POST /upload/session/start
//   2. runExtractionStep          → POST /upload/session/{id}/extract
//   3. runGuardrailStep           → POST /upload/session/{id}/guardrail
//   4. runImportStep              → POST /upload/session/{id}/import
//
// Cancellation: abandoning a session (page reload, "Clear") fires a
// best-effort POST /upload/session/{id}/cancel so the backend can drop
// the temp file. We DO NOT rely on the cancel call to succeed (offline
// users / closed tab / server restart) — the backend GC reaps stale
// sessions after `SESSION_TTL_SECONDS`.
// ---------------------------------------------------------------------------

async function startHitlDocumentSession(
  file: UploadedFile,
  actualFile: File,
  vertical: string,
  subVertical: string,
  capability: string,
  depth: string,
  onWizardStep: WizardStepCallback,
) {
  const controller = new AbortController();
  activeExtractions.set(file.id, controller);

  updateFile(file.id, {
    status: 'validating',
    progress: 15,
    sourceType: 'document',
  });
  setThinking(true, 'Uploading document and validating against FIBO ontology...');

  const formData = new FormData();
  formData.append('file', actualFile);

  const params = new URLSearchParams();
  if (vertical.trim()) params.append('vertical', vertical.trim());
  if (subVertical.trim()) params.append('subvertical', subVertical.trim());
  if (capability.trim()) params.append('capability', capability.trim());
  params.append('extraction_depth', depth);

  const url = `${API_BASE}/upload/session/start${
    params.toString() ? `?${params.toString()}` : ''
  }`;

  try {
    const response = await fetch(url, {
      method: 'POST',
      body: formData,
      signal: controller.signal,
    });

    if (!response.ok) {
      let detail = `Upload failed: ${response.statusText}`;
      try {
        const err = await response.json();
        if (err?.detail) detail = err.detail;
      } catch {
        // body not JSON
      }
      throw new Error(detail);
    }

    const payload = await response.json();
    const docGateRejected =
      payload.is_relevant === false &&
      payload.doc_gate?.available !== false; // unavailable gate is treated as "pass"

    if (docGateRejected) {
      const reason =
        payload.rejection_reason ||
        payload.doc_gate?.relevance?.rejection_reason ||
        'Document does not align with the FIBO ontology.';
      updateFile(file.id, {
        status: 'rejected',
        progress: 100,
        sourceType: 'document',
        session_id: payload.session_id,
        current_step: 'doc_gate',
        ontology: payload.ontology,
        document_relevance: payload.document_relevance,
        evidence_chunks: payload.evidence_chunks,
        chunk_count: payload.chunk_count,
        chunks_path: payload.chunks_path,
        ontology_status: 'document_rejected',
        rejection_reason: reason,
        extractedData: {
          name: file.name,
          description: '',
          vertical: '',
          processes: [],
        },
      });
      pendingRejection = { fileId: file.id, fileName: file.name, reason };
      setThinking(false);
      // Best-effort cleanup of the rejected session.
      void cancelSession(payload.session_id);
      try {
        onWizardStep(file.id, 'doc_gate');
      } catch {
        // page navigated away — the periodic poll on the page will pick this up
      }
      return;
    }

    updateFile(file.id, {
      status: 'awaiting_review',
      progress: 35,
      sourceType: 'document',
      session_id: payload.session_id,
      current_step: 'doc_gate',
      ontology: payload.ontology,
      document_relevance: payload.document_relevance,
      evidence_chunks: payload.evidence_chunks,
      chunk_count: payload.chunk_count,
      chunks_path: payload.chunks_path,
      ontology_status: 'success',
    });
    setThinking(false);

    try {
      onWizardStep(file.id, 'doc_gate');
    } catch {
      // ignore — modal will reopen on next mount via the periodic check
    }
  } catch (error: any) {
    if (error?.name === 'AbortError') return;
    console.error('Upload error:', error);
    const errorMsg = error instanceof Error ? error.message : 'Unknown error occurred';
    updateFile(file.id, { status: 'error', error: errorMsg });
    setThinking(false);
  } finally {
    activeExtractions.delete(file.id);
    if (activeExtractions.size === 0) {
      setThinking(false);
    }
  }
}

/**
 * Step 2 — run the LLM extractor on the session's chunks. Pure
 * server-side call; the result is the raw extracted capability model
 * (no FIBO guardrail yet).
 */
export async function runExtractionStep(fileId: string): Promise<void> {
  const file = cachedFiles.find((f) => f.id === fileId);
  if (!file?.session_id) {
    throw new Error('No active ingestion session for this file.');
  }

  updateFile(fileId, { status: 'extracting', progress: 55 });
  setThinking(true, 'Running LLM extraction on document chunks...');

  try {
    const response = await fetch(
      `${API_BASE}/upload/session/${file.session_id}/extract`,
      { method: 'POST' },
    );
    if (!response.ok) {
      let detail = `Extraction failed: ${response.statusText}`;
      try {
        const err = await response.json();
        if (err?.detail) detail = err.detail;
      } catch {
        // not JSON
      }
      throw new Error(detail);
    }

    const payload = await response.json();
    const extracted: ExtractedCapabilityModel = payload.extracted_data;

    updateFile(fileId, {
      status: 'awaiting_review',
      progress: 70,
      current_step: 'extraction',
      rawExtractedData: extracted,
      extractedData: extracted,
    });
    setThinking(false);
  } catch (error: any) {
    const errorMsg = error instanceof Error ? error.message : 'Unknown error';
    updateFile(fileId, { status: 'error', error: errorMsg });
    setThinking(false);
    throw error;
  }
}

/**
 * Step 3 — apply the FIBO post-extraction guardrail and trim the model
 * to the accepted processes. Updates the file's `extractedData` to the
 * guardrail-filtered version while keeping `rawExtractedData` for diff
 * comparison if the UI wants it.
 */
export async function runGuardrailStep(fileId: string): Promise<void> {
  const file = cachedFiles.find((f) => f.id === fileId);
  if (!file?.session_id) {
    throw new Error('No active ingestion session for this file.');
  }

  updateFile(fileId, { status: 'validating', progress: 85 });
  setThinking(true, 'Applying FIBO ontology guardrail to extracted processes...');

  try {
    const response = await fetch(
      `${API_BASE}/upload/session/${file.session_id}/guardrail`,
      { method: 'POST' },
    );
    if (!response.ok) {
      let detail = `Guardrail failed: ${response.statusText}`;
      try {
        const err = await response.json();
        if (err?.detail) detail = err.detail;
      } catch {
        // not JSON
      }
      throw new Error(detail);
    }

    const payload = await response.json();
    const annotated: ExtractedCapabilityModel = payload.annotated_data;
    const ontologyStatus = payload.ontology_status as
      | 'success'
      | 'ontology_rejected';

    if (ontologyStatus === 'ontology_rejected') {
      const candidates = payload.guardrail?.candidate_count ?? 0;
      const threshold = payload.guardrail?.threshold;
      const reason =
        `LLM extracted ${candidates} candidate process(es) but none aligned with` +
        ` any FIBO ontology concept above the` +
        `${threshold !== undefined ? ` ${threshold.toFixed(2)}` : ''} threshold.`;
      updateFile(fileId, {
        status: 'rejected',
        progress: 100,
        current_step: 'guardrail',
        extractedData: annotated,
        ontology: payload.ontology,
        guardrail: payload.guardrail,
        document_relevance: payload.document_relevance,
        ontology_status: 'ontology_rejected',
        rejection_reason: reason,
      });
      pendingRejection = { fileId, fileName: file.name, reason };
      setThinking(false);
      // Server has nothing else to do for a rejected guardrail run.
      void cancelSession(file.session_id);
      return;
    }

    updateFile(fileId, {
      status: 'awaiting_review',
      progress: 95,
      current_step: 'guardrail',
      extractedData: annotated,
      ontology: payload.ontology,
      guardrail: payload.guardrail,
      document_relevance: payload.document_relevance,
      chunks_path: payload.chunks_path,
      ontology_status: 'success',
    });
    setThinking(false);
  } catch (error: any) {
    const errorMsg = error instanceof Error ? error.message : 'Unknown error';
    updateFile(fileId, { status: 'error', error: errorMsg });
    setThinking(false);
    throw error;
  }
}

/**
 * Optional process/subprocess selection sent to the import endpoint when
 * the user has unchecked items in the preview. ``selected_process_indices``
 * indexes into the guardrail-approved processes returned in step 3, and
 * ``selected_subprocess_indices`` indexes into each process's subprocesses.
 * Omit either key to import "all" at that level.
 */
export interface ImportSelection {
  selected_process_indices?: number[];
  selected_subprocess_indices?: Record<string, number[]>;
}

/**
 * Step 4 — persist the guardrail-approved model into Neo4j. Returns the
 * import summary so the caller can render counts.
 *
 * Pass ``selection`` to narrow the imported model to a subset of the
 * guardrail-approved processes/subprocesses (driven by checkboxes in the
 * preview). When omitted, the full guardrail output is imported.
 */
export async function runImportStep(
  fileId: string,
  selection?: ImportSelection,
): Promise<any> {
  const file = cachedFiles.find((f) => f.id === fileId);
  if (!file?.session_id) {
    throw new Error('No active ingestion session for this file.');
  }

  setThinking(true, 'Importing capabilities into Neo4j...');
  try {
    const hasSelection =
      !!selection &&
      (selection.selected_process_indices !== undefined ||
        (selection.selected_subprocess_indices &&
          Object.keys(selection.selected_subprocess_indices).length > 0));

    const response = await fetch(
      `${API_BASE}/upload/session/${file.session_id}/import`,
      {
        method: 'POST',
        headers: hasSelection ? { 'Content-Type': 'application/json' } : undefined,
        body: hasSelection ? JSON.stringify(selection) : undefined,
      },
    );
    if (!response.ok) {
      let detail = `Import failed: ${response.statusText}`;
      try {
        const err = await response.json();
        if (err?.detail) detail = err.detail;
      } catch {
        // not JSON
      }
      throw new Error(detail);
    }
    const payload = await response.json();
    updateFile(fileId, {
      status: 'success',
      progress: 100,
      current_step: 'import',
    });
    setThinking(false);
    return payload.summary || {};
  } catch (error: any) {
    setThinking(false);
    throw error;
  }
}

/**
 * Mark a file as successfully imported.
 *
 * Used by the page-level "combined import" flow when several documents
 * are merged under one capability name and persisted via a single
 * ``/upload/import-to-graph`` call. Each contributing file is finalised
 * here so the UI status pill flips from "Review guardrail" to "Done"
 * without going through the per-file ``runImportStep`` path.
 */
export function markFileImported(fileId: string): void {
  updateFile(fileId, {
    status: 'success',
    progress: 100,
    current_step: 'import',
  });
}

/**
 * Best-effort cancel: drops the backend session so the temp upload is
 * deleted promptly. Errors are swallowed because the GC reaps abandoned
 * sessions automatically after the TTL window.
 */
export async function cancelSession(sessionId?: string): Promise<void> {
  if (!sessionId) return;
  try {
    await fetch(`${API_BASE}/upload/session/${sessionId}/cancel`, {
      method: 'POST',
    });
  } catch (e) {
    console.warn('Failed to cancel ingestion session:', e);
  }
}

export function getThinkingState() {
  return { ...thinkingState };
}

export function getPendingModalData() {
  const data = pendingModalData;
  pendingModalData = null;
  return data;
}

export function hasPendingModal(): boolean {
  return pendingModalData !== null;
}

/**
 * Pop the most recent rejection notification (if any) so the page can
 * surface it as a toast even if the user navigated away during extraction.
 */
export function getPendingRejection() {
  const rejection = pendingRejection;
  pendingRejection = null;
  return rejection;
}

export function hasPendingRejection(): boolean {
  return pendingRejection !== null;
}
