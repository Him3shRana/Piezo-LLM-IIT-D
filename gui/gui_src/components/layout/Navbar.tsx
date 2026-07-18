import { useLocation, useNavigate } from "react-router-dom";
import { useState, useEffect, useRef, useMemo, useCallback } from "react";
import {
  Search,
  Bell,
  ArrowLeft,
  Atom,
  BookOpen,
  X,
  CornerDownLeft,
  CheckCircle,
  AlertTriangle,
  XCircle,
  RefreshCw,
  Zap,
  ZapOff,
} from "lucide-react";

const BACKEND = "http://localhost:5000";

const pageTitles: Record<string, string> = {
  "/": "Dashboard",
  "/chat": "AI Chat",
  "/crystals": "Crystal Explorer",
  "/papers": "Research Papers",
  "/database": "Database",
  "/settings": "Settings",
};

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
interface CrystalLite {
  pmc_id: string;
  molecule_name: string;
  chemical_formula?: string;
  crystal_system?: string;
  is_piezoelectric?: boolean;
}

interface PaperLite {
  title?: string | null;
  journal?: string | null;
  year?: number | string | null;
  doi?: string | null;
}

type Result =
  | { kind: "crystal"; id: string; title: string; sub: string; piezo: boolean }
  | { kind: "paper"; id: string; title: string; sub: string; doi?: string | null };

type Level = "ok" | "warn" | "error";
interface HealthItem {
  label: string;
  level: Level;
  detail: string;
}

// ---------------------------------------------------------------------------
function Navbar() {
  const location = useLocation();
  const navigate = useNavigate();

  // ---- search ----
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [crystals, setCrystals] = useState<CrystalLite[]>([]);
  const [papers, setPapers] = useState<PaperLite[]>([]);
  const [activeIdx, setActiveIdx] = useState(0);
  const searchRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // ---- notifications ----
  const [bellOpen, setBellOpen] = useState(false);
  const [health, setHealth] = useState<HealthItem[]>([]);
  const [checking, setChecking] = useState(false);
  const bellRef = useRef<HTMLDivElement>(null);

  const canGoBack = location.pathname !== "/";

  const getTitle = () => {
    if (location.pathname.startsWith("/crystal/")) {
      return location.pathname.split("/").pop()?.toUpperCase() || "Crystal Details";
    }
    return pageTitles[location.pathname] || "Piezo-LLM";
  };

  // -------------------------------------------------------------------------
  // Load searchable data once
  // -------------------------------------------------------------------------
  useEffect(() => {
    fetch("/database/master_database.json")
      .then((r) => r.json())
      .then((d) => setCrystals(Object.values(d.crystals || {}) as CrystalLite[]))
      .catch(() => setCrystals([]));

    fetch(`${BACKEND}/api/papers`)
      .then((r) => (r.ok ? r.json() : { papers: [] }))
      .then((d) => setPapers(d.papers || []))
      .catch(() => setPapers([]));
  }, []);

  // -------------------------------------------------------------------------
  // System health — real checks, not placeholder notifications
  // -------------------------------------------------------------------------
  const runHealthChecks = useCallback(async () => {
    setChecking(true);
    const items: HealthItem[] = [];

    // Backend reachability + LLM status in one call
    try {
      const r = await fetch(`${BACKEND}/api/llm-status`);
      if (r.ok) {
        const d = await r.json();
        items.push({ label: "Backend", level: "ok", detail: "Flask reachable" });
        items.push(
          d.installed
            ? { label: "LLM", level: "ok", detail: "Qwen3-8B loaded" }
            : { label: "LLM", level: "warn", detail: "Not installed — AI Chat unavailable" },
        );
      } else {
        items.push({ label: "Backend", level: "error", detail: `Responded ${r.status}` });
      }
    } catch {
      items.push({
        label: "Backend",
        level: "error",
        detail: `Not reachable at ${BACKEND}`,
      });
    }

    // Crystal database
    if (crystals.length) {
      items.push({
        label: "Crystal database",
        level: "ok",
        detail: `${crystals.length} entries loaded`,
      });
      const unnamed = crystals.filter((c) => !c.molecule_name).length;
      if (unnamed > 0) {
        items.push({
          label: "Data quality",
          level: "warn",
          detail: `${unnamed} crystal${unnamed > 1 ? "s" : ""} missing a name`,
        });
      }
    } else {
      items.push({
        label: "Crystal database",
        level: "error",
        detail: "master_database.json failed to load",
      });
    }

    // Papers
    if (papers.length) {
      const untitled = papers.filter((p) => !p.title).length;
      items.push(
        untitled > 0
          ? { label: "Papers", level: "warn", detail: `${untitled} of ${papers.length} missing a title` }
          : { label: "Papers", level: "ok", detail: `${papers.length} references` },
      );
    }

    setHealth(items);
    setChecking(false);
  }, [crystals, papers]);

  // Re-run whenever the underlying data changes
  useEffect(() => { runHealthChecks(); }, [runHealthChecks]);

  const issueCount = health.filter((h) => h.level !== "ok").length;
  const worst: Level = health.some((h) => h.level === "error")
    ? "error"
    : issueCount > 0
    ? "warn"
    : "ok";

  // -------------------------------------------------------------------------
  // Search results
  // -------------------------------------------------------------------------
  const results = useMemo<Result[]>(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];

    const c: Result[] = crystals
      .filter(
        (x) =>
          (x.pmc_id || "").toLowerCase().includes(q) ||
          (x.molecule_name || "").toLowerCase().includes(q) ||
          (x.chemical_formula || "").toLowerCase().includes(q),
      )
      .slice(0, 6)
      .map((x) => ({
        kind: "crystal" as const,
        id: x.pmc_id,
        title: x.molecule_name || x.pmc_id,
        sub: [x.pmc_id, x.chemical_formula, x.crystal_system].filter(Boolean).join(" · "),
        piezo: !!x.is_piezoelectric,
      }));

    const p: Result[] = papers
      .filter(
        (x) =>
          (x.title || "").toLowerCase().includes(q) ||
          (x.journal || "").toLowerCase().includes(q) ||
          (x.doi || "").toLowerCase().includes(q),
      )
      .slice(0, 4)
      .map((x, i) => ({
        kind: "paper" as const,
        id: x.doi || String(i),
        title: x.title || "Title not recorded",
        sub: [x.journal, x.year].filter(Boolean).join(", "),
        doi: x.doi,
      }));

    return [...c, ...p];
  }, [query, crystals, papers]);

  useEffect(() => { setActiveIdx(0); }, [query]);

  const openResult = (r: Result) => {
    if (r.kind === "crystal") navigate(`/crystal/${r.id}`);
    else if (r.doi) window.open(`https://doi.org/${r.doi}`, "_blank", "noopener");
    else navigate("/papers");
    closeSearch();
  };

  const closeSearch = () => {
    setSearchOpen(false);
    setQuery("");
    setActiveIdx(0);
  };

  // -------------------------------------------------------------------------
  // Keyboard: Ctrl/Cmd+K opens search, Esc closes panels
  // -------------------------------------------------------------------------
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setSearchOpen(true);
        setBellOpen(false);
        setTimeout(() => inputRef.current?.focus(), 30);
      }
      if (e.key === "Escape") {
        closeSearch();
        setBellOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Click outside closes panels
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (searchOpen && searchRef.current && !searchRef.current.contains(e.target as Node)) closeSearch();
      if (bellOpen && bellRef.current && !bellRef.current.contains(e.target as Node)) setBellOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [searchOpen, bellOpen]);

  const onSearchKeyDown = (e: React.KeyboardEvent) => {
    if (!results.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIdx((i) => (i + 1) % results.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIdx((i) => (i - 1 + results.length) % results.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      openResult(results[activeIdx]);
    }
  };

  const levelIcon = (l: Level) =>
    l === "ok" ? <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />
    : l === "warn" ? <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
    : <XCircle className="w-3.5 h-3.5 text-red-400" />;

  // -------------------------------------------------------------------------
  return (
    <header className="relative flex h-14 items-center justify-between border-b border-white/[0.06] bg-[#060910]/80 backdrop-blur-xl px-4">

      {/* Left — back + title */}
      <div className="flex items-center gap-2">
        {canGoBack && (
          <button
            onClick={() => navigate(-1)}
            title="Go back"
            className="group flex items-center gap-1.5 pl-2 pr-3 py-1.5 rounded-lg text-gray-500 hover:text-gray-200 hover:bg-white/[0.05] transition-all"
          >
            <ArrowLeft className="w-4 h-4 group-hover:-translate-x-0.5 transition-transform" />
            <span className="text-xs font-medium">Back</span>
          </button>
        )}
        <h2 className={`text-sm font-semibold text-gray-300 tracking-wide ${canGoBack ? "" : "ml-2"}`}>
          {getTitle()}
        </h2>
      </div>

      {/* Right — search, bell, avatar */}
      <div className="flex items-center gap-2">

        {/* ---------------- Search ---------------- */}
        <div ref={searchRef} className="relative">
          {searchOpen ? (
            <div className="flex items-center gap-2 bg-white/[0.04] border border-cyan-500/30 rounded-lg px-3 py-1.5">
              <Search size={14} className="text-cyan-400 flex-shrink-0" />
              <input
                ref={inputRef}
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={onSearchKeyDown}
                placeholder="Search crystals and papers..."
                className="bg-transparent text-sm text-white placeholder-gray-600 outline-none w-64"
                autoFocus
              />
              <button onClick={closeSearch} className="text-gray-600 hover:text-gray-300 transition-colors">
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          ) : (
            <button
              onClick={() => { setSearchOpen(true); setBellOpen(false); setTimeout(() => inputRef.current?.focus(), 30); }}
              title="Search (Ctrl+K)"
              className="flex items-center gap-2 pl-2.5 pr-2 py-1.5 rounded-lg text-gray-500 hover:text-gray-300 hover:bg-white/[0.04] transition-all"
            >
              <Search size={16} />
              <kbd className="hidden sm:inline text-[9px] font-mono px-1.5 py-0.5 rounded bg-white/[0.04] border border-white/[0.08] text-gray-600">
                ⌘K
              </kbd>
            </button>
          )}

          {/* Results dropdown */}
          {searchOpen && query.trim() !== "" && (
            <div className="absolute right-0 top-full mt-2 w-[420px] max-h-[380px] overflow-y-auto rounded-xl border border-white/[0.08] bg-[#0d1117] shadow-2xl shadow-black/60 z-50">
              {results.length === 0 ? (
                <p className="px-4 py-6 text-center text-xs text-gray-600">
                  No matches for "{query}"
                </p>
              ) : (
                <>
                  {results.map((r, i) => (
                    <button
                      key={`${r.kind}-${r.id}-${i}`}
                      onMouseEnter={() => setActiveIdx(i)}
                      onClick={() => openResult(r)}
                      className={`w-full flex items-center gap-3 px-3.5 py-2.5 text-left transition-colors ${
                        i === activeIdx ? "bg-white/[0.05]" : "hover:bg-white/[0.02]"
                      } ${i !== results.length - 1 ? "border-b border-white/[0.04]" : ""}`}
                    >
                      <div className={`w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 border ${
                        r.kind === "crystal"
                          ? "bg-cyan-500/10 border-cyan-500/20"
                          : "bg-amber-500/10 border-amber-500/20"
                      }`}>
                        {r.kind === "crystal"
                          ? <Atom className="w-3.5 h-3.5 text-cyan-400" />
                          : <BookOpen className="w-3.5 h-3.5 text-amber-400" />}
                      </div>

                      <div className="flex-1 min-w-0">
                        <p className="text-[13px] font-medium text-white truncate">{r.title}</p>
                        <p className="text-[10px] text-gray-600 truncate">{r.sub}</p>
                      </div>

                      {r.kind === "crystal" && (
                        r.piezo
                          ? <Zap className="w-3 h-3 text-cyan-400 flex-shrink-0" />
                          : <ZapOff className="w-3 h-3 text-gray-700 flex-shrink-0" />
                      )}
                      {i === activeIdx && (
                        <CornerDownLeft className="w-3 h-3 text-gray-600 flex-shrink-0" />
                      )}
                    </button>
                  ))}
                  <div className="px-3.5 py-2 border-t border-white/[0.04] flex items-center gap-3 text-[9px] text-gray-700">
                    <span>↑↓ navigate</span>
                    <span>↵ open</span>
                    <span>esc close</span>
                  </div>
                </>
              )}
            </div>
          )}
        </div>

        {/* ---------------- Notifications ---------------- */}
        <div ref={bellRef} className="relative">
          <button
            onClick={() => { setBellOpen((v) => !v); closeSearch(); }}
            title="System status"
            className="relative p-2 rounded-lg text-gray-500 hover:text-gray-300 hover:bg-white/[0.04] transition-all"
          >
            <Bell size={16} />
            {issueCount > 0 && (
              <span className={`absolute top-1 right-1 w-2 h-2 rounded-full ring-2 ring-[#060910] ${
                worst === "error" ? "bg-red-500" : "bg-amber-500"
              }`} />
            )}
          </button>

          {bellOpen && (
            <div className="absolute right-0 top-full mt-2 w-[320px] rounded-xl border border-white/[0.08] bg-[#0d1117] shadow-2xl shadow-black/60 z-50 overflow-hidden">
              <div className="flex items-center justify-between px-4 py-3 border-b border-white/[0.06]">
                <div>
                  <p className="text-xs font-semibold text-white">System status</p>
                  <p className="text-[10px] text-gray-600">
                    {issueCount === 0 ? "All systems normal" : `${issueCount} item${issueCount > 1 ? "s" : ""} need attention`}
                  </p>
                </div>
                <button
                  onClick={runHealthChecks}
                  disabled={checking}
                  className="p-1.5 rounded-lg text-gray-600 hover:text-gray-300 hover:bg-white/[0.04] transition-all disabled:opacity-40"
                  title="Re-check"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${checking ? "animate-spin" : ""}`} />
                </button>
              </div>

              <div className="max-h-[300px] overflow-y-auto">
                {health.length === 0 ? (
                  <p className="px-4 py-6 text-center text-xs text-gray-600">Running checks...</p>
                ) : (
                  health.map((h, i) => (
                    <div
                      key={i}
                      className={`flex items-start gap-2.5 px-4 py-2.5 ${
                        i !== health.length - 1 ? "border-b border-white/[0.04]" : ""
                      }`}
                    >
                      <div className="mt-0.5 flex-shrink-0">{levelIcon(h.level)}</div>
                      <div className="min-w-0">
                        <p className="text-xs font-medium text-gray-300">{h.label}</p>
                        <p className="text-[10px] text-gray-600 leading-relaxed">{h.detail}</p>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}
        </div>

        {/* Avatar */}
        <div className="ml-1 w-7 h-7 rounded-full bg-gradient-to-br from-cyan-500 to-blue-600 flex items-center justify-center text-[10px] font-bold text-white cursor-pointer hover:shadow-lg hover:shadow-cyan-500/20 transition-shadow">
          H
        </div>
      </div>
    </header>
  );
}

export default Navbar;