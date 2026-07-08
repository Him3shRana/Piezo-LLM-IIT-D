import { useState, useEffect } from 'react';
import type { FC } from 'react';
import {
  Server, Cpu, Database, Info, CheckCircle, XCircle,
  Loader, Save, RotateCcw,
} from 'lucide-react';

// Default settings
const DEFAULTS = {
  backendUrl: 'http://localhost:5000',
  temperature: 0.2,
  topK: 4,
};

interface DbStatus {
  total_crystals: number;
  complete_crystals: number;
  incomplete_crystals: number;
  piezoelectric_count: number;
  ferroelectric_count: number;
  last_updated: string;
}

const Settings: FC = () => {
  const [backendUrl, setBackendUrl] = useState(DEFAULTS.backendUrl);
  const [temperature, setTemperature] = useState(DEFAULTS.temperature);
  const [topK, setTopK] = useState(DEFAULTS.topK);
  const [saved, setSaved] = useState(false);

  // Connection test
  const [testing, setTesting] = useState(false);
  const [connOk, setConnOk] = useState<boolean | null>(null);

  // DB status
  const [dbStatus, setDbStatus] = useState<DbStatus | null>(null);
  const [dbLoading, setDbLoading] = useState(false);

  // Load saved settings on mount
  useEffect(() => {
    const stored = localStorage.getItem('piezo_settings');
    if (stored) {
      try {
        const s = JSON.parse(stored);
        setBackendUrl(s.backendUrl ?? DEFAULTS.backendUrl);
        setTemperature(s.temperature ?? DEFAULTS.temperature);
        setTopK(s.topK ?? DEFAULTS.topK);
      } catch {
        // ignore malformed storage
      }
    }
  }, []);

  const saveSettings = () => {
    localStorage.setItem(
      'piezo_settings',
      JSON.stringify({ backendUrl, temperature, topK })
    );
    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  };

  const resetSettings = () => {
    setBackendUrl(DEFAULTS.backendUrl);
    setTemperature(DEFAULTS.temperature);
    setTopK(DEFAULTS.topK);
    localStorage.removeItem('piezo_settings');
  };

  const testConnection = async () => {
    setTesting(true);
    setConnOk(null);
    try {
      const res = await fetch(`${backendUrl}/api/admin/database-status`);
      setConnOk(res.ok);
    } catch {
      setConnOk(false);
    } finally {
      setTesting(false);
    }
  };

  const fetchDbStatus = async () => {
    setDbLoading(true);
    try {
      const res = await fetch(`${backendUrl}/api/admin/database-status`);
      if (res.ok) setDbStatus(await res.json());
    } catch {
      setDbStatus(null);
    } finally {
      setDbLoading(false);
    }
  };

  return (
    <div className="p-8 space-y-6 max-w-4xl">
      <h1 className="text-4xl font-bold text-white mb-2">Settings</h1>
      <p className="text-gray-400 mb-6">
        Configure the backend connection, AI chat behavior, and view database status.
      </p>

      {/* Backend Connection */}
      <div className="bg-gradient-to-r from-blue-900/30 to-cyan-900/30 border border-cyan-500/30 rounded-2xl p-8">
        <h2 className="text-2xl font-bold text-white mb-2 flex items-center gap-2">
          <Server className="w-6 h-6 text-cyan-400" />
          Backend Connection
        </h2>
        <p className="text-gray-400 mb-4">
          The address of your Flask backend. Change this to point at a remote GPU server.
        </p>

        <label className="block text-sm text-gray-300 mb-2">Backend URL</label>
        <input
          type="text"
          value={backendUrl}
          onChange={(e) => setBackendUrl(e.target.value)}
          placeholder="http://localhost:5000"
          className="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-2 text-white placeholder-gray-500 focus:outline-none focus:border-cyan-500 mb-4"
        />

        <button
          onClick={testConnection}
          disabled={testing}
          className="flex items-center justify-center gap-2 bg-gray-700 hover:bg-gray-600 disabled:bg-gray-800 text-white font-semibold py-2 px-4 rounded-lg transition-colors"
        >
          {testing ? (
            <>
              <Loader className="w-4 h-4 animate-spin" /> Testing...
            </>
          ) : (
            <>
              <Server className="w-4 h-4" /> Test Connection
            </>
          )}
        </button>

        {connOk === true && (
          <div className="mt-4 bg-green-900/40 border border-green-500/50 rounded-lg p-3 text-green-300 flex items-center gap-2">
            <CheckCircle className="w-5 h-5" /> Connected successfully.
          </div>
        )}
        {connOk === false && (
          <div className="mt-4 bg-red-900/40 border border-red-500/50 rounded-lg p-3 text-red-300 flex items-center gap-2">
            <XCircle className="w-5 h-5" /> Could not reach the backend at this URL.
          </div>
        )}
      </div>

      {/* AI Chat Settings */}
      <div className="bg-gradient-to-r from-purple-900/30 to-pink-900/30 border border-purple-500/30 rounded-2xl p-8">
        <h2 className="text-2xl font-bold text-white mb-2 flex items-center gap-2">
          <Cpu className="w-6 h-6 text-purple-400" />
          AI Chat Settings
        </h2>
        <p className="text-gray-400 mb-6">
          Controls how the AI answers questions using your crystal data.
        </p>

        {/* Temperature */}
        <div className="mb-6">
          <div className="flex justify-between mb-2">
            <label className="text-sm text-gray-300">
              Temperature (creativity)
            </label>
            <span className="text-sm font-mono text-purple-300">{temperature.toFixed(2)}</span>
          </div>
          <input
            type="range"
            min="0"
            max="1"
            step="0.05"
            value={temperature}
            onChange={(e) => setTemperature(parseFloat(e.target.value))}
            className="w-full accent-purple-500"
          />
          <p className="text-xs text-gray-500 mt-1">
            Lower = precise and factual (recommended for science). Higher = more creative.
          </p>
        </div>

        {/* Top-K */}
        <div>
          <div className="flex justify-between mb-2">
            <label className="text-sm text-gray-300">
              Retrieved chunks (top-k)
            </label>
            <span className="text-sm font-mono text-purple-300">{topK}</span>
          </div>
          <input
            type="range"
            min="1"
            max="10"
            step="1"
            value={topK}
            onChange={(e) => setTopK(parseInt(e.target.value))}
            className="w-full accent-purple-500"
          />
          <p className="text-xs text-gray-500 mt-1">
            How many crystal records are fed to the AI per question. More context vs. tighter focus.
          </p>
        </div>
      </div>

      {/* Save / Reset */}
      <div className="flex gap-4">
        <button
          onClick={saveSettings}
          className="flex-1 flex items-center justify-center gap-2 bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-white font-bold py-3 px-6 rounded-lg transition-all"
        >
          <Save className="w-5 h-5" /> Save Settings
        </button>
        <button
          onClick={resetSettings}
          className="flex items-center justify-center gap-2 bg-gray-700 hover:bg-gray-600 text-white font-semibold py-3 px-6 rounded-lg transition-colors"
        >
          <RotateCcw className="w-5 h-5" /> Reset
        </button>
      </div>
      {saved && (
        <div className="bg-green-900/40 border border-green-500/50 rounded-lg p-3 text-green-300 flex items-center gap-2">
          <CheckCircle className="w-5 h-5" /> Settings saved.
        </div>
      )}

      {/* Database Status */}
      <div className="bg-gray-900/50 border border-gray-700 rounded-2xl p-8">
        <h2 className="text-2xl font-bold text-white mb-2 flex items-center gap-2">
          <Database className="w-6 h-6 text-cyan-400" />
          Database Status
        </h2>
        <p className="text-gray-400 mb-4">
          Live snapshot of the crystal database.
        </p>

        <button
          onClick={fetchDbStatus}
          disabled={dbLoading}
          className="flex items-center justify-center gap-2 bg-gray-700 hover:bg-gray-600 disabled:bg-gray-800 text-white font-semibold py-2 px-4 rounded-lg transition-colors mb-4"
        >
          {dbLoading ? (
            <>
              <Loader className="w-4 h-4 animate-spin" /> Loading...
            </>
          ) : (
            <>
              <Database className="w-4 h-4" /> Load Status
            </>
          )}
        </button>

        {dbStatus && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="bg-gray-900 border border-gray-700 rounded-lg p-4">
              <p className="text-gray-400 text-sm mb-1">Total Crystals</p>
              <p className="text-3xl font-bold text-cyan-400">{dbStatus.total_crystals}</p>
            </div>
            <div className="bg-gray-900 border border-gray-700 rounded-lg p-4">
              <p className="text-gray-400 text-sm mb-1">Complete</p>
              <p className="text-3xl font-bold text-green-400">{dbStatus.complete_crystals}</p>
            </div>
            <div className="bg-gray-900 border border-gray-700 rounded-lg p-4">
              <p className="text-gray-400 text-sm mb-1">Piezoelectric</p>
              <p className="text-3xl font-bold text-blue-400">{dbStatus.piezoelectric_count}</p>
            </div>
            <div className="bg-gray-900 border border-gray-700 rounded-lg p-4">
              <p className="text-gray-400 text-sm mb-1">Ferroelectric</p>
              <p className="text-3xl font-bold text-purple-400">{dbStatus.ferroelectric_count}</p>
            </div>
          </div>
        )}
      </div>

      {/* About */}
      <div className="bg-gray-900/50 border border-gray-700 rounded-2xl p-8">
        <h2 className="text-2xl font-bold text-white mb-2 flex items-center gap-2">
          <Info className="w-6 h-6 text-cyan-400" />
          About
        </h2>
        <div className="text-gray-400 space-y-1 text-sm">
          <p><strong className="text-gray-300">Project:</strong> Piezo-LLM</p>
          <p><strong className="text-gray-300">Description:</strong> AI-powered search over piezoelectric crystal data</p>
          <p><strong className="text-gray-300">Stack:</strong> React + Vite frontend, Flask backend, Chroma vector DB, Qwen3</p>
        </div>
      </div>
    </div>
  );
};

export default Settings;