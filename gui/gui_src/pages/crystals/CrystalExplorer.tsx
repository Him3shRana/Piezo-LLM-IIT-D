// Import React state
import { useEffect, useState } from "react"; //Load data only when page is loaded

import type { Crystal } from "./Crystal";

// Import components
import CrystalCard from "./CrystalCard";
import SearchBar from "./SearchBar";
import FilterPanel from "./FilterPanel";


function CrystalExplorer() { // Crystal Explorer page

  // Search text
  const [search, setSearch] = useState("");
  const [system, setSystem] = useState("All");

// Real crystal database
const [crystals, setCrystals] = useState<Crystal[]>([]);

// Load database when page opens
useEffect(() => {

  fetch("/database/master_database.json")
    .then((response) => response.json())
    .then((data) => {

      // Convert object into array
const crystalArray = Object.values(data.crystals) as Crystal[];

      setCrystals(crystalArray);

    })
    .catch((error) => {

      console.error("Error loading database:", error);

    });

}, []);
  // Filter crystals
const filteredCrystals = crystals.filter((crystal) => {

const matchesSearch =
  (crystal.molecule_name ?? "")
    .toLowerCase()
    .includes(search.toLowerCase());

  const matchesSystem =
    system === "All" ||
    crystal.crystal_system === system;

  return matchesSearch && matchesSystem;

});

  return (

    <div className="p-8">

      {/* Page title */}
      <h1 className="mb-8 text-4xl font-bold">
        Crystal Explorer
      </h1>

      {/* Search Bar */}
      <SearchBar
        value={search}
        onChange={setSearch}
      />

      <FilterPanel
    system={system}
    setSystem={setSystem}
        />

      {/* Crystal Grid */}
      <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-3">

        {filteredCrystals.map((crystal) => (

          <CrystalCard
            key={crystal.pmc_id}
            id={crystal.pmc_id}
            name={crystal.molecule_name}
            system={crystal.crystal_system}
            piezo={crystal.is_piezoelectric}
          />
          

        ))}

      </div>

    </div>

  );

}

// Export page
export default CrystalExplorer;