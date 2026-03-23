// Module-level extraction state manager — survives component unmount/remount
interface ExtractedCapabilityModel {
  id?: number;
  name: string;
  description: string;
  vertical: string;
  subvertical?: string;
  processes: any[];
}

interface UploadedFile {
  id: string;
  name: string;
  size: number;
  type: string;
  status: 'pending' | 'uploading' | 'extracting' | 'success' | 'error';
  progress: number;
  error?: string;
  extractedData?: ExtractedCapabilityModel;
  chunks_path?: string;
}

interface ExtractionEvent {
  status: 'started' | 'cache_hit' | 'loading' | 'extracting' | 'success' | 'error';
  progress?: number;
  message?: string;
  data?: ExtractedCapabilityModel;
  output_path?: string;
  chunks_path?: string;
  filename?: string;
  error?: string;
  type?: string;
  cached?: boolean;
}

const INGESTION_STORAGE_KEY = 'compass_ingestion_files';

// Module-level state
let activeExtractions = new Map<string, AbortController>();
let cachedFiles: UploadedFile[] = [];
let thinkingState = { isThinking: false, message: '' };
let pendingModalData: { data: ExtractedCapabilityModel; fileId: string } | null = null;

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
    // Keep files in their current state - extractions continue in background
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
  notifySubscribers();
}

export function clearAllFiles() {
  cachedFiles = [];
  saveFiles(cachedFiles);
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

export async function startExtraction(
  file: UploadedFile,
  actualFile: File,
  vertical: string,
  subVertical: string,
  depth: string,
  onModalOpen: (data: ExtractedCapabilityModel, fileId: string) => void
) {
  const controller = new AbortController();
  activeExtractions.set(file.id, controller);

  updateFile(file.id, { status: 'uploading', progress: 10 });

  const formData = new FormData();
  formData.append('file', actualFile);

  const params = new URLSearchParams();
  if (vertical.trim()) params.append('vertical', vertical.trim());
  if (subVertical.trim()) params.append('subvertical', subVertical.trim());
  params.append('extraction_depth', depth);

  const url = `/api/upload/pdf${params.toString() ? `?${params.toString()}` : ''}`;

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
            handleExtractionEvent(file.id, event, onModalOpen);
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
        handleExtractionEvent(file.id, event, onModalOpen);
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
    // Clear thinking if no more active extractions
    if (activeExtractions.size === 0) {
      setThinking(false);
    }
  }
}

function handleExtractionEvent(
  fileId: string,
  event: ExtractionEvent,
  onModalOpen: (data: ExtractedCapabilityModel, fileId: string) => void
) {
  switch (event.status) {
    case 'started':
      updateFile(fileId, { status: 'uploading', progress: 5 });
      setThinking(true, 'Starting extraction...');
      break;

    case 'cache_hit':
      updateFile(fileId, {
        status: 'success',
        progress: 100,
        extractedData: event.data,
      });
      setThinking(false);
      if (event.data) {
        // Try to show modal, but store for later if callback fails
        try {
          onModalOpen(event.data, fileId);
        } catch (e) {
          // Component might be unmounted, store for later
          pendingModalData = { data: event.data, fileId };
        }
      }
      break;

    case 'loading':
      updateFile(fileId, {
        status: 'extracting',
        progress: Math.min(event.progress || 30, 50),
      });
      setThinking(true, event.message || 'Loading document...');
      break;

    case 'extracting':
      updateFile(fileId, {
        status: 'extracting',
        progress: Math.min(event.progress || 60, 95),
      });
      setThinking(true, event.message || 'LLM extracting capabilities...');
      break;

    case 'success':
      if (event.data) {
        updateFile(fileId, {
          status: 'success',
          progress: 100,
          extractedData: event.data,
          chunks_path: event.chunks_path,
        });
        setThinking(false);
        // Try to show modal, but store for later if callback fails
        try {
          onModalOpen(event.data, fileId);
        } catch (e) {
          // Component might be unmounted, store for later
          pendingModalData = { data: event.data, fileId };
        }
      }
      break;

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
  pendingModalData = null; // Clear after retrieval
  return data;
}

export function hasPendingModal(): boolean {
  return pendingModalData !== null;
}
