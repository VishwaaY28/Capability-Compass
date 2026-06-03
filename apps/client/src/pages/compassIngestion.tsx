import React, { useState, useRef, useEffect } from 'react';
import {
  FiUpload,
  FiFile,
  FiX,
  FiCheckCircle,
  FiAlertCircle,
  FiLoader,
  FiSlash,
} from 'react-icons/fi';
import toast, { Toaster } from 'react-hot-toast';
import * as ExtractionManager from '../utils/extractionManager';
import type {
  OntologyMeta,
  DocumentRelevance,
  OntologyGuardrailSummary,
  FileStatus,
} from '../utils/extractionManager';

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
  chunks_path?: string;
  ontology?: OntologyMeta;
  document_relevance?: DocumentRelevance;
  guardrail?: OntologyGuardrailSummary;
  ontology_status?: 'success' | 'document_rejected' | 'ontology_rejected';
  rejection_reason?: string;
}

function loadPersistedFiles(): UploadedFile[] {
  return ExtractionManager.loadPersistedFiles() as UploadedFile[];
}

const CompassIngestion: React.FC = () => {
  const [files, setFiles] = useState<UploadedFile[]>(() => loadPersistedFiles());
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [showModal, setShowModal] = useState<boolean>(false);
  const [modalData, setModalData] = useState<ExtractedCapabilityModel | null>(null);
  const [modalFileId, setModalFileId] = useState<string | null>(null);
  const [isThinking, setIsThinking] = useState<boolean>(false);
  const [thinkingMessage, setThinkingMessage] = useState<string>("");
  
  // Manual input fields
  const [manualVertical, setManualVertical] = useState<string>("");
  const [manualSubVertical, setManualSubVertical] = useState<string>("");
  const [extractionDepth, setExtractionDepth] = useState<string>("data_element");

  // Subscribe to extraction manager updates
  useEffect(() => {
    ExtractionManager.initializeFiles(files);

    const unsubscribe = ExtractionManager.subscribeToExtractions((updatedFiles, thinking) => {
      setFiles(updatedFiles as UploadedFile[]);
      setIsThinking(thinking.isThinking);
      setThinkingMessage(thinking.message);
    });

    // Check for pending modal data on mount (extraction completed while navigated away)
    const checkPendingModal = () => {
      const pending = ExtractionManager.getPendingModalData();
      if (pending) {
        setModalData(pending.data as ExtractedCapabilityModel);
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

    // Check immediately
    checkPendingModal();
    checkPendingRejection();

    // Also check periodically for any newly completed extractions
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
    const newFiles: UploadedFile[] = [];
    Array.from(fileList).forEach((file) => {
      const id = `${Date.now()}-${Math.random()}`;
      newFiles.push({
        id,
        name: file.name,
        size: file.size,
        type: file.type,
        status: 'pending',
        progress: 0,
      });
    });
    ExtractionManager.addFiles(newFiles);
    toast.success(`${newFiles.length} file(s) added`);
  };

  const removeFile = (id: string) => {
    ExtractionManager.removeFile(id);
  };

  const removeAllFiles = () => {
    ExtractionManager.clearAllFiles();
  };

  const uploadAndExtractFile = async (file: UploadedFile) => {
    const fileInputElement = fileInputRef.current;
    if (!fileInputElement || !fileInputElement.files) return;

    let actualFile: File | null = null;
    for (const f of fileInputElement.files) {
      if (f.name === file.name && f.size === file.size) {
        actualFile = f;
        break;
      }
    }
    
    if (!actualFile) return;

    await ExtractionManager.startExtraction(
      file,
      actualFile,
      manualVertical,
      manualSubVertical,
      extractionDepth,
      (data, fileId) => {
        setModalData(data as ExtractedCapabilityModel);
        setModalFileId(fileId);
        setShowModal(true);
        toast.success(`Extraction successful: ${file.name}`);
      }
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

  /**
   * Import extracted model to graph database
   */
  const handleImportToGraph = async (fileId: string) => {
    const file = files.find((f) => f.id === fileId);
    if (!file || !file.extractedData) {
      toast.error('No extracted data to import');
      return;
    }

    try {
      toast.loading('Importing to graph database...', { id: 'import-toast' });
      
      const response = await fetch('/api/upload/import-to-graph', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          model_data: file.extractedData,
          chunks_path: file.chunks_path || null,
        }),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Import failed');
      }

      const result = await response.json();
      
      // Close the modal after successful import
      setShowModal(false);
      setModalData(null);
      setModalFileId(null);
      
      toast.success('Successfully imported to graph database!', { id: 'import-toast' });
      
      // Show import summary
      const summary = result.summary;
      console.log('Import Summary:', summary);
      toast.success(
        `Created ${summary.processes_created} processes with ${summary.subprocesses_created} subprocesses${
          summary.chunks_imported ? ` and ${summary.chunks_imported} knowledge chunks` : ''
        }`,
        { duration: 4000 }
      );
    } catch (error) {
      const errorMsg =
        error instanceof Error ? error.message : 'Import failed';
      toast.error(errorMsg, { id: 'import-toast' });
      console.error('Import error:', error);
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
  const processingCount = files.filter(
    (f) => f.status === 'uploading' || f.status === 'extracting' || f.status === 'validating'
  ).length;

  const openModalForFile = (file: UploadedFile) => {
    if ((file.status === 'success' || file.status === 'rejected') && file.extractedData) {
      setModalData(file.extractedData);
      setModalFileId(file.id);
      setShowModal(true);
    } else if (file.status === 'rejected') {
      // No extractedData (pre-LLM rejection) — synthesise a minimal model
      // so the modal can still show the rejection panel.
      setModalData({
        id: undefined,
        name: file.name,
        description: '',
        vertical: '',
        processes: [],
      });
      setModalFileId(file.id);
      setShowModal(true);
    }
  };

  const activeFile = files.find((f) => f.id === modalFileId);
  const isRejectedView = activeFile?.status === 'rejected';

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
                  PDF, DOCX, TXT (Max 100MB)
                </p>
              </div>

              <input
                ref={fileInputRef}
                type="file"
                multiple
                onChange={handleFileInputChange}
                className="hidden"
                accept=".pdf,.docx,.doc,.txt"
              />
            </div>

            {files.length > 0 && (
              <div className="mt-4 pt-4 border-t border-gray-200">
                <div className="grid grid-cols-5 gap-2 mb-4">
                  <div className="text-center p-2 bg-blue-50 rounded">
                    <p className="text-lg font-bold text-blue-600">{pendingCount}</p>
                    <p className="text-xs text-gray-600">Pending</p>
                  </div>
                  <div className="text-center p-2 bg-yellow-50 rounded">
                    <p className="text-lg font-bold text-yellow-600">{processingCount}</p>
                    <p className="text-xs text-gray-600">Processing</p>
                  </div>
                  <div className="text-center p-2 bg-green-50 rounded">
                    <p className="text-lg font-bold text-green-600">{successCount}</p>
                    <p className="text-xs text-gray-600">Extracted</p>
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

      {/* Modal for extracted result */}
      {showModal && modalData && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/40" onClick={() => setShowModal(false)} />
          <div className="relative bg-white rounded-lg shadow-lg w-11/12 max-w-3xl max-h-[90vh] flex flex-col overflow-hidden">
            {/* Header — fixed at top */}
            <div className="px-6 pt-6 pb-3 border-b border-gray-200 shrink-0">
              <div className="flex items-start justify-between">
                <div className="flex items-start gap-3">
                  {isRejectedView ? (
                    <div className="p-2 bg-red-100 rounded-full">
                      <FiSlash className="w-5 h-5 text-red-600" />
                    </div>
                  ) : (
                    <div className="p-2 bg-green-100 rounded-full">
                      <FiCheckCircle className="w-5 h-5 text-green-600" />
                    </div>
                  )}
                  <div>
                    <h3 className="text-lg font-semibold">
                      {isRejectedView ? 'Invalid Document' : 'Extracted Capability'}
                    </h3>
                    <p className="text-sm text-gray-500">{modalData.name || activeFile?.name}</p>
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
            </div>

            {/* Body — the only scrollable region */}
            <div className="px-6 py-4 overflow-y-auto flex-1 min-h-0">
            {isRejectedView ? (
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

                {/* Document-level FIBO evidence */}
                {activeFile?.document_relevance && (
                  <div>
                    <p className="font-semibold mb-2">
                      Top FIBO concepts evaluated against the document
                    </p>
                    <div className="text-xs text-gray-500 mb-2">
                      Best score: {activeFile.document_relevance.aggregate_score?.toFixed(3)} ·
                      Doc threshold: {activeFile.document_relevance.doc_threshold?.toFixed(3)} ·
                      {' '}
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
                              <span className="font-medium">Best chunk: </span>
                              "{hit.best_chunk_excerpt}"
                            </p>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Post-LLM guardrail evidence */}
                {activeFile?.guardrail?.applied && (activeFile.guardrail.candidates?.length ?? 0) > 0 && (
                  <div>
                    <p className="font-semibold mb-2">
                      Processes the LLM produced (none cleared the post-extraction guardrail)
                    </p>
                    <div className="text-xs text-gray-500 mb-2">
                      Threshold: {activeFile.guardrail.threshold?.toFixed(3)} ·
                      Candidates: {activeFile.guardrail.candidate_count} ·
                      Accepted: {activeFile.guardrail.accepted_count} ·
                      Rejected: {activeFile.guardrail.rejected_count}
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
            ) : (
              <div className="space-y-3 text-sm text-gray-700">
                <div>
                  <p className="font-semibold">Description</p>
                  <p>{modalData.description || 'N/A'}</p>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <p className="font-semibold">Vertical</p>
                    <p>{modalData.vertical}</p>
                  </div>
                  <div>
                    <p className="font-semibold">SubVertical</p>
                    <p>{modalData.subvertical || 'N/A'}</p>
                  </div>
                </div>

                {activeFile?.guardrail?.applied && (
                  <div className="rounded border border-green-200 bg-green-50 p-2 text-xs">
                    FIBO guardrail kept{' '}
                    <strong>{activeFile.guardrail.accepted_count ?? modalData.processes.length}</strong>{' '}
                    of {activeFile.guardrail.candidate_count ?? modalData.processes.length}{' '}
                    candidate process(es) (threshold{' '}
                    {activeFile.guardrail.threshold?.toFixed(2)}).
                  </div>
                )}

                <div>
                  <p className="font-semibold mb-2">Processes ({modalData.processes.length})</p>
                  <div className="space-y-2">
                    {modalData.processes.map((proc, idx) => (
                      <div key={idx} className="p-2 border rounded bg-gray-50">
                        <div className="flex items-center justify-between">
                          <p className="font-medium">{proc.name}</p>
                          <p className="text-xs text-gray-500">{proc.level}</p>
                        </div>
                        <p className="text-xs text-gray-600 mt-1">{proc.description}</p>

                        {(proc as any).ontology_alignment && (
                          <p className="text-xs text-indigo-600 mt-1">
                            Aligned with FIBO concept{' '}
                            <strong>{(proc as any).ontology_alignment.concept_label}</strong>
                            {' '}(score {Number((proc as any).ontology_alignment.score).toFixed(3)})
                          </p>
                        )}

                        {(proc.subprocesses || []).length > 0 && (
                          <div className="mt-2 ml-2 border-l-2 border-gray-300 pl-2">
                            <p className="text-xs font-medium text-gray-700 mb-1">
                              Subprocesses ({proc.subprocesses.length})
                            </p>
                            <div className="space-y-1">
                              {proc.subprocesses.map((subproc: any, subIdx: number) => (
                                <div key={subIdx} className="p-1.5 bg-white border border-gray-200 rounded text-xs">
                                  <p className="font-medium text-gray-800">{subproc.name}</p>
                                  <p className="text-gray-600 mt-0.5">{subproc.description}</p>

                                  {(subproc.data_entities || []).length > 0 && (
                                    <div className="mt-1 ml-1 border-l border-gray-300 pl-1">
                                      <p className="text-xs font-medium text-gray-600 mb-0.5">
                                        Data Entities ({subproc.data_entities.length})
                                      </p>
                                      <div className="space-y-0.5">
                                        {subproc.data_entities.map((dataEnt: any, deIdx: number) => (
                                          <div key={deIdx} className="bg-blue-50 p-0.5 rounded text-xs">
                                            <p className="font-medium text-blue-800">{dataEnt.data_entity_name}</p>
                                            <p className="text-blue-700 text-xs">{dataEnt.data_entity_description}</p>

                                            {(dataEnt.data_elements || []).length > 0 && (
                                              <div className="mt-0.5 ml-0.5 border-l border-blue-300 pl-0.5">
                                                <p className="text-xs text-blue-600 font-medium mb-0.5">
                                                  Elements ({dataEnt.data_elements.length})
                                                </p>
                                                <div className="space-y-0.5">
                                                  {dataEnt.data_elements.map((dataElem: any, delemIdx: number) => (
                                                    <div key={delemIdx} className="bg-blue-100 p-0.5 rounded text-xs text-blue-800">
                                                      <p className="font-medium">{dataElem.data_element_name}</p>
                                                      <p className="text-blue-700 text-xs">{dataElem.data_element_description}</p>
                                                    </div>
                                                  ))}
                                                </div>
                                              </div>
                                            )}
                                          </div>
                                        ))}
                                      </div>
                                    </div>
                                  )}
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
            </div>

            {/* Footer — pinned at bottom, never hidden by long content */}
            <div className="px-6 py-3 border-t border-gray-200 bg-white shrink-0 flex gap-3 justify-end">
              {!isRejectedView && (
                <button
                  onClick={() => {
                    if (modalFileId) handleImportToGraph(modalFileId);
                  }}
                  disabled={!modalData.processes || modalData.processes.length === 0}
                  className="px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed"
                  title={
                    !modalData.processes || modalData.processes.length === 0
                      ? 'No processes available to import'
                      : 'Import this capability into the graph'
                  }
                >
                  Import to Graph
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
    </div>
  );
};

export default CompassIngestion;
