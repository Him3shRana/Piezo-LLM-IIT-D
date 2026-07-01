import { useState } from 'react';
import type { Crystal } from "../../crystals/Crystal";
import Crystal3DViewer from './Crystal3DViewer';

interface ViewerCardProps {
  crystal: Crystal;
}

function ViewerCard({ crystal }: ViewerCardProps) {
  const [show3D, setShow3D] = useState(false);

  return (
    <>
      <div className="mt-6 rounded-2xl bg-[#111827] p-6 shadow-lg">
        <h2 className="mb-6 text-2xl font-bold text-white">
          🔬 Visualize
        </h2>
        <button 
          onClick={() => setShow3D(true)} 
          className="rounded-lg bg-purple-600 px-5 py-3 font-semibold text-white hover:bg-purple-500"
        >
          View 3D Structure
        </button>
      </div>

      <Crystal3DViewer 
        pmc_id={crystal.pmc_id} 
        isOpen={show3D} 
        onClose={() => setShow3D(false)} 
      />
    </>
  );
}

export default ViewerCard;