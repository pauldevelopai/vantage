import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../lib/api';
import { AuthImg } from '../components/AuthImg';
import type { DashboardOverview, DashboardRow } from '../lib/types';

/**
 * The Overview dashboard. Everything here is REAL: KPI counts, the hourly series,
 * the type split, and every still image come from stored camera events. Nothing is
 * mocked — an idle system honestly shows zeros and says why.
 */

const RANGES: Array<{ key: string; label: string }> = [
  { key: '24h', label: 'Last 24 hours' },
  { key: '7d', label: 'Last 7 days' },
  { key: '30d', label: 'Last 30 days' },
];

const TYPE_META: Record<string, { label: string; color: string }> = {
  person_detected: { label: 'Person', color: '#6366f1' },
  vehicle_detected: { label: 'Vehicle', color: '#22d3ee' },
  activity_detected: { label: 'Activity', color: '#a78bfa' },
};

function typeMeta(t: string) {
  return TYPE_META[t] || { label: t.replace(/_/g, ' '), color: '#64748b' };
}

function timeAgo(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso + 'Z').getTime()) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function DashboardPage() {
  const [range, setRange] = useState('24h');
  const [data, setData] = useState<DashboardOverview | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  async function load(r: string) {
    try {
      const d = await api.getDashboardOverview(r);
      setData(d);
      setErr(null);
    } catch (e: any) {
      setErr(e?.message || 'Failed to load the dashboard');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setLoading(true);
    load(range);
    const t = setInterval(() => load(range), 15000);   // live-ish, cheap
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [range]);

  const k = data?.kpis;
  const isEmpty = !!data && (data.kpis.events === 0 && data.cameras.length === 0);

  return (
    <div className="min-h-screen bg-slate-950 -mx-4 -my-6 px-4 py-6 sm:px-6">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="flex flex-wrap items-center justify-between gap-3 mb-5">
          <div>
            <h1 className="text-2xl font-semibold text-white tracking-tight">Overview</h1>
            <p className="text-sm text-slate-400">
              Live intelligence from your cameras — real detections, real evidence.
            </p>
          </div>
          <div className="flex items-center gap-2">
            {RANGES.map(r => (
              <button
                key={r.key}
                onClick={() => setRange(r.key)}
                className={`px-3 py-1.5 text-xs font-medium rounded-md border transition ${
                  range === r.key
                    ? 'bg-indigo-600 border-indigo-500 text-white'
                    : 'bg-slate-900 border-slate-800 text-slate-400 hover:text-slate-200'
                }`}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>

        {err && <div className="mb-4 rounded-lg bg-red-950 border border-red-900 text-red-300 text-sm p-3">{err}</div>}
        {loading && !data && <p className="text-slate-500 py-10">Loading…</p>}

        {data && (
          <>
            {/* KPIs */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
              <Kpi label="Total Events" value={k!.events} accent="text-white" />
              <Kpi label="Alerts" value={k!.alerts} accent={k!.alerts > 0 ? 'text-amber-400' : 'text-white'} />
              <Kpi label="People Detected" value={k!.people} accent="text-indigo-400" />
              <Kpi label="Vehicles Detected" value={k!.vehicles} accent="text-cyan-400" />
            </div>

            {isEmpty && <EmptyState />}

            {!isEmpty && (
              <>
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
                  {/* Camera wall — latest REAL evidence still per camera */}
                  <div className="lg:col-span-2 rounded-xl bg-slate-900 border border-slate-800 p-4">
                    <div className="flex items-center justify-between mb-3">
                      <h2 className="text-sm font-medium text-white">Camera wall</h2>
                      <span className="text-xs text-slate-500">
                        {data.cameras.length} camera{data.cameras.length === 1 ? '' : 's'} · latest evidence frame
                      </span>
                    </div>
                    {data.cameras.length === 0 ? (
                      <p className="text-xs text-slate-500 py-6 text-center">No cameras registered yet.</p>
                    ) : (
                      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                        {data.cameras.map(c => (
                          <div key={c.camera_id} className="rounded-lg overflow-hidden bg-slate-950 border border-slate-800">
                            <div className="relative aspect-video bg-slate-900">
                              {c.latest?.snapshot_url ? (
                                <AuthImg src={c.latest.snapshot_url} alt={c.name} className="w-full h-full object-cover" />
                              ) : (
                                <div className="w-full h-full flex items-center justify-center text-[10px] text-slate-600 text-center px-2">
                                  No detection yet
                                </div>
                              )}
                              {c.latest && (
                                <span className="absolute top-1.5 right-1.5 text-[9px] px-1.5 py-0.5 rounded-full bg-black/70 text-slate-300">
                                  {timeAgo(c.latest.ts)}
                                </span>
                              )}
                            </div>
                            <div className="px-2 py-1.5">
                              <div className="text-[11px] font-medium text-slate-200 truncate">{c.name}</div>
                              {c.latest && (
                                <div className="text-[10px] text-slate-500 truncate">
                                  {c.latest.people > 0 && `${c.latest.people} person${c.latest.people === 1 ? '' : 's'}`}
                                  {c.latest.people > 0 && c.latest.vehicles > 0 && ' · '}
                                  {c.latest.vehicles > 0 && `${c.latest.vehicles} vehicle${c.latest.vehicles === 1 ? '' : 's'}`}
                                  {!c.latest.people && !c.latest.vehicles && typeMeta(c.latest.event_type).label}
                                </div>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Recent alerts */}
                  <div className="rounded-xl bg-slate-900 border border-slate-800 p-4">
                    <h2 className="text-sm font-medium text-white mb-3">Recent alerts</h2>
                    {data.alerts.length === 0 ? (
                      <p className="text-xs text-slate-500 py-6 text-center">
                        No alerts in this window. Alerts are watchlist/hotlist hits and high-severity events.
                      </p>
                    ) : (
                      <ul className="space-y-2">
                        {data.alerts.slice(0, 8).map(a => (
                          <li key={a.event_id} className="flex items-start gap-2">
                            <span className="mt-1 w-1.5 h-1.5 rounded-full bg-amber-400 flex-none" />
                            <div className="min-w-0 flex-1">
                              <div className="text-xs text-slate-200 truncate">
                                {a.watchlist_hit ? `Watchlist match${a.watchlist_label ? `: ${a.watchlist_label}` : ''}`
                                  : a.hotlist_hit ? `Hotlist plate${a.plates[0] ? `: ${a.plates[0]}` : ''}`
                                  : typeMeta(a.event_type).label}
                              </div>
                              <div className="text-[10px] text-slate-500 truncate">
                                {a.camera_name} · {timeAgo(a.ts)}
                              </div>
                            </div>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </div>

                {/* Charts */}
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
                  <div className="lg:col-span-2 rounded-xl bg-slate-900 border border-slate-800 p-4">
                    <h2 className="text-sm font-medium text-white mb-3">Events over time</h2>
                    <AreaChart series={data.over_time} />
                  </div>
                  <div className="rounded-xl bg-slate-900 border border-slate-800 p-4">
                    <h2 className="text-sm font-medium text-white mb-3">Events by type</h2>
                    <Donut items={data.by_type} total={data.kpis.events} />
                  </div>
                </div>

                {/* Recent detections — real stills */}
                <div className="rounded-xl bg-slate-900 border border-slate-800 p-4">
                  <h2 className="text-sm font-medium text-white mb-3">Recent detections</h2>
                  {data.recent.length === 0 ? (
                    <p className="text-xs text-slate-500 py-6 text-center">Nothing detected in this window.</p>
                  ) : (
                    <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3">
                      {data.recent.map(r => <DetectionCard key={r.event_id} row={r} />)}
                    </div>
                  )}
                </div>
              </>
            )}

            <p className="text-[11px] text-slate-600 mt-4">
              Every figure and image above is real data from your cameras · updated {timeAgo(data.generated_at)}
            </p>
          </>
        )}
      </div>
    </div>
  );
}

function Kpi({ label, value, accent }: { label: string; value: number; accent: string }) {
  return (
    <div className="rounded-xl bg-slate-900 border border-slate-800 p-4">
      <div className="text-xs text-slate-400">{label}</div>
      <div className={`text-3xl font-semibold mt-1 tabular-nums ${accent}`}>{value.toLocaleString()}</div>
    </div>
  );
}

function DetectionCard({ row }: { row: DashboardRow }) {
  const flagged = row.watchlist_hit || row.hotlist_hit;
  return (
    <Link to="/incidents" className="group rounded-lg overflow-hidden bg-slate-950 border border-slate-800 hover:border-indigo-600 transition no-underline">
      <div className="relative aspect-video bg-slate-900">
        {row.snapshot_url
          ? <AuthImg src={row.snapshot_url} alt={row.event_type} className="w-full h-full object-cover" />
          : <div className="w-full h-full flex items-center justify-center text-[10px] text-slate-600">no frame</div>}
        {flagged && (
          <span className="absolute top-1.5 left-1.5 text-[9px] px-1.5 py-0.5 rounded-full bg-amber-500 text-black font-medium">
            {row.watchlist_hit ? 'WATCHLIST' : 'HOTLIST'}
          </span>
        )}
        <span className="absolute bottom-1.5 right-1.5 text-[9px] px-1.5 py-0.5 rounded-full bg-black/70 text-slate-300">
          {timeAgo(row.ts)}
        </span>
      </div>
      <div className="px-2 py-1.5">
        <div className="text-[11px] font-medium text-slate-200 truncate">{typeMeta(row.event_type).label}</div>
        <div className="text-[10px] text-slate-500 truncate">{row.camera_name}</div>
        {row.plates.length > 0 && (
          <div className="mt-0.5 text-[9px] font-mono text-cyan-400 truncate">{row.plates.join(', ')}</div>
        )}
      </div>
    </Link>
  );
}

/** Dependency-free area chart over the real hourly series. */
function AreaChart({ series }: { series: Array<{ hour: string; events: number; alerts: number }> }) {
  if (!series.length) return <p className="text-xs text-slate-500 py-10 text-center">No events in this window.</p>;
  const W = 720, H = 180, P = 24;
  const max = Math.max(1, ...series.map(s => s.events));
  const x = (i: number) => P + (i * (W - P * 2)) / Math.max(1, series.length - 1);
  const y = (v: number) => H - P - (v / max) * (H - P * 2);
  const line = series.map((s, i) => `${i ? 'L' : 'M'}${x(i)},${y(s.events)}`).join(' ');
  const area = `${line} L${x(series.length - 1)},${H - P} L${x(0)},${H - P} Z`;
  const alertLine = series.map((s, i) => `${i ? 'L' : 'M'}${x(i)},${y(s.alerts)}`).join(' ');
  return (
    <div className="overflow-x-auto">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full min-w-[420px]" role="img" aria-label="Events over time">
        <defs>
          <linearGradient id="ev" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#6366f1" stopOpacity="0.5" />
            <stop offset="100%" stopColor="#6366f1" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0, 0.5, 1].map(f => (
          <line key={f} x1={P} x2={W - P} y1={y(max * f)} y2={y(max * f)} stroke="#1e293b" strokeWidth="1" />
        ))}
        <path d={area} fill="url(#ev)" />
        <path d={line} fill="none" stroke="#818cf8" strokeWidth="2" />
        <path d={alertLine} fill="none" stroke="#fbbf24" strokeWidth="1.5" strokeDasharray="3 3" />
        <text x={P} y={14} fill="#64748b" fontSize="10">peak {max}/h</text>
      </svg>
      <div className="flex gap-4 mt-1 text-[10px] text-slate-500">
        <span><span className="inline-block w-2 h-2 rounded-full bg-indigo-400 mr-1" />Events</span>
        <span><span className="inline-block w-2 h-2 rounded-full bg-amber-400 mr-1" />Alerts</span>
      </div>
    </div>
  );
}

/** Dependency-free donut over the real type split. */
function Donut({ items, total }: { items: Array<{ type: string; count: number }>; total: number }) {
  if (!items.length || total === 0) return <p className="text-xs text-slate-500 py-10 text-center">No events in this window.</p>;
  const R = 52, C = 2 * Math.PI * R;
  let offset = 0;
  return (
    <div className="flex items-center gap-4">
      <svg viewBox="0 0 140 140" className="w-32 h-32 flex-none" role="img" aria-label="Events by type">
        <g transform="translate(70,70) rotate(-90)">
          <circle r={R} fill="none" stroke="#1e293b" strokeWidth="16" />
          {items.map(it => {
            const frac = it.count / total;
            const dash = `${frac * C} ${C - frac * C}`;
            const el = (
              <circle key={it.type} r={R} fill="none" stroke={typeMeta(it.type).color}
                      strokeWidth="16" strokeDasharray={dash} strokeDashoffset={-offset} />
            );
            offset += frac * C;
            return el;
          })}
        </g>
        <text x="70" y="68" textAnchor="middle" fill="#fff" fontSize="20" fontWeight="600">{total}</text>
        <text x="70" y="83" textAnchor="middle" fill="#64748b" fontSize="9">events</text>
      </svg>
      <ul className="space-y-1.5 min-w-0">
        {items.map(it => (
          <li key={it.type} className="flex items-center gap-2 text-xs">
            <span className="w-2 h-2 rounded-full flex-none" style={{ background: typeMeta(it.type).color }} />
            <span className="text-slate-300 truncate">{typeMeta(it.type).label}</span>
            <span className="text-slate-500 tabular-nums ml-auto">{Math.round((it.count / total) * 100)}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Honest empty state — says exactly why there's nothing, and what to do. */
function EmptyState() {
  return (
    <div className="rounded-xl bg-slate-900 border border-slate-800 p-8 text-center">
      <p className="text-white font-medium">No camera intelligence yet</p>
      <p className="text-sm text-slate-400 mt-2 max-w-xl mx-auto">
        This dashboard only ever shows real detections from your cameras — so it stays empty until
        the recorder sends its first motion frame. Nothing here is simulated.
      </p>
      <div className="mt-4 text-xs text-slate-500">
        Check that a recorder is online on the <Link to="/recorders" className="text-indigo-400 underline">Recorders</Link> page,
        and that your cameras are linked to a site on <Link to="/sites" className="text-indigo-400 underline">Sites</Link>.
      </div>
    </div>
  );
}
