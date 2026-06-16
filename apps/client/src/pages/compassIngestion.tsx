import React, { useState, useRef, useEffect, useMemo } from 'react';
import {
  FiUpload,
  FiFile,
  FiX,
  FiCheckCircle,
  FiAlertCircle,
  FiLoader,
  FiSlash,
  FiArrowRight,
  FiSearch,
  FiCpu,
  FiShield,
  FiDatabase,
} from 'react-icons/fi';
import toast, { Toaster } from 'react-hot-toast';
import * as ExtractionManager from '../utils/extractionManager';
import { API_BASE } from '../utils/apiBase';

import type {
  OntologyMeta,
  DocumentRelevance,
  OntologyGuardrailSummary,
  FileStatus,
  SourceType,
  IngestionStep,
  EvidenceChunk,
  ImportSelection,
} from '../utils/extractionManager';

/**
 * Optional checkbox-driven selection passed down to the preview to let
 * the user trim which processes / subprocesses get imported. Omit this
 * prop on review-only screens (e.g. the raw extraction panel) to render
 * a plain list without checkboxes.
 */
interface ProcessSelectionAPI {
  isProcessChecked: (procIdx: number) => boolean;
  isSubprocessChecked: (procIdx: number, subIdx: number) => boolean;
  toggleProcess: (procIdx: number) => void;
  toggleSubprocess: (procIdx: number, subIdx: number) => void;
}

interface ExtractedCapabilityModel {
  id?: number;
  name: string;
  description: string;
  vertical: string;
  subvertical?: string;
  processes: ExtractedProcess[];
}

interface ExtractedProcess {
  id?: number;
  name: string;
  level: string;
  description: string;
  category?: string;
  subprocesses: ExtractedSubProcess[];
}

interface ExtractedSubProcess {
  id?: number;
  name: string;
  description: string;
  category?: string;
  data_entities?: unknown[];
}

interface UploadedFile {
  id: string;
  name: string;
  size: number;
  type: string;
  status: FileStatus;
  progress: number;
  error?: string;
  extractedData?: ExtractedCapabilityModel;
  /**
   * Distinguishes free-form documents (PDF/DOCX/TXT — LLM extraction) from
   * tabular uploads (CSV/XLSX — direct mapping). Only affects which import
   * endpoint the "Import to Graph" button hits; the preview popup is the same.
   */
  sourceType?: SourceType;
  chunks_path?: string;
  ontology?: OntologyMeta;
  document_relevance?: DocumentRelevance;
  guardrail?: OntologyGuardrailSummary;
  ontology_status?: 'success' | 'document_rejected' | 'ontology_rejected';
  rejection_reason?: string;

  // HITL wizard state
  session_id?: string;
  current_step?: IngestionStep;
  evidence_chunks?: EvidenceChunk[];
  chunk_count?: number;
  rawExtractedData?: ExtractedCapabilityModel;
}

function loadPersistedFiles(): UploadedFile[] {
  return ExtractionManager.loadPersistedFiles() as UploadedFile[];
}

// ---------------------------------------------------------------------------
// HITL wizard step panels
// ---------------------------------------------------------------------------

/**
 * Step 1 panel — render the FIBO document gate evidence so the user can
 * see *why* the document is considered relevant before paying for the
 * LLM extraction. Highlights:
 *   - the top FIBO concepts the document scored against,
 *   - for each concept, the chunk that drove the match (passed chunk),
 *   - whether the chunk crossed the chunk-level threshold (Stage 1's
 *     "passed chunks" definition).
 */
const DocGatePanel: React.FC<{ activeFile: UploadedFile }> = ({ activeFile }) => {
  const relevance = activeFile.document_relevance;
  const evidence = activeFile.evidence_chunks || [];

  return (
    <div className="space-y-4 text-sm text-gray-700">
      <div className="rounded border border-indigo-200 bg-indigo-50 p-3">
        <p className="font-semibold text-indigo-900 mb-1">
          Step 1 · Ontology validation
        </p>
        <p className="text-indigo-800 text-xs">
          The document was chunked and scored against the FIBO ontology. Below
          are the top concepts the document matched and the chunks that drove
          each match. Click <strong>Next</strong> to run the LLM extractor.
        </p>
      </div>

      {relevance && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
          <Stat label="Best score" value={relevance.aggregate_score?.toFixed(3) ?? '—'} />
          <Stat label="Doc threshold" value={relevance.doc_threshold?.toFixed(3) ?? '—'} />
          <Stat label="Chunk threshold" value={relevance.chunk_threshold?.toFixed(3) ?? '—'} />
          <Stat label="Chunks scanned" value={String(relevance.chunk_count ?? activeFile.chunk_count ?? '—')} />
        </div>
      )}

      {relevance?.top_concepts && relevance.top_concepts.length > 0 && (
        <div>
          <p className="font-semibold mb-2">
            Top FIBO concepts ({relevance.top_concepts.length})
          </p>
          <div className="space-y-2">
            {relevance.top_concepts.map((hit, i) => (
              <div
                key={hit.concept_iri || i}
                className="border border-gray-200 rounded p-2 bg-gray-50"
              >
                <div className="flex items-center justify-between">
                  <p className="font-medium text-gray-800">
                    {i + 1}. {hit.concept_label}
                  </p>
                  <span className="text-xs px-2 py-0.5 bg-indigo-100 text-indigo-800 rounded">
                    score {hit.best_chunk_score?.toFixed(3)}
                  </span>
                </div>
                {hit.concept_definition && (
                  <p className="text-xs text-gray-600 mt-1 italic">
                    {hit.concept_definition}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      <div>
        <p className="font-semibold mb-2">
          Passed chunks · {evidence.length}
        </p>
        {evidence.length === 0 ? (
          <p className="text-xs text-gray-500">
            No matching chunks were captured for this document.
          </p>
        ) : (
          <div className="space-y-2">
            {evidence.map((ev, idx) => (
              <div
                key={`${ev.chunk_index}-${ev.concept_iri ?? idx}`}
                className={`border rounded p-2.5 text-xs ${
                  ev.passes_chunk_threshold
                    ? 'border-green-200 bg-green-50'
                    : 'border-amber-200 bg-amber-50'
                }`}
              >
                <div className="flex items-center justify-between gap-2 mb-1">
                  <p className="font-medium text-gray-800">
                    Chunk #{ev.chunk_index}
                    {ev.page !== undefined && ev.page !== null
                      ? ` · page ${ev.page}`
                      : ''}
                    {' · '}
                    <span className="text-gray-500 font-normal">
                      matched <strong>{ev.concept_label || '—'}</strong>
                    </span>
                  </p>
                  <span className="px-2 py-0.5 bg-white border border-gray-200 rounded">
                    score {Number(ev.score ?? 0).toFixed(3)}
                  </span>
                </div>
                {ev.matched_synonym &&
                  ev.matched_synonym.toLowerCase() !==
                    (ev.concept_label || '').toLowerCase() && (
                    <p className="text-gray-500 mb-1">
                      via synonym: <em>{ev.matched_synonym}</em>
                    </p>
                  )}
                <p className="text-gray-700 whitespace-pre-wrap leading-snug">
                  {ev.excerpt || ev.text}
                </p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

/**
 * Step 2 panel — show the raw LLM extraction output (unfiltered). The
 * user reviews the processes/subprocesses the agent produced before the
 * FIBO post-extraction guardrail trims it down in step 3.
 */
const ExtractionPanel: React.FC<{
  activeFile: UploadedFile;
  modalData: ExtractedCapabilityModel;
}> = ({ modalData }) => {
  const procCount = modalData.processes?.length ?? 0;

  return (
    <div className="space-y-4 text-sm text-gray-700">
      <div className="rounded border border-indigo-200 bg-indigo-50 p-3">
        <p className="font-semibold text-indigo-900 mb-1">
          Step 2 · LLM extraction (pre-guardrail)
        </p>
        <p className="text-indigo-800 text-xs">
          The DeepAgent extracted <strong>{procCount}</strong> candidate
          process(es) from the document chunks. None of these have been
          checked against the FIBO ontology yet. Click <strong>Next</strong>{' '}
          to run the post-extraction guardrail.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4 text-xs">
        <div>
          <p className="font-semibold text-gray-600 uppercase tracking-wide">Vertical</p>
          <p className="text-gray-900 mt-0.5">{modalData.vertical || '—'}</p>
        </div>
        <div>
          <p className="font-semibold text-gray-600 uppercase tracking-wide">SubVertical</p>
          <p className="text-gray-900 mt-0.5">{modalData.subvertical || '—'}</p>
        </div>
      </div>

      {modalData.description && (
        <div>
          <p className="font-semibold text-gray-600 uppercase tracking-wide text-xs">
            Capability description
          </p>
          <p className="text-gray-900 mt-0.5">{modalData.description}</p>
        </div>
      )}

      <div>
        <p className="font-semibold mb-2">Extracted processes ({procCount})</p>
        {procCount === 0 ? (
          <p className="text-xs text-gray-500 border border-amber-200 bg-amber-50 rounded p-2">
            The LLM did not produce any processes. The guardrail step will reject this.
          </p>
        ) : (
          <ProcessList processes={modalData.processes} showAlignment={false} />
        )}
      </div>
      <p className="text-xs text-gray-400">
        Note: ontology alignment metadata is added in the next step.
      </p>
    </div>
  );
};

/**
 * Step 3 / final panel — show the guardrail-trimmed model and (when
 * available) the candidates the guardrail rejected so the user can see
 * exactly what FIBO let through.
 */
const CapabilityModelView: React.FC<{
  modalData: ExtractedCapabilityModel;
  guardrail?: OntologyGuardrailSummary;
  showGuardrailRejected?: boolean;
  selection?: ProcessSelectionAPI;
  selectAllAction?: { onSelectAll: () => void; onDeselectAll: () => void };
}> = ({
  modalData,
  guardrail,
  showGuardrailRejected = false,
  selection,
  selectAllAction,
}) => {
  const procCount = modalData.processes?.length ?? 0;
  const rejectedCandidates = (guardrail?.candidates || []).filter(
    (c: any) => !c.accepted,
  );

  return (
    <div className="space-y-3 text-sm text-gray-700">
      <div className="grid grid-cols-2 gap-4 text-xs">
        <div>
          <p className="font-semibold text-gray-600 uppercase tracking-wide">Vertical</p>
          <p className="text-gray-900 mt-0.5">{modalData.vertical || '—'}</p>
        </div>
        <div>
          <p className="font-semibold text-gray-600 uppercase tracking-wide">SubVertical</p>
          <p className="text-gray-900 mt-0.5">{modalData.subvertical || '—'}</p>
        </div>
      </div>

      {modalData.description && (
        <div>
          <p className="font-semibold text-gray-600 uppercase tracking-wide text-xs">
            Capability description
          </p>
          <p className="text-gray-900 mt-0.5">{modalData.description}</p>
        </div>
      )}

      {guardrail?.applied && (
        <div className="rounded border border-green-200 bg-green-50 p-2 text-xs">
          FIBO guardrail kept{' '}
          <strong>{guardrail.accepted_count ?? procCount}</strong> of{' '}
          {guardrail.candidate_count ?? procCount} candidate process(es)
          (threshold {guardrail.threshold?.toFixed(2)}).
        </div>
      )}

      <div>
        <div className="flex items-center justify-between mb-2">
          <p className="font-semibold">Accepted processes ({procCount})</p>
          {selection && selectAllAction && procCount > 0 && (
            <div className="flex items-center gap-2 text-xs">
              <button
                type="button"
                onClick={selectAllAction.onSelectAll}
                className="px-2 py-0.5 border border-indigo-200 text-indigo-700 rounded hover:bg-indigo-50"
                title="Mark every process and subprocess for import"
              >
                Select all
              </button>
              <button
                type="button"
                onClick={selectAllAction.onDeselectAll}
                className="px-2 py-0.5 border border-gray-200 text-gray-600 rounded hover:bg-gray-50"
                title="Clear every process selection"
              >
                Deselect all
              </button>
            </div>
          )}
        </div>
        {selection && procCount > 0 && (
          <p className="text-xs text-gray-500 mb-2">
            Uncheck any process or subprocess to exclude it from the graph
            import. Unchecking a process disables its subprocess checkboxes.
          </p>
        )}
        {procCount === 0 ? (
          <p className="text-xs text-gray-500">No processes available.</p>
        ) : (
          <ProcessList
            processes={modalData.processes}
            showAlignment
            selection={selection}
          />
        )}
      </div>

      {showGuardrailRejected && rejectedCandidates.length > 0 && (
        <div>
          <p className="font-semibold mb-2 text-gray-700">
            Rejected by guardrail ({rejectedCandidates.length})
          </p>
          <div className="space-y-1">
            {rejectedCandidates.map((c: any, i: number) => (
              <div
                key={`${c.process_index ?? i}`}
                className="border border-gray-200 rounded p-2 bg-gray-50 text-xs"
              >
                <div className="flex items-center justify-between">
                  <p className="font-medium text-gray-800">{c.process_name}</p>
                  <span className="px-2 py-0.5 bg-red-100 text-red-700 rounded">
                    score {Number(c.score).toFixed(3)} · {c.reason}
                  </span>
                </div>
                <p className="text-gray-600 mt-1">
                  best match: <em>{c.best_concept_label || '—'}</em>
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

/**
 * Rejection panel — used in two cases:
 *   - the document failed the pre-LLM gate (no LLM was called),
 *   - the post-LLM guardrail rejected every extracted process.
 */
const RejectionPanel: React.FC<{ activeFile: UploadedFile }> = ({ activeFile }) => (
  <div className="space-y-4 text-sm text-gray-700">
    <div className="rounded border border-red-200 bg-red-50 p-3">
      <p className="font-semibold text-red-800 mb-1">
        This document did not pass the FIBO ontology guardrail.
      </p>
      <p className="text-red-700">
        {activeFile?.rejection_reason ||
          'The document content does not align with any ontology concept above the configured threshold.'}
      </p>
      <p className="text-xs text-red-600 mt-2">
        Stage:{' '}
        {activeFile?.ontology_status === 'document_rejected'
          ? 'pre-LLM document gate (no extraction was attempted)'
          : 'post-LLM process guardrail (LLM ran but no extracted process aligned with the ontology)'}
      </p>
    </div>

    {activeFile?.document_relevance && (
      <div>
        <p className="font-semibold mb-2">
          Top FIBO concepts evaluated against the document
        </p>
        <div className="text-xs text-gray-500 mb-2">
          Best score: {activeFile.document_relevance.aggregate_score?.toFixed(3)} · Doc
          threshold: {activeFile.document_relevance.doc_threshold?.toFixed(3)} ·{' '}
          {activeFile.document_relevance.chunk_count} chunks scanned
        </div>
        <div className="space-y-2">
          {(activeFile.document_relevance.top_concepts || []).map((hit, i) => (
            <div
              key={hit.concept_iri || i}
              className="border border-gray-200 rounded p-2 bg-gray-50"
            >
              <div className="flex items-center justify-between">
                <p className="font-medium text-gray-800">
                  {i + 1}. {hit.concept_label}
                </p>
                <span className="text-xs px-2 py-0.5 bg-gray-200 rounded">
                  score {hit.best_chunk_score?.toFixed(3)}
                </span>
              </div>
              {hit.concept_definition && (
                <p className="text-xs text-gray-600 mt-1 italic">
                  {hit.concept_definition}
                </p>
              )}
              {hit.best_chunk_excerpt && (
                <p className="text-xs text-gray-500 mt-1">
                  <span className="font-medium">Best chunk: </span>"
                  {hit.best_chunk_excerpt}"
                </p>
              )}
            </div>
          ))}
        </div>
      </div>
    )}

    {activeFile?.guardrail?.applied &&
      (activeFile.guardrail.candidates?.length ?? 0) > 0 && (
        <div>
          <p className="font-semibold mb-2">
            Processes the LLM produced (none cleared the post-extraction guardrail)
          </p>
          <div className="text-xs text-gray-500 mb-2">
            Threshold: {activeFile.guardrail.threshold?.toFixed(3)} · Candidates:{' '}
            {activeFile.guardrail.candidate_count} · Accepted:{' '}
            {activeFile.guardrail.accepted_count} · Rejected:{' '}
            {activeFile.guardrail.rejected_count}
          </div>
          <div className="space-y-1">
            {(activeFile.guardrail.candidates || []).map((c: any, i: number) => (
              <div
                key={i}
                className="border border-gray-200 rounded p-2 bg-gray-50 text-xs"
              >
                <div className="flex items-center justify-between">
                  <p className="font-medium text-gray-800">{c.process_name}</p>
                  <span className="px-2 py-0.5 bg-gray-200 rounded">
                    score {Number(c.score).toFixed(3)}
                  </span>
                </div>
                <p className="text-gray-600 mt-1">
                  best match: <em>{c.best_concept_label || '—'}</em>
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
  </div>
);

/** Tiny helper to render a labelled metric in the wizard. */
const Stat: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className="rounded border border-gray-200 bg-white p-2">
    <p className="text-[11px] text-gray-500 uppercase tracking-wide">{label}</p>
    <p className="text-sm font-semibold text-gray-900 mt-0.5">{value}</p>
  </div>
);

/**
 * Reusable list renderer for processes → subprocesses → data entities →
 * data elements. Used both at the LLM-only step (no alignment metadata)
 * and at the final guardrail-trimmed step (alignment shown when present).
 */
const ProcessList: React.FC<{
  processes: any[];
  showAlignment: boolean;
  selection?: ProcessSelectionAPI;
}> = ({ processes, showAlignment, selection }) => (
  <div className="space-y-2">
    {processes.map((proc, idx) => {
      const procChecked = selection ? selection.isProcessChecked(idx) : true;
      return (
        <div
          key={idx}
          className={`p-2 border rounded bg-gray-50 ${
            selection && !procChecked ? 'opacity-60' : ''
          }`}
        >
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-start gap-2 min-w-0">
              {selection && (
                <input
                  type="checkbox"
                  className="mt-0.5 h-3.5 w-3.5 text-indigo-600 border-gray-300 rounded focus:ring-indigo-500 cursor-pointer"
                  checked={procChecked}
                  onChange={() => selection.toggleProcess(idx)}
                  title={
                    procChecked
                      ? 'Uncheck to skip this process during import'
                      : 'Check to include this process in import'
                  }
                />
              )}
              <p className="font-medium">{proc.name}</p>
            </div>
            <p className="text-xs text-gray-500 shrink-0">{proc.level}</p>
          </div>
          <p className="text-xs text-gray-600 mt-1">{proc.description}</p>

          {showAlignment && (proc as any).ontology_alignment && (
            <p className="text-xs text-indigo-600 mt-1">
              Aligned with FIBO concept{' '}
              <strong>{(proc as any).ontology_alignment.concept_label}</strong> (score{' '}
              {Number((proc as any).ontology_alignment.score).toFixed(3)})
            </p>
          )}

        {(proc.subprocesses || []).length > 0 && (
          <div className="mt-2 ml-2 border-l-2 border-gray-300 pl-2">
            <p className="text-xs font-medium text-gray-700 mb-1">
              Subprocesses ({proc.subprocesses.length})
            </p>
            <div className="space-y-1">
              {proc.subprocesses.map((subproc: any, subIdx: number) => {
                const subChecked = selection
                  ? selection.isSubprocessChecked(idx, subIdx)
                  : true;
                const subDisabled = selection ? !procChecked : false;
                return (
                <div
                  key={subIdx}
                  className={`p-1.5 bg-white border border-gray-200 rounded text-xs ${
                    selection && !subChecked ? 'opacity-60' : ''
                  }`}
                >
                  <div className="flex items-start gap-2">
                    {selection && (
                      <input
                        type="checkbox"
                        className="mt-0.5 h-3 w-3 text-indigo-600 border-gray-300 rounded focus:ring-indigo-500 cursor-pointer disabled:cursor-not-allowed disabled:opacity-50"
                        checked={subChecked && !subDisabled}
                        disabled={subDisabled}
                        onChange={() => selection.toggleSubprocess(idx, subIdx)}
                        title={
                          subDisabled
                            ? 'Enable the parent process to include this subprocess'
                            : subChecked
                            ? 'Uncheck to skip this subprocess during import'
                            : 'Check to include this subprocess in import'
                        }
                      />
                    )}
                    <div className="min-w-0 flex-1">
                      <p className="font-medium text-gray-800">{subproc.name}</p>
                      <p className="text-gray-600 mt-0.5">{subproc.description}</p>
                    </div>
                  </div>

                  {(subproc.data_entities || []).length > 0 && (
                    <div className="mt-1 ml-1 border-l border-gray-300 pl-1">
                      <p className="text-xs font-medium text-gray-600 mb-0.5">
                        Data Entities ({subproc.data_entities.length})
                      </p>
                      <div className="space-y-0.5">
                        {subproc.data_entities.map((dataEnt: any, deIdx: number) => (
                          <div key={deIdx} className="bg-blue-50 p-0.5 rounded text-xs">
                            <p className="font-medium text-blue-800">
                              {dataEnt.data_entity_name}
                            </p>
                            <p className="text-blue-700 text-xs">
                              {dataEnt.data_entity_description}
                            </p>

                            {(dataEnt.data_elements || []).length > 0 && (
                              <div className="mt-0.5 ml-0.5 border-l border-blue-300 pl-0.5">
                                <p className="text-xs text-blue-600 font-medium mb-0.5">
                                  Elements ({dataEnt.data_elements.length})
                                </p>
                                <div className="space-y-0.5">
                                  {dataEnt.data_elements.map(
                                    (dataElem: any, delemIdx: number) => (
                                      <div
                                        key={delemIdx}
                                        className="bg-blue-100 p-0.5 rounded text-xs text-blue-800"
                                      >
                                        <p className="font-medium">
                                          {dataElem.data_element_name}
                                        </p>
                                        <p className="text-blue-700 text-xs">
                                          {dataElem.data_element_description}
                                        </p>
                                      </div>
                                    ),
                                  )}
                                </div>
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
                );
              })}
            </div>
          </div>
        )}
        </div>
      );
    })}
  </div>
);

const CompassIngestion: React.FC = () => {
  const [files, setFiles] = useState<UploadedFile[]>(() => loadPersistedFiles());
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [showModal, setShowModal] = useState<boolean>(false);
  const [modalFileId, setModalFileId] = useState<string | null>(null);
  const [isImporting, setIsImporting] = useState<boolean>(false);
  const [isThinking, setIsThinking] = useState<boolean>(false);
  const [thinkingMessage, setThinkingMessage] = useState<string>("");
  // HITL wizard "Next" buttons set this so we can render a per-button spinner
  const [stepInFlight, setStepInFlight] = useState<IngestionStep | null>(null);

  // Manual input fields
  const [manualVertical, setManualVertical] = useState<string>("");
  const [manualSubVertical, setManualSubVertical] = useState<string>("");
  const [manualCapability, setManualCapability] = useState<string>("");
  const [extractionDepth, setExtractionDepth] = useState<string>("data_element");

  // Process / subprocess deselections for the currently-open preview. We
  // store *unchecked* entries so the default ("all selected") needs no
  // bookkeeping at modal-open time and reflects new processes added by
  // re-running a HITL step automatically.
  const [deselectedProcesses, setDeselectedProcesses] = useState<Set<number>>(
    () => new Set(),
  );
  const [deselectedSubprocesses, setDeselectedSubprocesses] = useState<
    Map<number, Set<number>>
  >(() => new Map());

  // ---------- Aggregated (multi-document → single capability) state ----------
  // When the user provides a Capability name manually and uploads more
  // than one document, each document still runs through its own HITL
  // wizard so the user can review per-document evidence. The combined
  // preview below lets the user then merge all of the guardrail-approved
  // processes under the single manual capability and persist them in one
  // round-trip to ``/upload/import-to-graph``.
  const [showAggregatedModal, setShowAggregatedModal] = useState(false);
  const [isAggregatedImporting, setIsAggregatedImporting] = useState(false);
  // Per-file deselections, keyed by file id. Same {procs, subs} shape as
  // the single-file preview so the existing ``ProcessList`` checkbox
  // wiring can be reused per section without changes.
  const [aggregatedDeselections, setAggregatedDeselections] = useState<
    Map<string, { procs: Set<number>; subs: Map<number, Set<number>> }>
  >(() => new Map());

  // Reset the selection whenever the modal switches to a different file so
  // the new file starts with everything checked.
  useEffect(() => {
    setDeselectedProcesses(new Set());
    setDeselectedSubprocesses(new Map());
  }, [modalFileId]);

  // Subscribe to extraction manager updates
  useEffect(() => {
    ExtractionManager.initializeFiles(files);

    const unsubscribe = ExtractionManager.subscribeToExtractions((updatedFiles, thinking) => {
      setFiles(updatedFiles as UploadedFile[]);
      setIsThinking(thinking.isThinking);
      setThinkingMessage(thinking.message);
    });

    // Check for pending modal data on mount (tabular flow only — the HITL
    // wizard reopens itself via the `onWizardStep` callback below, but if
    // the user navigated away mid-tabular-extraction we still want to
    // surface the result toast/modal on remount).
    const checkPendingModal = () => {
      const pending = ExtractionManager.getPendingModalData();
      if (pending) {
        setModalFileId(pending.fileId);
        setShowModal(true);
        toast.success(`Extraction completed: ${pending.data.name}`);
      }
    };

    const checkPendingRejection = () => {
      const rejection = ExtractionManager.getPendingRejection();
      if (rejection) {
        toast.error(
          `Invalid document: ${rejection.fileName}\n${rejection.reason}`,
          { duration: 8000 }
        );
      }
    };

    checkPendingModal();
    checkPendingRejection();

    const interval = setInterval(() => {
      if (ExtractionManager.hasPendingModal()) checkPendingModal();
      if (ExtractionManager.hasPendingRejection()) checkPendingRejection();
    }, 1000);

    return () => {
      unsubscribe();
      clearInterval(interval);
    };
  }, []);

  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    const droppedFiles = e.dataTransfer.files;
    if (droppedFiles) {
      handleFiles(droppedFiles);
    }
  };

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      handleFiles(e.target.files);
    }
  };

  const handleFiles = (fileList: FileList) => {
    const existing = ExtractionManager.getFiles();
    const existingKeys = new Set(existing.map((f) => `${f.name}|${f.size}`));

    const newFiles: UploadedFile[] = [];
    const skipped: string[] = [];

    Array.from(fileList).forEach((file) => {
      const key = `${file.name}|${file.size}`;
      if (existingKeys.has(key)) {
        skipped.push(file.name);
        return;
      }
      existingKeys.add(key);

      const id = `${Date.now()}-${Math.random()}`;
      newFiles.push({
        id,
        name: file.name,
        size: file.size,
        type: file.type,
        status: 'pending',
        progress: 0,
        sourceType: ExtractionManager.detectSourceType(file.name),
      });
      ExtractionManager.registerFileObject(id, file);
    });

    if (newFiles.length > 0) {
      ExtractionManager.addFiles(newFiles);
      toast.success(`${newFiles.length} file(s) added`);
    }
    if (skipped.length > 0) {
      toast.error(
        `Skipped ${skipped.length} duplicate file(s) already in the list: ${skipped.join(', ')}`,
        { duration: 4500 },
      );
    }
  };

  const removeFile = (id: string) => {
    ExtractionManager.removeFile(id);
  };

  const removeAllFiles = () => {
    ExtractionManager.clearAllFiles();
  };

  const uploadAndExtractFile = async (file: UploadedFile) => {
    // Prefer the cached File (works for drag-drop too); fall back to the
    // hidden input as a safety net.
    let actualFile: File | null = ExtractionManager.getFileObject(file.id) ?? null;
    if (!actualFile) {
      const fileInputElement = fileInputRef.current;
      if (fileInputElement && fileInputElement.files) {
        for (const f of fileInputElement.files) {
          if (f.name === file.name && f.size === file.size) {
            actualFile = f;
            break;
          }
        }
      }
    }

    if (!actualFile) {
      toast.error(`Could not locate file contents for "${file.name}". Please re-add it.`);
      return;
    }

    await ExtractionManager.startExtraction(
      file,
      actualFile,
      manualVertical,
      manualSubVertical,
      manualCapability,
      extractionDepth,
      (fileId, step) => {
        // Reopen the wizard on this file so the user can review the
        // freshly-completed step. This fires for every step transition;
        // the modal renders the panel that matches `current_step`.
        setModalFileId(fileId);
        setShowModal(true);
        if (step === 'doc_gate') {
          toast.success(`Document validated: ${file.name}`);
        }
      },
    );
  };

  const handleUploadAll = async () => {
    const pendingFiles = files.filter((f) => f.status === 'pending');
    if (pendingFiles.length === 0) {
      toast.error('No files to upload');
      return;
    }

    setIsProcessing(true);
    try {
      await Promise.all(pendingFiles.map((f) => uploadAndExtractFile(f)));
    } catch (error) {
      console.error('Batch upload error:', error);
      toast.error('Failed to upload some files');
    } finally {
      setIsProcessing(false);
    }
  };

  // ---------- HITL wizard step handlers (PDF/DOCX/TXT) ----------

  const handleNextExtraction = async (fileId: string) => {
    setStepInFlight('extraction');
    try {
      await ExtractionManager.runExtractionStep(fileId);
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : 'Extraction failed';
      toast.error(errorMsg);
    } finally {
      setStepInFlight(null);
    }
  };

  const handleNextGuardrail = async (fileId: string) => {
    setStepInFlight('guardrail');
    try {
      await ExtractionManager.runGuardrailStep(fileId);
      const updated = ExtractionManager.getFiles().find((f) => f.id === fileId);
      if (updated?.status === 'rejected') {
        toast.error(
          updated.rejection_reason ||
            'No extracted process aligned with the FIBO ontology.',
          { duration: 6000 },
        );
      }
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : 'Guardrail failed';
      toast.error(errorMsg);
    } finally {
      setStepInFlight(null);
    }
  };

  /**
   * Final step: import the (HITL-approved) model into Neo4j.
   *
   * - Document flow (PDF/DOCX/TXT): POSTs to `/upload/session/{id}/import`,
   *   which uses the chunks/model already cached in the session. If the
   *   user has unchecked processes/subprocesses, the selection indices
   *   are sent so the backend imports only the kept subset.
   * - Tabular flow (CSV/XLSX): defaults to re-sending the original
   *   spreadsheet to `/upload/csv` so the optimized batch importer can
   *   pick up the org-units / applications columns the in-memory model
   *   doesn't carry. If the user has unchecked anything we instead POST
   *   the filtered in-memory model to `/upload/import-to-graph` (this
   *   sacrifices the spreadsheet-only columns but honours the selection).
   */
  const handleImportToGraph = async (fileId: string) => {
    if (isImporting) return;

    const file = files.find((f) => f.id === fileId);
    if (!file) {
      toast.error('File not found');
      return;
    }

    const isTabular = file.sourceType === 'tabular';
    const selectionPayload = buildImportSelection();

    setIsImporting(true);
    try {
      toast.loading('Importing to graph database...', { id: 'import-toast' });

      let summary: Record<string, any> = {};
      if (isTabular) {
        if (selectionPayload && modalData) {
          // User unchecked something — switch to the JSON-body importer
          // so we can honour the selection. We forfeit the CSV-only
          // org-units / applications columns; warn the user about it.
          toast(
            'Importing the filtered preview only; spreadsheet org-units / applications columns will be skipped.',
            { duration: 4500, icon: '⚠️' },
          );
          const filteredModel = filterModelBySelection(modalData);
          const response = await fetch(`${API_BASE}/upload/import-to-graph`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model_data: filteredModel }),
          });
          if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || 'Import failed');
          }
          const result = await response.json();
          summary = result.summary || {};
        } else {
          const actualFile = ExtractionManager.getFileObject(fileId);
          if (!actualFile) {
            throw new Error(
              'Original spreadsheet contents are no longer available. Please re-upload the file.',
            );
          }
          const formData = new FormData();
          formData.append('file', actualFile);
          const response = await fetch(`${API_BASE}/upload/csv`, {
            method: 'POST',
            body: formData,
          });
          if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || 'Import failed');
          }
          const result = await response.json();
          summary = result.summary || {};
        }
      } else {
        if (!file.session_id) {
          throw new Error(
            'Cannot import — this file has no active ingestion session. ' +
              'Re-run the wizard so the document is re-ingested.',
          );
        }
        summary = await ExtractionManager.runImportStep(fileId, selectionPayload);
      }

      setShowModal(false);
      setModalFileId(null);

      toast.success('Successfully imported to graph database!', { id: 'import-toast' });

      console.log('Import Summary:', summary);
      if (isTabular) {
        toast.success(
          `Created ${summary.capabilities_created || 0} capability/ies, ` +
            `${summary.processes_created || 0} process(es), ` +
            `${summary.subprocesses_created || 0} subprocess(es)`,
          { duration: 5000 },
        );
      } else {
        toast.success(
          `Created ${summary.processes_created || 0} processes with ${
            summary.subprocesses_created || 0
          } subprocesses${
            summary.chunks_imported
              ? ` and ${summary.chunks_imported} knowledge chunks`
              : ''
          }`,
          { duration: 4000 },
        );
      }
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : 'Import failed';
      toast.error(errorMsg, { id: 'import-toast' });
      console.error('Import error:', error);
    } finally {
      setIsImporting(false);
    }
  };

  const formatFileSize = (bytes: number): string => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + ' ' + sizes[i];
  };

  const pendingCount = files.filter((f) => f.status === 'pending').length;
  const successCount = files.filter((f) => f.status === 'success').length;
  const errorCount = files.filter((f) => f.status === 'error').length;
  const rejectedCount = files.filter((f) => f.status === 'rejected').length;
  const reviewCount = files.filter((f) => f.status === 'awaiting_review').length;
  const processingCount = files.filter(
    (f) => f.status === 'uploading' || f.status === 'extracting' || f.status === 'validating'
  ).length;

  const openModalForFile = (file: UploadedFile) => {
    // The modal renders whatever step the file is currently parked at —
    // doc_gate (review evidence), extraction (review raw LLM output),
    // guardrail (review FIBO-trimmed model), or import (final preview).
    setModalFileId(file.id);
    setShowModal(true);
  };

  const activeFile = files.find((f) => f.id === modalFileId);
  const modalData: ExtractedCapabilityModel | null =
    activeFile?.extractedData ??
    activeFile?.rawExtractedData ??
    (activeFile
      ? {
          name: activeFile.name,
          description: '',
          vertical: '',
          processes: [],
        }
      : null);
  const isRejectedView = activeFile?.status === 'rejected';
  const currentStep: IngestionStep =
    activeFile?.current_step ||
    (activeFile?.status === 'success' ? 'import' : 'doc_gate');

  const procCountForSelection = modalData?.processes?.length ?? 0;

  // Checkboxes only make sense once the user is at (or past) the
  // guardrail review — i.e. when the model they're looking at is the one
  // about to be persisted. We also show them on the tabular preview
  // because it skips straight to "import".
  const allowSelection =
    !isRejectedView &&
    !!modalData &&
    procCountForSelection > 0 &&
    (activeFile?.sourceType === 'tabular' ||
      currentStep === 'guardrail' ||
      currentStep === 'import');

  const selectedProcessCount = modalData
    ? modalData.processes.reduce(
        (acc, _p, i) => acc + (deselectedProcesses.has(i) ? 0 : 1),
        0,
      )
    : 0;

  const toggleProcess = (procIdx: number) => {
    setDeselectedProcesses((prev) => {
      const next = new Set(prev);
      if (next.has(procIdx)) next.delete(procIdx);
      else next.add(procIdx);
      return next;
    });
  };

  const toggleSubprocess = (procIdx: number, subIdx: number) => {
    setDeselectedSubprocesses((prev) => {
      const next = new Map(prev);
      const inner = new Set(next.get(procIdx) ?? new Set<number>());
      if (inner.has(subIdx)) inner.delete(subIdx);
      else inner.add(subIdx);
      next.set(procIdx, inner);
      return next;
    });
  };

  const selectAllProcesses = () => {
    setDeselectedProcesses(new Set());
    setDeselectedSubprocesses(new Map());
  };

  const deselectAllProcesses = () => {
    if (!modalData) return;
    setDeselectedProcesses(
      new Set(modalData.processes.map((_, i) => i)),
    );
    setDeselectedSubprocesses(new Map());
  };

  const selectionApi: ProcessSelectionAPI | undefined = allowSelection
    ? {
        isProcessChecked: (procIdx) => !deselectedProcesses.has(procIdx),
        isSubprocessChecked: (procIdx, subIdx) =>
          !(deselectedSubprocesses.get(procIdx)?.has(subIdx) ?? false),
        toggleProcess,
        toggleSubprocess,
      }
    : undefined;

  /**
   * Build the selection payload to send to the import endpoint. Returns
   * `undefined` when the user has not unchecked anything (so the
   * frontend can keep using its existing "import everything" code path).
   */
  const buildImportSelection = (): ImportSelection | undefined => {
    if (!allowSelection || !modalData) return undefined;
    const total = modalData.processes.length;
    const hasDeselectedProcess = deselectedProcesses.size > 0;
    const hasDeselectedSubprocess = Array.from(
      deselectedSubprocesses.values(),
    ).some((s) => s.size > 0);
    if (!hasDeselectedProcess && !hasDeselectedSubprocess) return undefined;

    const selectedProcessIndices: number[] = [];
    for (let i = 0; i < total; i += 1) {
      if (!deselectedProcesses.has(i)) selectedProcessIndices.push(i);
    }

    const selectedSubprocessIndices: Record<string, number[]> = {};
    for (const procIdx of selectedProcessIndices) {
      const proc = modalData.processes[procIdx];
      const subs = (proc?.subprocesses || []) as any[];
      const unchecked = deselectedSubprocesses.get(procIdx);
      if (unchecked && unchecked.size > 0) {
        const kept: number[] = [];
        for (let s = 0; s < subs.length; s += 1) {
          if (!unchecked.has(s)) kept.push(s);
        }
        selectedSubprocessIndices[String(procIdx)] = kept;
      }
    }

    const payload: ImportSelection = {
      selected_process_indices: selectedProcessIndices,
    };
    if (Object.keys(selectedSubprocessIndices).length > 0) {
      payload.selected_subprocess_indices = selectedSubprocessIndices;
    }
    return payload;
  };

  // ---------- Aggregation helpers ----------

  const aggregationCapability = manualCapability.trim();
  const documentFileCount = files.filter((f) => f.sourceType === 'document').length;
  // Aggregation is "active" once the user has set a manual capability and
  // queued at least 2 free-form documents. We do not gate on the docs
  // having finished extraction yet — the banner appears immediately so
  // the user knows their uploads will be merged.
  const aggregationActive =
    aggregationCapability.length > 0 && documentFileCount >= 2;

  // A document file is eligible for combined import once it has passed
  // the FIBO guardrail and is parked at the "Review guardrail" step with
  // at least one accepted process. Files that have already been imported
  // individually (status === 'success') are excluded — they are already
  // in the graph and re-importing would create duplicates.
  const aggregationReadyFiles = useMemo(
    () =>
      files.filter(
        (f) =>
          f.sourceType === 'document' &&
          f.status === 'awaiting_review' &&
          f.current_step === 'guardrail' &&
          (f.extractedData?.processes?.length ?? 0) > 0,
      ),
    [files],
  );

  const aggregationCanImport =
    aggregationActive && aggregationReadyFiles.length >= 2;

  const isAggProcChecked = (fileId: string, procIdx: number) =>
    !(aggregatedDeselections.get(fileId)?.procs.has(procIdx) ?? false);

  const isAggSubChecked = (fileId: string, procIdx: number, subIdx: number) =>
    !(aggregatedDeselections.get(fileId)?.subs.get(procIdx)?.has(subIdx) ?? false);

  const toggleAggProc = (fileId: string, procIdx: number) => {
    setAggregatedDeselections((prev) => {
      const next = new Map(prev);
      const cur = next.get(fileId) ?? {
        procs: new Set<number>(),
        subs: new Map<number, Set<number>>(),
      };
      const procs = new Set(cur.procs);
      if (procs.has(procIdx)) procs.delete(procIdx);
      else procs.add(procIdx);
      next.set(fileId, { procs, subs: cur.subs });
      return next;
    });
  };

  const toggleAggSub = (fileId: string, procIdx: number, subIdx: number) => {
    setAggregatedDeselections((prev) => {
      const next = new Map(prev);
      const cur = next.get(fileId) ?? {
        procs: new Set<number>(),
        subs: new Map<number, Set<number>>(),
      };
      const subs = new Map(cur.subs);
      const inner = new Set(subs.get(procIdx) ?? new Set<number>());
      if (inner.has(subIdx)) inner.delete(subIdx);
      else inner.add(subIdx);
      subs.set(procIdx, inner);
      next.set(fileId, { procs: cur.procs, subs });
      return next;
    });
  };

  /**
   * Build one ``ExtractedCapabilityModel`` that merges every aggregation-
   * ready file's accepted processes under the manually-provided
   * capability name. Vertical / sub-vertical fall back to the first
   * non-empty value across the manual inputs and the contributing files
   * so the backend always has the fields it requires.
   */
  const buildAggregatedModel = (): ExtractedCapabilityModel | null => {
    if (!aggregationCapability || aggregationReadyFiles.length === 0) {
      return null;
    }

    let vertical = manualVertical.trim();
    let subvertical = manualSubVertical.trim();
    const combinedProcesses: any[] = [];

    for (const f of aggregationReadyFiles) {
      if (!vertical && f.extractedData?.vertical) {
        vertical = f.extractedData.vertical;
      }
      if (!subvertical && f.extractedData?.subvertical) {
        subvertical = f.extractedData.subvertical;
      }
      const deselect = aggregatedDeselections.get(f.id);
      const procs = f.extractedData?.processes ?? [];
      procs.forEach((proc, pIdx) => {
        if (deselect?.procs.has(pIdx)) return;
        const subDeselect = deselect?.subs.get(pIdx);
        const filteredSubs = (proc.subprocesses || []).filter(
          (_s, sIdx) => !(subDeselect?.has(sIdx) ?? false),
        );
        combinedProcesses.push({
          ...proc,
          subprocesses: filteredSubs,
          source_document: f.name,
        });
      });
    }

    return {
      name: aggregationCapability,
      description:
        `Aggregated from ${aggregationReadyFiles.length} document(s): ` +
        aggregationReadyFiles.map((f) => f.name).join(', '),
      vertical,
      subvertical: subvertical || undefined,
      processes: combinedProcesses,
    };
  };

  const aggregatedSelectedProcessCount = useMemo(
    () =>
      aggregationReadyFiles.reduce((total, f) => {
        const procs = f.extractedData?.processes ?? [];
        const deselect = aggregatedDeselections.get(f.id);
        return (
          total +
          procs.reduce((acc, _p, i) => acc + (deselect?.procs.has(i) ? 0 : 1), 0)
        );
      }, 0),
    [aggregationReadyFiles, aggregatedDeselections],
  );

  /**
   * Persist the combined model in a single round-trip. The session-based
   * ``/upload/session/{id}/import`` endpoint creates one Capability per
   * session, so it cannot merge multiple documents under one capability.
   * Instead we POST the combined model to ``/upload/import-to-graph``
   * (which uses get-or-create vertical / sub-vertical logic internally)
   * and then best-effort cancel every contributor's HITL session so its
   * temp file is dropped on the server.
   */
  const handleAggregatedImport = async () => {
    if (isAggregatedImporting) return;
    if (!aggregationCapability) {
      toast.error('Enter a Capability name to enable combined import.');
      return;
    }

    const combined = buildAggregatedModel();
    if (!combined || combined.processes.length === 0) {
      toast.error('Select at least one process from any document to import.');
      return;
    }
    if (!combined.vertical) {
      toast.error(
        'Vertical is required. Set it in the sidebar or wait for a document to detect one.',
      );
      return;
    }

    setIsAggregatedImporting(true);
    toast.loading('Importing combined capability to graph...', {
      id: 'agg-import-toast',
    });

    try {
      const response = await fetch(`${API_BASE}/upload/import-to-graph`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model_data: combined }),
      });
      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.detail || 'Combined import failed');
      }
      const result = await response.json();
      const summary = result.summary || {};

      const contributors = [...aggregationReadyFiles];
      await Promise.all(
        contributors.map(async (f) => {
          if (f.session_id) {
            await ExtractionManager.cancelSession(f.session_id);
          }
          ExtractionManager.markFileImported(f.id);
        }),
      );

      setShowAggregatedModal(false);
      setAggregatedDeselections(new Map());

      toast.success('Combined import succeeded!', { id: 'agg-import-toast' });
      toast.success(
        `Created 1 capability with ${summary.processes_created || 0} process(es) and ` +
          `${summary.subprocesses_created || 0} subprocess(es) from ` +
          `${contributors.length} document(s)`,
        { duration: 5000 },
      );
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : 'Combined import failed';
      toast.error(errorMsg, { id: 'agg-import-toast' });
      console.error('Combined import error:', error);
    } finally {
      setIsAggregatedImporting(false);
    }
  };

  /**
   * Apply the same selection to a model object client-side, used by the
   * tabular flow which posts the JSON model directly rather than going
   * through the session-based selection filter on the backend.
   */
  const filterModelBySelection = (
    model: ExtractedCapabilityModel,
  ): ExtractedCapabilityModel => {
    const sel = buildImportSelection();
    if (!sel) return model;
    const keepProc = new Set(sel.selected_process_indices ?? []);
    const keepSub = sel.selected_subprocess_indices ?? {};
    const filteredProcesses = model.processes
      .map((proc, idx) => ({ proc, idx }))
      .filter(({ idx }) => keepProc.has(idx))
      .map(({ proc, idx }) => {
        const subFilter = keepSub[String(idx)];
        if (subFilter === undefined) return proc;
        const keepSubSet = new Set(subFilter);
        return {
          ...proc,
          subprocesses: (proc.subprocesses || []).filter((_s, i) =>
            keepSubSet.has(i),
          ),
        };
      });
    return { ...model, processes: filteredProcesses };
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <Toaster position="top-right" />
      <header className="border-b sticky top-0 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 z-50">
        <div className="container px-6 py-4">
          <div className="flex items-center gap-3">
            <div>
              <h1 className="text-xl font-semibold">Compass Ingestion</h1>
              <p className="text-xs text-muted-foreground">
                Upload documents for AI-powered capability extraction and graph database import
              </p>
            </div>
          </div>
        </div>
      </header>

      <div className="mx-auto mt-6 grid lg:grid-cols-4 gap-6 px-6 max-w-7xl">
        {/* Sidebar: Configuration and File Management */}
        <div className="lg:col-span-1 space-y-4">
          {/* Manual Configuration Card */}
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
            {/* Vertical Input */}
            <div className="mb-4">
              <label className="block text-xs font-medium text-gray-700 mb-1.5">
                Vertical <span className="text-xs text-gray-500">(Optional)</span>
              </label>
              <input
                type="text"
                value={manualVertical}
                onChange={(e) => setManualVertical(e.target.value)}
                placeholder="e.g., Capital Markets"
                className="w-full px-2 py-1.5 border border-gray-300 rounded text-xs focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>

            {/* SubVertical Input */}
            <div className="mb-4">
              <label className="block text-xs font-medium text-gray-700 mb-1.5">
                SubVertical <span className="text-xs text-gray-500">(Optional)</span>
              </label>
              <input
                type="text"
                value={manualSubVertical}
                onChange={(e) => setManualSubVertical(e.target.value)}
                placeholder="e.g., Asset Management"
                className="w-full px-2 py-1.5 border border-gray-300 rounded text-xs focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>

            {/* Capability Input */}
            <div className="mb-4">
              <label className="block text-xs font-medium text-gray-700 mb-1.5">
                Capability <span className="text-xs text-gray-500">(Optional)</span>
              </label>
              <input
                type="text"
                value={manualCapability}
                onChange={(e) => setManualCapability(e.target.value)}
                placeholder="e.g., Portfolio Management"
                className="w-full px-2 py-1.5 border border-gray-300 rounded text-xs focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
              
            </div>

            {/* Extraction Depth Dropdown */}
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1.5">
                Extraction Depth <span className="text-xs text-gray-500">(Required)</span>
              </label>
              <select
                value={extractionDepth}
                onChange={(e) => setExtractionDepth(e.target.value)}
                className="w-full px-2 py-1.5 border border-gray-300 rounded text-xs focus:outline-none focus:ring-1 focus:ring-indigo-500"
              >
                <option value="capability">Capability Only</option>
                <option value="process">Process Level</option>
                <option value="subprocess">SubProcess Level</option>
                <option value="data_entity">Data Entity Level</option>
                <option value="data_element">Data Element Level</option>
              </select>
            </div>
          </div>

          {/* Files List Card */}
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
            <h3 className="text-sm font-semibold text-gray-900 mb-3">
              Files ({files.length})
            </h3>

            {files.length === 0 ? (
              <div className="text-center py-4">
                <FiFile className="w-8 h-8 text-gray-300 mx-auto mb-2" />
                <p className="text-xs text-gray-500">No files selected</p>
              </div>
            ) : (
              <div className="space-y-2 max-h-[400px] overflow-y-auto">
                {files.map((file) => {
                  const clickable =
                    (file.status === 'success' && !!file.extractedData) ||
                    file.status === 'awaiting_review' ||
                    file.status === 'rejected';
                  return (
                    <div
                      key={file.id}
                      className={`bg-gray-50 rounded border border-gray-200 p-2 transition-colors text-xs ${
                        clickable ? 'hover:bg-blue-50 cursor-pointer' : 'hover:bg-gray-100'
                      } ${file.status === 'rejected' ? 'border-red-300 bg-red-50' : ''}`}
                      onClick={() => clickable && openModalForFile(file)}
                    >
                      <div className="flex items-start justify-between gap-1 mb-1">
                        <div className="flex items-start gap-1 flex-1 min-w-0">
                          <FiFile className="w-3 h-3 text-gray-400 mt-0.5 flex-shrink-0" />
                          <div className="min-w-0 flex-1">
                            <p className="font-medium text-gray-900 truncate">{file.name}</p>
                            <p className="text-xs text-gray-500">{formatFileSize(file.size)}</p>
                          </div>
                        </div>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            removeFile(file.id);
                          }}
                          className="text-gray-400 hover:text-gray-600 flex-shrink-0"
                        >
                          <FiX size={14} />
                        </button>
                      </div>

                      {/* Status and Progress */}
                      <div className="flex items-center gap-1 flex-wrap">
                        {file.status === 'pending' && (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-blue-100 text-blue-700 rounded text-xs">
                            <span className="w-1.5 h-1.5 bg-blue-500 rounded-full"></span>
                            Pending
                          </span>
                        )}
                        {file.status === 'validating' && (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-purple-100 text-purple-700 rounded text-xs">
                            <FiLoader size={10} className="animate-spin" />
                            Validating ontology…
                          </span>
                        )}
                        {(file.status === 'uploading' || file.status === 'extracting') && (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-yellow-100 text-yellow-700 rounded text-xs">
                            <FiLoader size={10} className="animate-spin" />
                            {Math.round(file.progress)}%
                          </span>
                        )}
                        {file.status === 'awaiting_review' && (
                          <span
                            className="inline-flex items-center gap-1 px-2 py-0.5 bg-amber-100 text-amber-700 rounded text-xs"
                            title="Waiting for you to review and click Next"
                          >
                            <FiArrowRight size={10} />
                            {file.current_step === 'doc_gate'
                              ? 'Review ontology'
                              : file.current_step === 'extraction'
                              ? 'Review processes'
                              : file.current_step === 'guardrail'
                              ? 'Review guardrail'
                              : 'Review'}
                          </span>
                        )}
                        {file.status === 'success' && (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-green-100 text-green-700 rounded text-xs">
                            <FiCheckCircle size={10} />
                            Done (Click to view)
                          </span>
                        )}
                        {file.status === 'rejected' && (
                          <span
                            className="inline-flex items-center gap-1 px-2 py-0.5 bg-red-100 text-red-700 rounded text-xs"
                            title={file.rejection_reason}
                          >
                            <FiSlash size={10} />
                            Invalid Document (Click to view)
                          </span>
                        )}
                        {file.status === 'error' && (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-red-100 text-red-700 rounded text-xs">
                            <FiAlertCircle size={10} />
                            Error
                          </span>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* Main Content: Upload Area and Stats */}
        <div className="lg:col-span-3">
          {aggregationActive && (
            <div className="mb-4 rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-3">
              <div className="flex items-start justify-between gap-3 flex-wrap">
                <div className="min-w-0">
                  <p className="text-xs text-indigo-700 mt-1">
                    <strong>{aggregationReadyFiles.length}</strong> of{' '}
                    <strong>{documentFileCount}</strong> document(s) ready ·{' '}
                    {aggregationReadyFiles.length === 0
                      ? 'finish each run up to "Review guardrail"'
                      : aggregationReadyFiles.length === 1
                      ? 'need one more document at the guardrail step'
                      : 'click "Combined Preview" to review and import'}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setShowAggregatedModal(true)}
                  disabled={!aggregationCanImport}
                  className="px-3 py-1.5 bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed text-sm flex items-center gap-2 shrink-0"
                  title={
                    aggregationCanImport
                      ? 'Review and import every guardrail-approved process under one capability'
                      : 'At least two documents must reach the "Review guardrail" step'
                  }
                >
                  <FiDatabase size={14} />
                  Combined Preview
                </button>
              </div>
            </div>
          )}

          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
            <div
              onDragEnter={handleDragEnter}
              onDragLeave={handleDragLeave}
              onDragOver={handleDragOver}
              onDrop={handleDrop}
              className={`relative border-2 border-dashed rounded-lg p-6 text-center transition-all duration-200 ${
                isDragging
                  ? 'border-indigo-500 bg-indigo-50'
                  : 'border-gray-300 bg-gray-50 hover:border-indigo-400 hover:bg-indigo-50'
              }`}
            >
              <div className="flex flex-col items-center">
                <div className="mb-2 p-2 bg-indigo-100 rounded-full">
                  <FiUpload className="w-5 h-5 text-indigo-600" />
                </div>
                <h3 className="text-base font-semibold text-gray-900 mb-1">
                  {isDragging ? 'Drop files here' : 'Drag and drop documents'}
                </h3>
                <p className="text-sm text-gray-600 mb-3">
                  or <button
                    onClick={() => fileInputRef.current?.click()}
                    className="text-indigo-600 hover:text-indigo-700 font-medium"
                  >
                    select files
                  </button>
                </p>
                <p className="text-xs text-gray-500">
                  PDF, DOCX, TXT, CSV, XLSX (Max 100MB)
                </p>
              </div>

              <input
                ref={fileInputRef}
                type="file"
                multiple
                onChange={handleFileInputChange}
                className="hidden"
                accept=".pdf,.docx,.doc,.txt,.csv,.xlsx,.xls"
              />
            </div>

            {files.length > 0 && (
              <div className="mt-4 pt-4 border-t border-gray-200">
                <div className="grid grid-cols-6 gap-2 mb-4">
                  <div className="text-center p-2 bg-blue-50 rounded">
                    <p className="text-lg font-bold text-blue-600">{pendingCount}</p>
                    <p className="text-xs text-gray-600">Pending</p>
                  </div>
                  <div className="text-center p-2 bg-yellow-50 rounded">
                    <p className="text-lg font-bold text-yellow-600">{processingCount}</p>
                    <p className="text-xs text-gray-600">Processing</p>
                  </div>
                  <div className="text-center p-2 bg-amber-50 rounded">
                    <p className="text-lg font-bold text-amber-600">{reviewCount}</p>
                    <p className="text-xs text-gray-600">Review</p>
                  </div>
                  <div className="text-center p-2 bg-green-50 rounded">
                    <p className="text-lg font-bold text-green-600">{successCount}</p>
                    <p className="text-xs text-gray-600">Imported</p>
                  </div>
                  <div className="text-center p-2 bg-red-50 rounded">
                    <p className="text-lg font-bold text-red-600">{rejectedCount}</p>
                    <p className="text-xs text-gray-600">Rejected</p>
                  </div>
                  <div className="text-center p-2 bg-red-50 rounded">
                    <p className="text-lg font-bold text-red-600">{errorCount}</p>
                    <p className="text-xs text-gray-600">Failed</p>
                  </div>
                </div>

                <div className="flex gap-2">
                  <button
                    onClick={handleUploadAll}
                    disabled={pendingCount === 0 || isProcessing}
                    className="flex-1 px-4 py-2 bg-indigo-600 text-white rounded hover:bg-indigo-700 transition-colors font-medium disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2 text-sm"
                  >
                    <FiUpload size={18} />
                    Extract {pendingCount > 0 ? `${pendingCount} File(s)` : 'Files'}
                  </button>
                  <button
                    onClick={removeAllFiles}
                    disabled={isProcessing}
                    className="px-4 py-2 bg-gray-200 text-gray-700 rounded hover:bg-gray-300 transition-colors font-medium disabled:opacity-50 disabled:cursor-not-allowed text-sm"
                  >
                    Clear All
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Agent thinking overlay */}
      {isThinking && (
        <div className="fixed top-4 right-4 z-50 bg-white/90 backdrop-blur rounded-lg shadow px-4 py-2 flex items-center gap-3">
          <FiLoader className="animate-spin w-5 h-5 text-indigo-600" />
          <div className="text-sm text-gray-700">Thinking... {thinkingMessage}</div>
        </div>
      )}

      {/* HITL ingestion wizard */}
      {showModal && modalData && activeFile && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/40" onClick={() => setShowModal(false)} />
          <div className="relative bg-white rounded-lg shadow-lg w-11/12 max-w-4xl max-h-[92vh] flex flex-col overflow-hidden">
            {/* Header — fixed at top */}
            <div className="px-6 pt-5 pb-3 border-b border-gray-200 shrink-0">
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-start gap-3">
                  {isRejectedView ? (
                    <div className="p-2 bg-red-100 rounded-full">
                      <FiSlash className="w-5 h-5 text-red-600" />
                    </div>
                  ) : currentStep === 'import' && activeFile.status === 'success' ? (
                    <div className="p-2 bg-green-100 rounded-full">
                      <FiCheckCircle className="w-5 h-5 text-green-600" />
                    </div>
                  ) : (
                    <div className="p-2 bg-indigo-100 rounded-full">
                      <FiCpu className="w-5 h-5 text-indigo-600" />
                    </div>
                  )}
                  <div>
                    <h3 className="text-lg font-semibold">
                      {activeFile.sourceType === 'tabular'
                        ? 'Tabular Capability Preview'
                        : isRejectedView
                        ? 'Invalid Document'
                        : 'Compass Ingestion Wizard'}
                    </h3>
                    <p className="text-sm text-gray-500">
                      {modalData.name || activeFile?.name}
                    </p>
                    {activeFile?.ontology?.ontology_label && (
                      <p className="text-xs text-gray-400 mt-0.5">
                        Ontology: {activeFile.ontology.ontology_label}
                        {activeFile.ontology.concept_count
                          ? ` · ${activeFile.ontology.concept_count} concepts`
                          : ''}
                      </p>
                    )}
                  </div>
                </div>
              </div>

              {/* Stepper — only for the document HITL flow */}
              {activeFile.sourceType !== 'tabular' && (
                <div className="mt-4 flex items-center gap-2 text-xs">
                  {[
                    { id: 'doc_gate', label: 'Ontology', icon: <FiSearch size={12} /> },
                    { id: 'extraction', label: 'Extraction', icon: <FiCpu size={12} /> },
                    { id: 'guardrail', label: 'Guardrail', icon: <FiShield size={12} /> },
                    { id: 'import', label: 'Import', icon: <FiDatabase size={12} /> },
                  ].map((s, idx, arr) => {
                    const order: IngestionStep[] = ['doc_gate', 'extraction', 'guardrail', 'import'];
                    const myIdx = order.indexOf(s.id as IngestionStep);
                    const activeIdx = order.indexOf(currentStep);
                    const isDone = isRejectedView
                      ? false
                      : activeIdx > myIdx ||
                        (activeIdx === myIdx && activeFile.status === 'success');
                    const isCurrent = activeIdx === myIdx && !isRejectedView;
                    const pillColor = isRejectedView
                      ? 'bg-gray-100 text-gray-400'
                      : isDone
                      ? 'bg-green-100 text-green-700'
                      : isCurrent
                      ? 'bg-indigo-100 text-indigo-700'
                      : 'bg-gray-100 text-gray-500';
                    return (
                      <React.Fragment key={s.id}>
                        <div
                          className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded font-medium ${pillColor}`}
                        >
                          {s.icon}
                          {idx + 1}. {s.label}
                          {isDone && <FiCheckCircle size={12} />}
                        </div>
                        {idx < arr.length - 1 && (
                          <div className="flex-1 h-px bg-gray-200" />
                        )}
                      </React.Fragment>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Body — the only scrollable region */}
            <div className="px-6 py-4 overflow-y-auto flex-1 min-h-0">
              {isRejectedView ? (
                <RejectionPanel activeFile={activeFile} />
              ) : activeFile.sourceType === 'tabular' ? (
                <CapabilityModelView
                  modalData={modalData}
                  guardrail={activeFile.guardrail}
                  selection={selectionApi}
                  selectAllAction={
                    selectionApi
                      ? {
                          onSelectAll: selectAllProcesses,
                          onDeselectAll: deselectAllProcesses,
                        }
                      : undefined
                  }
                />
              ) : currentStep === 'doc_gate' ? (
                <DocGatePanel activeFile={activeFile} />
              ) : currentStep === 'extraction' ? (
                <ExtractionPanel activeFile={activeFile} modalData={modalData} />
              ) : (
                <CapabilityModelView
                  modalData={modalData}
                  guardrail={activeFile.guardrail}
                  showGuardrailRejected
                  selection={selectionApi}
                  selectAllAction={
                    selectionApi
                      ? {
                          onSelectAll: selectAllProcesses,
                          onDeselectAll: deselectAllProcesses,
                        }
                      : undefined
                  }
                />
              )}
            </div>

            {/* Footer — step-aware actions */}
            <div className="px-6 py-3 border-t border-gray-200 bg-white shrink-0 flex gap-3 justify-end">
              {/* Tabular flow: single Import-to-Graph button */}
              {activeFile.sourceType === 'tabular' && !isRejectedView && (
                <button
                  onClick={() => {
                    if (modalFileId) handleImportToGraph(modalFileId);
                  }}
                  disabled={
                    !modalData.processes ||
                    modalData.processes.length === 0 ||
                    isImporting ||
                    (allowSelection && selectedProcessCount === 0)
                  }
                  className="px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                  title={
                    allowSelection && selectedProcessCount === 0
                      ? 'Select at least one process to import'
                      : 'Import the selected processes into the graph'
                  }
                >
                  {isImporting && <FiLoader className="animate-spin" size={14} />}
                  {isImporting
                    ? 'Importing…'
                    : allowSelection &&
                      selectedProcessCount < modalData.processes.length
                    ? `Import ${selectedProcessCount} of ${modalData.processes.length}`
                    : 'Import to Graph'}
                </button>
              )}

              {/* HITL flow Step 1 → Step 2 */}
              {!isRejectedView &&
                activeFile.sourceType !== 'tabular' &&
                currentStep === 'doc_gate' && (
                  <button
                    onClick={() => modalFileId && handleNextExtraction(modalFileId)}
                    disabled={
                      stepInFlight !== null || activeFile.status === 'extracting'
                    }
                    className="px-4 py-2 bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                    title="Run the LLM agent to extract capability and processes from the document"
                  >
                    {stepInFlight === 'extraction' ? (
                      <>
                        <FiLoader className="animate-spin" size={14} />
                        Extracting…
                      </>
                    ) : (
                      <>
                        <FiCpu size={14} />
                        Next: Extract Processes
                        <FiArrowRight size={14} />
                      </>
                    )}
                  </button>
                )}

              {/* HITL flow Step 2 → Step 3 */}
              {!isRejectedView &&
                activeFile.sourceType !== 'tabular' &&
                currentStep === 'extraction' && (
                  <button
                    onClick={() => modalFileId && handleNextGuardrail(modalFileId)}
                    disabled={
                      stepInFlight !== null ||
                      !modalData.processes ||
                      modalData.processes.length === 0
                    }
                    className="px-4 py-2 bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                    title="Apply the FIBO ontology guardrail to keep only aligned processes"
                  >
                    {stepInFlight === 'guardrail' ? (
                      <>
                        <FiLoader className="animate-spin" size={14} />
                        Applying guardrail…
                      </>
                    ) : (
                      <>
                        <FiShield size={14} />
                        Next: Apply Ontology Guardrail
                        <FiArrowRight size={14} />
                      </>
                    )}
                  </button>
                )}

              {/* HITL flow Step 3 → Final import */}
              {!isRejectedView &&
                activeFile.sourceType !== 'tabular' &&
                (currentStep === 'guardrail' || currentStep === 'import') && (
                  <button
                    onClick={() => modalFileId && handleImportToGraph(modalFileId)}
                    disabled={
                      !modalData.processes ||
                      modalData.processes.length === 0 ||
                      isImporting ||
                      (allowSelection && selectedProcessCount === 0)
                    }
                    className="px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                    title={
                      !modalData.processes || modalData.processes.length === 0
                        ? 'No processes available to import'
                        : allowSelection && selectedProcessCount === 0
                        ? 'Select at least one process to import'
                        : 'Import the selected processes into the graph'
                    }
                  >
                    {isImporting && <FiLoader className="animate-spin" size={14} />}
                    <FiDatabase size={14} />
                    {isImporting
                      ? 'Importing…'
                      : allowSelection &&
                        selectedProcessCount < modalData.processes.length
                      ? `Import ${selectedProcessCount} of ${modalData.processes.length}`
                      : 'Import to Graph'}
                  </button>
                )}

              <button
                onClick={() => setShowModal(false)}
                className="px-4 py-2 bg-gray-100 rounded hover:bg-gray-200"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Combined preview for the multi-document → single capability flow */}
      {showAggregatedModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div
            className="absolute inset-0 bg-black/40"
            onClick={() => setShowAggregatedModal(false)}
          />
          <div className="relative bg-white rounded-lg shadow-lg w-11/12 max-w-5xl max-h-[92vh] flex flex-col overflow-hidden">
            <div className="px-6 pt-5 pb-3 border-b border-gray-200 shrink-0">
              <div className="flex items-start gap-3">
                <div className="p-2 bg-indigo-100 rounded-full">
                  <FiDatabase className="w-5 h-5 text-indigo-600" />
                </div>
                <div className="min-w-0">
                  <h3 className="text-lg font-semibold">Combined Capability Preview</h3>
                  <p className="text-sm text-gray-500">
                    Capability: <strong>{aggregationCapability}</strong>
                    {manualVertical && (
                      <>
                        {' · '}Vertical: <strong>{manualVertical}</strong>
                      </>
                    )}
                    {manualSubVertical && (
                      <>
                        {' · '}SubVertical: <strong>{manualSubVertical}</strong>
                      </>
                    )}
                  </p>
                  <p className="text-xs text-gray-500 mt-0.5">
                    {aggregationReadyFiles.length} document(s) ·{' '}
                    {aggregatedSelectedProcessCount} process(es) selected for import.
                    Each document's guardrail-accepted processes are listed below
                    in the order they were uploaded.
                  </p>
                </div>
              </div>
            </div>

            <div className="px-6 py-4 overflow-y-auto flex-1 min-h-0 space-y-4">
              {aggregationReadyFiles.length === 0 ? (
                <p className="text-sm text-gray-500">
                  No documents are at the guardrail step yet. Run each document
                  through the wizard up to "Review guardrail" first.
                </p>
              ) : (
                aggregationReadyFiles.map((f, idx) => {
                  const procs = f.extractedData?.processes ?? [];
                  const deselect = aggregatedDeselections.get(f.id);
                  const selectedCount = procs.reduce(
                    (acc, _p, i) => acc + (deselect?.procs.has(i) ? 0 : 1),
                    0,
                  );
                  const sectionSelection: ProcessSelectionAPI = {
                    isProcessChecked: (procIdx) => isAggProcChecked(f.id, procIdx),
                    isSubprocessChecked: (procIdx, subIdx) =>
                      isAggSubChecked(f.id, procIdx, subIdx),
                    toggleProcess: (procIdx) => toggleAggProc(f.id, procIdx),
                    toggleSubprocess: (procIdx, subIdx) =>
                      toggleAggSub(f.id, procIdx, subIdx),
                  };
                  return (
                    <div
                      key={f.id}
                      className="border border-gray-200 rounded-lg p-4 bg-white"
                    >
                      <div className="flex items-center justify-between mb-3 gap-3 flex-wrap">
                        <div className="min-w-0">
                          <p className="text-sm font-semibold text-gray-900 truncate">
                            Document {idx + 1} · {f.name}
                          </p>
                          <p className="text-xs text-gray-500 mt-0.5">
                            {selectedCount} of {procs.length} process(es) selected
                            {f.guardrail?.applied && (
                              <>
                                {' · '}guardrail kept{' '}
                                {f.guardrail.accepted_count ?? procs.length} of{' '}
                                {f.guardrail.candidate_count ?? procs.length} candidate(s)
                              </>
                            )}
                          </p>
                        </div>
                        <span className="px-2 py-0.5 bg-indigo-100 text-indigo-700 rounded text-xs shrink-0">
                          {procs.length} accepted
                        </span>
                      </div>
                      {procs.length === 0 ? (
                        <p className="text-xs text-gray-500">
                          No accepted processes from this document.
                        </p>
                      ) : (
                        <ProcessList
                          processes={procs}
                          showAlignment
                          selection={sectionSelection}
                        />
                      )}
                    </div>
                  );
                })
              )}
            </div>

            <div className="px-6 py-3 border-t border-gray-200 bg-white shrink-0 flex gap-3 justify-end">
              <button
                onClick={handleAggregatedImport}
                disabled={
                  isAggregatedImporting ||
                  aggregationReadyFiles.length === 0 ||
                  aggregatedSelectedProcessCount === 0
                }
                className="px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                title={
                  aggregatedSelectedProcessCount === 0
                    ? 'Select at least one process to import'
                    : 'Merge every selected process under the manual capability and persist'
                }
              >
                {isAggregatedImporting && (
                  <FiLoader className="animate-spin" size={14} />
                )}
                <FiDatabase size={14} />
                {isAggregatedImporting
                  ? 'Importing…'
                  : `Import ${aggregatedSelectedProcessCount} process(es) as 1 capability`}
              </button>
              <button
                onClick={() => setShowAggregatedModal(false)}
                className="px-4 py-2 bg-gray-100 rounded hover:bg-gray-200"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default CompassIngestion;
