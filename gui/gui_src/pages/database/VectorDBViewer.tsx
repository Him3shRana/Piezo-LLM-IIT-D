import { useState, useEffect } from 'react';
import { Search, Database, ChevronDown, ChevronUp, Layers, FileText, X, BarChart3 } from 'lucide-react';

interface VectorDoc {
  pmc_id: string;
  molecule_name: string;
  crystal_system: string;
  space_group: string;
  is_piezoelectric: string;
  sources_used: string;
  has_txt: string;
  has_pdf: string;
  has_cif: string;
  char_count: number;
  preview: string;
}

interface DocDetail {
  pmc_id: string;
  metadata: Record<string, string>;
  full_text: string;
  char_count: number;
  embedding: number[];
  embedding_dimensions: number;
}

interface SearchResult {
  pmc_id: string;
  molecule_name: string;
  crystal_system: string;
  similarity: number;
  score: number;
  preview: string;
}

const BACKEND_URL = 'http://localhost:5000';

export default function VectorDBViewer() {
  const [documents, setDocuments] = useState<VectorDoc[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Search
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);

  // Detail modal
  const [selectedDoc, setSelectedDoc] = useState<DocDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [showEmbedding, setShowEmbedding] = useState(false);

  // Sort
  const [sortBy, setSortBy] = useState<'pmc_id' | 'char_count' | 'molecule_name'>('pmc_id');
  const [sortAsc, setSortAsc] = useState(true);

  useEffect(() => {
    fetchDocuments();
  }, []);

  const fetchDocuments = async () => {
    try {
      setLoading(true);
      const resp = await fetch(`${BACKEND_URL}/api/vectordb/browse`);
      const data = await resp.json();
      if (data.status === 'success') {
        setDocuments(data.documents);
        setTotal(data.total);
      } else {
        setError(data.message || 'Failed to load');
      }
    } catch (e) {
      setError('Cannot connect to backend. Is Flask running?');
    } finally {
      setLoading(false);
    }
  };

  const handleSearch = async () => {
    if (!searchQuery.trim()) return;
    try {
      setSearching(true);
      const resp = await fetch(`${BACKEND_URL}/api/vectordb/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: searchQuery, top_k: 10 }),
      });
      const data = await resp.json();
      if (data.status === 'success') {
        setSearchResults(data.results);
      }
    } catch {
      setError('Search failed');
    } finally {
      setSearching(false);
    }
  };

  const handleViewDetail = async (pmcId: string) => {
    try {
      setLoadingDetail(true);
      setShowEmbedding(false);
      const resp = await fetch(`${BACKEND_URL}/api/vectordb/document/${pmcId}`);
      const data = await resp.json();
      if (data.status === 'success') {
        setSelectedDoc(data);
      }
    } catch {
      setError('Failed to load document');
    } finally {
      setLoadingDetail(false);
    }
  };

  const sortedDocs = [...documents].sort((a, b) => {
    let cmp = 0;
    if (sortBy === 'pmc_id') cmp = a.pmc_id.localeCompare(b.pmc_id);
    else if (sortBy === 'char_count') cmp = a.char_count - b.char_count;
    else if (sortBy === 'molecule_name') cmp = a.molecule_name.localeCompare(b.molecule_name);
    return sortAsc ? cmp : -cmp;
  });

  const toggleSort = (field: typeof sortBy) => {
    if (sortBy === field) setSortAsc(!sortAsc);
    else { setSortBy(field); setSortAsc(true); }
  };

  const SortIcon = ({ field }: { field: typeof sortBy }) => {
    if (sortBy !== field) return null;
    return sortAsc ? <ChevronUp className="w-3 h-3 inline ml-1" /> : <ChevronDown className="w-3 h-3 inline ml-1" />;
  };

  const sourceIcons = (doc: VectorDoc) => {
    const sources = doc.sources_used.split(',');
    return (
      <div className="flex gap-1">
        {sources.includes('Summary') && <span className="px-1.5 py-0.5 text-[10px] rounded bg-blue-900/30 text-blue-400 border border-blue-500/20">JSON</span>}
        {sources.includes('Metadata') && <span className="px-1.5 py-0.5 text-[10px] rounded bg-green-900/30 text-green-400 border border-green-500/20">TXT</span>}
        {sources.includes('Paper') && <span className="px-1.5 py-0.5 text-[10px] rounded bg-amber-900/30 text-amber-400 border border-amber-500/20">PDF</span>}
        {sources.includes('Structure') && <span className="px-1.5 py-0.5 text-[10px] rounded bg-purple-900/30 text-purple-400 border border-purple-500/20">CIF</span>}
      </div>
    );
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-gray-400">Loading vector database...</div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-600 to-blue-700 flex items-center justify-center">
            <Database className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-white">Vector Database Viewer</h1>
            <p className="text-xs text-gray-400">
              {total} molecules · BAAI/bge-small-en-v1.5 · 384 dimensions
            </p>
          </div>
        </div>
      </div>

      {error && (
        <div className="bg-red-900/20 border border-red-500/30 rounded-xl p-4 mb-4 text-red-400 text-sm">
          {error}
          <button onClick={() => setError('')} className="ml-2 text-red-300 hover:text-white">✕</button>
        </div>
      )}

      {/* Semantic Search */}
      <div className="bg-gray-800/50 border border-gray-700/50 rounded-xl p-4 mb-6">
        <div className="flex gap-3">
          <div className="flex-1 relative">
            <Search className="absolute left-3 top-2.5 w-4 h-4 text-gray-500" />
            <input
              type="text"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSearch()}
              placeholder="Semantic search: 'hydrogen bonding', 'amino acid piezoelectric', 'monoclinic P21'..."
              className="w-full bg-gray-900/50 border border-gray-600/50 rounded-lg pl-10 pr-4 py-2 text-sm text-gray-200 placeholder-gray-500 outline-none focus:border-cyan-500/50"
            />
          </div>
          <button
            onClick={handleSearch}
            disabled={searching || !searchQuery.trim()}
            className="px-4 py-2 bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 disabled:from-gray-700 disabled:to-gray-700 rounded-lg text-sm text-white transition-all"
          >
            {searching ? 'Searching...' : 'Search'}
          </button>
          {searchResults.length > 0 && (
            <button
              onClick={() => { setSearchResults([]); setSearchQuery(''); }}
              className="px-3 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm text-gray-300"
            >
              Clear
            </button>
          )}
        </div>

        {/* Search Results */}
        {searchResults.length > 0 && (
          <div className="mt-4 space-y-2">
            <p className="text-xs text-gray-400 mb-2">
              Found {searchResults.length} results for "{searchQuery}"
            </p>
            {searchResults.map((r, i) => (
              <div
                key={r.pmc_id}
                onClick={() => handleViewDetail(r.pmc_id)}
                className="bg-gray-900/50 border border-gray-700/30 rounded-lg p-3 cursor-pointer hover:border-cyan-500/30 transition-colors"
              >
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-2">
                    <span className="text-cyan-400 font-mono text-sm">{r.pmc_id}</span>
                    <span className="text-white text-sm">{r.molecule_name}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-gray-500">{r.crystal_system}</span>
                    <span className={`px-2 py-0.5 rounded text-xs ${
                      r.similarity > 0.8 ? 'bg-green-900/30 text-green-400' :
                      r.similarity > 0.5 ? 'bg-amber-900/30 text-amber-400' :
                      'bg-gray-800 text-gray-400'
                    }`}>
                      {Math.round(r.similarity * 100)}% match
                    </span>
                  </div>
                </div>
                <p className="text-xs text-gray-500 line-clamp-2">{r.preview}</p>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Documents Table */}
      <div className="bg-gray-800/30 border border-gray-700/50 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-700/50 bg-gray-800/50">
              <th className="text-left p-3 text-gray-400 font-medium cursor-pointer hover:text-white" onClick={() => toggleSort('pmc_id')}>
                PMC ID <SortIcon field="pmc_id" />
              </th>
              <th className="text-left p-3 text-gray-400 font-medium cursor-pointer hover:text-white" onClick={() => toggleSort('molecule_name')}>
                Molecule <SortIcon field="molecule_name" />
              </th>
              <th className="text-left p-3 text-gray-400 font-medium">System</th>
              <th className="text-left p-3 text-gray-400 font-medium">Space Group</th>
              <th className="text-left p-3 text-gray-400 font-medium">Sources</th>
              <th className="text-left p-3 text-gray-400 font-medium cursor-pointer hover:text-white" onClick={() => toggleSort('char_count')}>
                Chars <SortIcon field="char_count" />
              </th>
              <th className="text-left p-3 text-gray-400 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {sortedDocs.map((doc, i) => (
              <tr
                key={doc.pmc_id}
                className={`border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors ${
                  i % 2 === 0 ? '' : 'bg-gray-800/10'
                }`}
              >
                <td className="p-3 font-mono text-cyan-400">{doc.pmc_id}</td>
                <td className="p-3 text-white">{doc.molecule_name}</td>
                <td className="p-3 text-gray-300">{doc.crystal_system}</td>
                <td className="p-3 text-gray-300 font-mono text-xs">{doc.space_group}</td>
                <td className="p-3">{sourceIcons(doc)}</td>
                <td className="p-3 text-gray-400">
                  <div className="flex items-center gap-2">
                    <div className="w-16 h-1.5 bg-gray-700 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-cyan-500/60 rounded-full"
                        style={{ width: `${Math.min(100, (doc.char_count / 15000) * 100)}%` }}
                      />
                    </div>
                    <span className="text-xs">{doc.char_count.toLocaleString()}</span>
                  </div>
                </td>
                <td className="p-3">
                  <button
                    onClick={() => handleViewDetail(doc.pmc_id)}
                    className="px-2 py-1 text-xs bg-gray-700 hover:bg-gray-600 text-gray-300 rounded transition-colors"
                  >
                    View
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Detail Modal */}
      {selectedDoc && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-900 border border-gray-700 rounded-2xl max-w-4xl w-full max-h-[90vh] overflow-hidden flex flex-col">
            {/* Modal Header */}
            <div className="flex items-center justify-between p-4 border-b border-gray-700/50">
              <div>
                <h2 className="text-lg font-bold text-white">
                  <span className="text-cyan-400 font-mono">{selectedDoc.pmc_id}</span>
                  {' '}{selectedDoc.metadata.molecule_name}
                </h2>
                <p className="text-xs text-gray-400 mt-1">
                  {selectedDoc.char_count.toLocaleString()} chars ·
                  {selectedDoc.embedding_dimensions} dimensions ·
                  Sources: {selectedDoc.metadata.sources_used}
                </p>
              </div>
              <button
                onClick={() => setSelectedDoc(null)}
                className="p-2 hover:bg-gray-800 rounded-lg transition-colors"
              >
                <X className="w-5 h-5 text-gray-400" />
              </button>
            </div>

            {/* Tabs */}
            <div className="flex border-b border-gray-700/50">
              <button
                onClick={() => setShowEmbedding(false)}
                className={`flex items-center gap-2 px-4 py-2 text-sm transition-colors ${
                  !showEmbedding
                    ? 'text-cyan-400 border-b-2 border-cyan-400'
                    : 'text-gray-400 hover:text-white'
                }`}
              >
                <FileText className="w-4 h-4" />
                Embedded Text
              </button>
              <button
                onClick={() => setShowEmbedding(true)}
                className={`flex items-center gap-2 px-4 py-2 text-sm transition-colors ${
                  showEmbedding
                    ? 'text-cyan-400 border-b-2 border-cyan-400'
                    : 'text-gray-400 hover:text-white'
                }`}
              >
                <BarChart3 className="w-4 h-4" />
                Embedding Vector (384 values)
              </button>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto p-4">
              {!showEmbedding ? (
                <pre className="text-sm text-gray-300 whitespace-pre-wrap font-mono leading-relaxed">
                  {selectedDoc.full_text}
                </pre>
              ) : (
                <div>
                  {/* Vector visualization bar chart */}
                  <div className="mb-4">
                    <p className="text-xs text-gray-400 mb-2">
                      384-dimensional embedding vector — each bar represents one dimension.
                      Positive (cyan) and negative (coral) values.
                    </p>
                    <div className="flex items-end gap-[1px] h-32 bg-gray-800/50 rounded-lg p-2 overflow-hidden">
                      {selectedDoc.embedding.map((v, i) => {
                        const height = Math.abs(v) * 200;
                        return (
                          <div
                            key={i}
                            className="flex-1 min-w-[1px]"
                            style={{
                              height: `${Math.min(100, height)}%`,
                              backgroundColor: v >= 0 ? 'rgba(6,182,212,0.6)' : 'rgba(248,113,113,0.6)',
                              alignSelf: 'flex-end',
                            }}
                            title={`Dim ${i + 1}: ${v.toFixed(6)}`}
                          />
                        );
                      })}
                    </div>
                    <div className="flex justify-between text-[10px] text-gray-500 mt-1">
                      <span>Dim 1</span>
                      <span>Dim 192</span>
                      <span>Dim 384</span>
                    </div>
                  </div>

                  {/* Raw values */}
                  <div className="grid grid-cols-4 gap-1 text-xs font-mono">
                    {selectedDoc.embedding.map((v, i) => (
                      <div
                        key={i}
                        className={`p-1 rounded text-center ${
                          v >= 0
                            ? 'bg-cyan-900/20 text-cyan-400'
                            : 'bg-red-900/20 text-red-400'
                        }`}
                      >
                        <span className="text-gray-500">{i + 1}:</span> {v.toFixed(4)}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}