import { useState } from 'react';
import type { FC } from 'react';
import CrystalExplorer from '../crystals/CrystalExplorer';
import DatabaseAdminPanel from './DatabaseAdminPanel';
import { Database as DatabaseIcon, Settings, LogOut } from 'lucide-react';

const DatabasePage: FC = () => {
  const [activeTab, setActiveTab] = useState<'explorer' | 'admin'>('explorer');
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [showLoginModal, setShowLoginModal] = useState(false);
  const [loginId, setLoginId] = useState('');
  const [loginPass, setLoginPass] = useState('');
  const [loginError, setLoginError] = useState('');

  const ADMIN_ID = 'pravega2';
  const ADMIN_PASS = 'kb8DU2rG';

  const handleAdminClick = () => {
    if (isAuthenticated) {
      setActiveTab('admin');
    } else {
      setShowLoginModal(true);
    }
  };

  const handleLogin = () => {
    setLoginError('');
    if (loginId === ADMIN_ID && loginPass === ADMIN_PASS) {
      setIsAuthenticated(true);
      setShowLoginModal(false);
      setLoginId('');
      setLoginPass('');
      setActiveTab('admin');
    } else {
      setLoginError('Invalid ID or Password');
    }
  };

  const handleLogout = () => {
    setIsAuthenticated(false);
    setActiveTab('explorer');
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleLogin();
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-4xl font-bold text-white mb-2">Crystal Database</h1>
        <p className="text-gray-400">Browse, search, and manage piezoelectric crystal structures</p>
      </div>

      <div className="flex gap-4 border-b border-gray-700 items-center">
        <button
          onClick={() => setActiveTab('explorer')}
          className={`flex items-center gap-2 px-4 py-3 font-semibold transition-colors ${
            activeTab === 'explorer'
              ? 'text-cyan-400 border-b-2 border-cyan-400'
              : 'text-gray-400 hover:text-white'
          }`}
        >
          <DatabaseIcon className="w-5 h-5" />
          Crystal Explorer
        </button>
        
        <button
          onClick={handleAdminClick}
          className={`flex items-center gap-2 px-4 py-3 font-semibold transition-colors ${
            activeTab === 'admin'
              ? 'text-cyan-400 border-b-2 border-cyan-400'
              : 'text-gray-400 hover:text-white'
          }`}
        >
          <Settings className="w-5 h-5" />
          Administration
        </button>

        {isAuthenticated && (
          <button
            onClick={handleLogout}
            className="ml-auto flex items-center gap-2 px-4 py-3 font-semibold text-red-400 hover:text-red-300 transition-colors"
          >
            <LogOut className="w-5 h-5" />
            Logout
          </button>
        )}
      </div>

      {activeTab === 'explorer' && <CrystalExplorer />}
      {activeTab === 'admin' && isAuthenticated && <DatabaseAdminPanel />}

      {showLoginModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-[#111827] rounded-2xl p-8 border border-cyan-500/20 w-96 shadow-2xl">
            <h2 className="text-2xl font-bold text-white mb-2">Administration Login</h2>
            <p className="text-gray-400 text-sm mb-6">Enter credentials to access admin panel</p>

            <div className="mb-4">
              <label className="block text-gray-300 text-sm font-semibold mb-2">User ID</label>
              <input
                type="text"
                value={loginId}
                onChange={(e) => setLoginId(e.target.value)}
                onKeyPress={handleKeyPress}
                placeholder="pravega2"
                className="w-full bg-[#1a2332] border border-gray-600 rounded-lg px-4 py-2 text-white placeholder-gray-500 focus:outline-none focus:border-cyan-500"
              />
            </div>

            <div className="mb-6">
              <label className="block text-gray-300 text-sm font-semibold mb-2">Password</label>
              <input
                type="password"
                value={loginPass}
                onChange={(e) => setLoginPass(e.target.value)}
                onKeyPress={handleKeyPress}
                placeholder="••••••••"
                className="w-full bg-[#1a2332] border border-gray-600 rounded-lg px-4 py-2 text-white placeholder-gray-500 focus:outline-none focus:border-cyan-500"
              />
            </div>

            {loginError && (
              <div className="mb-6 p-3 bg-red-500/20 border border-red-500 rounded-lg text-red-300 text-sm">
                {loginError}
              </div>
            )}

            <div className="flex gap-3">
              <button
                onClick={handleLogin}
                className="flex-1 bg-cyan-600 hover:bg-cyan-500 text-white font-semibold py-2 rounded-lg transition"
              >
                Login
              </button>
              <button
                onClick={() => {
                  setShowLoginModal(false);
                  setLoginId('');
                  setLoginPass('');
                  setLoginError('');
                }}
                className="flex-1 bg-gray-600 hover:bg-gray-500 text-white font-semibold py-2 rounded-lg transition"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default DatabasePage;