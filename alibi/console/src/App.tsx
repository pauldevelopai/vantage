import { BrowserRouter, Routes, Route, Link, Navigate, useNavigate, useLocation } from 'react-router-dom';
import { useState } from 'react';
import { IncidentsPage } from './pages/IncidentsPage';
import { IncidentDetailPage } from './pages/IncidentDetailPage';
import { ReportsPage } from './pages/ReportsPage';
import { SettingsPage } from './pages/SettingsPage';
import { LoginPage } from './pages/LoginPage';
import { MetricsPage } from './pages/MetricsPage';
import { VehicleSearchPage } from './pages/VehicleSearchPage';
import { CamerasPage } from './pages/CamerasPage';
import { SitesPage } from './pages/SitesPage';
import { WatchlistPage } from './pages/WatchlistPage';
import { SearchPage } from './pages/SearchPage';
import PatternsPage from './pages/PatternsPage';
import { isAuthenticated, getUser, logout, hasRole } from './lib/auth';

type LayoutMode = 'standard' | 'control-room';

function useLayoutMode(): [LayoutMode, () => void] {
  const [mode, setMode] = useState<LayoutMode>(
    () => (localStorage.getItem('alibi-layout-mode') as LayoutMode) || 'standard'
  );
  const toggle = () => {
    const next = mode === 'standard' ? 'control-room' : 'standard';
    localStorage.setItem('alibi-layout-mode', next);
    setMode(next);
  };
  return [mode, toggle];
}

// Protected route wrapper
function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  
  if (!isAuthenticated()) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }
  
  return <>{children}</>;
}

// Main layout with navigation
function Layout({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate();
  const user = getUser();
  const location = useLocation();
  const [layoutMode, toggleLayout] = useLayoutMode();
  const isControlRoom = layoutMode === 'control-room';

  function handleLogout() {
    logout();
    navigate('/login');
  }

  const isActive = (path: string) => location.pathname === path || location.pathname.startsWith(path + '/');

  const apiBase = `http://${window.location.hostname}:8000`;

  const navLink = (to: string, label: string) => (
    <Link
      to={to}
      className={`${
        isActive(to) ? 'bg-indigo-500/[0.35] text-white' : 'text-white/[0.55] hover:text-white/[0.9] hover:bg-white/[0.08]'
      } px-3 py-1.5 rounded-md text-[13px] font-medium whitespace-nowrap transition-all duration-150`}
    >
      {label}
    </Link>
  );

  const extLink = (href: string, label: string) => (
    <a
      href={href}
      className="text-white/[0.55] hover:text-white/[0.9] hover:bg-white/[0.08] px-3 py-1.5 rounded-md text-[13px] font-medium whitespace-nowrap transition-all duration-150"
    >
      {label}
    </a>
  );

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Top Navigation */}
      <nav className="fixed top-0 left-0 right-0 z-50 bg-gray-900/95 backdrop-blur-xl border-b border-white/[0.08]">
        <div className={isControlRoom ? 'w-full px-8' : 'max-w-7xl mx-auto px-4'}>
          <div className="flex items-center h-[52px] gap-1">
            <a href={apiBase + '/'} className="text-white font-bold text-base mr-4 whitespace-nowrap tracking-tight no-underline">
              Vantage
            </a>
            <div className="hidden sm:flex items-center gap-0.5 overflow-x-auto flex-1" style={{ scrollbarWidth: 'none' }}>
              {extLink(apiBase + '/', 'Dashboard')}
              {extLink(apiBase + '/camera/secure-stream', 'Camera')}
              <div className="w-px h-5 bg-white/10 mx-1.5 flex-shrink-0" />
              {navLink('/incidents', 'Incidents')}
              {navLink('/patterns', 'Patterns')}
              {navLink('/reports', 'Reports')}
              {navLink('/search', 'Search')}
              {navLink('/metrics', 'Metrics')}
              {navLink('/vehicle-search', 'Vehicles')}
              {navLink('/cameras', 'Cameras')}
              {navLink('/sites', 'Sites')}
              {(hasRole('supervisor') || hasRole('admin')) && navLink('/watchlist', 'Watchlist')}
              {hasRole('admin') && navLink('/settings', 'Settings')}
            </div>
            <div className="flex items-center gap-2.5 ml-auto flex-shrink-0">
              <button
                onClick={toggleLayout}
                className="text-white/40 hover:text-white text-xs px-2.5 py-1 rounded-md border border-white/10 hover:border-white/30 hover:bg-white/5 transition-all duration-150"
                title={isControlRoom ? 'Switch to standard layout' : 'Switch to control room layout'}
              >
                {isControlRoom ? 'Standard' : 'Control Room'}
              </button>
              {user && (
                <>
                  <span className="text-white/50 text-xs font-medium hidden md:inline">{user.username}</span>
                  <span className="text-indigo-400/90 text-[10px] font-semibold uppercase tracking-wider bg-indigo-500/15 px-2 py-0.5 rounded hidden md:inline">
                    {user.role}
                  </span>
                  <button
                    onClick={handleLogout}
                    className="text-white/40 hover:text-white text-xs px-3 py-1 rounded-md border border-white/10 hover:border-white/30 hover:bg-white/5 transition-all duration-150"
                  >
                    Logout
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
      </nav>

      {/* Main Content — pushed below fixed nav */}
      <main className={`pt-[52px] ${isControlRoom ? 'w-full py-6 px-8' : 'max-w-7xl mx-auto py-6 sm:px-6 lg:px-8'}`}>
        {children}
      </main>
    </div>
  );
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/*"
          element={
            <ProtectedRoute>
              <Layout>
                <Routes>
                  <Route path="/" element={<Navigate to="/incidents" replace />} />
                  <Route path="/incidents" element={<IncidentsPage />} />
                  <Route path="/incidents/:id" element={<IncidentDetailPage />} />
                  <Route path="/patterns" element={<PatternsPage />} />
                  <Route path="/reports" element={<ReportsPage />} />
                  <Route path="/metrics" element={<MetricsPage />} />
                  <Route path="/search" element={<SearchPage />} />
                  <Route path="/vehicle-search" element={<VehicleSearchPage />} />
                  <Route path="/cameras" element={<CamerasPage />} />
                  <Route path="/sites" element={<SitesPage />} />
                  <Route path="/watchlist" element={<WatchlistPage />} />
                  <Route path="/settings" element={<SettingsPage />} />
                </Routes>
              </Layout>
            </ProtectedRoute>
          }
        />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
