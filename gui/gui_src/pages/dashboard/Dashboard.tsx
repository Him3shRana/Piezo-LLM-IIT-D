import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Database,
  FileText,
  Bot,
  Cpu,
  MessageSquare,
  FolderOpen,
  Upload,
  Search,
  X,
  CheckCircle,
  AlertCircle,
  Loader,
} from "lucide-react";

interface MasterDatabase {
  metadata: {
    total_crystals: number;
  };
  crystals: Record<string, any>;
}

function Dashboard() {
  const [data, setData] = useState<MasterDatabase | null>(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  // LLM status
  const [llmStatus, setLlmStatus] = useState<'checking' | 'ready' | 'not_installed'>('checking');

  // Upload modal state
  const [showUpload, setShowUpload] = useState(false);
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const [cifFile, setCifFile] = useState<File | null>(null);
  const [nextId, setNextId] = useState<string>('');
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<string>('');
  const [uploadError, setUploadError] = useState<string>('');

  useEffect(() => {
    fetch("/database/master_database.json")
      .then((res) => res.json())
      .then((data) => {
        setData(data);
        setLoading(false);
      })
      .catch((err) => {
        console.error("Failed to load database:", err);
        setLoading(false);
      });

    // Check LLM status from backend
    fetch("http://localhost:5000/api/llm-status")
      .then((res) => res.json())
      .then((d) => {
        setLlmStatus(d.installed ? 'ready' : 'not_installed');
      })
      .catch(() => {
        setLlmStatus('not_installed');
      });
  }, []);

  // When the modal opens, ask the backend what the next PMC id will be.
  const openUpload = async () => {
    setShowUpload(true);
    setPdfFile(null);
    setCifFile(null);
    setUploadResult('');
    setUploadError('');
    setNextId('');
    try {
      const res = await fetch('http://localhost:5000/api/next-pmc-id');
      if (res.ok) {
        const d = await res.json();
        setNextId(d.next_id || '');
      }
    } catch {
      // backend not ready yet — leave blank
    }
  };

  const closeUpload = () => {
    if (uploading) return; // don't close mid-upload
    setShowUpload(false);
  };

  const handleUpload = async () => {
    if (!pdfFile || !cifFile) {
      setUploadError('Both a PDF and a CIF file are required.');
      return;
    }
    setUploading(true);
    setUploadError('');
    setUploadResult('');

    try {
      const formData = new FormData();
      formData.append('pdf', pdfFile);
      formData.append('cif', cifFile);

      const res = await fetch('http://localhost:5000/api/upload-crystal', {
        method: 'POST',
        body: formData,
      });

      const d = await res.json();
      if (!res.ok || !d.success) {
        throw new Error(d.error || `Server error: ${res.status}`);
      }

      setUploadResult(
        `Created ${d.pmc_id}: saved PDF + CIF, generated JSON and TXT` +
        (d.fields_filled ? `, ${d.fields_filled} fields auto-filled from CIF.` : '.')
      );
    } catch (e) {
      setUploadError(`Upload failed: ${e}`);
    } finally {
      setUploading(false);
    }
  };

  if (loading) {
    return <div className="p-8 text-white">Loading Dashboard...</div>;
  }

  if (!data) {
    return <div className="p-8 text-white">Error loading data</div>;
  }

  const totalCrystals = data.metadata.total_crystals;
  const crystalList = Object.values(data.crystals).slice(0, 4);

  return (
    <div className="p-8">
      {/* Header */}
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-4xl font-bold">Dashboard</h1>
          <p className="mt-2 text-gray-400">Welcome back to Piezo-LLM</p>
        </div>
        <div className="rounded-full bg-green-500/20 px-4 py-2 text-green-400">
          System Ready
        </div>
      </div>

      {/* Statistics */}
      <div className="grid grid-cols-4 gap-5">
        <div className="rounded-2xl bg-[#111827] p-6">
          <Database className="mb-3 text-cyan-400" />
          <p className="text-gray-400">Crystals</p>
          <h2 className="mt-3 text-3xl font-bold">{totalCrystals}</h2>
        </div>

        <div className="rounded-2xl bg-[#111827] p-6">
          <FileText className="mb-3 text-cyan-400" />
          <p className="text-gray-400">Research Papers</p>
          <h2 className="mt-3 text-3xl font-bold">36</h2>
        </div>

        <div className="rounded-2xl bg-[#111827] p-6">
          <Bot className="mb-3 text-cyan-400" />
          <p className="text-gray-400">Embedding Model</p>
          <h2 className="mt-3 text-3xl font-bold">Ready</h2>
        </div>

        <div className="rounded-2xl bg-[#111827] p-6">
          <Cpu className="mb-3 text-cyan-400" />
          <p className="text-gray-400">LLM (Qwen3)</p>
          {llmStatus === 'checking' ? (
            <h2 className="mt-3 text-2xl font-bold text-gray-400">Checking...</h2>
          ) : llmStatus === 'ready' ? (
            <h2 className="mt-3 text-2xl font-bold text-green-400">Ready</h2>
          ) : (
            <h2 className="mt-3 text-2xl font-bold text-yellow-400">Not Installed</h2>
          )}
        </div>
      </div>

      {/* Quick Actions */}
      <h2 className="mt-10 mb-5 text-2xl font-bold">Quick Actions</h2>
      <div className="grid grid-cols-4 gap-5">
        <button
          onClick={() => navigate('/chat')}
          className="rounded-xl bg-cyan-600 p-5 transition hover:scale-105 text-white font-semibold"
        >
          <MessageSquare className="mx-auto mb-3" />
          AI Chat
        </button>

        <button
          onClick={() => navigate('/database')}
          className="rounded-xl bg-blue-600 p-5 transition hover:scale-105 text-white font-semibold"
        >
          <FolderOpen className="mx-auto mb-3" />
          Database
        </button>

        <button
          onClick={openUpload}
          className="rounded-xl bg-green-600 p-5 transition hover:scale-105 text-white font-semibold"
        >
          <Upload className="mx-auto mb-3" />
          Upload PDF
        </button>

        <button
          onClick={() => navigate('/crystals')}
          className="rounded-xl bg-purple-600 p-5 transition hover:scale-105 text-white font-semibold"
        >
          <Search className="mx-auto mb-3" />
          Crystal Search
        </button>
      </div>

      {/* Recent Crystals */}
      <h2 className="mt-10 mb-5 text-2xl font-bold">Recent Crystals</h2>
      <div className="rounded-2xl bg-[#111827] p-6">
        {crystalList.map((crystal: any, index: number) => (
          <div key={index} className="mb-4 flex items-center justify-between">
            <div>
              <h3 className="font-semibold">{crystal.pmc_id}</h3>
              <p className="text-sm text-gray-400">{crystal.molecule_name}</p>
            </div>
            <button
              onClick={() => navigate(`/crystal/${crystal.pmc_id}`)}
              className="text-cyan-400 hover:text-cyan-300"
            >
              View
            </button>
          </div>
        ))}
      </div>

      {/* System Status */}
      <h2 className="mt-10 mb-5 text-2xl font-bold">System Status</h2>
      <div className="rounded-2xl bg-[#111827] p-6 space-y-4">
        <div className="flex items-center justify-between">
          <span>Database</span>
          <span className="text-green-400">🟢 Connected</span>
        </div>
        <div className="flex items-center justify-between">
          <span>Backend</span>
          <span className="text-green-400">🟢 Running</span>
        </div>
        <div className="flex items-center justify-between">
          <span>Embedding Model</span>
          <span className="text-green-400">🟢 Ready</span>
        </div>
        <div className="flex items-center justify-between">
          <span>LLM</span>
          {llmStatus === 'ready' ? (
            <span className="text-green-400">🟢 Qwen3-8B Ready</span>
          ) : (
            <span className="text-yellow-400">🟡 Not Installed</span>
          )}
        </div>
        <div className="flex items-center justify-between">
          <span>GPU</span>
          <span className="text-green-400">🟢 Available (80GB)</span>
        </div>
      </div>

      {/* ===================== Upload Modal ===================== */}
      {showUpload && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
          onClick={closeUpload}
        >
          <div
            className="w-full max-w-lg rounded-2xl bg-[#111827] border border-gray-700 p-8"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal header */}
            <div className="flex items-start justify-between mb-2">
              <h2 className="text-2xl font-bold text-white flex items-center gap-2">
                <Upload className="w-6 h-6 text-green-400" />
                Upload New Crystal
              </h2>
              <button
                onClick={closeUpload}
                disabled={uploading}
                className="text-gray-400 hover:text-white disabled:opacity-40"
              >
                <X className="w-6 h-6" />
              </button>
            </div>

            <p className="text-gray-400 mb-6">
              Upload the paper PDF and its CIF file. A new entry will be created
              automatically.
            </p>

            {/* Next PMC id preview */}
            <div className="mb-6 rounded-lg bg-gray-900 border border-gray-700 p-4">
              <p className="text-sm text-gray-400">This will be saved as</p>
              <p className="text-xl font-bold text-cyan-400">
                {nextId || '(connecting to backend...)'}
              </p>
            </div>

            {/* PDF picker */}
            <label className="block text-sm text-gray-300 mb-2">
              PDF file <span className="text-red-400">*</span>
            </label>
            <input
              type="file"
              accept=".pdf"
              onChange={(e) => setPdfFile(e.target.files?.[0] || null)}
              className="w-full mb-4 text-sm text-gray-300 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:bg-green-600 file:text-white file:font-semibold hover:file:bg-green-500 file:cursor-pointer"
            />
            {pdfFile && (
              <p className="text-xs text-green-400 -mt-2 mb-4">
                ✓ {pdfFile.name}
              </p>
            )}

            {/* CIF picker */}
            <label className="block text-sm text-gray-300 mb-2">
              CIF file <span className="text-red-400">*</span>
            </label>
            <input
              type="file"
              accept=".cif"
              onChange={(e) => setCifFile(e.target.files?.[0] || null)}
              className="w-full mb-4 text-sm text-gray-300 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:bg-cyan-600 file:text-white file:font-semibold hover:file:bg-cyan-500 file:cursor-pointer"
            />
            {cifFile && (
              <p className="text-xs text-cyan-400 -mt-2 mb-4">
                ✓ {cifFile.name}
              </p>
            )}

            {/* Upload button */}
            <button
              onClick={handleUpload}
              disabled={uploading || !pdfFile || !cifFile}
              className="w-full flex items-center justify-center gap-2 bg-gradient-to-r from-green-600 to-emerald-600 hover:from-green-500 hover:to-emerald-500 disabled:from-gray-600 disabled:to-gray-600 text-white font-bold py-3 px-6 rounded-lg transition-all disabled:opacity-50 disabled:cursor-not-allowed mt-2"
            >
              {uploading ? (
                <>
                  <Loader className="w-5 h-5 animate-spin" />
                  Uploading...
                </>
              ) : (
                <>
                  <Upload className="w-5 h-5" />
                  Upload & Create Entry
                </>
              )}
            </button>

            {/* Result / error */}
            {uploadResult && (
              <div className="mt-4 bg-green-900/40 border border-green-500/50 rounded-lg p-4 text-green-300 flex items-start gap-2">
                <CheckCircle className="w-5 h-5 flex-shrink-0 mt-0.5" />
                <span>{uploadResult}</span>
              </div>
            )}
            {uploadError && (
              <div className="mt-4 bg-red-900/40 border border-red-500/50 rounded-lg p-4 text-red-300 flex items-start gap-2">
                <AlertCircle className="w-5 h-5 flex-shrink-0 mt-0.5" />
                <span>{uploadError}</span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default Dashboard;