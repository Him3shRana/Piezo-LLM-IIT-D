import type { Crystal } from "../../crystals/Crystal";

interface ChemicalInfoCardProps {
  crystal: Crystal;
}

function ChemicalInfoCard({ crystal }: ChemicalInfoCardProps) {
  return (
    <div className="mt-6 rounded-2xl bg-[#111827] p-6">
      <h2 className="mb-6 text-2xl font-bold text-white">
        Chemical Information
      </h2>

      <div className="grid grid-cols-2 gap-6">

        <div>
          <p className="text-gray-400">Chemical Formula</p>
          <p className="text-white font-semibold">
            {crystal.chemical_formula}
          </p>
        </div>

        <div>
          <p className="text-gray-400">Molecular Weight</p>
          <p className="text-white font-semibold">
            {crystal.molecular_weight ?? "Unknown"}
          </p>
        </div>

        <div>
          <p className="text-gray-400">Crystal Type</p>
          <p className="text-white font-semibold">
            {crystal.crystal_type}
          </p>
        </div>

        <div>
          <p className="text-gray-400">Components</p>
          <p className="text-white font-semibold">
            {crystal.component_count}
          </p>
        </div>

      </div>
    </div>
  );
}

export default ChemicalInfoCard;