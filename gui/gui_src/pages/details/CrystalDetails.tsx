import { useParams, useNavigate } from "react-router-dom";
import { useEffect, useState } from "react";
import type { Crystal } from "../crystals/Crystal";
import Crystal3DViewer from "./components/Crystal3DViewer";
import {
  ArrowLeft,
  Atom,
  Beaker,
  Box,
  Download,
  Eye,
  FileCode,
  FileText,
  File,
  Hexagon,
  Zap,
  ZapOff,
  Flame,
  Thermometer,
  Loader,
  ExternalLink,
  Copy,
  Check,
} from "lucide-react";

// Stored paths look like "../data/PMC-001/PMC-001-gamma-glycine.cif".
// Only the filename is reliable, so rebuild the URL from the PMC id.
function fileUrl(pmcId: string, storedPath: unknown, fallback: string): string {
  const name =
    typeof storedPath === "string" && storedPath.trim()
      ? storedPath.split("/").pop()!
      : fallback;
  return `/data/${pmcId}/${encodeURIComponent(name)}`;
}

function CrystalDetails() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [crystal, setCrystal] = useState<Crystal | null>(null);
  const [loading, setLoading] = useState(true);
  const [show3D, setShow3D] = useState(false);
  const [copied, setCopied] = useState(false);
  const [cifContent, setCifContent] = useState<string | undefined>(undefined);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const resp = await fetch("/database/master_database.json");
        const data = await resp.json();
        const base =
          (Object.values(data.crystals) as Crystal[]).find((c) => c.pmc_id === id) ?? null;

        // The master DB is a summary. Detailed fields (unit cell, density,
        // temperature, ...) live in the per-crystal JSON, so merge it in.
        let merged = base;
        if (base) {
          try {
            const detailResp = await fetch(`/data/${id}/${id}.json`);
            if (detailResp.ok) {
              const detail = await detailResp.json();
              merged = { ...base, ...detail };
            }
          } catch {
            /* per-crystal JSON missing - fall back to summary only */
          }
        }

        if (!cancelled) {
          setCrystal(merged);
          setLoading(false);
        }
      } catch {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => { cancelled = true; };
  }, [id]);

  const openViewer = async () => {
    setShow3D(true);
    if (cifContent) return;

    const candidates = [
      fileUrl(id!, (crystal as any)?.cif_path, `${id}.cif`),
      `/data/${id}/${id}.cif`,
    ];

    for (const path of candidates) {
      try {
        const resp = await fetch(path);
        if (!resp.ok) continue;
        const text = await resp.text();
        if (text.includes('_atom_site')) { setCifContent(text); return; }
      } catch { /* next */ }
    }
    console.warn('No CIF found. Tried:', candidates);
  };

  const copyFormula = () => {
    if (crystal?.chemical_formula) {
      navigator.clipboard.writeText(crystal.chemical_formula);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  if (loading) return (
    <div className="flex items-center justify-center h-screen">
      <Loader className="w-6 h-6 animate-spin text-cyan-400" />
    </div>
  );

  if (!crystal) return (
    <div className="flex flex-col items-center justify-center h-screen text-center">
      <Atom className="w-12 h-12 text-gray-700 mb-4" />
      <p className="text-gray-400 mb-2">Crystal not found</p>
      <button onClick={() => navigate('/crystals')} className="text-sm text-cyan-500 hover:text-cyan-400 transition-colors">
        Back to Crystal Explorer
      </button>
    </div>
  );

  const systemColors: Record<string, string> = {
    Trigonal: 'text-cyan-400', Monoclinic: 'text-blue-400', Orthorhombic: 'text-violet-400',
    Tetragonal: 'text-emerald-400', Hexagonal: 'text-amber-400', Cubic: 'text-rose-400', Triclinic: 'text-pink-400',
  };
  const sysColor = systemColors[crystal.crystal_system] || 'text-gray-400';

  const InfoItem = ({ label, value, mono }: { label: string; value: string | number | null | undefined; mono?: boolean }) => (
    <div className="py-3">
      <p className="text-[10px] font-medium uppercase tracking-wider text-gray-600 mb-1">{label}</p>
      <p className={`text-sm font-semibold text-white ${mono ? 'font-mono' : ''}`}>
        {value ?? <span className="text-gray-700 italic">—</span>}
      </p>
    </div>
  );

  return (
    <div className="p-6 lg:p-10 max-w-[1200px] mx-auto space-y-6">

      {/* Back button */}
      <button
        onClick={() => navigate(-1)}
        className="flex items-center gap-2 text-xs text-gray-500 hover:text-gray-300 transition-colors"
      >
        <ArrowLeft className="w-3.5 h-3.5" /> Back
      </button>

      {/* ─── Hero Header ─── */}
      <div className="rounded-2xl border border-white/[0.06] bg-gradient-to-r from-[#0a1628] to-[#0d1117] overflow-hidden">
        <div className="p-8">
          <div className="flex items-start justify-between">
            <div>
              <div className="flex items-center gap-3 mb-3">
                <div className="w-10 h-10 rounded-xl bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center">
                  <Atom className="w-5 h-5 text-cyan-400" />
                </div>
                <span className="text-sm font-bold text-cyan-400">{crystal.pmc_id}</span>
                <span className={`text-[9px] font-bold uppercase tracking-[0.12em] px-2 py-0.5 rounded border ${sysColor} border-current/20 bg-current/5`}>
                  {crystal.crystal_system}
                </span>
              </div>

              <h1 className="text-3xl font-bold text-white mb-2">{crystal.molecule_name}</h1>

              {crystal.chemical_formula && (
                <div className="flex items-center gap-2 mb-4">
                  <p className="text-sm font-mono text-gray-400">{crystal.chemical_formula}</p>
                  <button onClick={copyFormula} className="text-gray-600 hover:text-gray-400 transition-colors" title="Copy formula">
                    {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                  </button>
                </div>
              )}

              {/* Property Tags */}
              <div className="flex flex-wrap gap-2">
                {crystal.is_piezoelectric ? (
                  <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold px-3 py-1.5 rounded-full bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
                    <Zap className="w-3 h-3" /> Piezoelectric
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1.5 text-[11px] font-medium px-3 py-1.5 rounded-full bg-red-500/5 text-red-400/60 border border-red-500/10">
                    <ZapOff className="w-3 h-3" /> Non-piezoelectric
                  </span>
                )}
                {crystal.is_ferroelectric && (
                  <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold px-3 py-1.5 rounded-full bg-violet-500/10 text-violet-400 border border-violet-500/20">
                    <Hexagon className="w-3 h-3" /> Ferroelectric
                  </span>
                )}
                {crystal.is_pyroelectric && (
                  <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold px-3 py-1.5 rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/20">
                    <Flame className="w-3 h-3" /> Pyroelectric
                  </span>
                )}
                {crystal.crystal_type && (
                  <span className="inline-flex items-center gap-1.5 text-[11px] font-medium px-3 py-1.5 rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/20">
                    {crystal.crystal_type}
                  </span>
                )}
              </div>
            </div>

            {/* 3D Viewer Button */}
            <button
              onClick={openViewer}
              className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-gradient-to-r from-violet-600 to-purple-600 hover:from-violet-500 hover:to-purple-500 text-white text-sm font-semibold transition-all active:scale-95"
            >
              <Eye className="w-4 h-4" /> View 3D
            </button>
          </div>
        </div>
      </div>

      {/* ─── Info Grid ─── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">

        {/* Chemical Information */}
        <div className="rounded-2xl border border-white/[0.06] bg-[#0d1117] p-6">
          <div className="flex items-center gap-2 mb-4">
            <Beaker className="w-4 h-4 text-emerald-400" />
            <h2 className="text-sm font-semibold text-white">Chemical Information</h2>
          </div>
          <div className="grid grid-cols-2 gap-x-6">
            <InfoItem label="Chemical Formula" value={crystal.chemical_formula} mono />
            <InfoItem label="Molecular Weight" value={crystal.molecular_weight ? `${crystal.molecular_weight} g/mol` : null} />
            <InfoItem label="Crystal Type" value={crystal.crystal_type} />
            <InfoItem label="Components" value={crystal.component_count} />
          </div>
        </div>

        {/* Crystal Structure */}
        <div className="rounded-2xl border border-white/[0.06] bg-[#0d1117] p-6">
          <div className="flex items-center gap-2 mb-4">
            <Hexagon className="w-4 h-4 text-blue-400" />
            <h2 className="text-sm font-semibold text-white">Crystal Structure</h2>
          </div>
          <div className="grid grid-cols-2 gap-x-6">
            <InfoItem label="Crystal System" value={crystal.crystal_system} />
            <InfoItem label="Space Group" value={`${crystal.space_group_symbol} (${crystal.space_group_number})`} mono />
            <InfoItem label="Centrosymmetric" value={crystal.centrosymmetric ? 'Yes' : 'No'} />
            <InfoItem label="Symmetry Compatible" value={crystal.property_symmetry_compatible ? 'Yes' : 'No'} />
          </div>
        </div>

        {/* Unit Cell Parameters */}
        <div className="rounded-2xl border border-white/[0.06] bg-[#0d1117] p-6">
          <div className="flex items-center gap-2 mb-4">
            <Box className="w-4 h-4 text-cyan-400" />
            <h2 className="text-sm font-semibold text-white">Unit Cell</h2>
          </div>
          <div className="grid grid-cols-3 gap-x-4">
            <InfoItem label="a (Å)" value={crystal.cell_a?.toFixed(4)} mono />
            <InfoItem label="b (Å)" value={crystal.cell_b?.toFixed(4)} mono />
            <InfoItem label="c (Å)" value={crystal.cell_c?.toFixed(4)} mono />
            <InfoItem label="α (°)" value={crystal.cell_alpha?.toFixed(2)} mono />
            <InfoItem label="β (°)" value={crystal.cell_beta?.toFixed(2)} mono />
            <InfoItem label="γ (°)" value={crystal.cell_gamma?.toFixed(2)} mono />
          </div>
          <div className="mt-2 pt-3 border-t border-white/[0.04] grid grid-cols-3 gap-x-4">
            <InfoItem label="Volume (ų)" value={crystal.cell_volume?.toFixed(2)} mono />
            <InfoItem label="Z" value={crystal.cell_z} />
            <InfoItem label="Z'" value={crystal.cell_z_prime} />
          </div>
        </div>

        {/* Experimental Details */}
        <div className="rounded-2xl border border-white/[0.06] bg-[#0d1117] p-6">
          <div className="flex items-center gap-2 mb-4">
            <Thermometer className="w-4 h-4 text-amber-400" />
            <h2 className="text-sm font-semibold text-white">Experimental Details</h2>
          </div>
          <div className="grid grid-cols-2 gap-x-6">
            <InfoItem label="Density (g/cm³)" value={crystal.density_g_cm3?.toFixed(3)} mono />
            <InfoItem label="Temperature (K)" value={crystal.temperature_k} />
            <InfoItem label="R-Factor (%)" value={crystal.r_factor_percent?.toFixed(2)} mono />
            <InfoItem label="Radiation" value={crystal.radiation} />
            <InfoItem label="Colour" value={crystal.colour} />
            <InfoItem label="Habit" value={crystal.habit} />
          </div>
        </div>
      </div>

      {/* ─── Identifiers ─── */}
      {(crystal.csd_refcode || crystal.ccdc_number || crystal.cod_code || crystal.structure_doi) && (
        <div className="rounded-2xl border border-white/[0.06] bg-[#0d1117] p-6">
          <div className="flex items-center gap-2 mb-4">
            <FileCode className="w-4 h-4 text-violet-400" />
            <h2 className="text-sm font-semibold text-white">Identifiers & References</h2>
          </div>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-x-6">
            {crystal.csd_refcode && <InfoItem label="CSD Refcode" value={crystal.csd_refcode} mono />}
            {crystal.ccdc_number && <InfoItem label="CCDC Number" value={crystal.ccdc_number} mono />}
            {crystal.cod_code && <InfoItem label="COD Code" value={crystal.cod_code} mono />}
            {crystal.structure_doi && (
              <div className="py-3">
                <p className="text-[10px] font-medium uppercase tracking-wider text-gray-600 mb-1">DOI</p>
                <a
                  href={`https://doi.org/${crystal.structure_doi}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-cyan-400 hover:text-cyan-300 flex items-center gap-1 transition-colors"
                >
                  {crystal.structure_doi} <ExternalLink className="w-3 h-3" />
                </a>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ─── Interactions ─── */}
      {crystal.intermolecular_interactions && crystal.intermolecular_interactions.length > 0 && (
        <div className="rounded-2xl border border-white/[0.06] bg-[#0d1117] p-6">
          <h2 className="text-sm font-semibold text-white mb-3">Intermolecular Interactions</h2>
          <div className="flex flex-wrap gap-2">
            {crystal.intermolecular_interactions.map((int, i) => (
              <span key={i} className="text-[11px] px-2.5 py-1 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                {int}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* ─── Downloads ─── */}
      <div className="rounded-2xl border border-white/[0.06] bg-[#0d1117] p-6">
        <div className="flex items-center gap-2 mb-4">
          <Download className="w-4 h-4 text-gray-400" />
          <h2 className="text-sm font-semibold text-white">Downloads</h2>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {[
            { label: 'CIF Structure', icon: Atom, href: fileUrl(crystal.pmc_id, (crystal as any).cif_path, `${crystal.pmc_id}.cif`), color: 'from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500' },
            { label: 'JSON Data', icon: FileCode, href: fileUrl(crystal.pmc_id, (crystal as any).json_path, `${crystal.pmc_id}.json`), color: 'from-emerald-600 to-green-600 hover:from-emerald-500 hover:to-green-500' },
            { label: 'Research Paper', icon: FileText, href: fileUrl(crystal.pmc_id, (crystal as any).pdf_path, `${crystal.pmc_id}.pdf`), color: 'from-rose-600 to-red-600 hover:from-rose-500 hover:to-red-500' },
          ].map((dl, i) => (
            <a
              key={i}
              href={dl.href}
              download
              className={`flex items-center gap-3 px-4 py-3 rounded-xl bg-gradient-to-r ${dl.color} text-white text-sm font-semibold transition-all active:scale-95`}
            >
              <dl.icon className="w-4 h-4" />
              {dl.label}
            </a>
          ))}
        </div>
      </div>

      {/* 3D Viewer Modal */}
      <Crystal3DViewer pmc_id={crystal.pmc_id} isOpen={show3D} onClose={() => setShow3D(false)} cifContent={cifContent} />
    </div>
  );
}

export default CrystalDetails;