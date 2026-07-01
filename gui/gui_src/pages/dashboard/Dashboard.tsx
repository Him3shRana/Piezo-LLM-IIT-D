import { useEffect, useState } from 'react';
import {
  Database,
  FileText,
  Bot,
  Cpu,
  MessageSquare,
  FolderOpen,
  Upload,
  Search,
} from "lucide-react";

interface MasterDatabase {
  metadata: {
    total_crystals: number;
  };
  crystals: Record<string, any>;
}

function Dashboard() {
  const [data, setData] = useState<MasterDatabase | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/database/master_database.json")
      .then((res) => res.json())
      .then((data) => {
        setData(data);
        setLoading(false);
      })
      .catch((err) => {
        console.error("Failed to load database:", err);
        setLoading(false);
      });
  }, []);

  if (loading) {
    return <div className="p-8 text-white">Loading Dashboard...</div>;
  }

  if (!data) {
    return <div className="p-8 text-white">Error loading data</div>;
  }

  const totalCrystals = data.metadata.total_crystals;
  const crystalList = Object.values(data.crystals).slice(0, 4);

  return (
    <div className="p-8">
      {/* Header */}
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-4xl font-bold">Dashboard</h1>
          <p className="mt-2 text-gray-400">Welcome back to Piezo-LLM</p>
        </div>
        <div className="rounded-full bg-green-500/20 px-4 py-2 text-green-400">
          AI Ready
        </div>
      </div>

      

      {/* Statistics */}
      <div className="grid grid-cols-4 gap-5">
        <div className="rounded-2xl bg-[#111827] p-6">
          <Database className="mb-3 text-cyan-400" />
          <p className="text-gray-400">Crystals</p>
          <h2 className="mt-3 text-3xl font-bold">{totalCrystals}</h2>
        </div>

        <div className="rounded-2xl bg-[#111827] p-6">
        <FileText className="mb-3 text-cyan-400" />
        <p className="text-gray-400">Research Papers</p>
        <h2 className="mt-3 text-3xl font-bold">36</h2>
        </div>

        <div className="rounded-2xl bg-[#111827] p-6">
          <Bot className="mb-3 text-cyan-400" />
          <p className="text-gray-400">AI Status</p>
          <h2 className="mt-3 text-3xl font-bold">Ready</h2>
        </div>

        <div className="rounded-2xl bg-[#111827] p-6">
          <Cpu className="mb-3 text-cyan-400" />
          <p className="text-gray-400">GPU</p>
          <h2 className="mt-3 text-3xl font-bold">Online</h2>
        </div>
      </div>

      {/* Quick Actions */}
      <h2 className="mt-10 mb-5 text-2xl font-bold">Quick Actions</h2>
      <div className="grid grid-cols-4 gap-5">
        <button className="rounded-xl bg-cyan-600 p-5 transition hover:scale-105 text-white font-semibold">
          <MessageSquare className="mx-auto mb-3" />
          AI Chat
        </button>

        <button className="rounded-xl bg-blue-600 p-5 transition hover:scale-105 text-white font-semibold">
          <FolderOpen className="mx-auto mb-3" />
          Database
        </button>

        <button className="rounded-xl bg-green-600 p-5 transition hover:scale-105 text-white font-semibold">
          <Upload className="mx-auto mb-3" />
          Upload PDF
        </button>

        <button className="rounded-xl bg-purple-600 p-5 transition hover:scale-105 text-white font-semibold">
          <Search className="mx-auto mb-3" />
          Crystal Search
        </button>
      </div>

      {/* Recent Crystals */}
      <h2 className="mt-10 mb-5 text-2xl font-bold">Recent Crystals</h2>
      <div className="rounded-2xl bg-[#111827] p-6">
        {crystalList.map((crystal: any, index: number) => (
          <div key={index} className="mb-4 flex items-center justify-between">
            <div>
              <h3 className="font-semibold">{crystal.pmc_id}</h3>
              <p className="text-sm text-gray-400">{crystal.molecule_name}</p>
            </div>
            <a href={`/crystal/${crystal.pmc_id}`} className="text-cyan-400 hover:text-cyan-300">
              View
            </a>
          </div>
        ))}
      </div>

      {/* System Status */}
      <h2 className="mt-10 mb-5 text-2xl font-bold">System Status</h2>
      <div className="rounded-2xl bg-[#111827] p-6 space-y-4">
        <div className="flex items-center justify-between">
          <span>Database</span>
          <span className="text-green-400">🟢 Connected</span>
        </div>
        <div className="flex items-center justify-between">
          <span>Backend</span>
          <span className="text-green-400">🟢 Running</span>
        </div>
        <div className="flex items-center justify-between">
          <span>Embedding Model</span>
          <span className="text-green-400">🟢 Ready</span>
        </div>
        <div className="flex items-center justify-between">
          <span>LLM</span>
          <span className="text-yellow-400">🟡 Not Installed</span>
        </div>
        <div className="flex items-center justify-between">
          <span>GPU</span>
          <span className="text-red-400">🔴 Not Available</span>
        </div>
      </div>
    </div>
  );
}

export default Dashboard;