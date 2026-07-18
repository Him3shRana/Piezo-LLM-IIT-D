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
  ArrowRight,
  Activity,
  Zap,
  Atom,
  ChevronRight,
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
  const [llmStatus, setLlmStatus] = useState<'checking' | 'ready' | 'not_installed'>('checking');
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
      .then((data) => { setData(data); setLoading(false); })
      .catch((err) => { console.error("Failed to load database:", err); setLoading(false); });

    fetch("http://localhost:5000/api/llm-status")
      .then((res) => res.json())
      .then((d) => { setLlmStatus(d.installed ? 'ready' : 'not_installed'); })
      .catch(() => { setLlmStatus('not_installed'); });
  }, []);

  const openUpload = async () => {
    setShowUpload(true); setPdfFile(null); setCifFile(null);
    setUploadResult(''); setUploadError(''); setNextId('');
    try {
      const res = await fetch('http://localhost:5000/api/next-pmc-id');
      if (res.ok) { const d = await res.json(); setNextId(d.next_id || ''); }
    } catch { /* backend not ready */ }
  };

  const closeUpload = () => { if (!uploading) setShowUpload(false); };

  const handleUpload = async () => {
    if (!pdfFile || !cifFile) { setUploadError('Both a PDF and a CIF file are required.'); return; }
    setUploading(true); setUploadError(''); setUploadResult('');
    try {
      const formData = new FormData();
      formData.append('pdf', pdfFile); formData.append('cif', cifFile);
      const res = await fetch('http://localhost:5000/api/upload-crystal', { method: 'POST', body: formData });
      const d = await res.json();
      if (!res.ok || !d.success) throw new Error(d.error || `Server error: ${res.status}`);
      setUploadResult(`Created ${d.pmc_id}: saved PDF + CIF, generated JSON and TXT` + (d.fields_filled ? `, ${d.fields_filled} fields auto-filled from CIF.` : '.'));
    } catch (e) { setUploadError(`Upload failed: ${e}`); }
    finally { setUploading(false); }
  };

  if (loading) return (
    <div className="flex items-center justify-center h-screen">
      <Loader className="w-8 h-8 animate-spin text-cyan-400" />
    </div>
  );

  if (!data) return (
    <div className="flex items-center justify-center h-screen text-red-400">
      <AlertCircle className="w-6 h-6 mr-2" /> Error loading data
    </div>
  );

  const totalCrystals = data.metadata.total_crystals;
  const crystalList = Object.values(data.crystals).slice(0, 5);

  const statusItems = [
    { label: 'Database', ok: true, detail: 'Connected' },
    { label: 'Backend', ok: true, detail: 'Running' },
    { label: 'Embedding Model', ok: true, detail: 'Ready' },
    { label: 'LLM', ok: llmStatus === 'ready', detail: llmStatus === 'ready' ? 'Qwen3-8B' : 'Not Installed' },
    { label: 'GPU', ok: true, detail: 'A100 · 80GB' },
  ];

  return (
    <div className="min-h-screen p-6 lg:p-10 max-w-[1400px] mx-auto">

      {/* ─── Header ─── */}
      <div className="flex items-end justify-between mb-10">
        <div>
          <div className="flex items-center gap-3 mb-2">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-500 to-blue-600 flex items-center justify-center">
              <Atom className="w-5 h-5 text-white" />
            </div>
            <h1 className="text-3xl font-bold tracking-tight bg-gradient-to-r from-white to-gray-400 bg-clip-text text-transparent">
              Dashboard
            </h1>
          </div>
          <p className="text-sm text-gray-500 ml-[52px]">Piezo-LLM · Molecular Crystal Research Platform</p>
        </div>

        <div className="flex items-center gap-2 px-4 py-2 rounded-full border border-green-500/30 bg-green-500/5">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500" />
          </span>
          <span className="text-xs font-medium text-green-400">System Online</span>
        </div>
      </div>

      {/* ─── Stats Grid ─── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        {[
          { icon: Database, label: 'Crystals', value: totalCrystals, gradient: 'from-cyan-500/10 to-cyan-500/5', iconColor: 'text-cyan-400', borderColor: 'border-cyan-500/20' },
          { icon: FileText, label: 'Research Papers', value: 36, gradient: 'from-blue-500/10 to-blue-500/5', iconColor: 'text-blue-400', borderColor: 'border-blue-500/20' },
          { icon: Bot, label: 'Embedding Model', value: 'Active', gradient: 'from-violet-500/10 to-violet-500/5', iconColor: 'text-violet-400', borderColor: 'border-violet-500/20' },
          { icon: Cpu, label: 'LLM (Qwen3)', value: llmStatus === 'checking' ? '...' : llmStatus === 'ready' ? 'Active' : 'Offline', gradient: 'from-emerald-500/10 to-emerald-500/5', iconColor: llmStatus === 'ready' ? 'text-emerald-400' : 'text-yellow-400', borderColor: llmStatus === 'ready' ? 'border-emerald-500/20' : 'border-yellow-500/20' },
        ].map((stat, i) => (
          <div
            key={i}
            className={`group relative overflow-hidden rounded-2xl border ${stat.borderColor} bg-gradient-to-br ${stat.gradient} p-5 transition-all duration-300 hover:scale-[1.02] hover:shadow-lg hover:shadow-cyan-500/5`}
          >
            <div className="flex items-start justify-between">
              <div>
                <p className="text-xs font-medium uppercase tracking-wider text-gray-500 mb-3">{stat.label}</p>
                <p className="text-2xl font-bold text-white">{stat.value}</p>
              </div>
              <div className={`p-2.5 rounded-xl bg-white/5 ${stat.iconColor}`}>
                <stat.icon className="w-5 h-5" />
              </div>
            </div>
            <div className="absolute -bottom-6 -right-6 w-24 h-24 rounded-full bg-white/[0.02] group-hover:scale-150 transition-transform duration-500" />
          </div>
        ))}
      </div>

      {/* ─── Quick Actions + System Status ─── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-8">

        {/* Quick Actions - takes 2 cols */}
        <div className="lg:col-span-2">
          <h2 className="text-sm font-medium uppercase tracking-wider text-gray-500 mb-4">Quick Actions</h2>
          <div className="grid grid-cols-2 gap-3">
            {[
              { icon: MessageSquare, label: 'AI Chat', desc: 'Ask questions about crystals', color: 'from-cyan-600 to-cyan-700', hoverColor: 'hover:from-cyan-500 hover:to-cyan-600', onClick: () => navigate('/chat') },
              { icon: FolderOpen, label: 'Database', desc: 'Browse crystal database', color: 'from-blue-600 to-blue-700', hoverColor: 'hover:from-blue-500 hover:to-blue-600', onClick: () => navigate('/database') },
              { icon: Upload, label: 'Upload Crystal', desc: 'Add new PDF & CIF', color: 'from-emerald-600 to-emerald-700', hoverColor: 'hover:from-emerald-500 hover:to-emerald-600', onClick: openUpload },
              { icon: Search, label: 'Crystal Search', desc: 'Explore by properties', color: 'from-violet-600 to-violet-700', hoverColor: 'hover:from-violet-500 hover:to-violet-600', onClick: () => navigate('/crystals') },
            ].map((action, i) => (
              <button
                key={i}
                onClick={action.onClick}
                className={`group flex items-center gap-4 rounded-xl bg-gradient-to-r ${action.color} ${action.hoverColor} p-4 text-left transition-all duration-200 hover:shadow-lg hover:shadow-black/20 active:scale-[0.98]`}
              >
                <div className="p-2.5 rounded-lg bg-white/10">
                  <action.icon className="w-5 h-5 text-white" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="font-semibold text-white text-sm">{action.label}</p>
                  <p className="text-[11px] text-white/60 truncate">{action.desc}</p>
                </div>
                <ArrowRight className="w-4 h-4 text-white/40 group-hover:text-white/80 group-hover:translate-x-0.5 transition-all" />
              </button>
            ))}
          </div>
        </div>

        {/* System Status */}
        <div>
          <h2 className="text-sm font-medium uppercase tracking-wider text-gray-500 mb-4">System Status</h2>
          <div className="rounded-2xl border border-gray-800 bg-[#0d1117] p-4 space-y-1">
            {statusItems.map((item, i) => (
              <div key={i} className="flex items-center justify-between py-2.5 px-2 rounded-lg hover:bg-white/[0.02] transition-colors">
                <span className="text-sm text-gray-400">{item.label}</span>
                <div className="flex items-center gap-2">
                  <span className={`text-xs font-medium ${item.ok ? 'text-green-400' : 'text-yellow-400'}`}>
                    {item.detail}
                  </span>
                  <span className={`w-1.5 h-1.5 rounded-full ${item.ok ? 'bg-green-500' : 'bg-yellow-500'}`} />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ─── Recent Crystals ─── */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-medium uppercase tracking-wider text-gray-500">Recent Crystals</h2>
          <button
            onClick={() => navigate('/crystals')}
            className="text-xs text-cyan-500 hover:text-cyan-400 flex items-center gap-1 transition-colors"
          >
            View all <ChevronRight className="w-3 h-3" />
          </button>
        </div>

        <div className="rounded-2xl border border-gray-800 bg-[#0d1117] overflow-hidden">
          {crystalList.map((crystal: any, index: number) => (
            <div
              key={index}
              className={`group flex items-center justify-between px-5 py-4 hover:bg-white/[0.02] transition-colors cursor-pointer ${
                index !== crystalList.length - 1 ? 'border-b border-gray-800/50' : ''
              }`}
              onClick={() => navigate(`/crystal/${crystal.pmc_id}`)}
            >
              <div className="flex items-center gap-4">
                <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-cyan-500/20 to-blue-500/20 border border-cyan-500/10 flex items-center justify-center">
                  <Atom className="w-4 h-4 text-cyan-400" />
                </div>
                <div>
                  <p className="text-sm font-semibold text-white group-hover:text-cyan-300 transition-colors">
                    {crystal.pmc_id}
                  </p>
                  <p className="text-xs text-gray-500">{crystal.molecule_name}</p>
                </div>
              </div>
              <ChevronRight className="w-4 h-4 text-gray-600 group-hover:text-cyan-400 group-hover:translate-x-0.5 transition-all" />
            </div>
          ))}
        </div>
      </div>

      {/* ─── Upload Modal ─── */}
      {showUpload && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4" onClick={closeUpload}>
          <div
            className="w-full max-w-lg rounded-2xl bg-[#0d1117] border border-gray-700/50 shadow-2xl shadow-black/50 overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal header */}
            <div className="flex items-center justify-between p-6 pb-0">
              <div className="flex items-center gap-3">
                <div className="p-2 rounded-xl bg-emerald-500/10 border border-emerald-500/20">
                  <Upload className="w-5 h-5 text-emerald-400" />
                </div>
                <div>
                  <h2 className="text-lg font-bold text-white">Upload New Crystal</h2>
                  <p className="text-xs text-gray-500">Add paper PDF and CIF structure file</p>
                </div>
              </div>
              <button onClick={closeUpload} disabled={uploading}
                className="p-1.5 rounded-lg text-gray-500 hover:text-white hover:bg-white/5 disabled:opacity-40 transition-all">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-6 space-y-5">
              {/* Next PMC id */}
              <div className="rounded-xl bg-cyan-500/5 border border-cyan-500/20 p-4 flex items-center justify-between">
                <div>
                  <p className="text-[10px] font-medium uppercase tracking-wider text-gray-500">New Entry ID</p>
                  <p className="text-xl font-bold text-cyan-400 mt-1">
                    {nextId || <span className="text-gray-600 text-sm">Connecting...</span>}
                  </p>
                </div>
                <Zap className="w-5 h-5 text-cyan-500/30" />
              </div>

              {/* File pickers */}
              <div>
                <label className="text-xs font-medium text-gray-400 mb-2 block">
                  PDF File <span className="text-red-400">*</span>
                </label>
                <label className={`flex items-center gap-3 p-3 rounded-xl border border-dashed cursor-pointer transition-all ${
                  pdfFile ? 'border-emerald-500/40 bg-emerald-500/5' : 'border-gray-700 hover:border-gray-500 bg-white/[0.01]'
                }`}>
                  <div className={`p-2 rounded-lg ${pdfFile ? 'bg-emerald-500/10' : 'bg-white/5'}`}>
                    <FileText className={`w-4 h-4 ${pdfFile ? 'text-emerald-400' : 'text-gray-500'}`} />
                  </div>
                  <span className={`text-sm flex-1 ${pdfFile ? 'text-emerald-300' : 'text-gray-500'}`}>
                    {pdfFile ? pdfFile.name : 'Choose PDF file...'}
                  </span>
                  {pdfFile && <CheckCircle className="w-4 h-4 text-emerald-400" />}
                  <input type="file" accept=".pdf" onChange={(e) => setPdfFile(e.target.files?.[0] || null)} className="hidden" />
                </label>
              </div>

              <div>
                <label className="text-xs font-medium text-gray-400 mb-2 block">
                  CIF File <span className="text-red-400">*</span>
                </label>
                <label className={`flex items-center gap-3 p-3 rounded-xl border border-dashed cursor-pointer transition-all ${
                  cifFile ? 'border-cyan-500/40 bg-cyan-500/5' : 'border-gray-700 hover:border-gray-500 bg-white/[0.01]'
                }`}>
                  <div className={`p-2 rounded-lg ${cifFile ? 'bg-cyan-500/10' : 'bg-white/5'}`}>
                    <Atom className={`w-4 h-4 ${cifFile ? 'text-cyan-400' : 'text-gray-500'}`} />
                  </div>
                  <span className={`text-sm flex-1 ${cifFile ? 'text-cyan-300' : 'text-gray-500'}`}>
                    {cifFile ? cifFile.name : 'Choose CIF file...'}
                  </span>
                  {cifFile && <CheckCircle className="w-4 h-4 text-cyan-400" />}
                  <input type="file" accept=".cif" onChange={(e) => setCifFile(e.target.files?.[0] || null)} className="hidden" />
                </label>
              </div>

              {/* Upload button */}
              <button
                onClick={handleUpload}
                disabled={uploading || !pdfFile || !cifFile}
                className="w-full flex items-center justify-center gap-2 bg-gradient-to-r from-emerald-600 to-cyan-600 hover:from-emerald-500 hover:to-cyan-500 disabled:from-gray-700 disabled:to-gray-700 text-white font-semibold py-3 px-6 rounded-xl transition-all disabled:opacity-40 disabled:cursor-not-allowed active:scale-[0.98]"
              >
                {uploading ? (
                  <><Loader className="w-4 h-4 animate-spin" /> Processing...</>
                ) : (
                  <><Upload className="w-4 h-4" /> Upload & Create Entry</>
                )}
              </button>

              {/* Result / error */}
              {uploadResult && (
                <div className="rounded-xl bg-emerald-500/5 border border-emerald-500/20 p-4 flex items-start gap-3">
                  <CheckCircle className="w-5 h-5 text-emerald-400 flex-shrink-0 mt-0.5" />
                  <p className="text-sm text-emerald-300">{uploadResult}</p>
                </div>
              )}
              {uploadError && (
                <div className="rounded-xl bg-red-500/5 border border-red-500/20 p-4 flex items-start gap-3">
                  <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" />
                  <p className="text-sm text-red-300">{uploadError}</p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default Dashboard;