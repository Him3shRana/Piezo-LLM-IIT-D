import { useState } from 'react';
import type { FC } from 'react';
import {
  RefreshCw,
  Database,
  AlertCircle,
  CheckCircle,
  Loader,
  Layers,
  Search,
  ChevronDown,
  ChevronRight,
  FileText,
  FileCode,
  File,
  Atom,
  Zap,
  BarChart3,
} from 'lucide-react';

interface CrystalStatus {
  json: boolean;
  pdf: boolean;
  cif: boolean;
  txt: boolean;
}

interface Crystal {
  pmc_id: string;
  molecule_name?: string | null;
  is_piezoelectric?: boolean | null;
  is_ferroelectric?: boolean | null;
  status: CrystalStatus;
}

interface DatabaseStats {
  total_crystals: number;
  complete_crystals: number;
  incomplete_crystals: number;
  piezoelectric_count: number;
  ferroelectric_count: number;
  last_updated: string;
}

const DatabaseAdminPanel: FC = () => {
  const [stats, setStats] = useState<DatabaseStats | null>(null);
  const [crystals, setCrystals] = useState<Crystal[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [rebuildLoading, setRebuildLoading] = useState(false);
  const [rebuildProgress, setRebuildProgress] = useState('');
  const [rebuildSuccess, setRebuildSuccess] = useState(false);
  const [rebuildError, setRebuildError] = useState('');
  const [searchTerm, setSearchTerm] = useState('');
  const [expandedCrystal, setExpandedCrystal] = useState<string | null>(null);
  const [vectorLoading, setVectorLoading] = useState(false);
  const [vectorSuccess, setVectorSuccess] = useState('');
  const [vectorError, setVectorError] = useState('');

  const fetchDatabaseStatus = async () => {
    setIsLoading(true);
    try {
      const response = await fetch('http://localhost:5000/api/admin/database-status');
      const data = await response.json();
      setStats(data);
      const crystalsResponse = await fetch('http://localhost:5000/api/admin/crystals');
      const crystalsData = await crystalsResponse.json();
      setCrystals(crystalsData);
    } catch (error) {
      console.error('Error fetching database status:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleRebuildDatabase = async () => {
    setRebuildLoading(true);
    setRebuildProgress('Scanning crystal directories...');
    setRebuildSuccess(false);
    setRebuildError('');
    try {
      const response = await fetch('http://localhost:5000/api/admin/rebuild-database', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ full_scan: true }),
      });
      if (!response.ok) throw new Error(`Server error: ${response.status}`);
      const data = await response.json();
      setRebuildProgress(`Processing ${data.processed_count || 0} crystals...`);
      setTimeout(() => setRebuildProgress('Updating master database...'), 1000);
      setTimeout(() => setRebuildProgress('Verifying data integrity...'), 2000);
      setTimeout(() => {
        setRebuildProgress('');
        setRebuildSuccess(true);
        fetchDatabaseStatus();
        setTimeout(() => setRebuildSuccess(false), 5000);
      }, 3000);
    } catch (error) {
      setRebuildError(`Failed to rebuild database: ${error}`);
    } finally {
      setRebuildLoading(false);
    }
  };

  const handleRebuildVectorDB = async () => {
    setVectorLoading(true);
    setVectorSuccess('');
    setVectorError('');
    try {
      const response = await fetch('http://localhost:5000/api/admin/rebuild-vectordb', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      const data = await response.json();
      if (!response.ok || !data.success) throw new Error(data.error || `Server error: ${response.status}`);
      const skipped = data.skipped_count ? `, ${data.skipped_count} skipped` : '';
      setVectorSuccess(`Indexed ${data.total_in_db} molecules (${data.new} new, ${data.updated} updated)${skipped}.`);
      setTimeout(() => setVectorSuccess(''), 8000);
    } catch (error) {
      setVectorError(`Failed to rebuild vector database: ${error}`);
    } finally {
      setVectorLoading(false);
    }
  };

  const filteredCrystals = crystals.filter(
    (crystal) =>
      crystal.pmc_id.toLowerCase().includes(searchTerm.toLowerCase()) ||
      (crystal.molecule_name?.toLowerCase() || '').includes(searchTerm.toLowerCase())
  );

  const StatusDot = ({ ok }: { ok: boolean }) => (
    <span className={`w-1.5 h-1.5 rounded-full ${ok ? 'bg-emerald-500' : 'bg-red-500'}`} />
  );

  return (
    <div className="space-y-5">

      {/* Top Row - Two Action Cards */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">

        {/* Master Database Card */}
        <div className="rounded-2xl border border-white/[0.06] bg-[#0d1117] overflow-hidden">
          <div className="p-5 pb-4">
            <div className="flex items-center gap-3 mb-1">
              <div className="p-2 rounded-lg bg-cyan-500/10 border border-cyan-500/20">
                <Database className="w-4 h-4 text-cyan-400" />
              </div>
              <h3 className="text-sm font-semibold text-white">Master Database</h3>
            </div>
            <p className="text-xs text-gray-500 ml-[44px]">Scan and rebuild crystal data</p>
          </div>

          <div className="px-5 pb-5 space-y-3">
            <button
              onClick={handleRebuildDatabase}
              disabled={rebuildLoading}
              className="w-full flex items-center justify-center gap-2 bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 disabled:from-gray-700 disabled:to-gray-700 text-white text-sm font-semibold py-3 rounded-xl transition-all disabled:opacity-40 active:scale-[0.98]"
            >
              {rebuildLoading ? (
                <><Loader className="w-4 h-4 animate-spin" /> Rebuilding...</>
              ) : (
                <><RefreshCw className="w-4 h-4" /> Full Scan & Rebuild</>
              )}
            </button>

            {rebuildProgress && (
              <div className="flex items-center gap-2 px-3 py-2.5 rounded-lg bg-cyan-500/5 border border-cyan-500/20">
                <Loader className="w-3.5 h-3.5 animate-spin text-cyan-400" />
                <span className="text-xs text-cyan-300">{rebuildProgress}</span>
              </div>
            )}
            {rebuildSuccess && (
              <div className="flex items-center gap-2 px-3 py-2.5 rounded-lg bg-emerald-500/5 border border-emerald-500/20">
                <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />
                <span className="text-xs text-emerald-300">Database rebuilt successfully!</span>
              </div>
            )}
            {rebuildError && (
              <div className="flex items-center gap-2 px-3 py-2.5 rounded-lg bg-red-500/5 border border-red-500/20">
                <AlertCircle className="w-3.5 h-3.5 text-red-400" />
                <span className="text-xs text-red-300">{rebuildError}</span>
              </div>
            )}

            <details className="group">
              <summary className="text-[11px] text-gray-600 cursor-pointer hover:text-gray-400 transition-colors list-none flex items-center gap-1">
                <ChevronRight className="w-3 h-3 group-open:rotate-90 transition-transform" />
                What this does
              </summary>
              <ul className="mt-2 ml-4 space-y-1 text-[11px] text-gray-500">
                <li>• Scans all PMC folders for updated JSON files</li>
                <li>• Verifies CIF, PDF, and TXT file presence</li>
                <li>• Updates master_database.json with latest data</li>
                <li>• Validates crystal properties</li>
              </ul>
            </details>
          </div>
        </div>

        {/* Vector Database Card */}
        <div className="rounded-2xl border border-white/[0.06] bg-[#0d1117] overflow-hidden">
          <div className="p-5 pb-4">
            <div className="flex items-center gap-3 mb-1">
              <div className="p-2 rounded-lg bg-violet-500/10 border border-violet-500/20">
                <Layers className="w-4 h-4 text-violet-400" />
              </div>
              <h3 className="text-sm font-semibold text-white">Vector Database</h3>
            </div>
            <p className="text-xs text-gray-500 ml-[44px]">Rebuild AI search embeddings</p>
          </div>

          <div className="px-5 pb-5 space-y-3">
            <button
              onClick={handleRebuildVectorDB}
              disabled={vectorLoading}
              className="w-full flex items-center justify-center gap-2 bg-gradient-to-r from-violet-600 to-purple-600 hover:from-violet-500 hover:to-purple-500 disabled:from-gray-700 disabled:to-gray-700 text-white text-sm font-semibold py-3 rounded-xl transition-all disabled:opacity-40 active:scale-[0.98]"
            >
              {vectorLoading ? (
                <><Loader className="w-4 h-4 animate-spin" /> Building Embeddings...</>
              ) : (
                <><RefreshCw className="w-4 h-4" /> Rebuild Vector Database</>
              )}
            </button>

            {vectorSuccess && (
              <div className="flex items-center gap-2 px-3 py-2.5 rounded-lg bg-emerald-500/5 border border-emerald-500/20">
                <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />
                <span className="text-xs text-emerald-300">{vectorSuccess}</span>
              </div>
            )}
            {vectorError && (
              <div className="flex items-center gap-2 px-3 py-2.5 rounded-lg bg-red-500/5 border border-red-500/20">
                <AlertCircle className="w-3.5 h-3.5 text-red-400" />
                <span className="text-xs text-red-300">{vectorError}</span>
              </div>
            )}

            <details className="group">
              <summary className="text-[11px] text-gray-600 cursor-pointer hover:text-gray-400 transition-colors list-none flex items-center gap-1">
                <ChevronRight className="w-3 h-3 group-open:rotate-90 transition-transform" />
                What this does
              </summary>
              <ul className="mt-2 ml-4 space-y-1 text-[11px] text-gray-500">
                <li>• Converts each molecule's text to vector embedding</li>
                <li>• Updates Chroma vector store (no duplicates)</li>
                <li>• Skips empty placeholder folders</li>
                <li>• Run after adding/editing crystal data</li>
              </ul>
            </details>
          </div>
        </div>
      </div>

      {/* Stats Row */}
      {!stats && (
        <button
          onClick={fetchDatabaseStatus}
          disabled={isLoading}
          className="w-full flex items-center justify-center gap-2 py-3 rounded-xl border border-white/[0.06] bg-white/[0.02] hover:bg-white/[0.04] text-sm text-gray-400 hover:text-gray-300 transition-all"
        >
          {isLoading ? (
            <><Loader className="w-4 h-4 animate-spin" /> Loading...</>
          ) : (
            <><BarChart3 className="w-4 h-4" /> Load Database Status</>
          )}
        </button>
      )}

      {stats && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium uppercase tracking-wider text-gray-500">Statistics</h3>
            <button
              onClick={fetchDatabaseStatus}
              disabled={isLoading}
              className="text-[11px] text-gray-600 hover:text-gray-400 flex items-center gap-1 transition-colors"
            >
              <RefreshCw className={`w-3 h-3 ${isLoading ? 'animate-spin' : ''}`} /> Refresh
            </button>
          </div>

          <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
            {[
              { label: 'Total', value: stats.total_crystals, color: 'text-cyan-400', border: 'border-cyan-500/10' },
              { label: 'Complete', value: stats.complete_crystals, color: 'text-emerald-400', border: 'border-emerald-500/10' },
              { label: 'Incomplete', value: stats.incomplete_crystals, color: 'text-amber-400', border: 'border-amber-500/10' },
              { label: 'Piezoelectric', value: stats.piezoelectric_count, color: 'text-blue-400', border: 'border-blue-500/10' },
              { label: 'Ferroelectric', value: stats.ferroelectric_count, color: 'text-violet-400', border: 'border-violet-500/10' },
            ].map((s, i) => (
              <div key={i} className={`rounded-xl border ${s.border} bg-[#0d1117] p-4`}>
                <p className="text-[10px] font-medium uppercase tracking-wider text-gray-600 mb-1">{s.label}</p>
                <p className={`text-2xl font-bold ${s.color}`}>{s.value}</p>
              </div>
            ))}
          </div>

          {stats.last_updated && (
            <p className="text-[10px] text-gray-600 mt-2">
              Last updated: {new Date(stats.last_updated).toLocaleString()}
            </p>
          )}
        </div>
      )}

      {/* Crystal Inventory */}
      {crystals.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium uppercase tracking-wider text-gray-500">
              Crystal Inventory <span className="text-gray-600">({filteredCrystals.length})</span>
            </h3>
          </div>

          {/* Search */}
          <div className="relative mb-3">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-600" />
            <input
              type="text"
              placeholder="Search by PMC ID or molecule name..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full bg-white/[0.02] border border-white/[0.06] rounded-xl pl-10 pr-4 py-2.5 text-sm text-white placeholder-gray-600 outline-none focus:border-cyan-500/30 transition-colors"
            />
          </div>

          {/* Crystal List */}
          <div className="rounded-xl border border-white/[0.06] bg-[#0d1117] overflow-hidden max-h-[400px] overflow-y-auto">
            {filteredCrystals.map((crystal, idx) => (
              <div
                key={crystal.pmc_id}
                className={`cursor-pointer transition-colors hover:bg-white/[0.02] ${
                  idx !== filteredCrystals.length - 1 ? 'border-b border-white/[0.04]' : ''
                }`}
                onClick={() => setExpandedCrystal(expandedCrystal === crystal.pmc_id ? null : crystal.pmc_id)}
              >
                <div className="flex items-center justify-between px-4 py-3">
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-lg bg-cyan-500/10 border border-cyan-500/10 flex items-center justify-center flex-shrink-0">
                      <Atom className="w-3.5 h-3.5 text-cyan-400" />
                    </div>
                    <div>
                      <p className="text-sm font-semibold text-white">{crystal.pmc_id}</p>
                      <p className="text-[11px] text-gray-500">{crystal.molecule_name || 'Unknown'}</p>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    {Boolean(crystal.is_piezoelectric) && (
                      <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/20">
                        Piezo
                      </span>
                    )}
                    {Boolean(crystal.is_ferroelectric) && (
                      <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-violet-500/10 text-violet-400 border border-violet-500/20">
                        Ferro
                      </span>
                    )}
                    <ChevronDown className={`w-4 h-4 text-gray-600 transition-transform ${expandedCrystal === crystal.pmc_id ? 'rotate-180' : ''}`} />
                  </div>
                </div>

                {/* Expanded file status */}
                {expandedCrystal === crystal.pmc_id && (
                  <div className="px-4 pb-3 ml-11">
                    <div className="grid grid-cols-4 gap-2">
                      {[
                        { label: 'JSON', ok: crystal.status.json, icon: FileCode },
                        { label: 'PDF', ok: crystal.status.pdf, icon: FileText },
                        { label: 'CIF', ok: crystal.status.cif, icon: Atom },
                        { label: 'TXT', ok: crystal.status.txt, icon: File },
                      ].map((f) => (
                        <div key={f.label} className={`flex items-center gap-1.5 text-[11px] px-2 py-1.5 rounded-lg ${
                          f.ok ? 'bg-emerald-500/5 text-emerald-400' : 'bg-red-500/5 text-red-400'
                        }`}>
                          <StatusDot ok={f.ok} />
                          <f.icon className="w-3 h-3" />
                          {f.label}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ))}

            {filteredCrystals.length === 0 && (
              <p className="text-center text-sm text-gray-600 py-8">
                No crystals matching "{searchTerm}"
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default DatabaseAdminPanel;