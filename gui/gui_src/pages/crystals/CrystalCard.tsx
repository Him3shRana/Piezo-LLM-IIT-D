import { useNavigate } from "react-router-dom";
import { ChevronRight, Zap, ZapOff } from "lucide-react";

interface CrystalCardProps {
  id: string;
  name: string;
  system: string;
  piezo: boolean;
  formula?: string;
  spaceGroup?: string;
}

const SYSTEM_THEME: Record<string, { accent: string; bg: string; border: string; badge: string; text: string }> = {
  Trigonal:      { accent: 'bg-cyan-500',    bg: 'from-cyan-500/8 to-cyan-500/3',    border: 'border-l-cyan-500',    badge: 'bg-cyan-500/10 text-cyan-400 border-cyan-500/25',    text: 'text-cyan-400' },
  Monoclinic:    { accent: 'bg-blue-500',    bg: 'from-blue-500/8 to-blue-500/3',    border: 'border-l-blue-500',    badge: 'bg-blue-500/10 text-blue-400 border-blue-500/25',    text: 'text-blue-400' },
  Orthorhombic:  { accent: 'bg-violet-500',  bg: 'from-violet-500/8 to-violet-500/3', border: 'border-l-violet-500',  badge: 'bg-violet-500/10 text-violet-400 border-violet-500/25', text: 'text-violet-400' },
  Tetragonal:    { accent: 'bg-emerald-500', bg: 'from-emerald-500/8 to-emerald-500/3', border: 'border-l-emerald-500', badge: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/25', text: 'text-emerald-400' },
  Hexagonal:     { accent: 'bg-amber-500',   bg: 'from-amber-500/8 to-amber-500/3',   border: 'border-l-amber-500',   badge: 'bg-amber-500/10 text-amber-400 border-amber-500/25',   text: 'text-amber-400' },
  Cubic:         { accent: 'bg-rose-500',    bg: 'from-rose-500/8 to-rose-500/3',    border: 'border-l-rose-500',    badge: 'bg-rose-500/10 text-rose-400 border-rose-500/25',    text: 'text-rose-400' },
  Triclinic:     { accent: 'bg-pink-500',    bg: 'from-pink-500/8 to-pink-500/3',    border: 'border-l-pink-500',    badge: 'bg-pink-500/10 text-pink-400 border-pink-500/25',    text: 'text-pink-400' },
};

const DEFAULT_THEME = { accent: 'bg-gray-500', bg: 'from-gray-500/8 to-gray-500/3', border: 'border-l-gray-500', badge: 'bg-gray-500/10 text-gray-400 border-gray-500/25', text: 'text-gray-400' };

function CrystalCard({ id, name, system, piezo, formula, spaceGroup }: CrystalCardProps) {
  const navigate = useNavigate();
  const theme = SYSTEM_THEME[system] || DEFAULT_THEME;

  return (
    <div
      onClick={() => navigate(`/crystal/${id}`)}
      className={`
        group relative cursor-pointer transition-all duration-300
        hover:scale-[1.015] hover:shadow-lg hover:shadow-black/30
        rounded-xl overflow-hidden
        border border-white/[0.06] hover:border-white/[0.12]
        border-l-[3px] ${theme.border}
        ${piezo
          ? `bg-gradient-to-r ${theme.bg}`
          : 'bg-[#0c0e14]'
        }
      `}
    >
      <div className="px-5 py-4">
        {/* Row 1: ID + System badge */}
        <div className="flex items-center justify-between mb-2.5">
          <span className={`text-xs font-bold tracking-wide ${piezo ? theme.text : 'text-gray-500'}`}>
            {id}
          </span>
          <span className={`text-[9px] font-bold uppercase tracking-[0.12em] px-2 py-0.5 rounded border ${theme.badge}`}>
            {system}
          </span>
        </div>

        {/* Row 2: Name */}
        <h2 className={`text-base font-bold leading-snug mb-1 transition-colors ${
          piezo
            ? 'text-white group-hover:text-cyan-200'
            : 'text-gray-500 group-hover:text-gray-400'
        }`}>
          {name || <span className="text-gray-700 italic text-sm">Unnamed</span>}
        </h2>

        {/* Row 3: Formula + Space Group */}
        <p className="text-[11px] text-gray-600 font-mono mb-3">
          {formula || '—'}
          {spaceGroup && <span className="text-gray-700"> · {spaceGroup}</span>}
        </p>

        {/* Row 4: Piezo badge + Arrow */}
        <div className="flex items-center justify-between">
          {piezo ? (
            <span className="inline-flex items-center gap-1.5 text-[10px] font-bold px-2.5 py-1 rounded-full bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
              <Zap className="w-3 h-3" />
              Piezoelectric
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 text-[10px] font-medium px-2.5 py-1 rounded-full bg-red-500/5 text-red-400/60 border border-red-500/10">
              <ZapOff className="w-3 h-3" />
              Non-piezoelectric
            </span>
          )}

          <ChevronRight className={`w-4 h-4 opacity-0 group-hover:opacity-100 group-hover:translate-x-0.5 transition-all ${
            piezo ? theme.text : 'text-gray-600'
          }`} />
        </div>
      </div>
    </div>
  );
}

export default CrystalCard;