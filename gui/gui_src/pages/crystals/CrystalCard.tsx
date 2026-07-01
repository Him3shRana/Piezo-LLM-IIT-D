import { useNavigate } from "react-router-dom";

// Define the properties accepted by CrystalCard
interface CrystalCardProps {

  id: string;

  name: string;

  system: string;

  piezo: boolean;

}

// Crystal Card component
function CrystalCard({
  id,
  name,
  system,
  piezo,
}: CrystalCardProps) {

  // React Router navigation
  const navigate = useNavigate();

  return (

    <div className="rounded-2xl bg-[#111827] p-6 transition-all duration-300 hover:scale-[1.02] hover:bg-[#1a2235]">

      <p className="text-sm text-cyan-400">
        {id}
      </p>

      <h2 className="mt-3 text-2xl font-bold">
        {name}
      </h2>

      <p className="mt-3 text-gray-400">
        {system}
      </p>

      <div className="mt-5">

        {piezo ? (

          <span className="rounded-full bg-green-600 px-3 py-1 text-sm">
            Piezoelectric
          </span>

        ) : (

          <span className="rounded-full bg-red-600 px-3 py-1 text-sm">
            Non Piezoelectric
          </span>

        )}

      </div>

      <button
        onClick={() => navigate(`/crystal/${id}`)}
        className="mt-6 w-full rounded-xl bg-cyan-600 py-3 transition-all duration-300 hover:bg-cyan-700"
      >
        Open Crystal
      </button>

    </div>

  );

}

export default CrystalCard;