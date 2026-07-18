import { Outlet } from "react-router-dom";
import Sidebar from "./Sidebar";
import Navbar from "./Navbar";

function Layout() {
  return (
    <div className="flex h-screen w-full bg-[#080B12] text-white antialiased">

      {/* Left sidebar */}
      <Sidebar />

      {/* Right section */}
      <main className="flex flex-1 flex-col overflow-hidden">

        {/* Top navigation bar */}
        <Navbar />

        {/* Main page content */}
        <div className="flex-1 overflow-auto">
          <Outlet />
        </div>

      </main>
    </div>
  );
}

export default Layout;