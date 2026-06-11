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
 */
export type FileStatus =
  | 'pending'
  | 'uploading'
  | 'extracting'
  | 'validating'
  | 'success'
  | 'rejected'
  | 'error';

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
}

const TABULAR_EXTENSIONS = ['.csv', '.xlsx', '.xls'];

export function detectSourceType(fileName: string): SourceType {
  const lower = fileName.toLowerCase();
  return TABULAR_EXTENSIONS.some((ext) => lower.endsWith(ext)) ? 'tabular' : 'document';
}

interface ExtractionEvent {
  status:
    | 'started'
    | 'cache_hit'
    | 'loading'
    | 'validating_document'
    | 'document_validated'
    | 'document_rejected'
    | 'extracting'
    | 'validating'
    | 'ontology_applied'
    | 'success'
    | 'error';
  progress?: number;
  message?: string;
  data?: ExtractedCapabilityModel | null;
  output_path?: string;
  chunks_path?: string;
  filename?: string;
  error?: string;
  type?: string;
  cached?: boolean;
  ontology?: OntologyMeta;
  document_relevance?: DocumentRelevance;
  guardrail?: OntologyGuardrailSummary;
  ontology_status?: 'success' | 'document_rejected' | 'ontology_rejected';
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
  cachedFiles = cachedFiles.filter((f) => f.id !== id);
  saveFiles(cachedFiles);
  dropFileObject(id);
  notifySubscribers();
}

export function clearAllFiles() {
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
 * Public entry point: dispatches to either the LLM-backed document flow
 * (PDF/DOCX/TXT, with FIBO guardrail) or the tabular flow (CSV/XLSX,
 * parsed directly via the CSV import service — no LLM, no ontology).
 *
 * Both flows ultimately populate `extractedData` with the same shape and
 * trigger `onModalOpen` with that single model — the popup looks identical.
 */
export async function startExtraction(
  file: UploadedFile,
  actualFile: File,
  vertical: string,
  subVertical: string,
  depth: string,
  onModalOpen: (data: ExtractedCapabilityModel, fileId: string) => void,
) {
  registerFileObject(file.id, actualFile);

  const sourceType = detectSourceType(file.name);
  if (sourceType === 'tabular') {
    return startTabularExtraction(file, actualFile, onModalOpen);
  }
  return startDocumentExtraction(file, actualFile, vertical, subVertical, depth, onModalOpen);
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

async function startDocumentExtraction(
  file: UploadedFile,
  actualFile: File,
  vertical: string,
  subVertical: string,
  depth: string,
  onModalOpen: (data: ExtractedCapabilityModel, fileId: string) => void,
) {
  const controller = new AbortController();
  activeExtractions.set(file.id, controller);

  updateFile(file.id, { status: 'uploading', progress: 10, sourceType: 'document' });

  const formData = new FormData();
  formData.append('file', actualFile);

  const params = new URLSearchParams();
  if (vertical.trim()) params.append('vertical', vertical.trim());
  if (subVertical.trim()) params.append('subvertical', subVertical.trim());
  params.append('extraction_depth', depth);

  const url = `${API_BASE}/upload/pdf${params.toString() ? `?${params.toString()}` : ''}`;
  try {
    const response = await fetch(url, {
      method: 'POST',
      body: formData,
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new Error(`Upload failed: ${response.statusText}`);
    }

    const reader = response.body?.getReader();
    if (!reader) throw new Error('No response body');

    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');

      for (let i = 0; i < lines.length - 1; i++) {
        if (lines[i].trim()) {
          try {
            const event: ExtractionEvent = JSON.parse(lines[i]);
            handleExtractionEvent(file.id, file.name, event, onModalOpen);
          } catch (e) {
            console.error('Failed to parse event:', e);
          }
        }
      }

      buffer = lines[lines.length - 1];
    }

    if (buffer.trim()) {
      try {
        const event: ExtractionEvent = JSON.parse(buffer);
        handleExtractionEvent(file.id, file.name, event, onModalOpen);
      } catch (e) {
        console.error('Failed to parse final event:', e);
      }
    }
  } catch (error: any) {
    if (error.name === 'AbortError') {
      console.log('Extraction aborted for', file.id);
      return;
    }
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
 * Translate the backend's verbose `ontology_status` / event payload into
 * a short human-readable rejection reason for the UI.
 */
function buildRejectionReason(event: ExtractionEvent): string {
  // 1. Pre-LLM document gate rejection
  if (event.status === 'document_rejected' || event.ontology_status === 'document_rejected') {
    if (event.document_relevance?.rejection_reason) {
      return event.document_relevance.rejection_reason;
    }
    if (event.message) return event.message;
    return 'Document does not align with the FIBO ontology.';
  }

  // 2. Post-LLM guardrail rejection (LLM ran but no process passed)
  if (event.ontology_status === 'ontology_rejected') {
    const candidates = event.guardrail?.candidate_count ?? 0;
    const threshold = event.guardrail?.threshold;
    return (
      `LLM extracted ${candidates} candidate process(es) but none aligned with` +
      ` any FIBO ontology concept above the` +
      `${threshold !== undefined ? ` ${threshold.toFixed(2)}` : ''} threshold.`
    );
  }

  return event.message || 'Document rejected by the ontology guardrail.';
}

/**
 * Decide whether a `success` event from the backend should actually be
 * treated as a rejection by the UI.
 *
 * The backend keeps `status: "success"` for the *streaming envelope* even
 * when no process passes the guardrail (so existing clients don't break),
 * and signals the real outcome via `ontology_status` and `processes: []`.
 */
function isRejectedSuccess(event: ExtractionEvent): boolean {
  if (event.ontology_status === 'document_rejected' || event.ontology_status === 'ontology_rejected') {
    return true;
  }
  // Defensive: if data is empty, treat as rejection.
  if (event.data && Array.isArray(event.data.processes) && event.data.processes.length === 0) {
    return true;
  }
  return false;
}

function handleExtractionEvent(
  fileId: string,
  fileName: string,
  event: ExtractionEvent,
  onModalOpen: (data: ExtractedCapabilityModel, fileId: string) => void,
) {
  switch (event.status) {
    case 'started':
      updateFile(fileId, { status: 'uploading', progress: 5 });
      setThinking(true, 'Starting extraction...');
      break;

    case 'loading':
      updateFile(fileId, {
        status: 'extracting',
        progress: Math.min(event.progress || 30, 50),
      });
      setThinking(true, event.message || 'Loading document...');
      break;

    case 'validating_document':
      updateFile(fileId, {
        status: 'validating',
        progress: Math.min(event.progress || 38, 50),
      });
      setThinking(true, event.message || 'Validating document against FIBO ontology...');
      break;

    case 'document_validated':
      updateFile(fileId, {
        status: 'validating',
        progress: Math.min(event.progress || 40, 50),
        ontology: event.ontology,
        document_relevance: event.document_relevance,
      });
      setThinking(true, event.message || 'Document validated. Starting LLM extraction...');
      break;

    case 'document_rejected': {
      const reason = buildRejectionReason(event);
      updateFile(fileId, {
        status: 'rejected',
        progress: 100,
        ontology: event.ontology,
        document_relevance: event.document_relevance,
        ontology_status: 'document_rejected',
        rejection_reason: reason,
        // Synthesise a minimal extractedData so the modal has something to
        // show (filename + reason); processes array is intentionally empty.
        extractedData: event.data || {
          name: fileName,
          description: '',
          vertical: '',
          processes: [],
        },
      });
      pendingRejection = { fileId, fileName, reason };
      setThinking(false);
      break;
    }

    case 'extracting':
      updateFile(fileId, {
        status: 'extracting',
        progress: Math.min(event.progress || 60, 95),
      });
      setThinking(true, event.message || 'LLM extracting capabilities...');
      break;

    case 'validating':
      updateFile(fileId, {
        status: 'extracting',
        progress: Math.min(event.progress || 80, 95),
      });
      setThinking(true, event.message || 'Validating extracted processes...');
      break;

    case 'ontology_applied':
      updateFile(fileId, {
        status: 'extracting',
        progress: Math.min(event.progress || 90, 98),
        ontology: event.ontology,
        guardrail: event.guardrail,
      });
      setThinking(true, event.message || 'FIBO ontology applied to extracted processes.');
      break;

    case 'cache_hit': {
      // Cache hit: still re-applies the post-LLM guardrail server-side. Treat
      // identically to `success` here — the same rejection rules apply.
      const rejected = isRejectedSuccess(event);
      const finalData = event.data ?? undefined;
      if (rejected) {
        const reason = buildRejectionReason(event);
        updateFile(fileId, {
          status: 'rejected',
          progress: 100,
          extractedData: finalData,
          ontology: event.ontology,
          guardrail: event.guardrail,
          ontology_status: event.ontology_status || 'ontology_rejected',
          rejection_reason: reason,
        });
        pendingRejection = { fileId, fileName, reason };
        setThinking(false);
      } else {
        updateFile(fileId, {
          status: 'success',
          progress: 100,
          extractedData: finalData,
          ontology: event.ontology,
          guardrail: event.guardrail,
          ontology_status: 'success',
        });
        setThinking(false);
        if (finalData) {
          try {
            onModalOpen(finalData, fileId);
          } catch (e) {
            pendingModalData = { data: finalData, fileId };
          }
        }
      }
      break;
    }

    case 'success': {
      const rejected = isRejectedSuccess(event);
      const finalData = event.data ?? undefined;

      if (rejected) {
        const reason = buildRejectionReason(event);
        updateFile(fileId, {
          status: 'rejected',
          progress: 100,
          extractedData: finalData,
          ontology: event.ontology,
          document_relevance: event.document_relevance,
          guardrail: event.guardrail,
          ontology_status: event.ontology_status || 'ontology_rejected',
          rejection_reason: reason,
          chunks_path: event.chunks_path,
        });
        pendingRejection = { fileId, fileName, reason };
        setThinking(false);
        break;
      }

      if (finalData) {
        updateFile(fileId, {
          status: 'success',
          progress: 100,
          extractedData: finalData,
          chunks_path: event.chunks_path,
          ontology: event.ontology,
          document_relevance: event.document_relevance,
          guardrail: event.guardrail,
          ontology_status: 'success',
        });
        setThinking(false);
        try {
          onModalOpen(finalData, fileId);
        } catch (e) {
          pendingModalData = { data: finalData, fileId };
        }
      }
      break;
    }

    case 'error':
      updateFile(fileId, { status: 'error', error: event.error });
      setThinking(false);
      break;
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
