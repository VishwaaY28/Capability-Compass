import { useState, useEffect, useRef } from 'react'
import { FiEye, FiEdit2, FiEdit3, FiPlus, FiChevronRight, FiChevronDown, FiLayers, FiTrash2 } from 'react-icons/fi'
import { Toaster, toast } from 'react-hot-toast'


import { useCapabilityApi } from '../hooks/useCapability';
import type { Capability, Process, Vertical, SubVertical } from '../hooks/useCapability';
import favicon from '../assets/favicon.png';

// Domain to Sub-Vertical mapping
const DOMAIN_SUBVERTICAL_MAP: Record<string, string[]> = {
  'Capital Markets': [
    'Investment banking',
    'Wealth management',
    'Asset management',
    'Private equity',
    'Market infrastructure',
    'Asset services, Custodians',
    'Others',
  ],
  'International Financial Institution (IFI)': [
    'Multilateral Development Bank (MDB)',
    'Development Finance Institution',
    'Nondepository Credit Intermediation',
  ],
  'US Federal Government': [
    'Federal agencies',
  ],
  'Banking': [
    'Retail banking',
    'Investment banking',
    'Corporate banking',
    'Wealth management',
  ],
};

const SYSTEM_PROMPT = `You are a Senior Enterprise Architect and Process Subject Matter Expert (SME) in the **{domain}** domain, specializing in classifying business capabilities.

## Task:
Generate a **comprehensive list of high-level Business Capabilities (Processes)** for the sub-vertical **'{capability_name}'** within the **{domain}** domain. The processes must be categorized by their **Process Type** (Core or Support).

## Input Variables:
- **domain**: {domain}
- **subvertical_name**: {capability_name},{capability_description}
- **process_type_filter**: {process_type} (Filter: Only generate processes matching this type: 'Core' or 'Support')

## Requirements:
- The list must be **comprehensive**, capturing all relevant, high-level capabilities in the specified sub-vertical and matching the \`{process_type}\` filter. **Do not impose a limit on the number of processes.**
- Each capability must have a **Name** (Business Process), a **Category** (Front/Middle/Back Office), a **Type** (Core/Support), and a detailed **Description** (Activities and Description).
- The **Category** must be one of: **'Front Office'**, **'Middle Office'**, or **'Back Office'**.
- The **Type** must strictly match the \`{process_type}\` provided ('Core' or 'Support').
- Do not invent processes; base them strictly on standard industry practices for Enterprise Architecture in the specified domain and sub-vertical.
- If the domain/sub-vertical combination is not recognized or has no relevant processes for the specified type, return: {{'error': 'No relevant {process_type} capabilities found for {capability_name} in {domain}'}}

## Output Format:
Return the data as a valid JSON object matching the schema below. The output must be an array of process objects.

### JSON Schema:
{{
  "processes": [
    {{
      "name": "string (e.g., Market research & strategy development, Deal origination & sourcing, Investment screening & initial evaluation, Due Diligence, Financial Analysis & Deal Structuring, Transaction Execution & Closing)",
      "category": "string (Front Office | Middle Office | Back Office)",
      "process_type": "string (Core | Support)",
      "description": "string (description of activities)"
    }},
    // ... additional process objects
  ]
}}`;

export default function Home() {
  const [verticals, setVerticals] = useState<Vertical[]>([]);
  const [selectedVertical, setSelectedVertical] = useState('');
  const [subverticals, setSubverticals] = useState<SubVertical[]>([]);
  const [selectedSubVertical, setSelectedSubVertical] = useState('');
  const [capabilities, setCapabilities] = useState<Capability[]>([]);

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [modalMode, setModalMode] = useState<'add' | 'edit' | 'view'>('add');
  const [editingId, setEditingId] = useState<number | null>(null);

  const [formName, setFormName] = useState('');
  const [formDescription, setFormDescription] = useState('');

  const {
    listVerticals,
    listSubVerticals,
    listCapabilities,
    createVertical,
    createSubVertical,
    createCapability,
    updateCapability,
    listProcesses,
    createProcess,
    createSubprocess,
    deleteProcess,
    deleteCapability,
    generateProcesses,
    getPromptTemplate,
  } = useCapabilityApi();

  const [newVerticalName, setNewVerticalName] = useState('');
  const [isSavingVertical, setIsSavingVertical] = useState(false);

  const loadedRef = useRef(false);


  useEffect(() => {
    const prev = document.documentElement.style.overflowY;
    try {
      document.documentElement.style.overflowY = 'scroll';
    } catch (e) {

    }
    return () => {
      try {
        document.documentElement.style.overflowY = prev;
      } catch (e) {

      }
    };
  }, []);

  // Load sub-verticals when a vertical is selected
  useEffect(() => {
    async function loadSubVerticals() {
      if (!selectedVertical) {
        setSubverticals([]);
        return;
      }
      try {
        // Use the API's filtering by verticalId
        const subs = await listSubVerticals(Number(selectedVertical));
        console.log('[DEBUG] Loaded subverticals:', subs);
        setSubverticals(subs);
      } catch (e) {
        console.error('Failed to load sub-verticals:', e);
        setSubverticals([]);
      }
    }
    loadSubVerticals();
  }, [selectedVertical]);

  useEffect(() => {
    if (loadedRef.current) return;
    loadedRef.current = true;
    async function load() {
      try {
        const verts = await listVerticals();
        setVerticals(verts);
        
        // Load sub-verticals for the selected vertical
        if (selectedVertical) {
          const subs = await listSubVerticals();
          const filtered = subs.filter((sv: any) => String(sv.vertical_id || sv.vertical?.id) === selectedVertical);
          setSubverticals(filtered);
        }
        
        const caps = await listCapabilities();

        const first = caps && caps.length > 0 ? (caps[0] as any) : null;
        if (first && Array.isArray((first as any).processes)) {

          const normalized = caps.map((c: any) => ({ ...c, processes: c.processes || [] }));
          setCapabilities(normalized as Capability[]);
        } else {

          const allProcesses = await listProcesses();

          const capMap: Record<number, Process[]> = {};
          allProcesses.forEach((p: any) => {
            const capId = p.capability_id || p.capability || p.capabilityId || p.capability?.id;
            if (capId) {
              if (!capMap[capId]) capMap[capId] = [];
              capMap[capId].push(p);
            }
          });
          setCapabilities(
            caps.map((c: any) => ({ ...c, processes: capMap[c.id] || [] }))
          );
        }
      } catch (e) {
        toast.error('Failed to load capabilities');
      }
    }
    load();
  }, [listCapabilities, listProcesses, listVerticals]);

  function openAddModal() {
    setModalMode('add');
    setEditingId(null);
    setFormName('');
    setFormDescription('');
    
    console.log('[DEBUG] openAddModal - selectedSubVertical:', selectedSubVertical);
    
    setIsModalOpen(true);
  }

  function openEditModal(cap: Capability) {
    setModalMode('edit');
    setEditingId(cap.id);
    setFormName(cap.name);
    setFormDescription(cap.description);
    setIsModalOpen(true);
  }

  function openViewModal(cap: Capability) {
    setModalMode('view');
    setEditingId(cap.id);
    setFormName(cap.name);
    setFormDescription(cap.description);
    setIsModalOpen(true);
  }

  async function saveCapability() {
    try {
      if (modalMode === 'add') {
        if (!selectedSubVertical || !formName.trim()) {
          toast.error('Please select a sub-vertical and enter a capability name');
          return;
        }

        const newCap = await createCapability({
          subvertical: selectedSubVertical,
          name: formName,
          description: formDescription,
        });
        
        const selectedSV = subverticals.find((sv: any) => String(sv.id) === selectedSubVertical);
        const subverticalName = selectedSV?.name || selectedSubVertical;
        
        setCapabilities((s) => [
          { ...newCap, subvertical: subverticalName, processes: [] },
          ...s,
        ]);
        toast.success('Successfully added capability');
      } else if (modalMode === 'edit' && editingId != null) {
        const updated = await updateCapability(editingId, {
          name: formName,
          description: formDescription,
        });
        setCapabilities((s) =>
          s.map((c) => (c.id === editingId ? { ...c, ...updated } : c))
        );
        toast.success('Successfully updated capability');
      }
    } catch (e) {
      console.error(e);
      toast.error('Failed to save capability');
    }
    setIsModalOpen(false);
  }

  async function handleCreateVertical() {
    const name = newVerticalName.trim();
    if (!name) {
      toast.error('Enter a vertical name');
      return;
    }
    try {
      setIsSavingVertical(true);
      const created = await createVertical({ name });
      setVerticals((s) => [...s, created]);
      setSelectedVertical(String((created as any).id));
      setNewVerticalName('');
      toast.success('Vertical created successfully');
    } catch (e) {
      console.error(e);
      toast.error('Failed to create vertical');
    } finally {
      setIsSavingVertical(false);
    }
  }

  async function handleExportCapability() {
    if (selectedExportCapIds.size === 0) {
      toast.error('Select at least one capability to export');
      return;
    }
    try {
      setIsExporting(true);
      const ids = Array.from(selectedExportCapIds);

      if (ids.length === 1) {
        // Single export - download directly
        const res = await fetch(`/api/export/capability/${ids[0]}/csv`);
        if (!res.ok) throw new Error((await res.text()) || 'Export failed');
        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        const cap = capabilities.find((c) => c.id === ids[0]);
        a.href = url;
        a.download = cap ? `${cap.name.replace(/\s+/g, '_')}_export.csv` : `capability_${ids[0]}_export.csv`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(url);
      } else {
        // Multi export - download each file sequentially
        for (const id of ids) {
          const res = await fetch(`/api/export/capability/${id}/csv`);
          if (!res.ok) {
            toast.error(`Failed to export capability ${id}`);
            continue;
          }
          const blob = await res.blob();
          const url = window.URL.createObjectURL(blob);
          const a = document.createElement('a');
          const cap = capabilities.find((c) => c.id === id);
          a.href = url;
          a.download = cap ? `${cap.name.replace(/\s+/g, '_')}_export.csv` : `capability_${id}_export.csv`;
          document.body.appendChild(a);
          a.click();
          a.remove();
          window.URL.revokeObjectURL(url);
        }
      }

      toast.success(`${ids.length} CSV file${ids.length > 1 ? 's' : ''} downloaded`);
      setIsExportModalOpen(false);
      setSelectedExportCapIds(new Set());
    } catch (e) {
      console.error(e);
      toast.error('Failed to export CSV');
    } finally {
      setIsExporting(false);
    }
  }


  const [isProcessModalOpen, setIsProcessModalOpen] = useState(false);
  const [processCapId, setProcessCapId] = useState<number | null>(null);
  const [processLevel, setProcessLevel] = useState('');
  const [isGenerating, setIsGenerating] = useState(false);
  const [processMode, setProcessMode] = useState<'manual' | 'ai'>('ai'); // Toggle between manual and AI
  const [manualProcessName, setManualProcessName] = useState('');
  const [manualProcessDescription, setManualProcessDescription] = useState('');
  const [isSavingManual, setIsSavingManual] = useState(false);
  const [aiPrompt, setAiPrompt] = useState('');
  // Generated processes preview modal (LLM responses) - user must approve which to save
  const [generatedPreview, setGeneratedPreview] = useState<any[]>([]);
  const [isGeneratedModalOpen, setIsGeneratedModalOpen] = useState(false);
  
  // Subprocess modal state
  const [isSubprocessModalOpen, setIsSubprocessModalOpen] = useState(false);
  const [subprocessParentProcessId, setSubprocessParentProcessId] = useState<number | null>(null);
  const [subprocessParentCapId, setSubprocessParentCapId] = useState<number | null>(null);
  const [manualSubprocessName, setManualSubprocessName] = useState('');
  const [manualSubprocessDescription, setManualSubprocessDescription] = useState('');
  const [isSavingSubprocess, setIsSavingSubprocess] = useState(false);
  const [subprocessMode, setSubprocessMode] = useState<'manual' | 'ai'>('ai');
  const [isGeneratingSubprocess, setIsGeneratingSubprocess] = useState(false);
  const [aiSubprocessPrompt, setAiSubprocessPrompt] = useState('');
  
  const [selectedGeneratedIdxs, setSelectedGeneratedIdxs] = useState<Set<string>>(new Set());
  const [isSavingGenerated, setIsSavingGenerated] = useState(false);

  // CSV export modal state
  const [isExportModalOpen, setIsExportModalOpen] = useState(false);
  const [selectedExportCapIds, setSelectedExportCapIds] = useState<Set<number>>(new Set());
  const [isExporting, setIsExporting] = useState(false);

  const processLevelOptions = [
    'enterprise',
    'core',
    'process',
  ];

  function openProcessModal(capId: number) {
    setProcessCapId(capId);
    setProcessLevel('core');
    setProcessMode('ai');
    setManualProcessName('');
    setManualProcessDescription('');
    setAiPrompt('');
    setIsProcessModalOpen(true);
  }

  function openSubprocessModal(parentProcessId: number, parentCapId: number) {
    setSubprocessParentProcessId(parentProcessId);
    setSubprocessParentCapId(parentCapId);
    setManualSubprocessName('');
    setManualSubprocessDescription('');
    setSubprocessMode('ai');
    setAiSubprocessPrompt('');
    setIsSubprocessModalOpen(true);
  }

  useEffect(() => {
    if (processLevel && isProcessModalOpen && processMode === 'ai') {
      getPromptTemplate(processLevel).then((data) => {
        setAiPrompt(data.prompt);
      }).catch((e) => {
        console.error('Failed to fetch prompt', e);
        setAiPrompt('');
      });
    }
  }, [processLevel, isProcessModalOpen, processMode, getPromptTemplate]);

  useEffect(() => {
    if (isSubprocessModalOpen && subprocessMode === 'ai') {
      setAiSubprocessPrompt("Generate subprocesses for the process '{process_name}' (Description: {process_description}) in the {domain} domain. Return ONLY valid JSON with a 'subprocesses' array containing subprocess objects with 'name', 'category', and 'description' fields.");
    }
  }, [isSubprocessModalOpen, subprocessMode]);

  async function handleSaveManualProcess() {
    if (!manualProcessName.trim() || processCapId == null) return;
    try {
      setIsSavingManual(true);
      const newProcess = await createProcess({
        name: manualProcessName.trim(),
        level: processLevel,
        description: manualProcessDescription.trim(),
        capability_id: processCapId,
      });
      setCapabilities((s) =>
        s.map((c) =>
          c.id === processCapId ? { ...c, processes: [...(c.processes || []), newProcess] } : c
        )
      );
      setIsProcessModalOpen(false);
      setManualProcessName('');
      setManualProcessDescription('');
      toast.success('Process created successfully');
    } catch (e) {
      toast.error('Failed to create process');
      console.error(e);
    } finally {
      setIsSavingManual(false);
    }
  }

  async function handleSaveManualSubprocess() {
    if (!manualSubprocessName.trim() || subprocessParentProcessId == null || subprocessParentCapId == null) return;
    try {
      setIsSavingSubprocess(true);
      const newSubprocess = await createSubprocess({
        name: manualSubprocessName.trim(),
        description: manualSubprocessDescription.trim(),
        category: undefined, // Can be extended later if needed
        parent_process_id: subprocessParentProcessId,
      });
      setCapabilities((s) =>
        s.map((c) =>
          c.id === subprocessParentCapId
            ? {
                ...c,
                processes: c.processes.map((p: any) =>
                  p.id === subprocessParentProcessId
                    ? { ...p, subprocesses: [...(p.subprocesses || []), newSubprocess] }
                    : p
                ),
              }
            : c
        )
      );
      setIsSubprocessModalOpen(false);
      setManualSubprocessName('');
      setManualSubprocessDescription('');
      toast.success('Subprocess created successfully');
    } catch (e) {
      toast.error('Failed to create subprocess');
      console.error(e);
    } finally {
      setIsSavingSubprocess(false);
    }
  }

  async function handleGenerateSubprocess() {
    if (subprocessParentProcessId == null || subprocessParentCapId == null) return;
    try {
      setIsGeneratingSubprocess(true);
      
      const parentCapability = capabilities.find((c) => c.id === subprocessParentCapId);
      const parentProcess = parentCapability?.processes.find((p: any) => p.id === subprocessParentProcessId);
      
      if (!parentCapability || !parentProcess) {
        toast.error('Parent capability or process not found');
        return;
      }

      const result = await generateProcesses(parentProcess.name, subprocessParentCapId, parentCapability.subvertical || '', 'subprocess', parentProcess.description || '', 
        aiSubprocessPrompt
          .replace('{process_name}', parentProcess.name)
          .replace('{process_description}', parentProcess.description || '')
          .replace('{domain}', parentCapability.subvertical || '')
      );

      if (result.status === 'success') {
        let subprocessesFromLLM: any[] = [];
        
        console.log('[DEBUG] LLM Response for subprocesses:', result);
        
        if (result.data?.processes && Array.isArray(result.data.processes)) {
          subprocessesFromLLM = result.data.processes;
          console.log('[DEBUG] Using result.data.processes');
        } else if (result.data?.subprocesses && Array.isArray(result.data.subprocesses)) {
          subprocessesFromLLM = result.data.subprocesses;
          console.log('[DEBUG] Using result.data.subprocesses');
        } else if (Array.isArray(result.data)) {
          subprocessesFromLLM = result.data;
          console.log('[DEBUG] Using result.data directly as array');
        }

        const normalized = (Array.isArray(subprocessesFromLLM) ? subprocessesFromLLM : []).map((proc: any, idx: number) => ({
          tempId: idx,
          name: proc.name,
          description: proc.description,
          category: proc.category || '',
          level: 'subprocess',
          subprocesses: [],
        }));

        console.log('[DEBUG] normalized subprocesses:', normalized);
        setGeneratedPreview(normalized);
        setSelectedGeneratedIdxs(new Set());
        setIsGeneratedModalOpen(true);
        toast.success(`AI generated ${normalized.length} subprocesses (preview). Please select which to save.`);
        setIsSubprocessModalOpen(false);
      } else {
        toast.error('Failed to generate subprocesses');
      }
    } catch (e) {
      toast.error('Failed to generate subprocesses');
      console.error(e);
    } finally {
      setIsGeneratingSubprocess(false);
    }
  }

  async function handleGenerateProcess() {
    if (processCapId == null) return;
    try {
      setIsGenerating(true);
      
      const parentCapability = capabilities.find((c) => c.id === processCapId);
      if (!parentCapability) {
        toast.error('Capability not found');
        return;
      }

      const result = await generateProcesses(parentCapability.name, processCapId, parentCapability.subvertical || '', processLevel, parentCapability.description || '', aiPrompt);

      if (result.status === 'success') {
        const created = result.processes || [];
        
        // Handle the new response structure: result.data is the LLM JSON with 'processes' array
        let processesFromLLM: any[] = [];
        
        console.log('[DEBUG] LLM Response:', result);
        console.log('[DEBUG] result.data:', result.data);
        
        if (result.data?.processes && Array.isArray(result.data.processes)) {
          processesFromLLM = result.data.processes;
          console.log('[DEBUG] Using result.data.processes');
        } else if (result.data?.core_processes && Array.isArray(result.data.core_processes)) {
          // Fallback for old response format
          processesFromLLM = result.data.core_processes;
          console.log('[DEBUG] Using result.data.core_processes');
        } else if (result.data?.['Core Processes'] && Array.isArray(result.data['Core Processes'])) {
          // Fallback for another old format
          processesFromLLM = result.data['Core Processes'];
          console.log('[DEBUG] Using result.data[Core Processes]');
        } else if (Array.isArray(result.data)) {
          // If data is directly an array
          processesFromLLM = result.data;
          console.log('[DEBUG] Using result.data directly as array');
        } else {
          console.log('[DEBUG] No processes found in result.data, checking result.data keys:', Object.keys(result.data || {}));
        }

        const preferSource = Array.isArray(created) && created.length > 0 ? created : processesFromLLM;
        console.log('[DEBUG] processesFromLLM:', processesFromLLM);
        console.log('[DEBUG] preferSource length:', preferSource.length);

        
        const normalized = (Array.isArray(preferSource) ? preferSource : []).map((proc: any, idx: number) => ({
          tempId: idx,
          name: proc.name,
          description: proc.description,
          category: proc.category || '',
          level: proc.level || processLevel || 'core',
          subprocesses: Array.isArray(proc.subprocesses)
            ? proc.subprocesses.map((sub: any, subIdx: number) => ({
                id: sub.id ?? `${idx + 10000}-${subIdx}`,
                name: sub.name,
                description: sub.description,
                category: sub.category || '',
                lifecycle_phase: sub.lifecycle_phase,
              }))
            : [],
        }));

        console.log('[DEBUG] normalized processes:', normalized);
        setGeneratedPreview(normalized);
        setSelectedGeneratedIdxs(new Set());
        setIsGeneratedModalOpen(true);
        toast.success(`AI generated ${normalized.length} processes (preview). Please select which to save.`);
        setIsProcessModalOpen(false);
      } else {
        toast.error('Failed to generate processes');
      }
    } catch (e) {
      toast.error('Failed to generate processes');
      console.error(e);
    } finally {
      setIsGenerating(false);
    }
  }

  async function handleDeleteProcess(processId: number | string, capId: number, parentProcessId?: number | string) {
    const ok = window.confirm('Are you sure you want to delete this process? This cannot be undone.');
    if (!ok) return;
    try {
      
      if (typeof processId === 'number') {
        await deleteProcess(processId);
      }

      
      setCapabilities((prev) =>
        prev.map((c) => {
          if (c.id !== capId) return c;
          const processes = (c.processes || []).map((p: any) => ({ ...p }));
          if (parentProcessId == null) {
            
            return { ...c, processes: processes.filter((p: any) => String(p.id) !== String(processId)) };
          }
          
          return {
            ...c,
            processes: processes.map((p: any) => {
              if (String(p.id) !== String(parentProcessId)) return p;
              const subs = Array.isArray(p.subprocesses) ? p.subprocesses.filter((s: any) => String(s.id) !== String(processId)) : [];
              return { ...p, subprocesses: subs };
            }),
          };
        })
      );

      toast.success('Process deleted');
    } catch (e) {
      console.error(e);
      toast.error('Failed to delete process');
    }
  }

  async function handleDeleteCapability(capId: number) {
    const ok = window.confirm('Delete this capability and all its processes? This cannot be undone.');
    if (!ok) return;
    try {
      await deleteCapability(capId);
      setCapabilities((prev) => prev.filter((c) => c.id !== capId));
      toast.success('Capability deleted');
    } catch (e) {
      console.error(e);
      toast.error('Failed to delete capability');
    }
  }

   
  async function saveSelectedGeneratedProcesses() {
    // Check if we're saving subprocesses or processes
    const isSavingSubprocesses = subprocessParentProcessId != null;
    
    if (isSavingSubprocesses) {
      if (subprocessParentCapId == null) return;
    } else {
      if (processCapId == null) return;
    }
    
    if (!Array.isArray(generatedPreview) || generatedPreview.length === 0) return;
    if (selectedGeneratedIdxs.size === 0) {
      toast('No items selected to save');
      return;
    }

    try {
      setIsSavingGenerated(true);
      const createdProcs: any[] = [];
      
      for (let procIdx = 0; procIdx < generatedPreview.length; procIdx++) {
        const procKey = `proc-${procIdx}`;
        const isItemSelected = selectedGeneratedIdxs.has(procKey);
        
        if (!isItemSelected) continue; 
        
        const p = generatedPreview[procIdx];
        if (!p) continue;
        
        try {
          const selectedSubs: any[] = [];
          if (Array.isArray(p.subprocesses)) {
            for (let subIdx = 0; subIdx < p.subprocesses.length; subIdx++) {
              const subKey = `proc-${procIdx}-sub-${subIdx}`;
                if (selectedGeneratedIdxs.has(subKey)) {
                const sub = p.subprocesses[subIdx];
                selectedSubs.push({ name: sub.name, description: sub.description || '', category: sub.category || undefined });
              }
            }
          }

          const capId = isSavingSubprocesses ? subprocessParentCapId : processCapId;
          const createPayload: any = {
            name: p.name,
            level: p.level,
            description: p.description || '',
            capability_id: capId,
            category: p.category || undefined,
          };

          if (isSavingSubprocesses) {
            // Use createSubprocess for subprocess creation
            const subprocessPayload = {
              name: p.name,
              description: p.description || '',
              category: p.category || undefined,
              parent_process_id: subprocessParentProcessId,
            };
            const created = await createSubprocess(subprocessPayload);
            createdProcs.push(created);
          } else {
            // Use createProcess for process creation
            const processPayload: any = {
              name: p.name,
              level: p.level,
              description: p.description || '',
              capability_id: capId,
              category: p.category || undefined,
            };
            if (selectedSubs.length > 0) {
              processPayload.subprocesses = selectedSubs;
            }
            const created = await createProcess(processPayload);
            createdProcs.push(created);
          }
        } catch (err) {
          console.error('createProcess failed for generated item', err);
        }
      }

      if (createdProcs.length > 0) {
        if (isSavingSubprocesses) {
          // Update subprocesses
          setCapabilities((prev) =>
            prev.map((c) =>
              c.id === subprocessParentCapId
                ? {
                    ...c,
                    processes: c.processes.map((proc: any) =>
                      proc.id === subprocessParentProcessId
                        ? { ...proc, subprocesses: [...(proc.subprocesses || []), ...createdProcs] }
                        : proc
                    ),
                  }
                : c
            )
          );
        } else {
          // Update processes
          setCapabilities((prev) =>
            prev.map((c) => (c.id === processCapId ? { ...c, processes: [...(c.processes || []), ...createdProcs] } : c))
          );
          if (processCapId != null) setExpandedIds((prev) => (prev.includes(processCapId) ? prev : [processCapId, ...prev]));
        }
        toast.success(`Saved ${createdProcs.length} ${isSavingSubprocesses ? 'subprocesses' : 'processes'}`);
      } else {
        toast.error(`No ${isSavingSubprocesses ? 'subprocesses' : 'processes'} were saved`);
      }
    } catch (e) {
      console.error(e);
      toast.error(`Failed to save selected ${isSavingSubprocesses ? 'subprocesses' : 'processes'}`);
    } finally {
      setIsSavingGenerated(false);
      setIsGeneratedModalOpen(false);
      setGeneratedPreview([]);
      setSelectedGeneratedIdxs(new Set());
    }
  }


  const [expandedIds, setExpandedIds] = useState<number[]>([]);
  const [expandedProcessIds, setExpandedProcessIds] = useState<Set<number>>(new Set());

  function toggleExpand(capId: number) {
    setExpandedIds((prev) => (prev.includes(capId) ? prev.filter((id) => id !== capId) : [capId, ...prev]));
  }

  function toggleProcessExpand(processId: number) {
    setExpandedProcessIds((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(processId)) {
        newSet.delete(processId);
      } else {
        newSet.add(processId);
      }
      return newSet;
    });
  }


  const parentCap = capabilities.find((c) => c.id === processCapId);
  const selectedVerticalName = verticals.find((v) => String(v.id) === selectedVertical)?.name;
  const currentCap = editingId != null ? capabilities.find((c) => c.id === editingId) : undefined;
  const capSubVerticalName = currentCap?.subvertical ?? selectedVerticalName;

  return (
    <div className="min-h-screen bg-gray-50">
      <Toaster
        position="top-right"
        toastOptions={{
          duration: 3000,
          style: {
            background: '#363636',
            color: '#fff',
          },
        }}
      />
      <header className="border-b sticky top-0 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 z-50">
          <div className="container px-6 py-4">
              <div className="flex items-center gap-3">
           {/* <img src={favicon} width={40} height={40} alt="favicon" /> */}
                <div>
                    <h1 className="text-xl font-semibold">Master Catalog</h1>
                    <p className="text-xs text-muted-foreground">
                      Manage your enterprise capabilities and their associated processes.
                    </p>
                </div>
              </div>
          </div>
      </header>

      <div className="mx-auto mt-6 bg-white p-6 px-8 rounded-lg shadow-sm max-w-6xl">
        <div className="flex items-center gap-3 mb-6">
          <FiLayers className="w-8 h-8" />
          <h1 className="text-2xl font-semibold text-gray-900">Capabilities</h1>
          <div className="ml-auto">
                  <button
                    className="px-4 py-2 rounded-md text-sm font-medium transition-colors bg-gray-100 border border-primary text-indigo-600 hover:bg-indigo-700 hover:text-white"
                    onClick={() => setIsExportModalOpen(true)}
                    title="Export as CSV"
                  >
                    Export as CSV
                  </button>
                </div>
        </div>

        <div className="flex items-center gap-4 mb-6">
          <div className="flex items-center gap-3">
            {verticals.length === 0 ? (
              <div className="flex items-center gap-2">
                <input
                  className="border rounded-md px-3 py-2 bg-white text-sm text-gray-700 focus:ring-2 focus:ring-indigo-200 w-48"
                  placeholder="Enter vertical name"
                  value={newVerticalName}
                  onChange={(e) => setNewVerticalName(e.target.value)}
                />
                <button
                  className={`px-3 py-2 rounded-md text-sm font-medium whitespace-nowrap ${newVerticalName.trim() ? 'bg-indigo-600 text-white' : 'bg-gray-300 text-gray-500 cursor-not-allowed'}`}
                  disabled={!newVerticalName.trim() || isSavingVertical}
                  onClick={handleCreateVertical}
                >
                  {isSavingVertical ? 'Saving...' : 'Add Vertical'}
                </button>
              </div>
            ) : (
              <>
                <select
                  className="border rounded-md px-3 py-2 bg-white text-sm text-gray-700 focus:ring-2 focus:ring-indigo-200 w-48"
                  value={selectedVertical}
                  onChange={(e) => setSelectedVertical(e.target.value)}
                >
                  <option value="">Select Vertical</option>
                  {verticals.map((vertical) => (
                    <option key={vertical.id} value={String(vertical.id)}>
                      {vertical.name}
                    </option>
                  ))}
                </select>

                {/* Sub-Vertical Dropdown */}
                <select
                  className={`border rounded-md px-3 py-2 bg-white text-sm text-gray-700 focus:ring-2 focus:ring-indigo-200 w-48 ${!selectedVertical ? 'opacity-50 cursor-not-allowed' : ''}`}
                  value={selectedSubVertical}
                  onChange={(e) => setSelectedSubVertical(e.target.value)}
                  disabled={!selectedVertical}
                >
                  <option value="">Select Sub-Vertical</option>
                  {subverticals.map((subVertical: any) => (
                    <option key={subVertical.id} value={String(subVertical.id)}>
                      {subVertical.name}
                    </option>
                  ))}
                </select>
              </>
            )}
          </div>

          <button
            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors whitespace-nowrap ${selectedSubVertical ? 'bg-gray-100 border border-primary text-indigo-600 hover:bg-indigo-700 hover:text-white' : 'bg-gray-300 text-gray-500 cursor-not-allowed'}`}
            disabled={!selectedSubVertical}
            onClick={openAddModal}
          >
            Add Capability
          </button>
        </div>

        <div>
          {capabilities.length === 0 ? (
            <p className="text-gray-500">No Sub-Verticals yet.</p>
          ) : (
            <ul className="space-y-4">
              {capabilities.map((c) => {
                const isExpanded = expandedIds.includes(c.id)

                return (
                  <li key={c.id} className="bg-white border border-gray-100 rounded-2xl shadow-sm hover:shadow-md transition-shadow">
                    <div className="p-4 flex items-start justify-between gap-4">
                      <div className="flex-1">
                        <div className="flex items-center gap-3">
                          <button
                            className="text-gray-400 p-2 rounded-md hover:bg-gray-50 flex items-center justify-center"
                            onClick={() => toggleExpand(c.id)}
                            aria-expanded={isExpanded}
                            title={isExpanded ? 'Collapse' : 'Expand'}
                          >
                            {isExpanded ? <FiChevronDown size={18} /> : <FiChevronRight size={18} />}
                          </button>

                          <div>
                            <div className="text-lg font-semibold text-gray-900">{c.name}</div>
                            <div className="mt-1">
                              <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-indigo-50 text-indigo-700">{c.subvertical ?? 'Unassigned'}</span>
                            </div>
                            <div className="mt-3 text-sm text-gray-600">{c.description}</div>
                          </div>
                        </div>
                      </div>

                      <div className="flex items-center gap-2">
                        <button
                          className="w-9 h-9 flex items-center justify-center rounded-md text-gray-600 hover:bg-gray-50"
                          onClick={() => openViewModal(c)}
                          title="View"
                          aria-label="View capability"
                        >
                          <FiEye size={16} />
                        </button>

                        <button
                          className="w-9 h-9 flex items-center justify-center rounded-md text-gray-600 hover:bg-gray-50"
                          onClick={() => openEditModal(c)}
                          title="Edit"
                          aria-label="Edit capability"
                        >
                          <FiEdit2 size={16} />
                        </button>

                        <button
                          className="w-9 h-9 flex items-center justify-center rounded-md bg-indigo-600 text-white hover:bg-indigo-700"
                          onClick={() => openProcessModal(c.id)}
                          title="Add process"
                          aria-label="Add process"
                        >
                          <FiPlus size={16} />
                        </button>

                        <button
                          className="w-9 h-9 flex items-center justify-center rounded-md text-red-600 hover:bg-red-50"
                          onClick={() => handleDeleteCapability(c.id)}
                          title="Delete capability"
                          aria-label="Delete capability"
                        >
                          <FiTrash2 size={16} />
                        </button>
                      </div>
                    </div>

                    {isExpanded && (
                      <div className="p-6 border-t bg-gray-50">
                        <h3 className="text-lg font-semibold text-gray-900 mb-6 flex items-center gap-2">
                          <FiLayers className="w-5 h-5 text-indigo-600" />
                          Processes
                        </h3>
                        {c.processes.length === 0 ? (
                          <div className="text-gray-500 text-center py-8">No processes yet.</div>
                        ) : (
                          <div className="space-y-3">
                            {c.processes.map((p) => {
                              const subprocesses = Array.isArray(p.subprocesses) ? p.subprocesses : [];
                              const hasSubprocesses = subprocesses.length > 0;
                              const isSubprocessesExpanded = expandedProcessIds.has(Number(p.id));

                              return (
                                <div key={p.id} className="bg-white border border-gray-200 rounded-lg overflow-hidden hover:shadow-md transition-shadow">
                                  {/* Core Process Header */}
                                  <div className="p-4">
                                    <div className="flex items-start justify-between gap-4">
                                      <div className="flex-1">
                                        <div className="flex items-center gap-3">
                                          <div className="w-2 h-2 rounded-full bg-indigo-600 flex-shrink-0 mt-1"></div>
                                          <div className="flex-1">
                                            <h4 className="font-semibold text-gray-900">{p.name}</h4>
                                            <div className="flex items-center gap-2 mt-2">
                                              <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-indigo-100 text-indigo-800">
                                                {p.level}
                                              </span>
                                              {p.category && (
                                                <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-purple-100 text-purple-800">
                                                  {p.category}
                                                </span>
                                              )}
                                              {hasSubprocesses && (
                                                <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs bg-gray-200 text-gray-700 font-medium">
                                                  {subprocesses.length} subprocess{subprocesses.length !== 1 ? 'es' : ''}
                                                </span>
                                              )}
                                            </div>
                                          </div>
                                        </div>
                                        {p.description && <p className="mt-2 text-sm text-gray-600 ml-5">{p.description}</p>}
                                      </div>

                                      <div className="flex items-center gap-1 flex-shrink-0">
                                        <button
                                          className="w-8 h-8 flex items-center justify-center rounded-md bg-indigo-600 text-white hover:bg-indigo-700 transition-colors"
                                          title="Add subprocess"
                                          onClick={() => openSubprocessModal(Number(p.id), c.id)}
                                        >
                                          <FiPlus size={16} />
                                        </button>
                                        <button
                                          className="w-8 h-8 flex items-center justify-center rounded-md text-red-600 hover:bg-red-50 transition-colors"
                                          title="Delete process"
                                          onClick={() => handleDeleteProcess(p.id, c.id)}
                                        >
                                          <FiTrash2 size={16} />
                                        </button>
                                      </div>
                                    </div>
                                  </div>

                                  {/* Subprocesses Dropdown */}
                                  {hasSubprocesses && (
                                    <>
                                      <button
                                        onClick={() => toggleProcessExpand(Number(p.id))}
                                        className="w-full px-4 py-3 bg-indigo-50 border-t border-gray-200 hover:bg-indigo-100 transition-colors flex items-center justify-between gap-2"
                                      >
                                        <div className="flex items-center gap-2">
                                          {isSubprocessesExpanded ? <FiChevronDown size={16} className="text-indigo-600" /> : <FiChevronRight size={16} className="text-indigo-600" />}
                                          <span className="text-sm font-semibold text-indigo-900">Subprocesses</span>
                                        </div>
                                      </button>

                                      {isSubprocessesExpanded && (
                                        <ul className="divide-y divide-gray-200 bg-indigo-50">
                                          {subprocesses.map((sub: any) => {
                                            const dataEntities = sub.data_entities || [];
                                            const dataEntityNames = dataEntities.map((de: any) => de.data_entity_name).join(', ') || '';
                                            
                                            // Flatten data elements from all data entities
                                            const allDataElements: any[] = [];
                                            dataEntities.forEach((de: any) => {
                                              if (de.data_elements && Array.isArray(de.data_elements)) {
                                                de.data_elements.forEach((elem: any) => {
                                                  allDataElements.push({
                                                    name: elem.data_element_name,
                                                    entityName: de.data_entity_name,
                                                    description: elem.data_element_description
                                                  });
                                                });
                                              }
                                            });
                                            
                                            return (
                                            <li
                                              key={sub.id}
                                              className="px-4 py-3 hover:bg-indigo-100 transition-colors"
                                            >
                                              <div className="ml-6 flex items-start justify-between gap-4">
                                                <div className="flex items-start gap-3 flex-1">
                                                  <div className="w-1.5 h-1.5 rounded-full bg-teal-500 flex-shrink-0 mt-1.5"></div>

                                                  <div className="flex-1 min-w-0">
                                                    <h5 className="font-semibold text-gray-800">{sub.name}</h5>
                                                    <div className="flex items-center gap-2 mt-1">
                                                      <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-teal-100 text-teal-700">
                                                        subprocess
                                                      </span>
                                                      {sub.category && (
                                                        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-100 text-emerald-700">
                                                          {sub.category}
                                                        </span>
                                                      )}
                                                    </div>
                                                    {sub.description && <p className="text-xs text-gray-600 mt-2">{sub.description}</p>}
                                                    {dataEntityNames && (
                                                      <div className="mt-3 pt-3 border-t border-indigo-200">
                                                        <p className="text-xs font-semibold text-gray-700 mb-1">Data Entities:</p>
                                                        <p className="text-xs text-gray-600 whitespace-pre-wrap break-words">{dataEntityNames}</p>
                                                      </div>
                                                    )}
                                                    {allDataElements.length > 0 && (
                                                      <div className="mt-3 pt-3 border-t border-indigo-200">
                                                        <p className="text-xs font-semibold text-gray-700 mb-1">Data Elements:</p>
                                                        <div className="space-y-1">
                                                          {allDataElements.map((elem: any, elemIdx: number) => (
                                                            <p key={elemIdx} className="text-xs text-gray-600">
                                                              {elem.name} ({elem.entityName})
                                                            </p>
                                                          ))}
                                                        </div>
                                                      </div>
                                                    )}
                                                  </div>
                                                </div>

                                                <button
                                                  className="w-8 h-8 flex items-center justify-center rounded-md text-red-600 hover:bg-red-50 transition-colors flex-shrink-0"
                                                  title="Delete subprocess"
                                                  onClick={() => handleDeleteProcess(sub.id, c.id, p.id)}
                                                >
                                                  <FiTrash2 size={14} />
                                                </button>
                                              </div>
                                            </li>
                                            );
                                          })}
                                        </ul>
                                      )}
                                    </>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      </div>

      {isModalOpen && modalMode === 'view' && currentCap && (
        <div className="fixed inset-0 flex items-center justify-center z-50">
          <div className="fixed inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setIsModalOpen(false)} />
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-2xl z-50 max-h-[85vh] flex flex-col">
            {/* Header */}
            <div className="border-b border-gray-100 px-6 py-4 bg-gray-50 flex items-start justify-between flex-shrink-0">
              <div className="flex items-center gap-3">
                <FiEye className="w-5 h-5 text-indigo-600" />
                <div>
                  <h2 className="text-lg font-bold text-gray-900">{currentCap.name}</h2>
                  <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-indigo-50 text-indigo-700 mt-1">
                    {currentCap.subvertical ?? 'Unassigned'}
                  </span>
                </div>
              </div>
              <button
                className="text-gray-400 hover:text-gray-600 p-1 rounded-md"
                onClick={() => setIsModalOpen(false)}
              >
                ✕
              </button>
            </div>

            {/* Scrollable body */}
            <div className="p-6 overflow-y-auto flex-1 space-y-6">
              {/* Description */}
              {currentCap.description && (
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-1">Description</p>
                  <p className="text-sm text-gray-700">{currentCap.description}</p>
                </div>
              )}

              {/* Processes */}
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-3 flex items-center gap-2">
                  <FiLayers className="w-3.5 h-3.5" />
                  Processes ({currentCap.processes.length})
                </p>
                {currentCap.processes.length === 0 ? (
                  <p className="text-sm text-gray-400 italic">No processes defined.</p>
                ) : (
                  <div className="space-y-3">
                    {currentCap.processes.map((p, idx) => {
                      const subprocesses = Array.isArray(p.subprocesses) ? p.subprocesses : [];
                      return (
                        <div key={p.id ?? idx} className="border border-gray-200 rounded-xl overflow-hidden">
                          {/* Process row */}
                          <div className="px-4 py-3 bg-white">
                            <div className="flex items-start gap-3">
                              <div className="w-2 h-2 rounded-full bg-indigo-500 flex-shrink-0 mt-1.5" />
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2 flex-wrap">
                                  <span className="font-semibold text-gray-900 text-sm">{p.name}</span>
                                  {p.level && (
                                    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-indigo-100 text-indigo-700">
                                      {p.level}
                                    </span>
                                  )}
                                  {p.category && (
                                    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-purple-100 text-purple-700">
                                      {p.category}
                                    </span>
                                  )}
                                </div>
                                {p.description && (
                                  <p className="text-xs text-gray-500 mt-1">{p.description}</p>
                                )}
                              </div>
                            </div>
                          </div>

                          {/* Subprocesses */}
                          {subprocesses.length > 0 && (
                            <div className="border-t border-gray-100 bg-indigo-50 divide-y divide-indigo-100">
                              {subprocesses.map((sub: any, subIdx: number) => (
                                <div key={sub.id ?? subIdx} className="px-4 py-2.5 ml-5">
                                  <div className="flex items-start gap-2">
                                    <div className="w-1.5 h-1.5 rounded-full bg-teal-500 flex-shrink-0 mt-1.5" />
                                    <div className="flex-1 min-w-0">
                                      <div className="flex items-center gap-2 flex-wrap">
                                        <span className="font-medium text-gray-800 text-xs">{sub.name}</span>
                                        {sub.category && (
                                          <span className="inline-flex items-center px-1.5 py-0.5 rounded-full text-xs font-medium bg-teal-100 text-teal-700">
                                            {sub.category}
                                          </span>
                                        )}
                                      </div>
                                      {sub.description && (
                                        <p className="text-xs text-gray-500 mt-0.5">{sub.description}</p>
                                      )}
                                      {/* Data entities */}
                                      {Array.isArray(sub.data_entities) && sub.data_entities.length > 0 && (
                                        <div className="mt-2 space-y-1">
                                          {sub.data_entities.map((de: any, deIdx: number) => (
                                            <div key={deIdx} className="text-xs">
                                              <span className="font-medium text-gray-600">{de.data_entity_name}</span>
                                              {Array.isArray(de.data_elements) && de.data_elements.length > 0 && (
                                                <span className="text-gray-400 ml-1">
                                                  — {de.data_elements.map((el: any) => el.data_element_name).join(', ')}
                                                </span>
                                              )}
                                            </div>
                                          ))}
                                        </div>
                                      )}
                                    </div>
                                  </div>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>

            {/* Footer */}
            <div className="flex justify-end px-6 py-4 border-t border-gray-100 bg-gray-50 flex-shrink-0">
              <button
                className="px-4 py-1.5 rounded-md text-gray-600 hover:bg-gray-100 font-medium"
                onClick={() => setIsModalOpen(false)}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {isModalOpen && modalMode !== 'view' && (
        <div className="fixed inset-0 flex items-center justify-center z-50">
          <div className="fixed inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setIsModalOpen(false)} />
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md z-50 overflow-hidden">
            <div className="border-b border-gray-100 px-6 py-3 bg-gray-50 flex items-center gap-3">
              <FiEdit3 className="w-5 h-5 text-blue-600" />
              <h2 className="text-lg font-bold text-gray-900">
                {modalMode === 'edit' ? 'Edit capability' : 'Add Capability'}
              </h2>
            </div>

            <div className="p-6">
              <label className="block text-sm font-medium text-gray-700 mb-2">Capability Name</label>
              <input
                className="w-full bg-gray-50 border border-indigo-100 rounded-xl px-4 py-3 text-gray-800 placeholder:text-gray-400 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                placeholder="Enter capability name..."
                value={formName}
                onChange={(e) => setFormName(e.target.value)}
              />

              <label className="block text-sm font-medium text-gray-700 mb-2 mt-4">Description</label>
              <textarea
                className="w-full bg-gray-50 border border-indigo-100 rounded-xl px-4 py-3 text-gray-800 placeholder:text-gray-400 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 min-h-[100px] resize-y"
                placeholder="Enter capability description..."
                rows={4}
                value={formDescription}
                onChange={(e) => setFormDescription(e.target.value)}
              />

              <div className="flex justify-end gap-3 mt-6">
                <button
                  className="px-3 py-1.5 rounded-md text-gray-600 hover:bg-gray-100 font-medium"
                  onClick={() => {
                    setIsModalOpen(false)
                    setFormName('')
                    setFormDescription('')
                  }}
                >
                  Cancel
                </button>
                <button
                  className="px-4 py-1.5 bg-blue-600 text-white rounded-md font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                  onClick={saveCapability}
                  disabled={!formName.trim()}
                >
                  <FiPlus className="w-4 h-4" />
                  {modalMode === 'edit' ? 'Save changes' : 'Add Capability'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {isProcessModalOpen && (
        <div className="fixed inset-0 flex items-center justify-center z-50">
          <div className="fixed inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setIsProcessModalOpen(false)} />
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-lg max-h-[75vh] z-50 overflow-hidden flex flex-col">
            <div className="border-b border-gray-100 px-6 py-3 bg-gray-50 flex items-center gap-3">
              <FiEdit3 className="w-5 h-5 text-blue-600" />
              <h2 className="text-lg font-bold text-gray-900">Add process</h2>
              {parentCap && <span className="text-xs text-gray-400 ml-2">to {parentCap.name}</span>}
            </div>

            <div className="p-4 flex-1 overflow-y-auto">
              {/* Subtle Mode Toggle - Tab Style */}
              <div className="inline-flex gap-1 mb-4 p-1 bg-gray-100 rounded-lg">
                <button
                  className={`px-4 py-2 rounded-md text-sm font-medium transition-all duration-200 ${
                    processMode === 'manual'
                      ? 'bg-white text-gray-900 shadow-sm'
                      : 'text-gray-600 hover:text-gray-900'
                  }`}
                  onClick={() => setProcessMode('manual')}
                >
                  Add Manually
                </button>
                <button
                  className={`px-4 py-2 rounded-md text-sm font-medium transition-all duration-200 ${
                    processMode === 'ai'
                      ? 'bg-white text-gray-900 shadow-sm'
                      : 'text-gray-600 hover:text-gray-900'
                  }`}
                  onClick={() => setProcessMode('ai')}
                >
                  Generate with AI
                </button>
              </div>

              {/* Manual Mode */}
              {processMode === 'manual' && (
                <>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Process Name</label>
                  <input
                    className="w-full bg-gray-50 border border-indigo-100 rounded-xl px-4 py-3 text-gray-800 placeholder:text-gray-400 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 mb-4"
                    placeholder="Enter process name..."
                    value={manualProcessName}
                    onChange={(e) => setManualProcessName(e.target.value)}
                  />

                  <label className="block text-sm font-medium text-gray-700 mb-2">Process Level</label>
                  <select
                    className="w-full bg-gray-50 border border-indigo-100 rounded-xl px-4 py-3 text-gray-800 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 mb-4"
                    value={processLevel}
                    onChange={(e) => setProcessLevel(e.target.value)}
                  >
                    {processLevelOptions.map((opt) => (
                      <option key={opt} value={opt}>
                        {opt}
                      </option>
                    ))}
                  </select>

                  <label className="block text-sm font-medium text-gray-700 mb-2">Description</label>
                  <textarea
                    className="w-full bg-gray-50 border border-indigo-100 rounded-xl px-4 py-3 text-gray-800 placeholder:text-gray-400 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 min-h-[100px] resize-y"
                    placeholder="Enter process description..."
                    rows={3}
                    value={manualProcessDescription}
                    onChange={(e) => setManualProcessDescription(e.target.value)}
                  />

                  <div className="flex justify-end gap-3 mt-6">
                    <button
                      className="px-3 py-1.5 rounded-md text-gray-600 hover:bg-gray-100 font-medium"
                      onClick={() => setIsProcessModalOpen(false)}
                    >
                      Cancel
                    </button>
                    <button
                      className="px-4 py-1.5 bg-indigo-600 text-white rounded-md font-medium hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                      onClick={handleSaveManualProcess}
                      disabled={!manualProcessName.trim() || isSavingManual}
                    >
                      <FiPlus className="w-4 h-4" />
                      {isSavingManual ? 'Creating...' : 'Create Process'}
                    </button>
                  </div>
                </>
              )}

              {/* AI Generation Mode */}
              {processMode === 'ai' && (
                <>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Process Level</label>
                  <select
                    className="w-full bg-gray-50 border border-indigo-100 rounded-xl px-4 py-3 text-gray-800 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 mb-4"
                    value={processLevel}
                    onChange={(e) => setProcessLevel(e.target.value)}
                  >
                    {processLevelOptions.map((opt) => (
                      <option key={opt} value={opt}>
                        {opt}
                      </option>
                    ))}
                  </select>

                  <label className="block text-sm font-medium text-gray-700 mb-2">System Prompt (Read-only)</label>
                  <textarea
                    className="w-full bg-gray-100 border border-gray-200 rounded-xl px-4 py-3 text-gray-600 min-h-[80px] resize-y text-sm"
                    rows={4}
                    value={SYSTEM_PROMPT}
                    readOnly
                  />

                  <label className="block text-sm font-medium text-gray-700 mb-2">User Prompt (Editable)</label>
                  <textarea
                    className="w-full bg-gray-50 border border-indigo-100 rounded-xl px-4 py-3 text-gray-800 placeholder:text-gray-400 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 min-h-[80px] resize-y text-sm"
                    placeholder="Enter or modify the AI prompt..."
                    rows={4}
                    value={aiPrompt}
                    onChange={(e) => setAiPrompt(e.target.value)}
                  />

                  <div className="flex justify-end gap-3 mt-6">
                    <button
                      className="px-3 py-1.5 rounded-md text-gray-600 hover:bg-gray-100 font-medium"
                      onClick={() => setIsProcessModalOpen(false)}
                    >
                      Cancel
                    </button>
                    <button
                      className="px-4 py-1.5 bg-blue-600 text-white rounded-md font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                      onClick={handleGenerateProcess}
                      disabled={isGenerating}
                      title="Generate processes using AI"
                    >
                      <FiPlus className="w-4 h-4" />
                      {isGenerating ? 'Generating...' : 'Generate with AI'}
                    </button>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {isExportModalOpen && (
        <div className="fixed inset-0 flex items-center justify-center z-50">
          <div className="fixed inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setIsExportModalOpen(false)} />
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md z-50 overflow-hidden">
            <div className="border-b border-gray-100 px-6 py-3 bg-gray-50">
              <h2 className="text-lg font-bold text-gray-900">Export Capabilities as CSV</h2>
            </div>
            <div className="p-6">
              <label className="block text-sm font-medium text-gray-700 mb-2">Select Capabilities</label>
              {/* Custom multi-select dropdown */}
              <div className="relative">
                <div className="w-full border border-gray-300 rounded-md bg-white">
                  {/* Trigger / selected summary */}
                  <div className="px-3 py-2 text-sm text-gray-700 min-h-[38px] flex items-center gap-1 flex-wrap">
                    {selectedExportCapIds.size === 0 ? (
                      <span className="text-gray-400">-- Select capabilities --</span>
                    ) : selectedExportCapIds.size === capabilities.length ? (
                      <span className="bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded-full text-xs font-medium">All ({capabilities.length})</span>
                    ) : (
                      Array.from(selectedExportCapIds).map((id) => {
                        const cap = capabilities.find((c) => c.id === id);
                        return cap ? (
                          <span key={id} className="bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded-full text-xs font-medium flex items-center gap-1">
                            {cap.name}
                            <button
                              className="hover:text-indigo-900 leading-none"
                              onClick={(e) => { e.stopPropagation(); const n = new Set(selectedExportCapIds); n.delete(id); setSelectedExportCapIds(n); }}
                            >×</button>
                          </span>
                        ) : null;
                      })
                    )}
                  </div>
                  {/* Divider + options list */}
                  <div className="border-t border-gray-200">
                    {/* Select all row */}
                    <label className="flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-gray-50 border-b border-gray-100">
                      <input
                        type="checkbox"
                        className="accent-indigo-600 w-4 h-4"
                        checked={selectedExportCapIds.size === capabilities.length && capabilities.length > 0}
                        onChange={(e) => setSelectedExportCapIds(e.target.checked ? new Set(capabilities.map((c) => c.id)) : new Set())}
                      />
                      <span className="text-sm font-medium text-gray-700">Select all</span>
                    </label>
                    {/* Capability options */}
                    <div className="max-h-48 overflow-y-auto">
                      {capabilities.map((c) => {
                        const checked = selectedExportCapIds.has(c.id);
                        return (
                          <label key={c.id} className="flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-gray-50">
                            <input
                              type="checkbox"
                              className="accent-indigo-600 w-4 h-4 flex-shrink-0"
                              checked={checked}
                              onChange={(e) => {
                                const n = new Set(selectedExportCapIds);
                                if (e.target.checked) n.add(c.id); else n.delete(c.id);
                                setSelectedExportCapIds(n);
                              }}
                            />
                            <span className="text-sm text-gray-800 flex-1">{c.name}</span>
                            {c.subvertical && (
                              <span className="text-xs text-indigo-500 flex-shrink-0">{c.subvertical}</span>
                            )}
                          </label>
                        );
                      })}
                    </div>
                  </div>
                </div>
              </div>
              <div className="flex justify-end gap-2 mt-6">
                <button
                  className="px-3 py-1.5 rounded-md text-gray-600 hover:bg-gray-100"
                  onClick={() => { setIsExportModalOpen(false); setSelectedExportCapIds(new Set()); }}
                >
                  Cancel
                </button>
                <button
                  className={`px-4 py-2 rounded-md text-white ${isExporting || selectedExportCapIds.size === 0 ? 'bg-gray-400 cursor-not-allowed' : 'bg-indigo-600 hover:bg-indigo-700'}`}
                  onClick={handleExportCapability}
                  disabled={isExporting || selectedExportCapIds.size === 0}
                >
                  {isExporting ? 'Exporting...' : `Export${selectedExportCapIds.size > 0 ? ` (${selectedExportCapIds.size})` : ''}`}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Generated LLM preview modal - show checkbox list, select all, and save selected */}
      {isGeneratedModalOpen && (
        <div className="fixed inset-0 flex items-center justify-center z-50">
          <div className="fixed inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setIsGeneratedModalOpen(false)} />
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-2xl z-50 max-h-[85vh] flex flex-col">
            {/* Fixed Header */}
            <div className="border-b border-gray-100 px-6 py-3 bg-gray-50 flex items-center justify-between flex-shrink-0">
              <div className="flex items-center gap-3">
                <FiEdit3 className="w-5 h-5 text-blue-600" />
                <h2 className="text-lg font-bold text-gray-900">Review generated processes</h2>
                <span className="text-sm text-gray-500">Select which generated processes to save</span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  className="px-3 py-1.5 rounded-md text-sm bg-gray-100 hover:bg-gray-200"
                  onClick={() => {
                    // toggle select all (both top-level and all subprocesses)
                    if (!generatedPreview || generatedPreview.length === 0) return;
                    const allKeys = new Set<string>();
                    generatedPreview.forEach((proc, idx) => {
                      allKeys.add(`proc-${idx}`);
                      if (Array.isArray(proc.subprocesses)) {
                        proc.subprocesses.forEach((_sub: any, subIdx: number) => {
                          allKeys.add(`proc-${idx}-sub-${subIdx}`);
                        });
                      }
                    });
                    
                    if (selectedGeneratedIdxs.size === allKeys.size) {
                      setSelectedGeneratedIdxs(new Set());
                    } else {
                      setSelectedGeneratedIdxs(allKeys);
                    }
                  }}
                >
                  {selectedGeneratedIdxs.size === 0 ? 'Select all' : 'Unselect all'}
                </button>
              </div>
            </div>

            {/* Scrollable Content */}
            <div className="p-6 space-y-4 overflow-y-auto flex-1">
              {(!generatedPreview || generatedPreview.length === 0) ? (
                <div className="text-gray-500">No generated processes to review.</div>
              ) : (
                <ul className="space-y-4">
                  {generatedPreview.map((proc: any, idx: number) => {
                    const procKey = `proc-${idx}`;
                    const procChecked = selectedGeneratedIdxs.has(procKey);
                    
                    return (
                      <li key={idx} className="border rounded-lg p-4 bg-gray-50">
                        <div className="flex items-start gap-3">
                          <input
                            type="checkbox"
                            checked={procChecked}
                            onChange={(e) => {
                              const newSet = new Set(selectedGeneratedIdxs);
                              if (e.target.checked) {
                                newSet.add(procKey);
                                // Auto-select all subprocesses when parent is checked
                                if (Array.isArray(proc.subprocesses)) {
                                  proc.subprocesses.forEach((_sub: any, subIdx: number) => {
                                    newSet.add(`proc-${idx}-sub-${subIdx}`);
                                  });
                                }
                              } else {
                                newSet.delete(procKey);
                                // Auto-uncheck all subprocesses when parent is unchecked
                                if (Array.isArray(proc.subprocesses)) {
                                  proc.subprocesses.forEach((_sub: any, subIdx: number) => {
                                    newSet.delete(`proc-${idx}-sub-${subIdx}`);
                                  });
                                }
                              }
                              setSelectedGeneratedIdxs(newSet);
                            }}
                            className="mt-1"
                          />
                          <div className="flex-1">
                            <div className="flex items-center justify-between">
                              <div className="font-medium text-gray-900">{proc.name}</div>
                              <div className="flex items-center gap-2">
                                <div className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-teal-50 text-teal-700">{proc.level}</div>
                                {proc.category && (
                                  <div className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-purple-50 text-purple-700">{proc.category}</div>
                                )}
                              </div>
                            </div>
                            {proc.description && <div className="mt-1 text-sm text-gray-600">{proc.description}</div>}
                            
                            {/* Subprocesses with individual checkboxes */}
                            {Array.isArray(proc.subprocesses) && proc.subprocesses.length > 0 && (
                              <div className="mt-3 ml-6 space-y-2 border-l-2 border-gray-300 pl-4">
                                <div className="text-xs font-semibold text-gray-700">Subprocesses:</div>
                                {proc.subprocesses.map((sub: any, subIdx: number) => {
                                  const subKey = `proc-${idx}-sub-${subIdx}`;
                                  const subChecked = selectedGeneratedIdxs.has(subKey);
                                  return (
                                    <div key={subIdx} className="flex items-start gap-2">
                                      <input
                                        type="checkbox"
                                        checked={subChecked}
                                        onChange={(e) => {
                                          const newSet = new Set(selectedGeneratedIdxs);
                                          if (e.target.checked) {
                                            newSet.add(subKey);
                                            // Auto-check parent if any subprocess is checked
                                            newSet.add(procKey);
                                          } else {
                                            newSet.delete(subKey);
                                          }
                                          setSelectedGeneratedIdxs(newSet);
                                        }}
                                        className="mt-1"
                                      />
                                      <div className="text-sm text-gray-700 flex-1">
                                        <div className="flex items-center gap-2">
                                          <span className="font-medium">{sub.name}</span>
                                          {sub.category && (
                                            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-emerald-50 text-emerald-700">{sub.category}</span>
                                          )}
                                        </div>
                                        {sub.lifecycle_phase && <div className="text-xs text-gray-500 mt-0.5">Phase: {sub.lifecycle_phase}</div>}
                                        {sub.description && <div className="text-xs text-gray-600 mt-0.5">{sub.description}</div>}
                                      </div>
                                    </div>
                                  );
                                })}
                              </div>
                            )}
                          </div>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>

            {/* Fixed Footer */}
            <div className="flex justify-end gap-3 px-6 py-4 border-t border-gray-100 bg-gray-50 flex-shrink-0">
              <button
                className="px-3 py-1.5 rounded-md text-gray-600 hover:bg-gray-100"
                onClick={() => {
                  setIsGeneratedModalOpen(false);
                  setGeneratedPreview([]);
                  setSelectedGeneratedIdxs(new Set());
                }}
              >
                Cancel
              </button>

              <button
                className="px-4 py-1.5 bg-blue-600 text-white rounded-md font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
                onClick={saveSelectedGeneratedProcesses}
                disabled={isSavingGenerated || selectedGeneratedIdxs.size === 0}
              >
                {isSavingGenerated ? 'Saving...' : `Save selected (${selectedGeneratedIdxs.size})`}
              </button>
            </div>
          </div>
        </div>
      )}

      {isSubprocessModalOpen && (
        <div className="fixed inset-0 flex items-center justify-center z-50">
          <div className="fixed inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setIsSubprocessModalOpen(false)} />
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-lg max-h-[75vh] z-50 overflow-hidden flex flex-col">
            <div className="border-b border-gray-100 px-6 py-3 bg-gray-50 flex items-center gap-3">
              <FiEdit3 className="w-5 h-5 text-blue-600" />
              <h2 className="text-lg font-bold text-gray-900">Add subprocess</h2>
            </div>

            <div className="p-4 flex-1 overflow-y-auto">
              {/* Subtle Mode Toggle - Tab Style */}
              <div className="inline-flex gap-1 mb-4 p-1 bg-gray-100 rounded-lg">
                <button
                  className={`px-4 py-2 rounded-md text-sm font-medium transition-all duration-200 ${
                    subprocessMode === 'manual'
                      ? 'bg-white text-gray-900 shadow-sm'
                      : 'text-gray-600 hover:text-gray-900'
                  }`}
                  onClick={() => setSubprocessMode('manual')}
                >
                  Add Manually
                </button>
                <button
                  className={`px-4 py-2 rounded-md text-sm font-medium transition-all duration-200 ${
                    subprocessMode === 'ai'
                      ? 'bg-white text-gray-900 shadow-sm'
                      : 'text-gray-600 hover:text-gray-900'
                  }`}
                  onClick={() => setSubprocessMode('ai')}
                >
                  Generate with AI
                </button>
              </div>

              {/* Manual Mode */}
              {subprocessMode === 'manual' && (
                <>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Subprocess Name</label>
                  <input
                    className="w-full bg-gray-50 border border-indigo-100 rounded-xl px-4 py-3 text-gray-800 placeholder:text-gray-400 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 mb-4"
                    placeholder="Enter subprocess name..."
                    value={manualSubprocessName}
                    onChange={(e) => setManualSubprocessName(e.target.value)}
                  />

                  <label className="block text-sm font-medium text-gray-700 mb-2">Description</label>
                  <textarea
                    className="w-full bg-gray-50 border border-indigo-100 rounded-xl px-4 py-3 text-gray-800 placeholder:text-gray-400 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 min-h-[100px] resize-y"
                    placeholder="Enter subprocess description..."
                    rows={3}
                    value={manualSubprocessDescription}
                    onChange={(e) => setManualSubprocessDescription(e.target.value)}
                  />

                  <div className="flex justify-end gap-3 mt-6">
                    <button
                      className="px-3 py-1.5 rounded-md text-gray-600 hover:bg-gray-100 font-medium"
                      onClick={() => {
                        setIsSubprocessModalOpen(false);
                        setManualSubprocessName('');
                        setManualSubprocessDescription('');
                      }}
                    >
                      Cancel
                    </button>
                    <button
                      className="px-4 py-1.5 bg-indigo-600 text-white rounded-md font-medium hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                      onClick={handleSaveManualSubprocess}
                      disabled={!manualSubprocessName.trim() || isSavingSubprocess}
                    >
                      <FiPlus className="w-4 h-4" />
                      {isSavingSubprocess ? 'Creating...' : 'Create Subprocess'}
                    </button>
                  </div>
                </>
              )}

              {/* AI Generation Mode */}
              {subprocessMode === 'ai' && (
                <>
                  <p className="text-sm text-gray-600 mb-4">
                    AI will generate subprocesses based on the parent process name and description.
                  </p>

                  <label className="block text-sm font-medium text-gray-700 mb-2">System Prompt (Read-only)</label>
                  <textarea
                    className="w-full bg-gray-100 border border-gray-200 rounded-xl px-4 py-3 text-gray-600 min-h-[80px] resize-y text-sm"
                    rows={4}
                    value={SYSTEM_PROMPT}
                    readOnly
                  />

                  <label className="block text-sm font-medium text-gray-700 mb-2">User Prompt (Editable)</label>
                  <textarea
                    className="w-full bg-gray-50 border border-indigo-100 rounded-xl px-4 py-3 text-gray-800 placeholder:text-gray-400 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 min-h-[80px] resize-y text-sm"
                    placeholder="Enter or modify the AI prompt..."
                    rows={4}
                    value={aiSubprocessPrompt}
                    onChange={(e) => setAiSubprocessPrompt(e.target.value)}
                  />

                  <div className="flex justify-end gap-3 mt-6">
                    <button
                      className="px-3 py-1.5 rounded-md text-gray-600 hover:bg-gray-100 font-medium"
                      onClick={() => setIsSubprocessModalOpen(false)}
                    >
                      Cancel
                    </button>
                    <button
                      className="px-4 py-1.5 bg-blue-600 text-white rounded-md font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                      onClick={handleGenerateSubprocess}
                      disabled={isGeneratingSubprocess}
                      title="Generate subprocesses using AI"
                    >
                      <FiPlus className="w-4 h-4" />
                      {isGeneratingSubprocess ? 'Generating...' : 'Generate with AI'}
                    </button>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
