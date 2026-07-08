import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

interface Crystal {
  pmc_id: string;
  molecule_name: string;
  crystal_type: string;
  chemical_formula: string;
  crystal_system: string;
  is_piezoelectric: boolean | null;
  is_ferroelectric: boolean | null;
}

interface MasterDatabase {
  metadata: { total_crystals: number };
  crystals: Record<string, Crystal>;
}

interface ChemicalClass {
  name: string;
  bg: string;
  accent: string;
  border: string;
  crystals: Crystal[];
}

// Map raw crystal_type values to broader categories
function classifyCrystal(type: string | null | undefined): string {
  if (!type || type === "None") return "Unclassified";

  const t = type.toLowerCase();

  if (t.includes("amino acid") || t.includes("peptide"))
    return "Amino Acid / Peptide";

  if (t.includes("salt") || t.includes("ionic") || t.includes("cocrystal"))
    return "Molecular Salt / Ionic";

  if (t.includes("hybrid") || t.includes("inorganic"))
    return "Organic-Inorganic Hybrid";

  if (t.includes("hydrogen-bonded"))
    return "Hydrogen-Bonded Molecular";

  if (t.includes("pure") || t.includes("single-component"))
    return "Pure Molecular";

  if (t.includes("non-linear optical") || t.includes("nlo"))
    return "NLO Crystal";

  if (t.includes("organic"))
    return "Organic Molecular";

  return "Other";
}

// Colors for each broad category
const CLASS_STYLES: Record<string, { bg: string; accent: string; border: string }> = {
  "Organic Molecular": {
    bg: "bg-[#1a3a5c]",
    accent: "text-blue-400",
    border: "border-blue-400",
  },
  "Pure Molecular": {
    bg: "bg-[#1a4a2e]",
    accent: "text-emerald-400",
    border: "border-emerald-400",
  },
  "Amino Acid / Peptide": {
    bg: "bg-[#3d1f4e]",
    accent: "text-purple-400",
    border: "border-purple-400",
  },
  "Molecular Salt / Ionic": {
    bg: "bg-[#4a3a1a]",
    accent: "text-yellow-400",
    border: "border-yellow-400",
  },
  "Hydrogen-Bonded Molecular": {
    bg: "bg-[#1a4a4a]",
    accent: "text-teal-400",
    border: "border-teal-400",
  },
  "Organic-Inorganic Hybrid": {
    bg: "bg-[#4a1a2e]",
    accent: "text-red-400",
    border: "border-red-400",
  },
  "NLO Crystal": {
    bg: "bg-[#3a1a4a]",
    accent: "text-pink-400",
    border: "border-pink-400",
  },
  "Unclassified": {
    bg: "bg-[#2a2a3a]",
    accent: "text-gray-400",
    border: "border-gray-500",
  },
  "Other": {
    bg: "bg-[#2a2a3a]",
    accent: "text-cyan-400",
    border: "border-cyan-400",
  },
};

const PiezoClassification = () => {
  const [classes, setClasses] = useState<ChemicalClass[]>([]);
  const [totalCrystals, setTotalCrystals] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    fetch("/database/master_database.json")
      .then((res) => res.json())
      .then((data: MasterDatabase) => {
        const crystalList = Object.values(data.crystals);
        setTotalCrystals(crystalList.length);

        // Group crystals by broad category
        const grouped: Record<string, Crystal[]> = {};
        for (const crystal of crystalList) {
          const category = classifyCrystal(crystal.crystal_type);
          if (!grouped[category]) grouped[category] = [];
          grouped[category].push(crystal);
        }

        // Sort by count descending
        const sorted = Object.entries(grouped)
          .sort((a, b) => b[1].length - a[1].length)
          .map(([name, crystals]) => {
            const style = CLASS_STYLES[name] || CLASS_STYLES["Other"];
            return { name, crystals, ...style };
          });

        setClasses(sorted);
        setLoading(false);
      })
      .catch((err) => {
        console.error("Failed to load database:", err);
        setLoading(false);
      });
  }, []);

  const active = classes.find((c) => c.name === selected);

  if (loading) {
    return <div className="text-gray-400 p-8">Loading classification data...</div>;
  }

  return (
    <div>
      {/* Header */}
      <div className="mb-8 text-center">
        <h2 className="text-2xl font-light text-gray-400 tracking-wide">
          Piezoelectric Molecular Crystals
        </h2>
        <p className="text-gray-500 mt-1 italic">
          Classification by Chemical Class
        </p>
      </div>

      {/* Cards grid */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4 mb-6">
        {classes.map((cls) => {
          const isActive = selected === cls.name;
          return (
            <button
              key={cls.name}
              onClick={() => setSelected(isActive ? null : cls.name)}
              className={`${cls.bg} rounded-2xl p-6 text-center transition-all duration-200 cursor-pointer border-2 ${
                isActive
                  ? `${cls.border} -translate-y-1 shadow-lg`
                  : "border-transparent hover:border-gray-600"
              }`}
            >
              <div className={`text-4xl font-bold ${cls.accent}`}>
                {cls.crystals.length}
              </div>
              <div className="text-sm font-semibold text-gray-200 mt-2">
                {cls.name}
              </div>
              <div className="text-xs text-gray-500 mt-1">
                crystal{cls.crystals.length !== 1 ? "s" : ""}
              </div>
            </button>
          );
        })}
      </div>

      {/* Summary */}
      <p className="text-center text-sm text-gray-500 mb-6">
        Total: {totalCrystals} crystals across {classes.length} classes &nbsp;·&nbsp; From master database
      </p>

      {/* Crystal list panel */}
      {active && (
        <div className={`${active.bg} rounded-2xl p-6 border border-gray-700`}>
          <div className="flex justify-between items-center mb-4">
            <h3 className={`text-lg font-semibold ${active.accent}`}>
              {active.name}
              <span className="text-gray-400 font-normal text-sm ml-2">
                — {active.crystals.length} crystal{active.crystals.length !== 1 ? "s" : ""}
              </span>
            </h3>
            <button
              onClick={() => setSelected(null)}
              className="text-gray-400 hover:text-white text-xl px-1"
            >
              ✕
            </button>
          </div>
          <div
            className={`grid gap-2 ${
              active.crystals.length > 4 ? "md:grid-cols-2" : "grid-cols-1"
            }`}
          >
            {active.crystals.map((crystal, i) => (
              <div
                key={crystal.pmc_id}
                onClick={() => navigate(`/crystal/${crystal.pmc_id}`)}
                className={`flex items-center gap-3 px-4 py-3 bg-black/20 rounded-lg border-l-[3px] ${active.border} cursor-pointer hover:bg-black/30 transition-colors`}
              >
                <span className={`text-xs font-bold ${active.accent} w-5`}>
                  {String(i + 1).padStart(2, "0")}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-gray-200">
                      {crystal.molecule_name}
                    </span>
                    <span className="text-xs text-gray-500">
                      {crystal.pmc_id}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 mt-0.5 flex-wrap">
                    <span className="text-xs text-gray-400">
                      {crystal.chemical_formula}
                    </span>
                    <span className="text-xs text-gray-500">
                      {crystal.crystal_system}
                    </span>
                    <span className="text-[10px] text-gray-600 italic">
                      {crystal.crystal_type}
                    </span>
                    {crystal.is_piezoelectric && (
                      <span className="text-[10px] bg-cyan-500/20 text-cyan-400 px-1.5 py-0.5 rounded">
                        Piezoelectric
                      </span>
                    )}
                    {crystal.is_ferroelectric && (
                      <span className="text-[10px] bg-green-500/20 text-green-400 px-1.5 py-0.5 rounded">
                        Ferroelectric
                      </span>
                    )}
                  </div>
                </div>
                <span className="text-cyan-400 text-xs hover:text-cyan-300 whitespace-nowrap">
                  View →
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default PiezoClassification;