import React, { useState, useEffect } from 'react';
import { FiChevronLeft, FiChevronRight,FiEye, FiLogOut,FiUpload, FiHome, FiBarChart, FiLayers, FiSettings, FiX, FiMessageSquare } from 'react-icons/fi';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';

interface LLMSettings {
  provider: string;
  vaultName: string;
  temperature: number;
  topP: number;
}

const Sidebar: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [llmSettings, setLlmSettings] = useState<LLMSettings>({
    provider: 'azure',
    vaultName: 'https://fstodevazureopenai.vault.azure.net/',
    temperature: 0.2,
    topP: 0.9,
  });
  const [isLoadingLLM, setIsLoadingLLM] = useState(false);
  const [isEditingSettings, setIsEditingSettings] = useState(false);

  const navItems = [
    { label: 'Master Catalog', path: '/dashboard', icon: FiHome },
    { label: 'Compass Ingestion', path: '/dashboard/compass-ingestion', icon: FiUpload },
    { label: 'Compass Chat', path: '/dashboard/compass-chat', icon: FiMessageSquare },
    { label: 'Look-It-Up', path: '/dashboard/research-agent', icon: FiLayers },
    { label: 'View', path: '/dashboard/compass-view', icon: FiEye },
    { label: 'Visualizer', path: '/dashboard/compass-visualizer', icon: FiBarChart },

  ];

  // Load current LLM settings on mount
  useEffect(() => {
    const fetchLLMSettings = async () => {
      try {
        const response = await fetch('/api/settings/llm-provider');
        const data = await response.json();
        setLlmSettings(prev => ({
          ...prev,
          provider: data.provider || 'azure',
          vaultName: data.vaultName || 'https://kvcapabilitycompass.vault.azure.net/',
          temperature: data.temperature ?? 0.2,
          topP: data.topP ?? 0.9,
        }));
      } catch (error) {
        console.error('Failed to fetch LLM settings:', error);
      }
    };
    fetchLLMSettings();
  }, []);

  const handleLLMProviderChange = async (provider: string) => {
    setIsLoadingLLM(true);
    try {
      const response = await fetch('/api/settings/llm-provider', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider }),
      });
      if (!response.ok) throw new Error('Failed to change LLM provider');
      await response.json();
      setLlmSettings(prev => ({ ...prev, provider }));
      toast.success(`Switched to ${provider.toUpperCase()} LLM`);
    } catch (error) {
      console.error('Error changing LLM provider:', error);
      toast.error('Failed to change LLM provider');
    } finally {
      setIsLoadingLLM(false);
    }
  };

  const handleLLMSettingsSave = async () => {
    setIsLoadingLLM(true);
    try {
      const response = await fetch('/api/settings/llm-config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(llmSettings),
      });
      if (!response.ok) throw new Error('Failed to save LLM settings');
      await response.json();
      setIsEditingSettings(false);
      toast.success('LLM settings updated successfully');
    } catch (error) {
      console.error('Error saving LLM settings:', error);
      toast.error('Failed to save LLM settings');
    } finally {
      setIsLoadingLLM(false);
    }
  };

  return (
    <aside
      className={`bg-white border-r border-gray-200 transition-all duration-300 flex flex-col ${
        collapsed ? 'w-16' : 'w-64'
      }`}
    >
      {/* Header */}
      <div className={`p-4 border-b border-gray-200 flex items-center justify-between relative`}>
        {collapsed ? (
          <>
            <img src="/favicon.png" alt="Compass" className="w-6 h-6" />
            <button
              onClick={() => setCollapsed(!collapsed)}
              className="p-1 hover:bg-gray-100 rounded-md"
              title="Expand"
            >
              <FiChevronRight size={18} />
            </button>
          </>
        ) : (
          <>
            <div className="flex items-center gap-2">
              <img src="/favicon.png" alt="Compass" className="w-6 h-6" />
              <h2 className="font-bold text-lg text-gray-900">Capability Compass</h2>
            </div>
            <button
              onClick={() => setCollapsed(!collapsed)}
              className="p-1 hover:bg-gray-100 rounded-md flex-shrink-0"
              title="Collapse"
            >
              <FiChevronLeft size={18} />
            </button>
          </>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-4 space-y-2">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = location.pathname === item.path;

          return (
            <NavLink
              key={item.path}
              to={item.path}
              className={`flex items-center ${collapsed ? 'justify-center' : 'justify-start'} gap-3 px-3 py-2 rounded-md transition-colors ${
                isActive
                  ? 'bg-indigo-100 text-indigo-700 font-medium'
                  : 'text-gray-700 hover:bg-gray-100'
              }`}
              title={collapsed ? item.label : ''}
            >
              <Icon size={20} className="flex-shrink-0 w-5 h-5" />
              {!collapsed && <span className="text-sm">{item.label}</span>}
            </NavLink>
          );
        })}
      </nav>

      {/* Footer with Settings */}
      <div className="p-4 border-t border-gray-200 space-y-2">
        <button
          onClick={() => setShowSettings(!showSettings)}
          className={`w-full flex items-center ${collapsed ? 'justify-center' : 'justify-start'} gap-3 px-3 py-2 rounded-md text-gray-700 hover:bg-gray-100 transition-colors`}
          title={collapsed ? 'Settings' : ''}
        >
          <FiSettings size={20} className="flex-shrink-0 w-5 h-5" />
          {!collapsed && <span className="text-sm">Settings</span>}
        </button>

        {showSettings && !collapsed && (
          <div className="mt-3 p-3 bg-gray-50 rounded-lg border border-gray-200 max-h-96 overflow-y-auto">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-gray-900">LLM Settings</h3>
              <button
                onClick={() => {
                  setShowSettings(false);
                  setIsEditingSettings(false);
                }}
                className="p-0.5 hover:bg-gray-200 rounded"
              >
                <FiX size={16} />
              </button>
            </div>

            {!isEditingSettings ? (
              <>
                <div className="space-y-2 mb-3">
                  <p className="text-xs font-medium text-gray-600">Provider</p>
                  <div className="space-y-2">
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="radio"
                        name="llm-provider"
                        value="azure"
                        checked={llmSettings.provider === 'azure'}
                        onChange={() => handleLLMProviderChange('azure')}
                        disabled={isLoadingLLM}
                        className="cursor-pointer"
                      />
                      <span className="text-sm text-gray-700">Azure OpenAI</span>
                    </label>
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="radio"
                        name="llm-provider"
                        value="gemini"
                        checked={llmSettings.provider === 'gemini'}
                        onChange={() => handleLLMProviderChange('gemini')}
                        disabled={isLoadingLLM}
                        className="cursor-pointer"
                      />
                      <span className="text-sm text-gray-700">Google Gemini</span>
                    </label>
                  </div>
                </div>

                <button
                  onClick={() => setIsEditingSettings(true)}
                  disabled={isLoadingLLM}
                  className="w-full text-xs px-3 py-2 bg-indigo-100 text-indigo-700 rounded hover:bg-indigo-200 disabled:opacity-50 font-medium"
                >
                  Advanced Settings
                </button>
                {isLoadingLLM && <p className="text-xs text-gray-500 mt-2">Updating...</p>}
              </>
            ) : (
              <>
                <div className="space-y-3">
                  <div>
                    <label className="text-xs font-medium text-gray-600">Vault URL</label>
                    <input
                      type="text"
                      value={llmSettings.vaultName}
                      onChange={(e) => setLlmSettings(prev => ({ ...prev, vaultName: e.target.value }))}
                      className="w-full text-xs px-2 py-1 border border-gray-300 rounded mt-1"
                      placeholder="https://kvcapabilitycompass.vault.azure.net/"
                    />
                  </div>

                  <div>
                    <label className="text-xs font-medium text-gray-600">
                      Temperature: {llmSettings.temperature.toFixed(2)}
                    </label>
                    <input
                      type="range"
                      min="0"
                      max="1"
                      step="0.1"
                      value={llmSettings.temperature}
                      onChange={(e) => setLlmSettings(prev => ({ ...prev, temperature: parseFloat(e.target.value) }))}
                      className="w-full text-xs mt-1"
                    />
                    <p className="text-xs text-gray-500">Creativity level (0-1)</p>
                  </div>

                  <div>
                    <label className="text-xs font-medium text-gray-600">
                      Top P: {llmSettings.topP.toFixed(2)}
                    </label>
                    <input
                      type="range"
                      min="0"
                      max="1"
                      step="0.1"
                      value={llmSettings.topP}
                      onChange={(e) => setLlmSettings(prev => ({ ...prev, topP: parseFloat(e.target.value) }))}
                      className="w-full text-xs mt-1"
                    />
                    <p className="text-xs text-gray-500">Diversity level (0-1)</p>
                  </div>
                </div>

                <div className="flex gap-2 mt-3">
                  <button
                    onClick={() => setIsEditingSettings(false)}
                    disabled={isLoadingLLM}
                    className="flex-1 text-xs px-2 py-1 bg-gray-200 text-gray-700 rounded hover:bg-gray-300 disabled:opacity-50"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleLLMSettingsSave}
                    disabled={isLoadingLLM}
                    className="flex-1 text-xs px-2 py-1 bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50"
                  >
                    Save
                  </button>
                </div>
                {isLoadingLLM && <p className="text-xs text-gray-500 mt-2">Saving...</p>}
              </>
            )}
          </div>
        )}

        <button
          onClick={() => navigate('/')}
          className={`w-full flex items-center ${collapsed ? 'justify-center' : 'justify-start'} gap-3 px-3 py-2 rounded-md text-gray-700 hover:bg-gray-100 transition-colors`}
          title={collapsed ? 'Logout' : ''}
        >
          <FiLogOut size={20} className="flex-shrink-0 w-5 h-5" />
          {!collapsed && <span className="text-sm">Exit</span>}
        </button>
      </div>
    </aside>
  );
};

export default Sidebar;


