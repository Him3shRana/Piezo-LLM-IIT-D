// Import Search icon
import { Search } from "lucide-react";

// Navbar component
function Navbar() {

  return (

    // Top navigation bar
    <header className="flex h-16 items-center justify-between border-b border-white/10 bg-[#0B1220] px-6">

      {/* Left section */}
      <div>

        {/* Current page title */}
        <h2 className="text-xl font-semibold">
          Dashboard
        </h2>

      </div>

      {/* Right section */}
      <div className="flex items-center gap-4">

        {/* Search button */}
        <button className="rounded-lg p-2 transition-all duration-300 hover:bg-cyan-500/10">

          <Search size={20} />

        </button>

      </div>

    </header>

  );

}

// Export Navbar component
export default Navbar;