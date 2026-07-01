// Import Outlet from React Router
import { Outlet } from "react-router-dom";

// Import Sidebar component
import Sidebar from "./Sidebar";

// Import Navbar component
import Navbar from "./Navbar";

// Main application layout
function Layout() {
  return (

    // Main application container
    <div className="flex h-screen w-full bg-[#080B12] text-white">

      {/* Left sidebar */}
      <Sidebar />

      {/* Right section */}
      <main className="flex flex-1 flex-col overflow-hidden">

        {/* Top navigation bar */}
        <Navbar />

        {/* Main page content */}
        <div className="flex-1 overflow-auto p-6">

          {/* Current routed page */}
          <Outlet />

        </div>

      </main>

    </div>

  );
}

// Export Layout component
export default Layout;