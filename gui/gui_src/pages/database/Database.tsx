import { useState, useRef, useEffect } from 'react';
import type { FC } from 'react';
import CrystalExplorer from '../crystals/CrystalExplorer';
import DatabaseAdminPanel from './DatabaseAdminPanel';
import PiezoClassification from './PiezoClassification';
import VectorDBViewer from './VectorDBViewer';
import {
  Database as DatabaseIcon,
  Settings,
  LogOut,
  FlaskConical,
  Layers,
  Shield,
  Lock,
  Eye,
  EyeOff,
  AlertCircle,
  ArrowRight,
} from 'lucide-react';

const DatabasePage: FC = () => {
  const [activeTab, setActiveTab] = useState<'explorer' | 'classification' | 'vectordb' | 'admin'>('explorer');
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [showLoginModal, setShowLoginModal] = useState(false);
  const [loginId, setLoginId] = useState('');
  const [loginPass, setLoginPass] = useState('');
  const [loginError, setLoginError] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loginLoading, setLoginLoading] = useState(false);

  const userIdRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);

  const ADMIN_ID = 'pravega2';
  const ADMIN_PASS = 'kb8DU2rG';

  // Auto-focus user ID field when modal opens
  useEffect(() => {
    if (showLoginModal) {
      setTimeout(() => userIdRef.current?.focus(), 100);
    }
  }, [showLoginModal]);

  const handleAdminClick = () => {
    if (isAuthenticated) {
      setActiveTab('admin');
    } else {
      setShowLoginModal(true);
    }
  };

  const handleLogin = () => {
    setLoginError('');
    setLoginLoading(true);

    // Simulate brief loading for UX
    setTimeout(() => {
      console.log('typed:', JSON.stringify(loginId), JSON.stringify(loginPass));
      console.log('expected:', JSON.stringify(ADMIN_ID), JSON.stringify(ADMIN_PASS));
      if (loginId === ADMIN_ID && loginPass === ADMIN_PASS) {
        setIsAuthenticated(true);
        setShowLoginModal(false);
        setLoginId('');
        setLoginPass('');
        setActiveTab('admin');
      } else {
        setLoginError('Invalid credentials. Please try again.');
        passwordRef.current?.select();
      }
      setLoginLoading(false);
    }, 400);
  };

  const handleLogout = () => {
    setIsAuthenticated(false);
    setActiveTab('explorer');
  };

  const handleKeyDown = (e: React.KeyboardEvent, field: 'id' | 'pass') => {
    if (e.key === 'Enter') {
      if (field === 'id') {
        // Tab to password on Enter from User ID
        passwordRef.current?.focus();
      } else {
        // Submit on Enter from Password
        handleLogin();
      }
    }
    if (e.key === 'Escape') {
      closeModal();
    }
  };

  const closeModal = () => {
    setShowLoginModal(false);
    setLoginId('');
    setLoginPass('');
    setLoginError('');
    setShowPassword(false);
  };

  const tabs = [
    { id: 'explorer' as const, icon: DatabaseIcon, label: 'Crystal Explorer' },
    { id: 'classification' as const, icon: FlaskConical, label: 'Classification' },
    { id: 'vectordb' as const, icon: Layers, label: 'Vector DB' },
    { id: 'admin' as const, icon: Settings, label: 'Administration', locked: !isAuthenticated },
  ];

  return (
    <div className="p-6 lg:p-10 max-w-[1400px] mx-auto space-y-6">

      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-white tracking-tight">Crystal Database</h1>
        <p className="text-sm text-gray-500 mt-1">Browse, search, and manage piezoelectric crystal structures</p>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1 border-b border-white/[0.06] pb-px">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => tab.id === 'admin' ? handleAdminClick() : setActiveTab(tab.id)}
            className={`
              group relative flex items-center gap-2 px-4 py-3 text-[13px] font-medium transition-all duration-200 rounded-t-lg
              ${activeTab === tab.id
                ? 'text-cyan-400'
                : 'text-gray-500 hover:text-gray-300 hover:bg-white/[0.02]'
              }
            `}
          >
            <tab.icon className="w-4 h-4" />
            {tab.label}
            {tab.locked && <Lock className="w-3 h-3 text-gray-600" />}

            {/* Active indicator */}
            {activeTab === tab.id && (
              <div className="absolute bottom-0 left-2 right-2 h-[2px] bg-cyan-400 rounded-full" />
            )}
          </button>
        ))}

        {/* Logout button */}
        {isAuthenticated && (
          <button
            onClick={handleLogout}
            className="ml-auto flex items-center gap-2 px-3 py-2 text-xs font-medium text-red-400/70 hover:text-red-400 hover:bg-red-500/5 rounded-lg transition-all"
          >
            <LogOut className="w-3.5 h-3.5" />
            Logout
          </button>
        )}
      </div>

      {/* Tab Content */}
      {activeTab === 'explorer' && <CrystalExplorer />}
      {activeTab === 'classification' && <PiezoClassification />}
      {activeTab === 'vectordb' && <VectorDBViewer />}
      {activeTab === 'admin' && isAuthenticated && <DatabaseAdminPanel />}

      {/* Login Modal */}
      {showLoginModal && (
        <div
          className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 p-4"
          onClick={closeModal}
        >
          <div
            className="w-full max-w-sm rounded-2xl bg-[#0d1117] border border-white/[0.08] shadow-2xl shadow-black/50 overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal header */}
            <div className="p-6 pb-2 text-center">
              <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-cyan-500/10 to-blue-500/10 border border-cyan-500/20 flex items-center justify-center mx-auto mb-4">
                <Shield className="w-7 h-7 text-cyan-400" />
              </div>
              <h2 className="text-lg font-bold text-white">Admin Access</h2>
              <p className="text-xs text-gray-500 mt-1">Enter credentials to continue</p>
            </div>

            {/* Form */}
            <div className="p-6 pt-4 space-y-4">

              {/* User ID */}
              <div>
                <label className="text-[11px] font-medium uppercase tracking-wider text-gray-500 mb-1.5 block">
                  User ID
                </label>
                <input
                  ref={userIdRef}
                  type="text"
                  value={loginId}
                  onChange={(e) => { setLoginId(e.target.value); setLoginError(''); }}
                  onKeyDown={(e) => handleKeyDown(e, 'id')}
                  placeholder="Enter user ID"
                  autoComplete="username"
                  className="w-full bg-white/[0.03] border border-white/[0.08] focus:border-cyan-500/50 rounded-xl px-4 py-3 text-sm text-white placeholder-gray-600 outline-none transition-all focus:ring-1 focus:ring-cyan-500/20"
                />
              </div>

              {/* Password */}
              <div>
                <label className="text-[11px] font-medium uppercase tracking-wider text-gray-500 mb-1.5 block">
                  Password
                </label>
                <div className="relative">
                  <input
                    ref={passwordRef}
                    type={showPassword ? 'text' : 'password'}
                    value={loginPass}
                    onChange={(e) => { setLoginPass(e.target.value); setLoginError(''); }}
                    onKeyDown={(e) => handleKeyDown(e, 'pass')}
                    placeholder="Enter password"
                    autoComplete="current-password"
                    className="w-full bg-white/[0.03] border border-white/[0.08] focus:border-cyan-500/50 rounded-xl px-4 py-3 pr-11 text-sm text-white placeholder-gray-600 outline-none transition-all focus:ring-1 focus:ring-cyan-500/20"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300 transition-colors"
                    tabIndex={-1}
                  >
                    {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
              </div>

              {/* Error */}
              {loginError && (
                <div className="flex items-center gap-2 px-3 py-2.5 rounded-lg bg-red-500/5 border border-red-500/20">
                  <AlertCircle className="w-4 h-4 text-red-400 flex-shrink-0" />
                  <p className="text-xs text-red-400">{loginError}</p>
                </div>
              )}

              {/* Buttons */}
              <div className="flex gap-3 pt-1">
                <button
                  onClick={handleLogin}
                  disabled={loginLoading || !loginId || !loginPass}
                  className="flex-1 flex items-center justify-center gap-2 bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 disabled:from-gray-700 disabled:to-gray-700 text-white text-sm font-semibold py-3 rounded-xl transition-all disabled:opacity-40 disabled:cursor-not-allowed active:scale-[0.98]"
                >
                  {loginLoading ? (
                    <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  ) : (
                    <>Login <ArrowRight className="w-3.5 h-3.5" /></>
                  )}
                </button>
                <button
                  onClick={closeModal}
                  className="flex-1 bg-white/[0.04] hover:bg-white/[0.08] text-gray-400 hover:text-white text-sm font-medium py-3 rounded-xl transition-all border border-white/[0.06]"
                >
                  Cancel
                </button>
              </div>

              {/* Keyboard hint */}
              <p className="text-[10px] text-gray-600 text-center">
                Press <kbd className="px-1.5 py-0.5 rounded bg-white/[0.04] border border-white/[0.08] text-gray-500 font-mono text-[9px]">Enter</kbd> to continue · <kbd className="px-1.5 py-0.5 rounded bg-white/[0.04] border border-white/[0.08] text-gray-500 font-mono text-[9px]">Esc</kbd> to cancel
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default DatabasePage;