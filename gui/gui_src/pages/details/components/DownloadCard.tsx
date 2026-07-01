import type { Crystal } from "../../crystals/Crystal";

interface DownloadCardProps {
  crystal: Crystal;
}

function DownloadCard({ crystal }: DownloadCardProps) {
  return (
    <div className="mt-6 rounded-2xl bg-[#111827] p-6 shadow-lg">
      <h2 className="mb-6 text-2xl font-bold text-white">
        📥 Downloads
      </h2>
      <div className="flex flex-wrap gap-4">
        <a href={"/database/cif/" + crystal.pmc_id + "-gamma-glycine.cif"} download className="rounded-lg bg-cyan-600 px-5 py-3 font-semibold text-white hover:bg-cyan-500">
          Download CIF
        </a>
        <a href={"/database/json/" + crystal.pmc_id + ".json"} download className="rounded-lg bg-green-600 px-5 py-3 font-semibold text-white hover:bg-green-500">
          Download JSON
        </a>
        <a href={"/database/pdf/" + crystal.pmc_id + ".pdf"} download className="rounded-lg bg-red-600 px-5 py-3 font-semibold text-white hover:bg-red-500">
          Download PDF
        </a>
      </div>
    </div>
  );
}

export default DownloadCard;