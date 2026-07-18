import { Link, useLocation } from "react-router-dom";
import {
  LayoutDashboard,
  MessageSquare,
  Gem,
  FileText,
  Database,
  Settings,
  Atom,
} from "lucide-react";

// Each destination gets its own accent so the active page is
// identifiable at a glance, not just by position.
const navItems = [
  { to: "/",          icon: LayoutDashboard, label: "Dashboard",        activeText: "text-cyan-400",    activeBg: "bg-cyan-500/10",    bar: "bg-cyan-400",    idleHover: "group-hover:text-cyan-400/70" },
  { to: "/chat",      icon: MessageSquare,   label: "AI Chat",          activeText: "text-violet-400",  activeBg: "bg-violet-500/10",  bar: "bg-violet-400",  idleHover: "group-hover:text-violet-400/70" },
  { to: "/crystals",  icon: Gem,             label: "Crystal Explorer", activeText: "text-emerald-400", activeBg: "bg-emerald-500/10", bar: "bg-emerald-400", idleHover: "group-hover:text-emerald-400/70" },
  { to: "/papers",    icon: FileText,        label: "Papers",           activeText: "text-amber-400",   activeBg: "bg-amber-500/10",   bar: "bg-amber-400",   idleHover: "group-hover:text-amber-400/70" },
  { to: "/database",  icon: Database,        label: "Database",         activeText: "text-blue-400",    activeBg: "bg-blue-500/10",    bar: "bg-blue-400",    idleHover: "group-hover:text-blue-400/70" },
  { to: "/settings",  icon: Settings,        label: "Settings",         activeText: "text-rose-400",    activeBg: "bg-rose-500/10",    bar: "bg-rose-400",    idleHover: "group-hover:text-rose-400/70" },
];

function Sidebar() {
  const location = useLocation();

  const isActive = (path: string) => {
    if (path === "/") return location.pathname === "/";
    // /crystal/PMC-001 should keep Crystal Explorer highlighted
    if (path === "/crystals") return location.pathname.startsWith("/crystal");
    return location.pathname.startsWith(path);
  };

  return (
    <aside className="w-[240px] flex flex-col border-r border-white/[0.06] bg-[#060910]">

      {/* Logo */}
      <div className="px-5 py-6">
        <Link to="/" className="flex items-center gap-2.5 group">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-500 to-blue-600 flex items-center justify-center shadow-lg shadow-cyan-500/20 group-hover:shadow-cyan-500/40 transition-shadow">
            <Atom className="w-4 h-4 text-white" />
          </div>
          <div>
            <span className="text-base font-bold bg-gradient-to-r from-cyan-400 to-blue-400 bg-clip-text text-transparent">
              Piezo-LLM
            </span>
            <p className="text-[9px] text-gray-600 font-medium tracking-widest uppercase -mt-0.5">
              Research Platform
            </p>
          </div>
        </Link>
      </div>

      <div className="mx-4 h-px bg-gradient-to-r from-transparent via-white/[0.06] to-transparent" />

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4 space-y-0.5">
        <p className="px-3 mb-3 text-[10px] font-semibold uppercase tracking-[0.15em] text-gray-600">
          Navigation
        </p>

        {navItems.map((item) => {
          const active = isActive(item.to);
          return (
            <Link
              key={item.to}
              to={item.to}
              className={`
                group relative flex items-center gap-3 rounded-xl px-3 py-2.5
                text-[13px] font-medium transition-all duration-200
                ${active
                  ? `${item.activeBg} ${item.activeText}`
                  : "text-gray-500 hover:text-gray-200 hover:bg-white/[0.03]"
                }
              `}
            >
              {/* Active indicator bar, tinted to match the item */}
              {active && (
                <div className={`absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 rounded-r-full ${item.bar}`} />
              )}

              <item.icon
                size={17}
                className={`flex-shrink-0 transition-colors ${
                  active ? item.activeText : `text-gray-600 ${item.idleHover}`
                }`}
              />
              {item.label}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="mx-4 h-px bg-gradient-to-r from-transparent via-white/[0.06] to-transparent" />
      <div className="p-4">
        <div className="rounded-xl bg-gradient-to-br from-cyan-500/5 to-blue-500/5 border border-cyan-500/10 p-3.5">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-500 mb-1">Version</p>
          <p className="text-xs text-gray-400">
            Piezo-LLM <span className="text-cyan-500">v1.0</span>
          </p>
        </div>
      </div>
    </aside>
  );
}

export default Sidebar;