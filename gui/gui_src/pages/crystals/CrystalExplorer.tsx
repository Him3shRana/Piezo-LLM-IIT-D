import { useEffect, useState } from "react";
import type { Crystal } from "./Crystal";
import CrystalCard from "./CrystalCard";
import { Search, SlidersHorizontal, Atom, X } from "lucide-react";

function CrystalExplorer() {
  const [search, setSearch] = useState("");
  const [system, setSystem] = useState("All");
  const [crystals, setCrystals] = useState<Crystal[]>([]);
  const [loading, setLoading] = useState(true);

  const systems = ["All", "Orthorhombic", "Monoclinic", "Trigonal", "Tetragonal", "Hexagonal", "Cubic", "Triclinic"];

  useEffect(() => {
    fetch("/database/master_database.json")
      .then((response) => response.json())
      .then((data) => {
        const crystalArray = Object.values(data.crystals) as Crystal[];
        setCrystals(crystalArray);
        setLoading(false);
      })
      .catch((error) => {
        console.error("Error loading database:", error);
        setLoading(false);
      });
  }, []);

  const filteredCrystals = crystals.filter((crystal) => {
    const searchLower = search.toLowerCase();
    const matchesSearch =
      (crystal.molecule_name ?? "").toLowerCase().includes(searchLower) ||
      (crystal.pmc_id ?? "").toLowerCase().includes(searchLower) ||
      (crystal.chemical_formula ?? "").toLowerCase().includes(searchLower);
    const matchesSystem = system === "All" || crystal.crystal_system === system;
    return matchesSearch && matchesSystem;
  });

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="w-6 h-6 border-2 border-cyan-500/30 border-t-cyan-500 rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-5">

      {/* Search + Filter row */}
      <div className="flex flex-col sm:flex-row gap-3">
        {/* Search */}
        <div className="relative flex-1">
          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-600" />
          <input
            type="text"
            placeholder="Search by name, PMC ID, or formula..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full bg-white/[0.02] border border-white/[0.06] rounded-xl pl-10 pr-10 py-3 text-sm text-white placeholder-gray-600 outline-none focus:border-cyan-500/30 transition-colors"
          />
          {search && (
            <button
              onClick={() => setSearch("")}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-600 hover:text-gray-400 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>

        {/* System filter */}
        <div className="relative">
          <SlidersHorizontal className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-600 pointer-events-none" />
          <select
            value={system}
            onChange={(e) => setSystem(e.target.value)}
            className="appearance-none bg-white/[0.02] border border-white/[0.06] rounded-xl pl-10 pr-8 py-3 text-sm text-gray-300 outline-none focus:border-cyan-500/30 transition-colors cursor-pointer min-w-[180px]"
          >
            {systems.map((s) => (
              <option key={s} value={s} className="bg-[#0d1117] text-white">
                {s === "All" ? "All Systems" : s}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Results count */}
      <div className="flex items-center justify-between">
        <p className="text-xs text-gray-500">
          {filteredCrystals.length} crystal{filteredCrystals.length !== 1 ? 's' : ''} found
          {system !== "All" && <span className="text-cyan-500"> · {system}</span>}
          {search && <span className="text-cyan-500"> · "{search}"</span>}
        </p>
        {(search || system !== "All") && (
          <button
            onClick={() => { setSearch(""); setSystem("All"); }}
            className="text-xs text-gray-600 hover:text-gray-400 transition-colors"
          >
            Clear filters
          </button>
        )}
      </div>

      {/* Crystal Grid */}
      {filteredCrystals.length > 0 ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {filteredCrystals.map((crystal) => (
            <CrystalCard
              key={crystal.pmc_id}
              id={crystal.pmc_id}
              name={crystal.molecule_name}
              system={crystal.crystal_system}
              piezo={crystal.is_piezoelectric}
              formula={crystal.chemical_formula}
              spaceGroup={crystal.space_group_symbol}
            />
          ))}
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <div className="w-14 h-14 rounded-2xl bg-gray-500/5 border border-white/[0.06] flex items-center justify-center mb-4">
            <Atom className="w-7 h-7 text-gray-600" />
          </div>
          <p className="text-sm text-gray-500 mb-1">No crystals found</p>
          <p className="text-xs text-gray-600">Try adjusting your search or filters</p>
        </div>
      )}
    </div>
  );
}

export default CrystalExplorer;