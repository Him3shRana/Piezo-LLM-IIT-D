import { useState } from 'react';
import type { FC } from 'react';
import { RefreshCw, Database, AlertCircle, CheckCircle, Loader } from 'lucide-react';

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

  // Fetch database status
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

  // Rebuild Master Database
  const handleRebuildDatabase = async () => {
    setRebuildLoading(true);
    setRebuildProgress('Starting database rebuild...');
    setRebuildSuccess(false);
    setRebuildError('');

    try {
      setRebuildProgress('Scanning crystal directories...');
      
      const response = await fetch('http://localhost:5000/api/admin/rebuild-database', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          full_scan: true,
        }),
      });

      if (!response.ok) {
        throw new Error(`Server error: ${response.status}`);
      }

      const data = await response.json();

      setRebuildProgress(`Processing ${data.processed_count || 0} crystals...`);
      
      setTimeout(() => {
        setRebuildProgress('Updating master database...');
      }, 1000);

      setTimeout(() => {
        setRebuildProgress('Verifying data integrity...');
      }, 2000);

      setTimeout(() => {
        setRebuildProgress('');
        setRebuildSuccess(true);
        fetchDatabaseStatus();
        
        setTimeout(() => {
          setRebuildSuccess(false);
        }, 5000);
      }, 3000);
    } catch (error) {
      setRebuildError(`Failed to rebuild database: ${error}`);
      console.error('Rebuild error:', error);
    } finally {
      setRebuildLoading(false);
    }
  };

  // Filter crystals based on search term
  const filteredCrystals = crystals.filter(
    (crystal) =>
      crystal.pmc_id.toLowerCase().includes(searchTerm.toLowerCase()) ||
      (crystal.molecule_name?.toLowerCase() || '').includes(searchTerm.toLowerCase())
  );

  return (
    <div className="space-y-6">
      {/* Rebuild Database Section */}
      <div className="bg-gradient-to-r from-blue-900/30 to-cyan-900/30 border border-cyan-500/30 rounded-2xl p-8">
        <div className="flex items-start justify-between mb-4">
          <div>
            <h2 className="text-2xl font-bold text-white mb-2 flex items-center gap-2">
              <Database className="w-6 h-6 text-cyan-400" />
              Master Database Tools
            </h2>
            <p className="text-gray-400">
              Rebuild and update the master database with latest crystal data
            </p>
          </div>
        </div>

        {/* Rebuild Button and Progress */}
        <div className="space-y-4">
          <button
            onClick={handleRebuildDatabase}
            disabled={rebuildLoading}
            className="w-full flex items-center justify-center gap-3 bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 disabled:from-gray-600 disabled:to-gray-600 text-white font-bold py-4 px-6 rounded-lg transition-all disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {rebuildLoading ? (
              <>
                <Loader className="w-5 h-5 animate-spin" />
                Rebuilding Database...
              </>
            ) : (
              <>
                <RefreshCw className="w-5 h-5" />
                Full Scan & Rebuild Master Database
              </>
            )}
          </button>

          {/* Progress Message */}
          {rebuildProgress && (
            <div className="bg-blue-900/40 border border-blue-500/50 rounded-lg p-4 text-blue-300 flex items-center gap-3">
              <Loader className="w-5 h-5 animate-spin" />
              {rebuildProgress}
            </div>
          )}

          {/* Success Message */}
          {rebuildSuccess && (
            <div className="bg-green-900/40 border border-green-500/50 rounded-lg p-4 text-green-300 flex items-center gap-3">
              <CheckCircle className="w-5 h-5" />
              ✅ Database rebuilt successfully! All crystals updated.
            </div>
          )}

          {/* Error Message */}
          {rebuildError && (
            <div className="bg-red-900/40 border border-red-500/50 rounded-lg p-4 text-red-300 flex items-center gap-3">
              <AlertCircle className="w-5 h-5" />
              {rebuildError}
            </div>
          )}

          {/* Info Box */}
          <div className="bg-gray-900/50 border border-gray-700 rounded-lg p-4 text-sm text-gray-300">
            <p className="mb-2">
              <strong>What this does:</strong>
            </p>
            <ul className="list-disc list-inside space-y-1 text-gray-400">
              <li>Scans all PMC folders for updated JSON files</li>
              <li>Verifies CIF, PDF, and TXT file presence</li>
              <li>Updates master_database.json with latest data</li>
              <li>Validates crystal properties (piezoelectric, ferroelectric, etc.)</li>
              <li>Updates timestamp for all processed entries</li>
            </ul>
          </div>
        </div>
      </div>

      {/* Database Statistics */}
      {stats && (
        <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
          <div className="bg-gray-900 border border-gray-700 rounded-lg p-4">
            <p className="text-gray-400 text-sm mb-1">Total Crystals</p>
            <p className="text-3xl font-bold text-cyan-400">{stats.total_crystals}</p>
          </div>
          <div className="bg-gray-900 border border-gray-700 rounded-lg p-4">
            <p className="text-gray-400 text-sm mb-1">Complete</p>
            <p className="text-3xl font-bold text-green-400">{stats.complete_crystals}</p>
          </div>
          <div className="bg-gray-900 border border-gray-700 rounded-lg p-4">
            <p className="text-gray-400 text-sm mb-1">Incomplete</p>
            <p className="text-3xl font-bold text-yellow-400">{stats.incomplete_crystals}</p>
          </div>
          <div className="bg-gray-900 border border-gray-700 rounded-lg p-4">
            <p className="text-gray-400 text-sm mb-1">Piezoelectric</p>
            <p className="text-3xl font-bold text-blue-400">{stats.piezoelectric_count}</p>
          </div>
          <div className="bg-gray-900 border border-gray-700 rounded-lg p-4">
            <p className="text-gray-400 text-sm mb-1">Ferroelectric</p>
            <p className="text-3xl font-bold text-purple-400">{stats.ferroelectric_count}</p>
          </div>
        </div>
      )}

      {/* Fetch Status Button */}
      <button
        onClick={fetchDatabaseStatus}
        disabled={isLoading}
        className="w-full bg-gray-700 hover:bg-gray-600 disabled:bg-gray-800 text-white font-semibold py-2 px-4 rounded-lg transition-colors flex items-center justify-center gap-2"
      >
        {isLoading ? (
          <>
            <Loader className="w-4 h-4 animate-spin" />
            Loading Status...
          </>
        ) : (
          <>
            <RefreshCw className="w-4 h-4" />
            Refresh Status
          </>
        )}
      </button>

      {/* Crystals List */}
      {crystals.length > 0 && (
        <div className="space-y-4">
          <h3 className="text-xl font-bold text-white">Crystal Inventory</h3>

          {/* Search */}
          <input
            type="text"
            placeholder="Search by PMC ID or molecule name..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-2 text-white placeholder-gray-500 focus:outline-none focus:border-cyan-500"
          />

          {/* Crystals Table */}
          <div className="space-y-2 max-h-96 overflow-y-auto">
            {filteredCrystals.map((crystal) => (
              <div
                key={crystal.pmc_id}
                className="bg-gray-900 border border-gray-700 rounded-lg p-4 cursor-pointer hover:bg-gray-800 transition-colors"
                onClick={() =>
                  setExpandedCrystal(
                    expandedCrystal === crystal.pmc_id ? null : crystal.pmc_id
                  )
                }
              >
                <div className="flex items-center justify-between">
                  <div>
                    <p className="font-semibold text-cyan-400">{crystal.pmc_id}</p>
                    <p className="text-sm text-gray-400">
                      {crystal.molecule_name || 'Unknown molecule'}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    {Boolean(crystal.is_piezoelectric) && (
                      <span className="bg-blue-600/30 text-blue-300 text-xs px-3 py-1 rounded-full">
                        Piezoelectric
                      </span>
                    )}
                    {Boolean(crystal.is_ferroelectric) && (
                      <span className="bg-purple-600/30 text-purple-300 text-xs px-3 py-1 rounded-full">
                        Ferroelectric
                      </span>
                    )}
                  </div>
                </div>

                {/* Expanded Details */}
                {expandedCrystal === crystal.pmc_id && (
                  <div className="mt-4 pt-4 border-t border-gray-700 space-y-2">
                    <div className="grid grid-cols-2 gap-2 text-sm">
                      <div className="flex items-center gap-2">
                        <span
                          className={`w-2 h-2 rounded-full ${
                            crystal.status.json ? 'bg-green-500' : 'bg-red-500'
                          }`}
                        ></span>
                        <span className="text-gray-300">
                          JSON: {crystal.status.json ? '✓' : '✗'}
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span
                          className={`w-2 h-2 rounded-full ${
                            crystal.status.pdf ? 'bg-green-500' : 'bg-red-500'
                          }`}
                        ></span>
                        <span className="text-gray-300">
                          PDF: {crystal.status.pdf ? '✓' : '✗'}
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span
                          className={`w-2 h-2 rounded-full ${
                            crystal.status.cif ? 'bg-green-500' : 'bg-red-500'
                          }`}
                        ></span>
                        <span className="text-gray-300">
                          CIF: {crystal.status.cif ? '✓' : '✗'}
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span
                          className={`w-2 h-2 rounded-full ${
                            crystal.status.txt ? 'bg-green-500' : 'bg-red-500'
                          }`}
                        ></span>
                        <span className="text-gray-300">
                          TXT: {crystal.status.txt ? '✓' : '✗'}
                        </span>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>

          {filteredCrystals.length === 0 && (
            <p className="text-gray-400 text-center py-4">
              No crystals found matching "{searchTerm}"
            </p>
          )}
        </div>
      )}
    </div>
  );
};

export default DatabaseAdminPanel;
