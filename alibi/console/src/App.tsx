import { BrowserRouter, Routes, Route, Link, Navigate, useNavigate, useLocation } from 'react-router-dom';
import { useState, useEffect } from 'react';
import { IncidentsPage } from './pages/IncidentsPage';
import { IncidentDetailPage } from './pages/IncidentDetailPage';
import { ReportsPage } from './pages/ReportsPage';
import { SettingsPage } from './pages/SettingsPage';
import { LoginPage } from './pages/LoginPage';
import { MetricsPage } from './pages/MetricsPage';
import { VehicleSearchPage } from './pages/VehicleSearchPage';
import { VehicleReviewPage } from './pages/VehicleReviewPage';
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
  const [mobileOpen, setMobileOpen] = useState(false);
  const [openMenu, setOpenMenu] = useState<string | null>(null);   // which desktop dropdown is open

  function handleLogout() {
    logout();
    navigate('/login');
  }

  const isActive = (path: string) => location.pathname === path || location.pathname.startsWith(path + '/');

  const navLink = (to: string, label: string) => (
    <Link
      key={to}
      to={to}
      onClick={() => setMobileOpen(false)}
      className={`${
        isActive(to) ? 'bg-indigo-500/[0.35] text-white' : 'text-white/[0.55] hover:text-white/[0.9] hover:bg-white/[0.08]'
      } px-3 py-1.5 rounded-md text-[13px] font-medium whitespace-nowrap transition-all duration-150`}
    >
      {label}
    </Link>
  );

  // One source of nav truth. 18 destinations don't fit on one row (they clipped),
  // so on desktop they collapse into a few labelled dropdown groups, and on a
  // phone into the hamburger drawer. Role-gates drop items an operator can't see.
  const sup = hasRole('supervisor') || hasRole('admin');
  const adm = hasRole('admin');
  type NavItem = { to: string; label: string };
  const navGroups: { title: string | null; items: NavItem[] }[] = [
    { title: null, items: [{ to: '/overview', label: 'Overview' }] },
    { title: 'Setup', items: [{ to: '/cameras', label: 'Cameras' }, { to: '/recorders', label: 'Recorders' }, { to: '/sites', label: 'Sites' }] },
    { title: 'Intelligence', items: [
      { to: '/advisor', label: 'Advisor' }, { to: '/incidents', label: 'Incidents' },
      { to: '/people', label: 'People' }, { to: '/patterns', label: 'Patterns' },
      { to: '/reports', label: 'Reports' }, { to: '/search', label: 'Search' },
      { to: '/metrics', label: 'Metrics' }, { to: '/vehicle-search', label: 'Vehicles' },
      { to: '/intel', label: 'Intel' },
    ] },
    { title: 'Watchlist', items: sup ? [{ to: '/vehicle-review', label: 'Review' }, { to: '/hotlist', label: 'Hotlist' }, { to: '/faces', label: 'Faces' }] : [] },
    { title: 'Admin', items: adm ? [{ to: '/costs', label: 'Costs' }, { to: '/settings', label: 'Settings' }] : [] },
  ].filter(g => g.title === null || g.items.length > 0);

  // Close any open dropdown / the mobile drawer whenever the route changes.
  useEffect(() => { setOpenMenu(null); setMobileOpen(false); }, [location.pathname]);

  return (
    <div className="min-h-screen vg-app">
      {/* Top Navigation */}
      <nav className="fixed top-0 left-0 right-0 z-50 bg-gray-900/95 backdrop-blur-xl border-b border-white/[0.08]">
        <div className={isControlRoom ? 'w-full px-8' : 'max-w-7xl mx-auto px-4'}>
          <div className="flex items-center h-[52px] gap-1">
            {/* Hamburger — only below sm, where the link row is hidden */}
            <button
              onClick={() => setMobileOpen(o => !o)}
              className="sm:hidden text-white/70 hover:text-white p-1.5 -ml-1 rounded-md hover:bg-white/[0.08]"
              aria-label="Menu" aria-expanded={mobileOpen}
            >
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                {mobileOpen
                  ? <><line x1="6" y1="6" x2="18" y2="18" /><line x1="6" y1="18" x2="18" y2="6" /></>
                  : <><line x1="3" y1="6" x2="21" y2="6" /><line x1="3" y1="12" x2="21" y2="12" /><line x1="3" y1="18" x2="21" y2="18" /></>}
              </svg>
            </button>
            <Link to="/" onClick={() => setMobileOpen(false)} className="text-white font-bold text-base mr-4 whitespace-nowrap tracking-tight no-underline">
              Vantage
            </Link>
            <div className="hidden sm:flex items-center gap-0.5 flex-1">
              {navGroups.map(g => g.title === null
                ? g.items.map(item => navLink(item.to, item.label))
                : (
                  <div key={g.title} className="relative">
                    <button
                      onClick={() => setOpenMenu(openMenu === g.title ? null : g.title)}
                      className={`flex items-center gap-1 px-3 py-1.5 rounded-md text-[13px] font-medium whitespace-nowrap transition-all duration-150 ${
                        g.items.some(it => isActive(it.to)) || openMenu === g.title
                          ? 'bg-indigo-500/[0.35] text-white'
                          : 'text-white/[0.55] hover:text-white/[0.9] hover:bg-white/[0.08]'
                      }`}
                    >
                      {g.title}
                      <svg width="9" height="9" viewBox="0 0 12 12" className="opacity-60"><path d="M2 4l4 4 4-4" stroke="currentColor" strokeWidth="1.6" fill="none" /></svg>
                    </button>
                    {openMenu === g.title && (
                      <div className="absolute left-0 top-full mt-1 min-w-[180px] rounded-lg bg-gray-900 border border-white/10 shadow-xl py-1 z-50 flex flex-col">
                        {g.items.map(item => (
                          <Link key={item.to} to={item.to} onClick={() => setOpenMenu(null)}
                                className={`px-3 py-1.5 text-[13px] whitespace-nowrap no-underline ${
                                  isActive(item.to) ? 'text-white bg-indigo-500/20' : 'text-white/70 hover:text-white hover:bg-white/[0.08]'
                                }`}>
                            {item.label}
                          </Link>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
            </div>
            <div className="flex items-center gap-2.5 ml-auto flex-shrink-0 pl-3 border-l border-white/10 bg-gray-900/95 backdrop-blur-xl">
              <ThemeToggle />
              <button
                onClick={toggleLayout}
                className="hidden sm:inline-flex text-white/40 hover:text-white text-xs px-2.5 py-1 rounded-md border border-white/10 hover:border-white/30 hover:bg-white/5 transition-all duration-150"
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
        {/* Click-away layer that closes an open desktop dropdown. */}
        {openMenu && <div className="hidden sm:block fixed inset-0 z-40" onClick={() => setOpenMenu(null)} />}
        {/* Mobile menu — the link row is hidden below sm, so a phone reaches
            every page through this drawer, grouped by section. Tapping closes it. */}
        {mobileOpen && (
          <div className="sm:hidden border-t border-white/10 bg-gray-900/98 backdrop-blur-xl max-h-[75vh] overflow-y-auto">
            <div className="px-4 py-3 flex flex-col gap-1">
              {navGroups.map((g, gi) => (
                <div key={g.title ?? 'main'} className="flex flex-col gap-1">
                  {gi > 0 && <div className="h-px bg-white/10 my-1.5" />}
                  {g.title && <div className="text-[10px] uppercase tracking-wider text-white/30 px-3 pt-1">{g.title}</div>}
                  {g.items.map(item => navLink(item.to, item.label))}
                </div>
              ))}
            </div>
          </div>
        )}
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
                  <Route path="/vehicle-review" element={<VehicleReviewPage />} />
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
