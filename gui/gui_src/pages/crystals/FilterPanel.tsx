// Define Filter Panel properties
interface FilterPanelProps {

  // Selected crystal system
  system: string;

  // Update crystal system
  setSystem: (value: string) => void;

}

// Filter Panel component
function FilterPanel({
  system,
  setSystem,
}: FilterPanelProps) {

  return (

    // Filter container
    <div className="mb-8 flex gap-4">

      {/* Crystal System */}
      <select
        value={system}
        onChange={(event) => setSystem(event.target.value)}
        className="rounded-xl bg-[#111827] p-3 outline-none"
      >

        <option value="All">
          All Systems
        </option>

        <option value="Orthorhombic">
          Orthorhombic
        </option>

        <option value="Monoclinic">
          Monoclinic
        </option>

        <option value="Trigonal">
          Trigonal
        </option>

        <option value="Tetragonal">
          Tetragonal
        </option>

      </select>

    </div>

  );

}

// Export component
export default FilterPanel;