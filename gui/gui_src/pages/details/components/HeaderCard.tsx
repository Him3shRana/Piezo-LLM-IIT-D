// Header Card Component

import type { Crystal } from "../../crystals/Crystal";

// Props
interface HeaderCardProps {
  crystal: Crystal;
}

// Component
function HeaderCard({ crystal }: HeaderCardProps) {

  return (

    <div className="rounded-2xl bg-[#111827] p-8 shadow-lg">

      {/* Crystal Name */}
      <h1 className="text-4xl font-bold">
        {crystal.molecule_name}
      </h1>

      {/* PMC ID */}
      <p className="mt-2 text-cyan-400 text-lg">
        {crystal.pmc_id}
      </p>

      {/* Badges */}
      <div className="mt-6 flex flex-wrap gap-3">

        {crystal.is_piezoelectric && (

          <span className="rounded-full bg-green-600 px-4 py-2 text-sm font-semibold">
            🟢 Piezoelectric
          </span>

        )}

        {crystal.is_ferroelectric && (

          <span className="rounded-full bg-purple-600 px-4 py-2 text-sm font-semibold">
            🟣 Ferroelectric
          </span>

        )}

        {crystal.is_pyroelectric && (

          <span className="rounded-full bg-orange-600 px-4 py-2 text-sm font-semibold">
            🟠 Pyroelectric
          </span>

        )}

        <span className="rounded-full bg-blue-600 px-4 py-2 text-sm font-semibold">
          {crystal.crystal_type}
        </span>

      </div>

    </div>

  );

}

export default HeaderCard;