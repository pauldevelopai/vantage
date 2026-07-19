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
import { RecordersPage } from './pages/RecordersPage';
import { DashboardPage } from './pages/DashboardPage';
import { PeoplePage } from './pages/PeoplePage';
import { HotlistPage } from './pages/HotlistPage';
import { AdvisorPage } from './pages/AdvisorPage';
import { SitesPage } from './pages/SitesPage';
import { FacesPage } from './pages/FacesPage';
import { SearchPage } from './pages/SearchPage';
import PatternsPage from './pages/PatternsPage';
import { IntelPage } from './pages/IntelPage';
import { CostsPage } from './pages/CostsPage';
import { isAuthenticated, getUser, logout, hasRole } from './lib/auth';
import { getTheme, initTheme, setTheme, type Theme } from './lib/theme';

initTheme();

/** Icon-only light/dark flip — sun when dark (tap for light), moon when light. */
function ThemeToggle() {
  const [theme, setThemeState] = useState<Theme>(getTheme());
  const flip = () => {
    const next: Theme = theme === 'dark' ? 'light' : 'dark';
    setTheme(next);
    setThemeState(next);
  };
  return (
    <button onClick={flip} aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            title={theme === 'dark' ? 'Light mode' : 'Dark mode'}
            className="text-white/40 hover:text-white p-1.5 rounded-md border border-white/10 hover:border-white/30 hover:bg-white/5 transition-all duration-150">
      {theme === 'dark' ? (
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4m11.4-11.4 1.4-1.4" />
        </svg>
      ) : (
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
        </svg>
      )}
    </button>
  );
}

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

  return (
    <div className="min-h-screen vg-app">
      {/* Top Navigation */}
      <nav className="fixed top-0 left-0 right-0 z-50 bg-gray-900/95 backdrop-blur-xl border-b border-white/[0.08]">
        <div className={isControlRoom ? 'w-full px-8' : 'max-w-7xl mx-auto px-4'}>
          <div className="flex items-center h-[52px] gap-1">
            <Link to="/" className="text-white font-bold text-base mr-4 whitespace-nowrap tracking-tight no-underline">
              Vantage
            </Link>
            <div className="hidden sm:flex items-center gap-0.5 overflow-x-auto flex-1 pr-3" style={{ scrollbarWidth: 'none' }}>
              {/* The at-a-glance view of everything the cameras have seen */}
              {navLink('/overview', 'Overview')}
              <div className="w-px h-5 bg-white/10 mx-1.5 flex-shrink-0" />
              {/* Setup — your cameras, recorders, and what you're protecting */}
              {navLink('/cameras', 'Cameras')}
              {navLink('/recorders', 'Recorders')}
              {navLink('/sites', 'Sites')}
              <div className="w-px h-5 bg-white/10 mx-1.5 flex-shrink-0" />
              {/* Intelligence — AI analysis of the footage */}
              {navLink('/advisor', 'Advisor')}
              {navLink('/incidents', 'Incidents')}
              {navLink('/people', 'People')}
              {navLink('/patterns', 'Patterns')}
              {navLink('/reports', 'Reports')}
              {navLink('/search', 'Search')}
              {navLink('/metrics', 'Metrics')}
              {navLink('/vehicle-search', 'Vehicles')}
              {(hasRole('supervisor') || hasRole('admin')) && navLink('/hotlist', 'Hotlist')}
              {(hasRole('supervisor') || hasRole('admin')) && navLink('/faces', 'Faces')}
              <div className="w-px h-5 bg-white/10 mx-1.5 flex-shrink-0" />
              {/* Data & configuration */}
              {navLink('/intel', 'Intel')}
              {hasRole('admin') && navLink('/costs', 'Costs')}
              {hasRole('admin') && navLink('/settings', 'Settings')}
            </div>
            <div className="flex items-center gap-2.5 ml-auto flex-shrink-0 pl-3 border-l border-white/10 bg-gray-900/95 backdrop-blur-xl">
              <ThemeToggle />
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
                  <Route path="/" element={<Navigate to="/overview" replace />} />
                  <Route path="/overview" element={<DashboardPage />} />
                  <Route path="/incidents" element={<IncidentsPage />} />
                  <Route path="/incidents/:id" element={<IncidentDetailPage />} />
                  <Route path="/advisor" element={<AdvisorPage />} />
                  <Route path="/people" element={<PeoplePage />} />
                  <Route path="/patterns" element={<PatternsPage />} />
                  <Route path="/reports" element={<ReportsPage />} />
                  <Route path="/metrics" element={<MetricsPage />} />
                  <Route path="/search" element={<SearchPage />} />
                  <Route path="/vehicle-search" element={<VehicleSearchPage />} />
                  <Route path="/hotlist" element={<HotlistPage />} />
                  <Route path="/cameras" element={<CamerasPage />} />
                  <Route path="/recorders" element={<RecordersPage />} />
                  <Route path="/sites" element={<SitesPage />} />
                  <Route path="/intel" element={<IntelPage />} />
                  <Route path="/costs" element={<CostsPage />} />
                  <Route path="/faces" element={<FacesPage />} />
                  {/* old bookmarks keep working */}
                  <Route path="/watchlist" element={<Navigate to="/faces" replace />} />
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
