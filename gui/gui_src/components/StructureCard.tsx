import type { Crystal } from "../pages/crystals/Crystal";

interface StructureCardProps {
  crystal: Crystal;
}

function StructureCard({ crystal }: StructureCardProps) {
  return (
    <div className="mt-6 rounded-2xl bg-[#111827] p-6 shadow-lg">
      <h2 className="mb-6 text-2xl font-bold text-white">
        🏛 Crystal Structure
      </h2>
      <div className="grid grid-cols-2 gap-6">
        <div>
          <p className="text-gray-400">Crystal System</p>
          <p className="text-white font-semibold">
            {crystal.crystal_system}
          </p>
        </div>
        <div>
          <p className="text-gray-400">Space Group</p>
          <p className="text-white font-semibold">
            {crystal.space_group_symbol}
          </p>
        </div>
        <div>
          <p className="text-gray-400">Space Group Number</p>
          <p className="text-white font-semibold">
            {crystal.space_group_number}
          </p>
        </div>
        <div>
          <p className="text-gray-400">Centrosymmetric</p>
          <p className="text-white font-semibold">
            {crystal.centrosymmetric ? "Yes" : "No"}
          </p>
        </div>
      </div>
    </div> 
  )
}

export default StructureCard;