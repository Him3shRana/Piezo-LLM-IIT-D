import { useParams } from "react-router-dom";
import { useEffect, useState } from "react";
import StructureCard from "./components/StructureCard";
import DownloadCard from "./components/DownloadCard";
import ViewerCard from "./components/ViewerCard";
import type { Crystal } from "../crystals/Crystal";
import ChemicalInfoCard from "./components/ChemicalInfoCard";
import HeaderCard from "./components/HeaderCard";

// Crystal Details Page
function CrystalDetails() {
  // Get PMC ID from URL
  const { id } = useParams();
  
  // Selected crystal
  const [crystal, setCrystal] = useState<Crystal | null>(null);
  
  // Load crystal data
  useEffect(() => {
    fetch("/database/master_database.json")
      .then((response) => response.json())
      .then((data) => {
        console.log("Full data:", data);
        const crystals = Object.values(data.crystals) as Crystal[];
        console.log("Crystal Array:", crystals);
        console.log("URL ID:", id);
        const selectedCrystal = crystals.find((c) => c.pmc_id === id);
        console.log("Selected Crystal:", selectedCrystal);
        setCrystal(selectedCrystal ?? null);
      })
      .catch((error) => {
        console.error(error);
      });
  }, [id]);

  // Loading Screen
  if (!crystal) {
    return (
      <div className="p-8 text-white">
        Loading Crystal...
      </div>
    );
  }

  // Main Page
  return (
    <div className="p-8 space-y-6">
      {/* Header */}
      <HeaderCard crystal={crystal} />
      
      {/* Chemical Information */}
      <ChemicalInfoCard crystal={crystal} />
      
      {/* Crystal Structure */}
      <StructureCard crystal={crystal} />
      
      {/* Downloads */}
      <DownloadCard crystal={crystal} />
      
      {/* 3D Viewer */}
      <ViewerCard crystal={crystal} />
    </div>
  );
}

export default CrystalDetails;