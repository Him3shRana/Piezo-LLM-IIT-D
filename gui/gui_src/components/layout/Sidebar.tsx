// Import routing
import { Link } from "react-router-dom";

// Import icons from Lucide
import {
  LayoutDashboard,
  MessageSquare,
  Gem,
  FileText,
  Database,
  Settings,
} from "lucide-react";

// Sidebar component
function Sidebar() {
  return (

    // Sidebar container
    <aside className="w-72 border-r border-white/10 bg-[#0B1220]">

      {/* Logo section */}
      <div className="border-b border-white/10 p-6">

        {/* Application title */}
        <h1 className="text-2xl font-bold text-cyan-400">
          🧬 Piezo-LLM
        </h1>

      </div>

      {/* Navigation menu */}
      <nav className="space-y-2 p-4">

        {/* Dashboard */}
        <Link
          to="/"
          className="flex w-full items-center gap-3 rounded-xl p-3 transition-all duration-300 hover:bg-cyan-500/10"
        >
          <LayoutDashboard size={20} />
          Dashboard
        </Link>

        {/* AI Chat */}
        <Link
          to="/chat"
          className="flex w-full items-center gap-3 rounded-xl p-3 transition-all duration-300 hover:bg-cyan-500/10"
        >
          <MessageSquare size={20} />
          AI Chat
        </Link>

        {/* Crystal Explorer */}
        <Link
          to="/crystals"
          className="flex w-full items-center gap-3 rounded-xl p-3 transition-all duration-300 hover:bg-cyan-500/10"
        >
          <Gem size={20} />
          Crystal Explorer
        </Link>

        {/* Papers */}
        <Link
          to="/papers"
          className="flex w-full items-center gap-3 rounded-xl p-3 transition-all duration-300 hover:bg-cyan-500/10"
        >
          <FileText size={20} />
          Papers
        </Link>

        {/* Database */}
        <Link
          to="/database"
          className="flex w-full items-center gap-3 rounded-xl p-3 transition-all duration-300 hover:bg-cyan-500/10"
        >
          <Database size={20} />
          Database
        </Link>

        {/* Settings */}
        <Link
          to="/settings"
          className="flex w-full items-center gap-3 rounded-xl p-3 transition-all duration-300 hover:bg-cyan-500/10"
        >
          <Settings size={20} />
          Settings
        </Link>

      </nav>

    </aside>

  );
}

// Export Sidebar component
export default Sidebar;