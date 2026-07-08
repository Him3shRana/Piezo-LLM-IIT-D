import { useState, useEffect } from 'react';
import type { FC } from 'react';
import { FileText, ExternalLink, Search, Loader, BookOpen } from 'lucide-react';

interface LinkedMolecule {
  pmc_id: string;
  name: string;
}

interface Paper {
  title?: string | null;
  journal?: string | null;
  year?: number | string | null;
  authors?: string[];
  doi?: string | null;
  type: string;
  molecules: LinkedMolecule[];
}

const Papers: FC = () => {
  const [papers, setPapers] = useState<Paper[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [searchTerm, setSearchTerm] = useState('');

  const fetchPapers = async () => {
    setLoading(true);
    setError('');
    try {
      const res = await fetch('http://localhost:5000/api/papers');
      if (!res.ok) throw new Error(`Server error: ${res.status}`);
      const data = await res.json();
      setPapers(data.papers || []);
    } catch (e) {
      setError(`Failed to load papers: ${e}`);
    } finally {
      setLoading(false);
    }
  };

  // Load once when the page opens
  useEffect(() => {
    fetchPapers();
  }, []);

  const filtered = papers.filter((p) => {
    const q = searchTerm.toLowerCase();
    return (
      (p.title || '').toLowerCase().includes(q) ||
      (p.journal || '').toLowerCase().includes(q) ||
      (p.authors || []).join(' ').toLowerCase().includes(q) ||
      p.molecules.some(
        (m) =>
          m.pmc_id.toLowerCase().includes(q) ||
          m.name.toLowerCase().includes(q)
      )
    );
  });

  return (
    <div className="p-8 space-y-6">
      <div>
        <h1 className="text-4xl font-bold text-white mb-2 flex items-center gap-3">
          <BookOpen className="w-9 h-9 text-cyan-400" />
          Papers
        </h1>
        <p className="text-gray-400">
          Reference papers behind the crystal database — structure and property sources.
        </p>
      </div>

      {/* Search */}
      <input
        type="text"
        placeholder="Search by title, author, journal, or molecule..."
        value={searchTerm}
        onChange={(e) => setSearchTerm(e.target.value)}
        className="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-3 text-white placeholder-gray-500 focus:outline-none focus:border-cyan-500"
      />

      {/* Loading */}
      {loading && (
        <div className="flex items-center gap-3 text-gray-400">
          <Loader className="w-5 h-5 animate-spin" /> Loading papers...
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="bg-red-900/40 border border-red-500/50 rounded-lg p-4 text-red-300">
          {error}
        </div>
      )}

      {/* Count */}
      {!loading && !error && (
        <p className="text-gray-500 text-sm">
          {filtered.length} paper{filtered.length !== 1 ? 's' : ''}
          {searchTerm && ` matching "${searchTerm}"`}
        </p>
      )}

      {/* Papers list */}
      <div className="space-y-4">
        {filtered.map((paper, idx) => (
          <div
            key={idx}
            className="bg-gray-900 border border-gray-700 rounded-2xl p-6 hover:border-cyan-500/50 transition-colors"
          >
            <div className="flex items-start gap-3">
              <FileText className="w-6 h-6 text-cyan-400 mt-1 flex-shrink-0" />
              <div className="flex-1 min-w-0">
                {/* Type badge */}
                <span
                  className={`inline-block text-xs px-3 py-1 rounded-full mb-2 ${
                    paper.type.startsWith('Property')
                      ? 'bg-blue-600/30 text-blue-300'
                      : 'bg-purple-600/30 text-purple-300'
                  }`}
                >
                  {paper.type}
                </span>

                {/* Title */}
                <h3 className="text-lg font-semibold text-white mb-1">
                  {paper.title || 'Untitled reference'}
                </h3>

                {/* Authors */}
                {paper.authors && paper.authors.length > 0 && (
                  <p className="text-sm text-gray-400 mb-1">
                    {paper.authors.join(', ')}
                  </p>
                )}

                {/* Journal + year */}
                {(paper.journal || paper.year) && (
                  <p className="text-sm text-gray-500 italic mb-3">
                    {paper.journal}
                    {paper.journal && paper.year ? ', ' : ''}
                    {paper.year}
                  </p>
                )}

                {/* Linked molecules */}
                {paper.molecules.length > 0 && (
                  <div className="flex flex-wrap gap-2 mb-3">
                    {paper.molecules.map((m) => (
                      <span
                        key={m.pmc_id}
                        className="bg-gray-800 text-gray-300 text-xs px-3 py-1 rounded-full"
                      >
                        {m.pmc_id} · {m.name}
                      </span>
                    ))}
                  </div>
                )}

                {/* DOI link */}
                {paper.doi && (
                  <a
                    href={`https://doi.org/${paper.doi}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-2 text-cyan-400 hover:text-cyan-300 text-sm font-medium"
                  >
                    <ExternalLink className="w-4 h-4" />
                    View paper (DOI: {paper.doi})
                  </a>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Empty state */}
      {!loading && !error && filtered.length === 0 && (
        <div className="text-center py-12 text-gray-500">
          <Search className="w-10 h-10 mx-auto mb-3 opacity-50" />
          <p>No papers found{searchTerm && ` matching "${searchTerm}"`}.</p>
        </div>
      )}
    </div>
  );
};

export default Papers;