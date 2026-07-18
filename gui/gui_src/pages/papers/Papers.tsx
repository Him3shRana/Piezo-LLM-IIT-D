import { useState, useEffect, useMemo } from 'react';
import type { FC } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ExternalLink,
  Search,
  Loader,
  BookOpen,
  X,
  Atom,
  FlaskConical,
  Hexagon,
  ArrowUpDown,
  AlertCircle,
  RefreshCw,
} from 'lucide-react';

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

type SortKey = 'newest' | 'oldest' | 'title';

// Property vs Structure references get distinct accents so the list
// can be scanned by reference type without reading the badge text.
function typeTheme(type: string) {
  if (type.startsWith('Property')) {
    return {
      border: 'border-l-blue-500',
      badge: 'bg-blue-500/10 text-blue-400 border-blue-500/25',
      icon: 'text-blue-400',
      iconBg: 'bg-blue-500/10 border-blue-500/20',
      Icon: FlaskConical,
    };
  }
  return {
    border: 'border-l-violet-500',
    badge: 'bg-violet-500/10 text-violet-400 border-violet-500/25',
    icon: 'text-violet-400',
    iconBg: 'bg-violet-500/10 border-violet-500/20',
    Icon: Hexagon,
  };
}

const Papers: FC = () => {
  const navigate = useNavigate();
  const [papers, setPapers] = useState<Paper[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [searchTerm, setSearchTerm] = useState('');
  const [typeFilter, setTypeFilter] = useState<string>('All');
  const [sortKey, setSortKey] = useState<SortKey>('newest');

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

  useEffect(() => { fetchPapers(); }, []);

  // Distinct reference types present in the data
  const types = useMemo(() => {
    const set = new Set(papers.map(p => p.type).filter(Boolean));
    return ['All', ...Array.from(set).sort()];
  }, [papers]);

  const untitledCount = useMemo(
    () => papers.filter(p => !p.title).length,
    [papers],
  );

  const filtered = useMemo(() => {
    const q = searchTerm.toLowerCase();
    const out = papers.filter((p) => {
      if (typeFilter !== 'All' && p.type !== typeFilter) return false;
      if (!q) return true;
      return (
        (p.title || '').toLowerCase().includes(q) ||
        (p.journal || '').toLowerCase().includes(q) ||
        (p.doi || '').toLowerCase().includes(q) ||
        (p.authors || []).join(' ').toLowerCase().includes(q) ||
        p.molecules.some(
          (m) =>
            m.pmc_id.toLowerCase().includes(q) ||
            m.name.toLowerCase().includes(q),
        )
      );
    });

    const yearOf = (p: Paper) => {
      const n = parseInt(String(p.year ?? ''), 10);
      return isNaN(n) ? 0 : n;
    };

    return [...out].sort((a, b) => {
      if (sortKey === 'newest') return yearOf(b) - yearOf(a);
      if (sortKey === 'oldest') return yearOf(a) - yearOf(b);
      return (a.title || 'zzz').localeCompare(b.title || 'zzz');
    });
  }, [papers, searchTerm, typeFilter, sortKey]);

  const hasFilters = searchTerm !== '' || typeFilter !== 'All';

  return (
    <div className="p-6 lg:p-10 max-w-[1200px] mx-auto space-y-5">

      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <div className="w-10 h-10 rounded-xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center">
              <BookOpen className="w-5 h-5 text-amber-400" />
            </div>
            <h1 className="text-2xl font-bold text-white tracking-tight">Papers</h1>
          </div>
          <p className="text-sm text-gray-500 ml-[52px]">
            Reference papers behind the crystal database — structure and property sources
          </p>
        </div>

        <button
          onClick={fetchPapers}
          disabled={loading}
          className="flex items-center gap-2 px-3 py-2 rounded-lg border border-white/[0.06] bg-white/[0.02] hover:bg-white/[0.05] text-xs text-gray-400 hover:text-gray-200 transition-all disabled:opacity-40"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* Search + filters */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-600" />
          <input
            type="text"
            placeholder="Search by title, author, journal, DOI, or molecule..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full bg-white/[0.02] border border-white/[0.06] rounded-xl pl-10 pr-10 py-3 text-sm text-white placeholder-gray-600 outline-none focus:border-amber-500/30 transition-colors"
          />
          {searchTerm && (
            <button
              onClick={() => setSearchTerm('')}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-600 hover:text-gray-400 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>

        <div className="relative">
          <ArrowUpDown className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-600 pointer-events-none" />
          <select
            value={sortKey}
            onChange={(e) => setSortKey(e.target.value as SortKey)}
            className="appearance-none bg-white/[0.02] border border-white/[0.06] rounded-xl pl-10 pr-8 py-3 text-sm text-gray-300 outline-none focus:border-amber-500/30 transition-colors cursor-pointer min-w-[150px]"
          >
            <option value="newest" className="bg-[#0d1117]">Newest first</option>
            <option value="oldest" className="bg-[#0d1117]">Oldest first</option>
            <option value="title" className="bg-[#0d1117]">Title A–Z</option>
          </select>
        </div>
      </div>

      {/* Type pills */}
      {types.length > 2 && (
        <div className="flex flex-wrap gap-2">
          {types.map((t) => {
            const active = typeFilter === t;
            const count = t === 'All' ? papers.length : papers.filter(p => p.type === t).length;
            return (
              <button
                key={t}
                onClick={() => setTypeFilter(t)}
                className={`text-xs font-medium px-3 py-1.5 rounded-full border transition-all ${
                  active
                    ? 'bg-amber-500/10 text-amber-400 border-amber-500/25'
                    : 'bg-white/[0.02] text-gray-500 border-white/[0.06] hover:text-gray-300 hover:border-white/[0.12]'
                }`}
              >
                {t}
                <span className={`ml-1.5 ${active ? 'text-amber-500/60' : 'text-gray-600'}`}>{count}</span>
              </button>
            );
          })}
        </div>
      )}

      {/* Status row */}
      {loading && (
        <div className="flex items-center gap-2 text-sm text-gray-500">
          <Loader className="w-4 h-4 animate-spin" /> Loading papers...
        </div>
      )}

      {error && (
        <div className="flex items-center gap-2 px-4 py-3 rounded-xl bg-red-500/5 border border-red-500/20">
          <AlertCircle className="w-4 h-4 text-red-400 flex-shrink-0" />
          <p className="text-sm text-red-300">{error}</p>
        </div>
      )}

      {!loading && !error && (
        <div className="flex items-center justify-between">
          <p className="text-xs text-gray-500">
            {filtered.length} paper{filtered.length !== 1 ? 's' : ''}
            {typeFilter !== 'All' && <span className="text-amber-500"> · {typeFilter}</span>}
            {searchTerm && <span className="text-amber-500"> · "{searchTerm}"</span>}
            {untitledCount > 0 && typeFilter === 'All' && !searchTerm && (
              <span className="text-gray-600"> · {untitledCount} missing title</span>
            )}
          </p>
          {hasFilters && (
            <button
              onClick={() => { setSearchTerm(''); setTypeFilter('All'); }}
              className="text-xs text-gray-600 hover:text-gray-400 transition-colors"
            >
              Clear filters
            </button>
          )}
        </div>
      )}

      {/* Papers list */}
      <div className="space-y-2.5">
        {filtered.map((paper, idx) => {
          const theme = typeTheme(paper.type);
          const Icon = theme.Icon;
          const missingTitle = !paper.title;

          return (
            <div
              key={idx}
              className={`
                group rounded-xl border border-white/[0.06] border-l-[3px] ${theme.border}
                bg-[#0d1117] px-5 py-4
                hover:border-white/[0.12] hover:bg-white/[0.015] transition-all
              `}
            >
              <div className="flex items-start gap-3.5">
                <div className={`w-8 h-8 rounded-lg border flex items-center justify-center flex-shrink-0 mt-0.5 ${theme.iconBg}`}>
                  <Icon className={`w-4 h-4 ${theme.icon}`} />
                </div>

                <div className="flex-1 min-w-0">
                  {/* Title + type badge on one line */}
                  <div className="flex items-start justify-between gap-4 mb-1">
                    <h3 className={`text-[15px] font-semibold leading-snug ${
                      missingTitle ? 'text-gray-600 italic' : 'text-white'
                    }`}>
                      {paper.title || 'Title not recorded'}
                    </h3>
                    <span className={`flex-shrink-0 text-[9px] font-bold uppercase tracking-[0.1em] px-2 py-0.5 rounded border ${theme.badge}`}>
                      {paper.type.replace(/^(Property|Structure)\s*/, '').replace(/[()]/g, '') || paper.type}
                    </span>
                  </div>

                  {/* Authors · journal · year on one line */}
                  <p className="text-xs text-gray-500 mb-2.5 truncate">
                    {paper.authors && paper.authors.length > 0 && (
                      <span>{paper.authors.slice(0, 3).join(', ')}
                        {paper.authors.length > 3 && ` +${paper.authors.length - 3}`}
                      </span>
                    )}
                    {paper.authors?.length && (paper.journal || paper.year) ? ' · ' : ''}
                    {paper.journal && <span className="italic">{paper.journal}</span>}
                    {paper.journal && paper.year ? ', ' : ''}
                    {paper.year}
                  </p>

                  {/* Molecules + DOI on one row */}
                  <div className="flex items-center justify-between gap-4 flex-wrap">
                    <div className="flex flex-wrap gap-1.5">
                      {paper.molecules.map((m) => (
                        <button
                          key={m.pmc_id}
                          onClick={() => navigate(`/crystal/${m.pmc_id}`)}
                          title={`Open ${m.pmc_id}`}
                          className="inline-flex items-center gap-1.5 text-[10px] font-medium px-2 py-1 rounded-full bg-cyan-500/[0.07] text-cyan-400/80 border border-cyan-500/15 hover:bg-cyan-500/15 hover:text-cyan-300 transition-all"
                        >
                          <Atom className="w-2.5 h-2.5" />
                          {m.pmc_id} · {m.name}
                        </button>
                      ))}
                    </div>

                    {paper.doi && (
                      <a
                        href={`https://doi.org/${paper.doi}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        title={paper.doi}
                        className="inline-flex items-center gap-1.5 text-[11px] text-gray-600 hover:text-amber-400 transition-colors flex-shrink-0"
                      >
                        <ExternalLink className="w-3 h-3" />
                        DOI
                      </a>
                    )}
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Empty state */}
      {!loading && !error && filtered.length === 0 && (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <div className="w-14 h-14 rounded-2xl bg-gray-500/5 border border-white/[0.06] flex items-center justify-center mb-4">
            <BookOpen className="w-7 h-7 text-gray-600" />
          </div>
          <p className="text-sm text-gray-500 mb-1">No papers found</p>
          <p className="text-xs text-gray-600">
            {hasFilters ? 'Try adjusting your search or filters' : 'The database has no reference papers yet'}
          </p>
        </div>
      )}
    </div>
  );
};

export default Papers;