import { useState, useEffect, useRef } from 'react';
import { FiDownload, FiX, FiSearch } from 'react-icons/fi';
import { Toaster, toast } from 'react-hot-toast';
import { useCapabilityApi } from '../hooks/useCapability';
import type { Capability } from '../hooks/useCapability';
import favicon from '../assets/favicon.png';

export default function CompassView() {
  const [capabilities, setCapabilities] = useState<Capability[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isDownloading, setIsDownloading] = useState(false);
  const [isDescriptionModalOpen, setIsDescriptionModalOpen] = useState(false);
  const [modalDescription, setModalDescription] = useState('');
  const [modalTitle, setModalTitle] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const [searchTerm, setSearchTerm] = useState('');
  const itemsPerPage = 20;
  const loadedRef = useRef(false);

  const { listDomains, listCapabilities, listProcesses } = useCapabilityApi();

  const truncateAtWordBoundary = (text: string, maxWords: number = 2) => {
    if (!text) return { truncated: '', full: '', shouldShowMore: false };
    
    const words = text.split(' ');
    if (words.length <= maxWords) {
      return { truncated: text, full: text, shouldShowMore: false };
    }
    
    const truncated = words.slice(0, maxWords).join(' ');
    return { truncated, full: text, shouldShowMore: true };
  };

  // Function to open description modal
  const openDescriptionModal = (title: string, description: string) => {
    setModalTitle(title);
    setModalDescription(description);
    setIsDescriptionModalOpen(true);
  };

  useEffect(() => {
    const prev = document.documentElement.style.overflowY;
    try {
      document.documentElement.style.overflowY = 'scroll';
    } catch (e) {
      // Handle error
    }
    return () => {
      try {
        document.documentElement.style.overflowY = prev;
      } catch (e) {
        // Handle error
      }
    };
  }, []);

  useEffect(() => {
    if (loadedRef.current) return;
    loadedRef.current = true;

    async function load() {
      try {
        setIsLoading(true);
        await listDomains();

        const caps = await listCapabilities();

        const first = caps && caps.length > 0 ? (caps[0] as any) : null;
        if (first && Array.isArray((first as any).processes)) {
          const normalized = caps.map((c: any) => ({ ...c, processes: c.processes || [] }));
          setCapabilities(normalized as Capability[]);
        } else {
          const allProcesses = await listProcesses();

          const capMap: Record<number, any[]> = {};
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
        console.error(e);
        toast.error('Failed to load capabilities');
      } finally {
        setIsLoading(false);
      }
    }

    load();
  }, [listCapabilities, listProcesses]);

  // Reset to first page when capabilities change
  useEffect(() => {
    setCurrentPage(1);
  }, [capabilities]);

  // Reset to first page when search term changes
  useEffect(() => {
    setCurrentPage(1);
  }, [searchTerm]);

  // Filter function for search
  const filterFlattenedData = (data: any[], term: string) => {
    if (!term.trim()) return data;
    
    const lowerTerm = term.toLowerCase();
    return data.filter((row) => {
      return (
        row.vertical?.toLowerCase().includes(lowerTerm) ||
        row.subvertical?.toLowerCase().includes(lowerTerm) ||
        row.capabilityName?.toLowerCase().includes(lowerTerm) ||
        row.capabilityDescription?.toLowerCase().includes(lowerTerm) ||
        row.processName?.toLowerCase().includes(lowerTerm) ||
        row.processDescription?.toLowerCase().includes(lowerTerm) ||
        row.subprocessName?.toLowerCase().includes(lowerTerm) ||
        row.subprocessDescription?.toLowerCase().includes(lowerTerm) ||
        row.subprocessData?.toLowerCase().includes(lowerTerm) ||
        row.processLevel?.toString().toLowerCase().includes(lowerTerm) ||
        row.processCategory?.toLowerCase().includes(lowerTerm) ||
        row.subprocessApplication?.toLowerCase().includes(lowerTerm) ||
        row.subprocessApi?.toLowerCase().includes(lowerTerm) ||
        (row.dataElements && row.dataElements.some((de: any) => 
          de.name?.toLowerCase().includes(lowerTerm) || 
          de.entityName?.toLowerCase().includes(lowerTerm)
        ))
      );
    });
  };

  // Flatten the data for table display
  const flattenedData: any[] = [];
  capabilities.forEach((cap) => {
    if (!cap.processes || cap.processes.length === 0) {
      // Add capability with empty process row
      flattenedData.push({
        vertical: cap.vertical || 'Unassigned',
        subvertical: cap.subvertical || 'Unassigned',
        capabilityName: cap.name,
        capabilityDescription: cap.description,
        processName: '',
        processDescription: '',
        processLevel: '',
        processCategory: '',
        subprocessName: '',
        subprocessDescription: '',
        subprocessData: '',
        dataEntities: [],
        dataElements: [],
        subprocessApplication: '',
        subprocessApi: '',
      });
    } else {
      // Add capability with each process
      cap.processes.forEach((proc: any) => {
        if (!proc.subprocesses || proc.subprocesses.length === 0) {
          flattenedData.push({
            vertical: cap.vertical || 'Unassigned',
            subvertical: cap.subvertical || 'Unassigned',
            capabilityName: cap.name,
            capabilityDescription: cap.description,
            processName: proc.name,
            processDescription: proc.description || '',
            processLevel: proc.level || '',
            processCategory: proc.category || '',
            subprocessName: '',
            subprocessDescription: '',
            subprocessData: '',
            dataEntities: [],
            dataElements: [],
            subprocessApplication: '',
            subprocessApi: '',
          });
        } else {
          // Add each subprocess
          proc.subprocesses.forEach((subprocess: any) => {
            const dataEntities = subprocess.data_entities || [];
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
            
            flattenedData.push({
              vertical: cap.vertical || 'Unassigned',
              subvertical: cap.subvertical || 'Unassigned',
              capabilityName: cap.name,
              capabilityDescription: cap.description,
              processName: proc.name,
              processDescription: proc.description || '',
              processLevel: proc.level || '',
              processCategory: proc.category || '',
              subprocessName: subprocess.name || subprocess.subprocess_name,
              subprocessDescription: subprocess.description || subprocess.subprocess_description || '',
              subprocessData: dataEntityNames,
              dataEntities: dataEntities,
              dataElements: allDataElements,
              subprocessApplication: subprocess.application || subprocess.subprocess_application || '',
              subprocessApi: subprocess.api || subprocess.subprocess_api || '',
            });
          });
        }
      });
    }
  });

  // Calculate pagination values
  const filteredAndPaginatedData = filterFlattenedData(flattenedData, searchTerm);
  const totalPages = Math.ceil(filteredAndPaginatedData.length / itemsPerPage);
  const startIndex = (currentPage - 1) * itemsPerPage;
  const endIndex = startIndex + itemsPerPage;
  const paginatedData = filteredAndPaginatedData.slice(startIndex, endIndex);

  const handleDownloadCSV = async () => {
    try {
      setIsDownloading(true);

      // Use filtered data (respects search) but not paginated (exports all filtered results)
      const dataToExport = searchTerm.trim() ? filteredAndPaginatedData : flattenedData;

      if (dataToExport.length === 0) {
        toast.error('No data to export');
        setIsDownloading(false);
        return;
      }

      // CSV headers
      const headers = [
        'Vertical',
        'Sub-Vertical',
        'Capability Name',
        'Capability Description',
        'Process Name',
        'Process Level',
        'Process Category',
        'Process Description',
        'Subprocess Name',
        'Description',
        'Data Entities',
        'Data Elements',
        'Application',
        'API',
      ];

      // Escape CSV values
      const escapeCSV = (val: string | undefined | null) => {
        if (!val) return '';
        const strVal = String(val);
        if (strVal.includes(',') || strVal.includes('"') || strVal.includes('\n')) {
          return `"${strVal.replace(/"/g, '""')}"`;
        }
        return strVal;
      };

      // Build CSV rows
      const rows = dataToExport.map((row) => {
        const dataElementsText = row.dataElements && row.dataElements.length > 0
          ? row.dataElements.map((de: any) => `${de.name} (${de.entityName})`).join('; ')
          : '';
        
        return [
          escapeCSV(row.vertical),
          escapeCSV(row.subvertical),
          escapeCSV(row.capabilityName),
          escapeCSV(row.capabilityDescription),
          escapeCSV(row.processName),
          escapeCSV(row.processLevel),
          escapeCSV(row.processCategory),
          escapeCSV(row.processDescription),
          escapeCSV(row.subprocessName),
          escapeCSV(row.subprocessDescription),
          escapeCSV(row.subprocessData),
          escapeCSV(dataElementsText),
          escapeCSV(row.subprocessApplication),
          escapeCSV(row.subprocessApi),
        ].join(',');
      });

      // Combine headers and rows
      const csv = [headers.join(','), ...rows].join('\n');

      // Add BOM for proper Excel UTF-8 support
      const BOM = '\uFEFF';
      const csvWithBOM = BOM + csv;

      // Create blob and download
      const blob = new Blob([csvWithBOM], { type: 'text/csv;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `compass_view_${new Date().toISOString().split('T')[0]}.csv`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);

      toast.success(`CSV downloaded successfully (${dataToExport.length} rows)`);
    } catch (error) {
      console.error('Error downloading CSV:', error);
      toast.error(`Failed to download CSV: ${error instanceof Error ? error.message : 'Unknown error'}`);
    } finally {
      setIsDownloading(false);
    }
  };

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
              <h1 className="text-xl font-semibold">View</h1>
              <p className="text-xs text-muted-foreground">
                View all your enterprise capabilities and processes in one place.
              </p>
            </div>
          </div>
        </div>
      </header>

      <div className="mx-auto mt-6 bg-white p-6 px-8 rounded-lg shadow-sm max-w-7xl">
        <div className="flex flex-col gap-4 mb-6">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-semibold text-gray-900">Capability Mapping</h1>
            <div className="ml-auto flex items-center gap-3">
              <div className="relative">
                <FiSearch className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 h-4 w-4" />
                <input
                  type="text"
                  placeholder="Search table data..."
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  className="pl-10 pr-4 py-2 rounded-md border border-gray-300 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent w-72"
                />
              </div>
              <button
                className="px-4 py-2 rounded-md text-sm font-medium transition-colors bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                onClick={handleDownloadCSV}
                disabled={isDownloading || flattenedData.length === 0}
                title="Download table as CSV"
              >
                <FiDownload size={18} />
                {isDownloading ? 'Downloading...' : 'Download CSV'}
              </button>
            </div>
          </div>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center py-16">
            <p className="text-gray-500">Loading capabilities...</p>
          </div>
        ) : flattenedData.length === 0 ? (
          <div className="flex items-center justify-center py-16">
            <p className="text-gray-500">No capabilities found.</p>
          </div>
        ) : filteredAndPaginatedData.length === 0 ? (
          <div className="flex items-center justify-center py-16">
            <p className="text-gray-500">No results match your search. Try a different search term.</p>
          </div>
        ) : (
          <div>
            <div className="overflow-x-auto">
              <table className="w-full border-collapse">
                <thead>
                  <tr className="bg-gray-100 border-b-2 border-gray-300">
                    <th className="px-4 py-3 text-left text-sm font-semibold text-gray-900 border-r border-gray-200">Vertical</th>
                    <th className="px-4 py-3 text-left text-sm font-semibold text-gray-900 border-r border-gray-200">Sub-Vertical</th>
                    <th className="px-4 py-3 text-left text-sm font-semibold text-gray-900 border-r border-gray-200">Capability Name</th>
                    <th className="px-4 py-3 text-left text-sm font-semibold text-gray-900 border-r border-gray-200">Capability Description</th>
                    <th className="px-4 py-3 text-left text-sm font-semibold text-gray-900 border-r border-gray-200">Process Name</th>
                    <th className="px-4 py-3 text-left text-sm font-semibold text-gray-900 border-r border-gray-200">Process Level</th>
                    <th className="px-4 py-3 text-left text-sm font-semibold text-gray-900 border-r border-gray-200">Process Category</th>
                    <th className="px-4 py-3 text-left text-sm font-semibold text-gray-900 border-r border-gray-200">Process Description</th>
                    <th className="px-4 py-3 text-left text-sm font-semibold text-gray-900 border-r border-gray-200">Subprocess Name</th>
                    <th className="px-4 py-3 text-left text-sm font-semibold text-gray-900 border-r border-gray-200">Description</th>
                    <th className="px-4 py-3 text-left text-sm font-semibold text-gray-900 border-r border-gray-200">Data Entities</th>
                    <th className="px-4 py-3 text-left text-sm font-semibold text-gray-900 border-r border-gray-200">Data Elements</th>
                    <th className="px-4 py-3 text-left text-sm font-semibold text-gray-900 border-r border-gray-200">Application</th>
                    <th className="px-4 py-3 text-left text-sm font-semibold text-gray-900">API</th>
                  </tr>
                </thead>
                <tbody>
                  {paginatedData.map((row, idx) => {
                  const capDescTruncated = truncateAtWordBoundary(row.capabilityDescription, 2);
                  const procDescTruncated = truncateAtWordBoundary(row.processDescription, 2);
                  const subprocDescTruncated = truncateAtWordBoundary(row.subprocessDescription, 2);
                  const dataEntitiesTruncated = truncateAtWordBoundary(row.subprocessData, 2);
                  const dataElementsTruncated = row.dataElements && row.dataElements.length > 0
                    ? truncateAtWordBoundary(row.dataElements.map((e: any) => `${e.name} (${e.entityName})`).join('; '), 2)
                    : { truncated: '', full: '', shouldShowMore: false };
                  const subprocAppTruncated = truncateAtWordBoundary(row.subprocessApplication, 2);
                  const subprocApiTruncated = truncateAtWordBoundary(row.subprocessApi, 2);

                  return (
                    <tr
                      key={idx}
                      className="border-b border-gray-200 hover:bg-indigo-50 transition-colors"
                    >
                      <td className="px-4 py-3 text-sm text-gray-700 border-r border-gray-200">
                        <span className="text-sm text-gray-900 font-medium">
                          {row.vertical}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-700 border-r border-gray-200">
                        <span className="text-sm text-gray-900 font-medium">
                          {row.subvertical}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-900 font-medium border-r border-gray-200">{row.capabilityName}</td>
                      <td className="px-4 py-3 text-sm text-gray-700 border-r border-gray-200">
                        <span className="line-clamp-2">{capDescTruncated.truncated}</span>
                        {capDescTruncated.shouldShowMore && (
                          <button
                            onClick={() => openDescriptionModal('Capability Description', capDescTruncated.full)}
                            className="ml-2 text-blue-600 hover:text-blue-800 font-medium"
                          >
                            more
                          </button>
                        )}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-900 border-r border-gray-200">{row.processName}</td>
                      <td className="px-4 py-3 text-sm text-gray-700 border-r border-gray-200">
                        {row.processLevel && (
                          <span className="text-sm text-gray-900">
                            {row.processLevel}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-700 border-r border-gray-200">
                        {row.processCategory && (
                          <span className="text-sm text-gray-900">
                            {row.processCategory}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-700 border-r border-gray-200">
                        <span className="line-clamp-2">{procDescTruncated.truncated}</span>
                        {procDescTruncated.shouldShowMore && (
                          <button
                            onClick={() => openDescriptionModal('Process Description', procDescTruncated.full)}
                            className="ml-2 text-blue-600 hover:text-blue-800 font-medium"
                          >
                            more
                          </button>
                        )}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-900 border-r border-gray-200">{row.subprocessName}</td>
                      <td className="px-4 py-3 text-sm text-gray-700 border-r border-gray-200">
                        <span className="line-clamp-2">{subprocDescTruncated.truncated}</span>
                        {subprocDescTruncated.shouldShowMore && (
                          <button
                            onClick={() => openDescriptionModal('Subprocess Description', subprocDescTruncated.full)}
                            className="ml-2 text-blue-600 hover:text-blue-800 font-medium"
                          >
                            more
                          </button>
                        )}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-700 border-r border-gray-200">
                        {row.subprocessData ? (
                          <>
                            <span className="line-clamp-2">{dataEntitiesTruncated.truncated}</span>
                            {dataEntitiesTruncated.shouldShowMore && (
                              <button
                                onClick={() => openDescriptionModal('Data Entities', dataEntitiesTruncated.full)}
                                className="ml-2 text-blue-600 hover:text-blue-800 font-medium"
                              >
                                more
                              </button>
                            )}
                          </>
                        ) : (
                          <span className="text-gray-400">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-700 border-r border-gray-200">
                        {row.dataElements && row.dataElements.length > 0 ? (
                          <>
                            <span className="line-clamp-2 text-gray-900">{dataElementsTruncated.truncated}</span>
                            {dataElementsTruncated.shouldShowMore && (
                              <button
                                onClick={() => openDescriptionModal('Data Elements', dataElementsTruncated.full)}
                                className="ml-2 text-blue-600 hover:text-blue-800 font-medium"
                              >
                                more
                              </button>
                            )}
                          </>
                        ) : (
                          <span className="text-gray-400">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-700 border-r border-gray-200">
                        <span className="line-clamp-2">{subprocAppTruncated.truncated}</span>
                        {subprocAppTruncated.shouldShowMore && (
                          <button
                            onClick={() => openDescriptionModal('Subprocess Application', subprocAppTruncated.full)}
                            className="ml-2 text-blue-600 hover:text-blue-800 font-medium"
                          >
                            more
                          </button>
                        )}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-700 border-r border-gray-200">
                        <span className="line-clamp-2">{subprocApiTruncated.truncated}</span>
                        {subprocApiTruncated.shouldShowMore && (
                          <button
                            onClick={() => openDescriptionModal('Subprocess API', subprocApiTruncated.full)}
                            className="ml-2 text-blue-600 hover:text-blue-800 font-medium"
                          >
                            more
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Pagination Controls */}
          {totalPages > 1 && (
            <div className="mt-6 flex items-center justify-center gap-2">
              <button
                onClick={() => setCurrentPage(prev => Math.max(prev - 1, 1))}
                disabled={currentPage === 1}
                className="px-3 py-2 rounded-md text-sm font-medium bg-gray-200 text-gray-900 hover:bg-gray-300 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                Previous
              </button>

              <div className="flex items-center gap-1">
                {Array.from({ length: totalPages }, (_, i) => i + 1).map((pageNum) => (
                  <button
                    key={pageNum}
                    onClick={() => setCurrentPage(pageNum)}
                    className={`px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                      currentPage === pageNum
                        ? 'bg-indigo-600 text-white'
                        : 'bg-gray-200 text-gray-900 hover:bg-gray-300'
                    }`}
                  >
                    {pageNum}
                  </button>
                ))}
              </div>

              <button
                onClick={() => setCurrentPage(prev => Math.min(prev + 1, totalPages))}
                disabled={currentPage === totalPages}
                className="px-3 py-2 rounded-md text-sm font-medium bg-gray-200 text-gray-900 hover:bg-gray-300 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                Next
              </button>

              <span className="ml-4 text-sm text-gray-600">
                Page {currentPage} of {totalPages} | Showing {startIndex + 1} to {Math.min(endIndex, filteredAndPaginatedData.length)} of {filteredAndPaginatedData.length} records
              </span>
            </div>
          )}
        </div>
      )}
      </div>

      {/* Description Modal */}
      {isDescriptionModalOpen && (
        <div className="fixed inset-0 flex items-center justify-center z-50">
          <div className="fixed inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setIsDescriptionModalOpen(false)} />
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-2xl z-50 overflow-hidden max-h-[80vh] flex flex-col">
            <div className="border-b border-gray-100 px-6 py-4 bg-gray-50 flex items-center justify-between">
              <h2 className="text-lg font-bold text-gray-900">{modalTitle}</h2>
              <button
                onClick={() => setIsDescriptionModalOpen(false)}
                className="p-1 hover:bg-gray-200 rounded-md transition-colors"
                title="Close"
              >
                <FiX size={20} />
              </button>
            </div>
            <div className="p-6 overflow-y-auto flex-1">
              <p className="text-gray-700 whitespace-pre-wrap break-words">{modalDescription}</p>
            </div>
            <div className="border-t border-gray-100 px-6 py-4 bg-gray-50 flex justify-end">
              <button
                onClick={() => setIsDescriptionModalOpen(false)}
                className="px-4 py-2 rounded-md text-sm font-medium bg-indigo-600 text-white hover:bg-indigo-700 transition-colors"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
