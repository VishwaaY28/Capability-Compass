import { useState } from "react";
import { useResearch } from "../hooks/useResearch";
import { Building2, Search, Sparkles } from "lucide-react";
import { FiChevronRight, FiChevronDown, FiLayers } from "react-icons/fi";

const exampleQueries = [
  "What are all the capabilities used to evaluate fund?",
  "Show me the fund sourcing and evaluation process",
  "What are the data entities involved in market research?",
  "Give me processes for KYC verification"
];

export default function ResearchAgent() {
  const [query, setQuery] = useState("");
  const [expandedCaps, setExpandedCaps] = useState<Record<number, boolean>>({});
  const [expandedProcs, setExpandedProcs] = useState<Record<number, boolean>>({});
  const { research, results, isLoading, error } = useResearch();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (query.trim()) research(query);
  };

  // Default to expanded (true) when not yet toggled, since we now only return one result.
  const isCapOpen = (id: number) => expandedCaps[id] !== false;
  const isProcOpen = (id: number) => expandedProcs[id] !== false;

  const toggleCap = (id: number) =>
    setExpandedCaps(prev => ({ ...prev, [id]: prev[id] === false ? true : false }));

  const toggleProc = (id: number) =>
    setExpandedProcs(prev => ({ ...prev, [id]: prev[id] === false ? true : false }));

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <header className="border-b sticky top-0 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 z-50">
        <div className="container mx-auto px-6 py-4">
          <div className="flex items-center gap-3">
            <div>
              <h1 className="text-xl font-semibold">Look-It-Up</h1>
              <p className="text-xs text-muted-foreground">AI-Driven Capability Finder</p>
            </div>
          </div>
        </div>
      </header>

      <main className="flex-1 container mx-auto px-6 py-6">
        <div className="space-y-6">
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="relative">
              <textarea
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Ask a what-if question about your business architecture..."
                className="w-full min-h-[120px] resize-none text-base p-4 border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary bg-background"
                data-testid="input-query"
              />
              <div className="absolute top-3 right-3">
                <Sparkles className="h-5 w-5 text-muted-foreground" />
              </div>
            </div>

            <div className="flex items-center justify-between gap-4">
              <div className="flex flex-wrap gap-2">
                {exampleQueries.map((example, idx) => (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => setQuery(example)}
                    className="px-3 py-1 text-xs bg-secondary text-secondary-foreground border rounded hover:shadow-md transition-shadow cursor-pointer"
                    data-testid={`badge-example-${idx}`}
                  >
                    {example}
                  </button>
                ))}
              </div>
              <button
                type="submit"
                disabled={!query.trim() || isLoading}
                className="px-6 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2 text-white whitespace-nowrap"
                data-testid="button-analyze"
              >
                <Search className="h-4 w-4" />
                {isLoading ? "Analyzing..." : "Analyze"}
              </button>
            </div>
          </form>

          {error && (
            <div className="border border-destructive rounded-lg p-4 bg-destructive/10">
              <p className="text-sm text-destructive">{error}</p>
            </div>
          )}

          {isLoading ? (
            <div className="text-center py-16">Analyzing...</div>
          ) : results.length > 0 ? (
            <div className="py-8">
              <div className="flex items-center gap-3 mb-6">
                <FiLayers className="w-8 h-8 text-indigo-600" />
                <h3 className="text-2xl font-semibold text-gray-900">
                  Relevant Results ({results.length})
                </h3>
              </div>
              <ul className="space-y-4">
                {results.map((cap: any) => {
                  const isCapExpanded = isCapOpen(cap.id);
                  const processes: any[] = cap.processes || [];

                  return (
                    <li key={cap.id} className="bg-white border border-gray-100 rounded-2xl shadow-sm hover:shadow-md transition-shadow">
                      {/* Capability header */}
                      <div className="p-4 flex items-start gap-3">
                        <button
                          className="text-gray-400 p-2 rounded-md hover:bg-gray-50 flex-shrink-0"
                          onClick={() => toggleCap(cap.id)}
                          aria-expanded={isCapExpanded}
                        >
                          {isCapExpanded ? <FiChevronDown size={18} /> : <FiChevronRight size={18} />}
                        </button>
                        <div className="flex-1">
                          <div className="text-lg font-semibold text-gray-900">{cap.name}</div>
                          <div className="mt-1 flex items-center gap-2 flex-wrap">
                            {cap.subvertical && (
                              <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-indigo-50 text-indigo-700">
                                {cap.subvertical}
                              </span>
                            )}
                            {cap.vertical && (
                              <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600">
                                {cap.vertical}
                              </span>
                            )}
                            <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-blue-50 text-blue-600">
                              {processes.length} process{processes.length !== 1 ? "es" : ""}
                            </span>
                          </div>
                          {cap.description && (
                            <div className="mt-2 text-sm text-gray-600">{cap.description}</div>
                          )}
                        </div>
                      </div>

                      {/* Processes */}
                      {isCapExpanded && (
                        <div className="border-t border-gray-100 px-4 py-4 bg-gray-50">
                          {processes.length === 0 ? (
                            <p className="text-sm text-gray-500 text-center py-4">No processes found</p>
                          ) : (
                            <div className="space-y-3">
                              {processes.map((proc: any) => {
                                const isProcExpanded = isProcOpen(proc.id);
                                const subprocesses: any[] = proc.subprocesses || [];

                                return (
                                  <div key={proc.id} className="bg-white border border-gray-200 rounded-lg overflow-hidden">
                                    {/* Process row */}
                                    <div
                                      className="p-3 flex items-start gap-3 cursor-pointer hover:bg-gray-50 transition"
                                      onClick={() => toggleProc(proc.id)}
                                    >
                                      <button className="flex-shrink-0 text-gray-400 mt-0.5">
                                        {isProcExpanded ? <FiChevronDown size={16} /> : <FiChevronRight size={16} />}
                                      </button>
                                      <div className="flex-1">
                                        <div className="flex items-center gap-2 flex-wrap">
                                          <span className="font-semibold text-gray-900 text-sm">{proc.name}</span>
                                          {proc.level && (
                                            <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-blue-50 text-blue-700">{proc.level}</span>
                                          )}
                                          {proc.category && (
                                            <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-purple-50 text-purple-700">{proc.category}</span>
                                          )}
                                          {subprocesses.length > 0 && (
                                            <span className="px-2 py-0.5 rounded-full text-xs bg-gray-100 text-gray-600">
                                              {subprocesses.length} subprocess{subprocesses.length !== 1 ? "es" : ""}
                                            </span>
                                          )}
                                        </div>
                                        {proc.description && (
                                          <p className="text-xs text-gray-500 mt-1">{proc.description}</p>
                                        )}
                                      </div>
                                    </div>

                                    {/* Subprocesses */}
                                    {isProcExpanded && subprocesses.length > 0 && (
                                      <ul className="divide-y divide-gray-100 border-t border-gray-200 bg-indigo-50">
                                        {subprocesses.map((sp: any) => {
                                          const dataEntities: any[] = sp.data_entities || [];
                                          return (
                                            <li key={sp.id} className="px-4 py-3">
                                              <div className="flex items-start gap-2">
                                                <div className="w-1.5 h-1.5 rounded-full bg-teal-500 flex-shrink-0 mt-1.5" />
                                                <div className="flex-1">
                                                  <div className="flex items-center gap-2 flex-wrap">
                                                    <span className="font-semibold text-gray-800 text-sm">{sp.name}</span>
                                                    {sp.category && (
                                                      <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-teal-100 text-teal-700">{sp.category}</span>
                                                    )}
                                                  </div>
                                                  {sp.description && (
                                                    <p className="text-xs text-gray-500 mt-1">{sp.description}</p>
                                                  )}
                                                  {dataEntities.length > 0 && (
                                                    <div className="mt-2 pt-2 border-t border-indigo-200 space-y-2">
                                                      <p className="text-xs font-semibold text-gray-600">
                                                        Data Entities ({dataEntities.length}):
                                                      </p>
                                                      <ul className="space-y-2">
                                                        {dataEntities.map((de: any) => {
                                                          const dataElements: any[] = de.data_elements || [];
                                                          return (
                                                            <li
                                                              key={de.data_entity_id}
                                                              className="bg-white border border-indigo-200 rounded-md px-3 py-2"
                                                            >
                                                              <div className="flex items-center gap-2 flex-wrap">
                                                                <span className="font-semibold text-xs text-gray-800">
                                                                  {de.data_entity_name}
                                                                </span>
                                                                <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-amber-50 text-amber-700">
                                                                  {dataElements.length} element{dataElements.length !== 1 ? "s" : ""}
                                                                </span>
                                                              </div>
                                                              {de.data_entity_description && (
                                                                <p className="text-[11px] text-gray-500 mt-1">
                                                                  {de.data_entity_description}
                                                                </p>
                                                              )}
                                                              {dataElements.length > 0 && (
                                                                <div className="mt-2 pt-2 border-t border-gray-100">
                                                                  <p className="text-[11px] font-semibold text-gray-600 mb-1">
                                                                    Data Elements:
                                                                  </p>
                                                                  <ul className="flex flex-wrap gap-1.5">
                                                                    {dataElements.map((el: any) => (
                                                                      <li
                                                                        key={el.data_element_id}
                                                                        className="px-2 py-0.5 rounded-md text-[11px] bg-amber-50 text-amber-800 border border-amber-100"
                                                                        title={el.data_element_description || ""}
                                                                      >
                                                                        {el.data_element_name}
                                                                      </li>
                                                                    ))}
                                                                  </ul>
                                                                </div>
                                                              )}
                                                            </li>
                                                          );
                                                        })}
                                                      </ul>
                                                    </div>
                                                  )}
                                                </div>
                                              </div>
                                            </li>
                                          );
                                        })}
                                      </ul>
                                    )}

                                    {isProcExpanded && subprocesses.length === 0 && (
                                      <div className="px-4 py-3 border-t border-gray-100 text-xs text-gray-400 text-center">
                                        No subprocesses
                                      </div>
                                    )}
                                  </div>
                                );
                              })}
                            </div>
                          )}
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          ) : query.trim() && !isLoading ? (
            <div className="text-center py-16" data-testid="no-results-state">
              <Building2 className="h-16 w-16 mx-auto text-muted-foreground/50 mb-4" />
              <h3 className="text-lg font-medium mb-2">No Matching Capabilities Found</h3>
              <p className="text-muted-foreground max-w-md mx-auto">
                Try rewording your question or exploring different topics.
              </p>
            </div>
          ) : (
            <div className="text-center py-16" data-testid="empty-state">
              <Building2 className="h-16 w-16 mx-auto text-muted-foreground/50 mb-4" />
              <h3 className="text-lg font-medium mb-2">Ready to Explore</h3>
              <p className="text-muted-foreground max-w-md mx-auto">
                Enter a question above to discover architecture relationships across your enterprise.
              </p>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
