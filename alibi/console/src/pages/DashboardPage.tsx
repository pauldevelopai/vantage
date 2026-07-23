import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../lib/api';
import { hasRole } from '../lib/auth';
import { AuthImg } from '../components/AuthImg';
import { CropImg } from '../components/CropImg';
import { WINDOWS, windowPhrase, type Win } from '../components/TimeWindow';
import { VehicleHistoryModal } from '../components/VehicleHistoryModal';
import type { DashboardOverview, DashboardPatterns, DashboardPerson, DashboardRow, DashboardVehicle, FieldReport, PatternFinding, RecurringVehicle, WatchingFor } from '../lib/types';

/**
 * The Overview dashboard — the tab shown to clients.
 *
 * Everything here is REAL: KPI counts, the hourly series, the type split, and
 * every still come from stored camera events. The motion is presentation only —
 * numbers roll to their true value, charts draw themselves in, live things pulse.
 * An idle system animates its way to an honest zero. We never invent a figure to
 * make the page look busier.
 */

// The four the whole system offers (incl. All time). Styling stays bespoke to
// this dark control-room header; only the vocabulary is shared.
const RANGES = WINDOWS.map(w => ({ key: w.key, label: w.short, title: w.label }));

const TYPE_META: Record<string, { label: string; color: string }> = {
  person_detected: { label: 'Person', color: '#818cf8' },
  vehicle_detected: { label: 'Vehicle', color: '#22d3ee' },
  activity_detected: { label: 'Activity', color: '#a78bfa' },
};

function typeMeta(t: string) {
  return TYPE_META[t] || { label: t.replace(/_/g, ' '), color: '#64748b' };
}

function timeAgo(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso.endsWith('Z') ? iso : iso + 'Z').getTime()) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

/** Roll a number to its real value. The destination is always the true figure. */
function useCountUp(target: number, ms = 900): number {
  const [n, setN] = useState(target);
  const from = useRef(target);
  useEffect(() => {
    const start = performance.now();
    const a = from.current;
    const b = target;
    if (a === b) return;
    let raf = 0;
    const tick = (now: number) => {
      const p = Math.min(1, (now - start) / ms);
      const eased = 1 - Math.pow(1 - p, 3);       // easeOutCubic
      setN(Math.round(a + (b - a) * eased));
      if (p < 1) raf = requestAnimationFrame(tick);
      else from.current = b;
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, ms]);
  return n;
}

const CSS = `
@keyframes vg-pulse { 0%,100% { opacity:1; transform:scale(1) } 50% { opacity:.35; transform:scale(.82) } }
@keyframes vg-sweep { 0% { transform:translateX(-100%) } 100% { transform:translateX(300%) } }
@keyframes vg-rise  { from { opacity:0; transform:translateY(10px) } to { opacity:1; transform:translateY(0) } }
@keyframes vg-draw  { from { stroke-dashoffset: 2000 } to { stroke-dashoffset: 0 } }
@keyframes vg-glow  { 0%,100% { opacity:.35 } 50% { opacity:.75 } }
.vg-live   { animation: vg-pulse 1.8s ease-in-out infinite }
.vg-rise   { animation: vg-rise .5s cubic-bezier(.2,.7,.3,1) both }
.vg-draw   { stroke-dasharray: 2000; animation: vg-draw 1.6s cubic-bezier(.2,.7,.3,1) forwards }
.vg-glow   { animation: vg-glow 3.2s ease-in-out infinite }
.vg-scan::after {
  content:''; position:absolute; inset:0; pointer-events:none;
  background:linear-gradient(90deg,transparent,rgba(129,140,248,.10),transparent);
  animation: vg-sweep 3.5s ease-in-out infinite;
}
.vg-grid {
  background-image:
    linear-gradient(rgba(99,102,241,.055) 1px, transparent 1px),
    linear-gradient(90deg, rgba(99,102,241,.055) 1px, transparent 1px);
  background-size: 46px 46px;
}
@media (prefers-reduced-motion: reduce) {
  .vg-live,.vg-rise,.vg-draw,.vg-glow,.vg-scan::after { animation: none }
  .vg-draw { stroke-dasharray: none }
}
`;

export function DashboardPage() {
  const [range, setRange] = useState<Win>('24h');
  const [vehicleHistory, setVehicleHistory] = useState<string | null>(null);
  const [logReport, setLogReport] = useState(false);
  const [data, setData] = useState<DashboardOverview | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [beat, setBeat] = useState(0);

  async function load(r: string) {
    try {
      const d = await api.getDashboardOverview(r);
      setData(d);
      setErr(null);
      setBeat(b => b + 1);
    } catch (e: any) {
      setErr(e?.message || 'Failed to load the dashboard');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setLoading(true);
    load(range);
    const t = setInterval(() => load(range), 15000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [range]);

  const k = data?.kpis;
  const isEmpty = !!data && data.kpis.events === 0 && data.cameras.length === 0;

  return (
    <div className="min-h-screen bg-[#070912] vg-grid -mx-4 -my-6 px-4 py-6 sm:px-6">
      <style>{CSS}</style>
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="flex flex-wrap items-center justify-between gap-3 mb-5 vg-rise">
          <div>
            <div className="flex items-center gap-2.5">
              <h1 className="text-2xl font-semibold text-white tracking-tight">Overview</h1>
              <span className="flex items-center gap-1.5 text-[10px] font-medium tracking-widest text-emerald-400 uppercase">
                <span className="vg-live w-1.5 h-1.5 rounded-full bg-emerald-400 shadow-[0_0_8px_2px_rgba(52,211,153,.7)]" />
                Live
              </span>
            </div>
            <p className="text-sm text-slate-500">
              Real detections from your cameras, {windowPhrase(range)} · updated {data ? timeAgo(data.generated_at) : '…'}
            </p>
            <p className="mt-1 text-xs">
              <Link to="/advisor" className="text-indigo-400 hover:text-indigo-300 no-underline">
                What needs attention →
              </Link>
              <Link to="/search" className="ml-4 text-slate-500 hover:text-slate-300 no-underline">Search</Link>
              <Link to="/metrics" className="ml-4 text-slate-500 hover:text-slate-300 no-underline">Metrics</Link>
            </p>
          </div>
          <div className="flex items-center gap-1 p-1 rounded-lg bg-slate-900/70 border border-slate-800">
            {RANGES.map(r => (
              <button
                key={r.key}
                title={r.title}
                onClick={() => setRange(r.key as Win)}
                className={`px-3 py-1 text-xs font-semibold tracking-wide rounded-md transition-all duration-200 ${
                  range === r.key
                    ? 'bg-indigo-500 text-white shadow-[0_0_16px_-2px_rgba(99,102,241,.8)]'
                    : 'text-slate-500 hover:text-slate-200'
                }`}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>

        {err && <div className="mb-4 rounded-lg bg-red-950/60 border border-red-900 text-red-300 text-sm p-3">{err}</div>}
        {loading && !data && <SkeletonRow />}

        {data && (
          <>
            {/* KPIs */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
              <Link to="/patterns" className="no-underline">
                <Kpi label="Total Events" value={k!.events} tint="#818cf8" delay={0} sub="patterns →" />
              </Link>
              <Link to="/incidents" className="no-underline">
                <Kpi label="Incidents" value={k!.alerts} tint={k!.alerts > 0 ? '#fbbf24' : '#64748b'} delay={60} alert={k!.alerts > 0} sub="incidents →" />
              </Link>
              <Link to="/people" className="no-underline">
                <Kpi label="People Detected" value={k!.people} tint="#6366f1" delay={120} sub="people →" />
              </Link>
              <Link to="/vehicle-search" className="no-underline">
                <Kpi label={k!.vehicles_distinct !== null ? 'Distinct Vehicles' : 'Vehicles Detected'}
                     value={k!.vehicles_distinct !== null ? k!.vehicles_distinct : k!.vehicles}
                     sub={k!.vehicles_distinct !== null ? `${k!.vehicles.toLocaleString()} sightings · vehicles →` : 'vehicles →'}
                     tint="#22d3ee" delay={180} />
              </Link>
            </div>

            {isEmpty && <EmptyState />}

            {!isEmpty && (
              <>
                {/* Situations — did anything happen? The loudest surface on the
                    page. The machine flags "needs review"; only a HUMAN turns
                    that into "confirmed: attempted break-in", with their name
                    on it. */}
                <Panel className="mb-4" delay={190}>
                  <div className="flex items-center justify-between mb-3">
                    <h2 className="text-[11px] font-semibold text-slate-300 uppercase tracking-[0.14em]">Alerts · top 10</h2>
                    <div className="flex items-center gap-3">
                      <span className="text-[10px] text-slate-600 font-mono hidden sm:inline">ranked by importance · most notable first</span>
                      <Link to="/incidents" className="text-[10px] text-indigo-400 hover:text-indigo-300 no-underline">all incidents →</Link>
                    </div>
                  </div>
                  <SituationsPanel situations={data.situations || []} total={data.alerts_total}
                                   onChanged={() => load(range)}
                                   onOpenVehicle={(eid) => setVehicleHistory(eid)} />
                </Panel>

                {/* Your vehicles — the persistent list of cars you've named. It
                    stays here for good (that's where a just-named car "goes"),
                    visible even when it hasn't been seen lately. */}
                {(data.named_vehicles?.length ?? 0) > 0 && (
                  <Panel className="mb-4" delay={193}>
                    <div className="flex items-center justify-between mb-3">
                      <h2 className="text-[11px] font-semibold text-slate-300 uppercase tracking-[0.14em]">Your vehicles</h2>
                      <span className="text-[10px] text-slate-600 font-mono hidden sm:inline">named &amp; remembered · kept even when idle</span>
                    </div>
                    <NamedVehiclesPanel vehicles={data.named_vehicles || []}
                                        onOpen={(eid) => setVehicleHistory(eid)} />
                  </Panel>
                )}

                {/* Out of the ordinary — the cars that are NOT the usual scene,
                    with how often each came down the road and when. Residents,
                    regulars and named vehicles are excluded by definition. */}
                {(data.out_of_ordinary_vehicles?.length ?? 0) > 0 && (
                  <Panel className="mb-4" delay={195}>
                    <div className="flex items-center justify-between mb-3">
                      <h2 className="text-[11px] font-semibold text-slate-300 uppercase tracking-[0.14em]">Out of the ordinary</h2>
                      <span className="text-[10px] text-slate-600 font-mono hidden sm:inline">not one of the usual cars · how often &amp; when</span>
                    </div>
                    <OutOfOrdinaryPanel vehicles={data.out_of_ordinary_vehicles || []}
                                        onOpen={(eid) => setVehicleHistory(eid)} />
                  </Panel>
                )}

                {/* What we're watching for — up top, because "what is this
                    system looking for" is the first client question. Never
                    framed as crimes: situations worth review, honestly stated. */}
                {data.watching_for && data.watching_for.triggers.length > 0 && (
                  <Panel className="mb-4" delay={200}>
                    <PanelHead title="Watching for"
                               right={`${data.watching_for.posture_label.toLowerCase()} · ${data.watching_for.site_name}`} />
                    <WatchingForPanel wf={data.watching_for} />
                  </Panel>
                )}

                <Panel className="mb-4" delay={210}>
                  <div className="flex items-center justify-between mb-3">
                    <h2 className="text-[11px] font-semibold text-slate-300 uppercase tracking-[0.14em]">Reports from the ground</h2>
                    <Link to="/reports" className="text-[10px] text-indigo-400 hover:text-indigo-300 no-underline mr-2">
                      all reports →
                    </Link>
                    <button onClick={() => setLogReport(true)}
                            className="text-[10px] text-indigo-400 hover:text-indigo-300 border border-indigo-500/30 hover:border-indigo-400/60 rounded px-2 py-0.5">
                      + Log a report
                    </button>
                  </div>
                  <FieldReportsList reports={data.field_reports || []} />
                </Panel>

                <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
                  <Panel className="lg:col-span-2" delay={220}>
                    <div className="flex items-center justify-between mb-3">
                      <h2 className="text-[11px] font-semibold text-slate-300 uppercase tracking-[0.14em]">Camera wall</h2>
                      <div className="flex items-center gap-3">
                        <span className="text-[10px] text-slate-600 font-mono">{data.cameras.length} camera{data.cameras.length === 1 ? '' : 's'} · latest evidence</span>
                        <Link to="/cameras" className="text-[10px] text-indigo-400 hover:text-indigo-300 no-underline">manage →</Link>
                      </div>
                    </div>
                    {data.cameras.length === 0 ? (
                      <p className="text-xs text-slate-600 py-8 text-center">No cameras registered yet.</p>
                    ) : (
                      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                        {data.cameras.map((c, i) => (
                          <div key={c.camera_id}
                               className="vg-rise group relative rounded-lg overflow-hidden bg-black border border-slate-800 hover:border-indigo-500/70 transition-all duration-300"
                               style={{ animationDelay: `${260 + i * 60}ms` }}>
                            <div className="relative aspect-video bg-slate-900 vg-scan">
                              {c.latest?.snapshot_url ? (
                                <AuthImg src={c.latest.snapshot_url} alt={c.name}
                                         className="w-full h-full object-cover opacity-90 group-hover:opacity-100 group-hover:scale-[1.04] transition-all duration-500" />
                              ) : (
                                <div className="w-full h-full flex items-center justify-center text-[10px] text-slate-700">
                                  awaiting detection
                                </div>
                              )}
                              <div className="absolute inset-0 bg-gradient-to-t from-black/85 via-transparent to-transparent" />
                              {c.latest && (
                                <span className="absolute top-1.5 right-1.5 text-[9px] px-1.5 py-0.5 rounded bg-black/80 text-slate-300 font-mono">
                                  {timeAgo(c.latest.ts)}
                                </span>
                              )}
                              <div className="absolute bottom-0 left-0 right-0 px-2 py-1.5">
                                <div className="text-[11px] font-medium text-white truncate">{c.name}</div>
                                {c.latest && (
                                  <div className="text-[9px] text-slate-400 truncate">
                                    {c.latest.people > 0 && `${c.latest.people} person${c.latest.people === 1 ? '' : 's'}`}
                                    {c.latest.people > 0 && c.latest.vehicles > 0 && ' · '}
                                    {c.latest.vehicles > 0 && `${c.latest.vehicles} vehicle${c.latest.vehicles === 1 ? '' : 's'}`}
                                    {!c.latest.people && !c.latest.vehicles && typeMeta(c.latest.event_type).label}
                                  </div>
                                )}
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </Panel>

                  <Panel delay={280}>
                    <PanelHead title="Watchlist & hotlist" />
                    {data.alerts.length === 0 ? (
                      <p className="text-xs text-slate-600 py-8 text-center leading-relaxed">
                        No watchlist or hotlist matches in this window.
                      </p>
                    ) : (
                      <ul className="space-y-2">
                        {data.alerts.slice(0, 8).map((a, i) => (
                          <li key={a.event_id} className="vg-rise flex items-start gap-2"
                              style={{ animationDelay: `${320 + i * 50}ms` }}>
                            <span className="vg-live mt-1 w-1.5 h-1.5 rounded-full bg-amber-400 flex-none shadow-[0_0_6px_1px_rgba(251,191,36,.8)]" />
                            <div className="min-w-0 flex-1">
                              <div className="text-xs text-slate-200 truncate">
                                {a.watchlist_hit ? `Watchlist match${a.watchlist_label ? `: ${a.watchlist_label}` : ''}`
                                  : a.hotlist_hit ? `Hotlist plate${a.plates[0] ? `: ${a.plates[0]}` : ''}`
                                  : typeMeta(a.event_type).label}
                              </div>
                              <div className="text-[10px] text-slate-500 truncate">{a.camera_name} · {timeAgo(a.ts)}</div>
                            </div>
                          </li>
                        ))}
                      </ul>
                    )}
                  </Panel>
                </div>

                {data.recent_people?.length > 0 && (
                  <Panel className="mb-4" delay={300}>
                    <div className="flex items-center justify-between mb-3">
                      <h2 className="text-[11px] font-semibold text-slate-300 uppercase tracking-[0.14em]">People seen</h2>
                      <div className="flex items-center gap-3">
                        <span className="text-[10px] text-slate-600 font-mono hidden sm:inline">enrolled people are named, strangers never are</span>
                        <Link to="/people" className="text-[10px] text-indigo-400 hover:text-indigo-300 no-underline">
                          full history →
                        </Link>
                      </div>
                    </div>
                    <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-6 gap-3">
                      {data.recent_people.map((p, i) => (
                        <PersonCard key={p.sighting_id} p={p} i={i} onEnrolled={() => load(range)} />
                      ))}
                    </div>
                  </Panel>
                )}

                {data.recent_vehicles?.length > 0 && (
                  <Panel className="mb-4" delay={310}>
                    <div className="flex items-center justify-between mb-3">
                      <h2 className="text-[11px] font-semibold text-slate-300 uppercase tracking-[0.14em]">Vehicles seen</h2>
                      <div className="flex items-center gap-3">
                        <span className="text-[10px] text-slate-600 font-mono hidden sm:inline">details only when read from the image</span>
                        <Link to="/vehicle-search" className="text-[10px] text-indigo-400 hover:text-indigo-300 no-underline">all vehicles →</Link>
                      </div>
                    </div>
                    <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3">
                      {data.recent_vehicles.map((v, i) => <VehicleCard key={`${v.event_id}-${i}`} v={v} i={i} />)}
                    </div>
                  </Panel>
                )}

                {data.patterns && (
                  <Panel className="mb-4" delay={315}>
                    <PanelHeadLinked title="Activity patterns" linkTo="/patterns" linkLabel="full patterns →"
                               right={data.patterns.busiest_hour !== null
                                 ? `busiest ${String(data.patterns.busiest_hour).padStart(2, '0')}:00–${String((data.patterns.busiest_hour + 1) % 24).padStart(2, '0')}:00 · ${data.patterns.busiest_camera || ''}`
                                 : 'no activity in this window'} />
                    <PatternsHeatmap p={data.patterns} />
                    {data.pattern_findings?.length > 0 && (
                      <div className="mt-4 pt-3 border-t border-slate-800/70">
                        <h3 className="text-[10px] font-semibold text-slate-400 uppercase tracking-[0.14em] mb-2">
                          What's happening <span className="text-slate-600 normal-case tracking-normal">— familiar vs new, from your own cameras</span>
                        </h3>
                        <FindingsList findings={data.pattern_findings} />
                      </div>
                    )}
                    {data.recurring_vehicles?.length > 0 && (
                      <div className="mt-4 pt-3 border-t border-slate-800/70">
                        <h3 className="text-[10px] font-semibold text-slate-400 uppercase tracking-[0.14em] mb-2">
                          Recurring vehicles <span className="text-slate-600 normal-case tracking-normal">— linked by appearance · name yours and it reads as familiar</span>
                        </h3>
                        <ul className="space-y-1.5">
                          {data.recurring_vehicles.map(v => (
                            <RecurringVehicleRow key={v.entity_id} v={v} onSaved={() => load(range)}
                                                 onOpen={() => setVehicleHistory(v.entity_id)} />
                          ))}
                        </ul>
                      </div>
                    )}
                  </Panel>
                )}

                {data.security_suggestions?.length > 0 && (
                  <Panel className="mb-4" delay={318}>
                    <PanelHead title="Improve your security"
                               right="from this system's own gaps · disappears when fixed" />
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      {data.security_suggestions.map(sg => (
                        <div key={sg.title} className="rounded-lg border border-slate-800 bg-black/30 p-3">
                          <div className="text-xs font-medium text-slate-200">{sg.title}</div>
                          <p className="mt-1 text-[11px] text-slate-500 leading-relaxed">{sg.why}</p>
                          <Link to={sg.link} className="mt-1.5 inline-block text-[11px] text-indigo-400 hover:text-indigo-300 no-underline">
                            {sg.action} →
                          </Link>
                        </div>
                      ))}
                    </div>
                  </Panel>
                )}

                <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
                  <Panel className="lg:col-span-2" delay={320}>
                    <PanelHead title="Events over time" />
                    <AreaChart key={`${range}-${beat}`} series={data.over_time} />
                  </Panel>
                  <Panel delay={360}>
                    <PanelHead title="Events by type" />
                    <Donut items={data.by_type} total={data.kpis.events} />
                  </Panel>
                </div>

                <Panel delay={400}>
                  <PanelHead title="Recent detections" right={`${data.recent.length} shown`} />
                  {data.recent.length === 0 ? (
                    <p className="text-xs text-slate-600 py-8 text-center">Nothing detected in this window.</p>
                  ) : (
                    <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3">
                      {data.recent.map((r, i) => <DetectionCard key={r.event_id} row={r} i={i} />)}
                    </div>
                  )}
                </Panel>
              </>
            )}

            <p className="text-[11px] text-slate-700 mt-4 text-center tracking-wide">
              Every figure and image above is real data from your cameras
            </p>
          </>
        )}
      </div>
      {vehicleHistory && (
        <VehicleHistoryModal entityId={vehicleHistory} onClose={() => setVehicleHistory(null)}
                             onSaved={() => { setVehicleHistory(null); load(range); }} />
      )}
      {logReport && (
        <LogReportModal cameras={(data?.cameras || []).map(c => ({ id: c.camera_id, name: c.name }))}
                        onClose={() => setLogReport(false)}
                        onSaved={() => { setLogReport(false); load(range); }} />
      )}
    </div>
  );
}

/** Recent human observations, newest first, each with a corroboration badge
 *  when a camera sighting backs it up. Honest empty state. */
function FieldReportsList({ reports }: { reports: FieldReport[] }) {
  if (reports.length === 0) {
    return <p className="text-xs text-slate-600 py-3">No reports yet. A guard or operator can log what they see — it sits beside the camera data.</p>;
  }
  const icon: Record<string, string> = { vehicle: '🚗', person: '🚶', other: '📍' };
  return (
    <ul className="space-y-2">
      {reports.map(r => (
        <li key={r.report_id} className="flex items-start gap-2 text-xs">
          <span className="text-sm leading-none mt-0.5">{icon[r.subject] || '📍'}</span>
          <div className="min-w-0 flex-1">
            <div className="text-slate-300">{r.note}</div>
            <div className="text-[10px] text-slate-500">
              {r.observer}{r.camera_name ? ` · ${r.camera_name}` : r.location ? ` · ${r.location}` : ''} · {timeAgo(r.ts)}
              {r.corroboration && (
                <span className="ml-1 text-emerald-400" title={`Camera sighting at ${r.corroboration.camera_name || ''}`}>
                  ✓ camera corroborates
                </span>
              )}
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}

/** Log a field report — a guard/operator observation. Situational, not a verdict. */
function LogReportModal({ cameras, onClose, onSaved }:
                        { cameras: Array<{ id: string; name: string }>; onClose: () => void; onSaved: () => void }) {
  const [subject, setSubject] = useState('vehicle');
  const [note, setNote] = useState('');
  const [cameraId, setCameraId] = useState('');
  const [colour, setColour] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function save() {
    if (!note.trim()) { setErr('Describe what you saw'); return; }
    setBusy(true); setErr(null);
    try {
      const tags: Record<string, string> = {};
      if (colour.trim()) tags.colour = colour.trim();
      await api.submitFieldReport({ subject, note: note.trim(), camera_id: cameraId || undefined, tags });
      onSaved();
    } catch (e: any) { setErr(e?.message || 'Failed to log'); } finally { setBusy(false); }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div className="bg-slate-900 border border-slate-700 rounded-xl shadow-xl max-w-md w-full" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between p-4 border-b border-slate-800">
          <h2 className="text-sm font-semibold text-white">Log a report</h2>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-300 text-sm">✕</button>
        </div>
        <div className="p-4 space-y-3">
          <div className="flex gap-2">
            {['vehicle', 'person', 'other'].map(s => (
              <button key={s} onClick={() => setSubject(s)}
                      className={`px-2.5 py-1 text-xs rounded ${subject === s ? 'bg-indigo-500 text-white' : 'bg-slate-800 text-slate-400'}`}>
                {s}
              </button>
            ))}
          </div>
          <textarea autoFocus value={note} onChange={e => setNote(e.target.value)} rows={3}
                    placeholder="e.g. White bakkie, no plate, parked at the north gate ~02:00, left after 20 min"
                    className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1.5 text-xs text-slate-200 placeholder:text-slate-600 focus:border-indigo-500 outline-none" />
          <div className="flex gap-2">
            <select value={cameraId} onChange={e => setCameraId(e.target.value)}
                    className="flex-1 bg-slate-950 border border-slate-700 rounded px-2 py-1 text-xs text-slate-300">
              <option value="">Location / camera (optional)</option>
              {cameras.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
            {subject === 'vehicle' && (
              <input value={colour} onChange={e => setColour(e.target.value)} placeholder="colour"
                     className="w-24 bg-slate-950 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200 placeholder:text-slate-600" />
            )}
          </div>
          {err && <div className="text-xs text-red-400">{err}</div>}
          <div className="flex justify-end gap-2">
            <button onClick={onClose} className="text-xs text-slate-500 px-2">Cancel</button>
            <button onClick={save} disabled={busy}
                    className="text-xs bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded px-3 py-1.5">
              {busy ? 'Saving…' : 'Log report'}
            </button>
          </div>
          <p className="text-[10px] text-slate-600">Kept as evidence beside the camera data. Situational — never an accusation.</p>
        </div>
      </div>
    </div>
  );
}



function Panel({ children, className = '', delay = 0 }:
               { children: React.ReactNode; className?: string; delay?: number }) {
  return (
    <div className={`vg-rise relative rounded-xl bg-slate-900/60 border border-slate-800/80 backdrop-blur p-4 ${className}`}
         style={{ animationDelay: `${delay}ms` }}>
      {children}
    </div>
  );
}

function PanelHead({ title, right }: { title: string; right?: string }) {
  return (
    <div className="flex items-center justify-between mb-3">
      <h2 className="text-[11px] font-semibold text-slate-300 uppercase tracking-[0.14em]">{title}</h2>
      {right && <span className="text-[10px] text-slate-600 font-mono">{right}</span>}
    </div>
  );
}

function PanelHeadLinked({ title, right, linkTo, linkLabel }:
                         { title: string; right?: string; linkTo: string; linkLabel: string }) {
  return (
    <div className="flex items-center justify-between mb-3">
      <h2 className="text-[11px] font-semibold text-slate-300 uppercase tracking-[0.14em]">{title}</h2>
      <div className="flex items-center gap-3">
        {right && <span className="text-[10px] text-slate-600 font-mono hidden sm:inline">{right}</span>}
        <Link to={linkTo} className="text-[10px] text-indigo-400 hover:text-indigo-300 no-underline">{linkLabel}</Link>
      </div>
    </div>
  );
}

function Kpi({ label, value, tint, delay, alert, sub }:
             { label: string; value: number; tint: string; delay: number; alert?: boolean; sub?: string }) {
  const shown = useCountUp(value);
  return (
    <div className="vg-rise relative rounded-xl bg-slate-900/60 border border-slate-800/80 backdrop-blur p-4 overflow-hidden"
         style={{ animationDelay: `${delay}ms` }}>
      <div className="vg-glow absolute -top-16 -right-10 w-32 h-32 rounded-full blur-3xl"
           style={{ background: tint, opacity: 0.35 }} />
      <div className="relative">
        <div className="text-[10px] text-slate-500 uppercase tracking-[0.14em]">{label}</div>
        <div className="flex items-baseline gap-2 mt-1">
          <span className="text-4xl font-semibold tabular-nums tracking-tight"
                style={{ color: tint, textShadow: `0 0 22px ${tint}55` }}>
            {shown.toLocaleString()}
          </span>
          {alert && <span className="vg-live w-2 h-2 rounded-full bg-amber-400" />}
        </div>
        {sub && <div className="text-[10px] text-slate-500 mt-0.5">{sub}</div>}
      </div>
      <div className="absolute bottom-0 left-0 h-[2px] w-full opacity-70"
           style={{ background: `linear-gradient(90deg, ${tint}, transparent)` }} />
    </div>
  );
}

/** "since Tue" for a recent first sighting, "since 9 Jul" for an older one. */
function sinceLabel(iso: string): string {
  const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z');
  const days = (Date.now() - d.getTime()) / 86400000;
  if (days < 1) return 'today';
  if (days < 7) return `since ${d.toLocaleDateString(undefined, { weekday: 'short' })}`;
  return `since ${d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })}`;
}

/**
 * One person on the strip. The boundary this card must hold: an enrolled person
 * shows their real name; a stranger shows CONTINUITY ("seen 4× since Tue") and
 * is labelled "Unknown person" — we never guess who a stranger is. The only way
 * a stranger becomes named is the owner enrolling them ("Add to Faces").
 */
function PersonCard({ p, i, onEnrolled }: { p: DashboardPerson; i: number; onEnrolled: () => void }) {
  const enrolled = !!p.matched_label;
  const isFace = p.source !== 'detection' && !!p.sighting_id;
  // Enrolment needs a face embedding — a body-only detection has none.
  const canEnroll = isFace && (hasRole('supervisor') || hasRole('admin'));
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState('');
  const [details, setDetails] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function enrol() {
    if (!name.trim() || !p.sighting_id) return;
    setBusy(true);
    setErr(null);
    try {
      await api.enrollFaceFromSighting(p.sighting_id, name.trim(), details.trim());
      setNaming(false);
      onEnrolled();
    } catch (e: any) {
      setErr(e?.message || 'Enrolment failed');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="vg-rise group rounded-lg overflow-hidden bg-black border border-slate-800 hover:border-indigo-500/70 transition-all duration-300"
         style={{ animationDelay: `${340 + i * 40}ms` }}>
      <CropLink incidentId={p.incident_id} className="relative block aspect-square bg-slate-900">
        <CropImg src={p.frame_url} alt={enrolled ? p.matched_label! : 'Person'}
                 bbox={p.bbox as [number, number, number, number]} pad={isFace ? 0.45 : 0.2}
                 className="w-full h-full" />
        <span className="absolute bottom-1 right-1.5 text-[8px] px-1 py-0.5 rounded bg-black/80 text-slate-400 font-mono">
          {timeAgo(p.ts)}
        </span>
        {p.incident_id && (
          <span className="absolute top-1 right-1.5 text-[8px] px-1 py-0.5 rounded bg-black/70 text-indigo-300">details →</span>
        )}
      </CropLink>
      <div className="px-2 py-1.5 border-t border-slate-800/70">
        <div className={`text-[11px] font-medium truncate ${enrolled ? 'text-emerald-300' : 'text-slate-200'}`}>
          {enrolled ? p.matched_label : isFace ? 'Unknown person' : 'Person'}
        </div>
        <div className="text-[9px] text-slate-500 truncate">
          {isFace
            ? (p.times_seen > 1 ? `seen ${p.times_seen}× ${sinceLabel(p.first_seen!)}` : 'first sighting')
            : 'no face captured'}
        </div>
        <div className="text-[9px] text-slate-600 truncate">{p.camera_name}</div>
        {isFace && (
          <Link to="/people" className="text-[9px] text-indigo-400 hover:text-indigo-300 no-underline">
            history →
          </Link>
        )}
        {!enrolled && canEnroll && !naming && (
          <button onClick={() => setNaming(true)}
                  className="mt-1 w-full text-[9px] font-medium text-indigo-400 hover:text-indigo-300 border border-indigo-500/30 hover:border-indigo-400/60 rounded px-1 py-0.5 transition-colors">
            Add to Faces
          </button>
        )}
        {naming && (
          <div className="mt-1 space-y-1">
            <input autoFocus value={name}
                   onChange={e => setName(e.target.value)}
                   onKeyDown={e => { if (e.key === 'Enter') enrol(); if (e.key === 'Escape') setNaming(false); }}
                   placeholder="Their name"
                   className="w-full bg-slate-900 border border-slate-700 rounded px-1 py-0.5 text-[10px] text-slate-200 placeholder:text-slate-600 focus:border-indigo-500 outline-none" />
            <input value={details}
                   onChange={e => setDetails(e.target.value)}
                   onKeyDown={e => { if (e.key === 'Enter') enrol(); if (e.key === 'Escape') setNaming(false); }}
                   placeholder="Details (optional)"
                   className="w-full bg-slate-900 border border-slate-700 rounded px-1 py-0.5 text-[10px] text-slate-200 placeholder:text-slate-600 focus:border-indigo-500 outline-none" />
            <div className="flex gap-1">
              <button onClick={enrol} disabled={busy || !name.trim()}
                      className="flex-1 text-[9px] font-medium bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded px-1 py-0.5">
                {busy ? '…' : 'Enrol'}
              </button>
              <button onClick={() => { setNaming(false); setErr(null); }}
                      className="text-[9px] text-slate-500 hover:text-slate-300 px-1">
                Cancel
              </button>
            </div>
            {err && <div className="text-[8px] text-red-400 truncate" title={err}>{err}</div>}
          </div>
        )}
      </div>
    </div>
  );
}

const TIER_META = {
  confirmed: { label: 'CONFIRMED', badge: 'bg-red-500 text-white', border: 'border-red-500/60', glow: 'shadow-[0_0_24px_-6px_rgba(239,68,68,.8)]' },
  review:    { label: 'NEEDS REVIEW', badge: 'bg-amber-400 text-black', border: 'border-amber-500/60', glow: 'shadow-[0_0_24px_-6px_rgba(251,191,36,.7)]' },
  noted:     { label: 'NOTED', badge: 'bg-slate-700 text-slate-300', border: 'border-slate-800', glow: '' },
} as const;

// When NO vision model ran, the basic-CV fallback writes a pixel-statistics
// string ("High activity or complex scene detected"). That is not a description
// of anything — never show it as if it were one.
const GENERIC_DESCRIPTIONS = [
  'static scene, very low activity',
  'calm scene with minimal movement',
  'moderate activity detected',
  'high activity or complex scene detected',
];
function realDesc(d?: string | null): string | null {
  const t = (d || '').trim();
  if (!t) return null;
  return GENERIC_DESCRIPTIONS.includes(t.toLowerCase()) ? null : t;
}

// Criteria-signal badges — things the system surfaces "worth a look" against our
// own criteria (not raised incidents). All carry the amber "review" styling; the
// label just names WHICH criterion. Never red — red is a human confirmation only.
const KIND_META: Record<string, string> = {
  new_vehicle: 'OUT-OF-ORDINARY VEHICLE',
  after_hours: 'AFTER HOURS',
  at_vehicles: 'AT THE VEHICLES',
  repeated_passes: 'REPEATED PASSES',
  dwell: 'LINGERING',
};

/**
 * Situations: every incident in the window, big and visual. Tier ceiling for
 * the MACHINE is "needs review". "CONFIRMED · <their words>" appears only when
 * an operator confirms — the label is a quoted human judgment with a name on
 * it, which is what makes a red banner defensible.
 */
function SituationsPanel({ situations, total, onChanged, onOpenVehicle }: { situations: import('../lib/types').DashboardSituation[]; total?: number; onChanged: () => void; onOpenVehicle?: (entityId: string) => void }) {
  const canConfirm = hasRole('operator') || hasRole('supervisor') || hasRole('admin');
  const [confirming, setConfirming] = useState<string | null>(null);
  const [label, setLabel] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function confirm(incidentId: string | null) {
    if (!incidentId || !label.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      await api.recordDecision(incidentId, {
        action_taken: 'confirmed',
        operator_notes: label.trim(),
        was_true_positive: true,
        label: label.trim(),
      });
      setConfirming(null);
      setLabel('');
      onChanged();
    } catch (e: any) {
      setErr(e?.message || 'Could not confirm');
    } finally {
      setBusy(false);
    }
  }

  // The backend already ranked these: the top ten by importance, worst first,
  // each carrying its `rank`. We render them in that order and lead with the
  // number — no urgent-vs-routine split, because a ranked list IS the split.

  if (!situations.length) {
    return (
      <div className="py-5 text-center">
        <p className="text-xs text-slate-600 leading-relaxed">
          Nothing to rank in this window — no activity has been recorded yet.
        </p>
        <p className="text-xs text-slate-700 mt-1">
          The system is watching — see <span className="text-slate-500">Watching for</span> below for exactly what.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {situations.map((s, i) => {
        const m = TIER_META[s.tier] || TIER_META.noted;
        const badgeLabel = (s.kind && KIND_META[s.kind]) || m.label;
        const key = s.incident_id || s.entity_id || `${s.kind || 'sit'}-${s.ts}-${i}`;
        // Media/click target: an incident links to its full evidence page; a
        // criteria vehicle row opens that vehicle's history; otherwise the frame
        // is shown but isn't a link.
        const media = (s.frame_url && s.bbox)
          ? <CropImg src={s.frame_url} alt={s.title || 'vehicle'}
                     bbox={s.bbox as [number, number, number, number]} pad={0.25}
                     className="w-full h-full min-h-[96px]" />
          : s.snapshot_url
            ? <AuthImg src={s.snapshot_url} alt={s.event_type || 'evidence'} className="w-full h-full object-cover min-h-[96px]" />
            : <div className="w-full h-full min-h-[96px] flex items-center justify-center text-[10px] text-slate-700">no frame</div>;
        const mediaCls = "relative w-40 sm:w-52 flex-none bg-slate-900 no-underline";
        const rank = s.rank ?? (i + 1);
        return (
          <div key={key}
               className={`vg-rise flex gap-3 rounded-lg overflow-hidden bg-black/40 border ${m.border} ${m.glow} transition-all duration-300`}
               style={{ animationDelay: `${210 + i * 60}ms` }}>
            {/* The rank leads — this is a ranked list, so the number is the
                first thing the eye lands on. 1 is the most important. */}
            <div className="flex-none w-9 flex items-start justify-center pt-3 bg-black/30">
              <span className={`text-lg font-bold tabular-nums ${rank <= 3 ? 'text-indigo-300' : 'text-slate-600'}`}>{rank}</span>
            </div>
            {s.incident_id
              ? <Link to={`/incidents/${s.incident_id}`} className={mediaCls}>{media}</Link>
              : s.entity_id && onOpenVehicle
                ? <button onClick={() => onOpenVehicle(s.entity_id!)} className={`${mediaCls} cursor-pointer`}>{media}</button>
                : <div className={mediaCls}>{media}</div>}
            <div className="flex-1 min-w-0 py-2.5 pr-3">
              <div className="flex items-center gap-2 flex-wrap">
                <span className={`text-[9px] font-bold tracking-wider px-1.5 py-0.5 rounded ${m.badge} ${s.tier === 'confirmed' ? 'vg-live' : ''}`}>
                  {badgeLabel}
                </span>
                <span className="text-[10px] text-slate-500">{s.camera_name || ''} · {timeAgo(s.ts)}</span>
              </div>
              <div className="mt-1 text-sm font-medium text-slate-100 truncate">
                {s.confirmed?.label
                  ? <>“{s.confirmed.label}” <span className="text-[10px] font-normal text-slate-500">— confirmed by {s.confirmed.by}</span></>
                  : (s.who || s.title || typeMeta(s.event_type || '').label)}
              </div>
              {realDesc(s.description) && (
                <p className="mt-0.5 text-xs text-slate-500 line-clamp-2">{realDesc(s.description)}</p>
              )}
              <div className="mt-1.5 flex items-center gap-3">
                {s.incident_id
                  ? <Link to={`/incidents/${s.incident_id}`}
                          className="text-[10px] text-indigo-400 hover:text-indigo-300 no-underline">
                      evidence & why flagged →
                    </Link>
                  : s.entity_id && onOpenVehicle
                    ? <button onClick={() => onOpenVehicle(s.entity_id!)}
                              className="text-[10px] text-indigo-400 hover:text-indigo-300">
                        see this vehicle's history →
                      </button>
                    : null}
                {s.incident_id && canConfirm && !s.confirmed && confirming !== s.incident_id && (
                  <button onClick={() => { setConfirming(s.incident_id); setLabel(''); setErr(null); }}
                          className="text-[10px] text-slate-400 hover:text-white border border-slate-700 hover:border-slate-500 rounded px-1.5 py-0.5">
                    Confirm what happened…
                  </button>
                )}
              </div>
              {s.incident_id && confirming === s.incident_id && (
                <div className="mt-2 flex items-center gap-1.5">
                  <input autoFocus value={label}
                         onChange={e => setLabel(e.target.value)}
                         onKeyDown={e => { if (e.key === 'Enter') confirm(s.incident_id); if (e.key === 'Escape') setConfirming(null); }}
                         placeholder="In your words — e.g. attempted break-in"
                         className="flex-1 max-w-xs bg-slate-900 border border-slate-700 rounded px-2 py-1 text-[11px] text-slate-200 placeholder:text-slate-600 focus:border-red-500 outline-none" />
                  <button onClick={() => confirm(s.incident_id)} disabled={busy || !label.trim()}
                          className="text-[10px] font-semibold bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white rounded px-2 py-1">
                    {busy ? '…' : 'Confirm'}
                  </button>
                  <button onClick={() => setConfirming(null)} className="text-[10px] text-slate-500 hover:text-slate-300 px-1">
                    Cancel
                  </button>
                  {err && <span className="text-[9px] text-red-400">{err}</span>}
                </div>
              )}
            </div>
          </div>
        );
      })}
      {typeof total === 'number' && total > situations.length && (
        <p className="text-[11px]">
          <Link to="/incidents" className="text-slate-400 hover:text-slate-200 no-underline">
            + {total - situations.length} more below the top ten →
          </Link>
        </p>
      )}
      <p className="text-[10px] text-slate-600">
        Ranked by importance — most notable first. The system flags what's worth a look; it never declares a
        crime. A red “confirmed” is a person's own statement of what happened, with their name attached.
      </p>
    </div>
  );
}

/**
 * The armed panel. Three honest states per trigger:
 *   fired            → when + where, linked to the incidents view
 *   evaluated, quiet → "not seen"
 *   not evaluated    → "armed · not yet evaluated" — we never imply we checked
 *                      and found nothing when we didn't check.
 * Language stays situational (the trigger texts come from the posture).
 */
function WatchingForPanel({ wf }: { wf: WatchingFor }) {
  return (
    <ul className="space-y-2">
      {wf.triggers.map((t, i) => (
        <li key={t.trigger} className="vg-rise flex items-center gap-2.5"
            style={{ animationDelay: `${340 + i * 50}ms` }}>
          <span className={`w-1.5 h-1.5 rounded-full flex-none ${
            t.fired ? 'vg-live bg-amber-400 shadow-[0_0_6px_1px_rgba(251,191,36,.8)]'
              : t.evaluated ? 'bg-emerald-500/80'
              : 'bg-slate-600'
          }`} />
          <span className="text-xs text-slate-300 flex-1 min-w-0 truncate first-letter:uppercase">{t.trigger}</span>
          {t.fired ? (
            <Link to="/incidents" className="text-[11px] font-mono text-amber-300 hover:text-amber-200 flex-none no-underline">
              ✓ {t.ts ? timeAgo(t.ts) : ''}{t.camera_name ? ` · ${t.camera_name}` : ''} →
            </Link>
          ) : t.evaluated ? (
            <span className="text-[11px] text-slate-600 flex-none">not seen</span>
          ) : t.note && t.note.includes('normal hours') ? (
            <Link to="/sites" className="text-[11px] text-indigo-400 hover:text-indigo-300 flex-none italic no-underline">
              armed · set normal hours →
            </Link>
          ) : (
            <span className="text-[11px] text-slate-600 flex-none italic"
                  title={t.note || 'not yet evaluated'}>
              armed · {t.note || 'not yet evaluated'}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}

/**
 * Hour-of-day activity heatmap (site-local time): one row per camera, plus
 * people/vehicles rows. Cell intensity = events in that hour of day. All real
 * events, zeros stay dark — an idle system reads as an honest quiet grid.
 */
function PatternsHeatmap({ p }: { p: DashboardPatterns }) {
  const rows: Array<{ label: string; hours: number[]; tint: string }> = [
    ...p.by_camera_hour.map(c => ({ label: c.camera_name, hours: c.hours, tint: '129,140,248' })),
    { label: 'People', hours: p.people_by_hour, tint: '99,102,241' },
    { label: 'Vehicles', hours: p.vehicles_by_hour, tint: '34,211,238' },
  ];
  const max = Math.max(1, ...rows.flatMap(r => r.hours));
  return (
    <div className="overflow-x-auto">
      <div className="min-w-[560px]">
        {rows.map(r => (
          <div key={r.label} className="flex items-center gap-2 mb-1.5">
            <span className="w-24 flex-none text-[10px] text-slate-500 truncate text-right pr-1">{r.label}</span>
            <div className="flex-1 grid gap-[3px]" style={{ gridTemplateColumns: 'repeat(24, 1fr)' }}>
              {r.hours.map((n, h) => (
                <div key={h}
                     title={`${String(h).padStart(2, '0')}:00 · ${n} event${n === 1 ? '' : 's'}`}
                     className="h-5 rounded-[3px]"
                     style={{ background: n > 0
                       ? `rgba(${r.tint}, ${0.15 + 0.85 * (n / max)})`
                       : 'rgba(30,41,59,.55)' }} />
              ))}
            </div>
          </div>
        ))}
        <div className="flex items-center gap-2">
          <span className="w-24 flex-none" />
          <div className="flex-1 grid gap-[3px]" style={{ gridTemplateColumns: 'repeat(24, 1fr)' }}>
            {Array.from({ length: 24 }, (_, h) => (
              <span key={h} className="text-[8px] text-slate-600 text-center font-mono">
                {h % 6 === 0 ? String(h).padStart(2, '0') : ''}
              </span>
            ))}
          </div>
        </div>
        <p className="text-[9px] text-slate-600 mt-1.5 ml-[104px]">hour of day ({p.tz})</p>
      </div>
    </div>
  );
}

const FINDING_BADGE: Record<string, { label: string; cls: string }> = {
  new:        { label: 'NEW', cls: 'bg-amber-400 text-black' },
  regular:    { label: 'PATTERN', cls: 'bg-indigo-500/80 text-white' },
  resident:   { label: 'FAMILIAR', cls: 'bg-emerald-600/80 text-white' },
  occasional: { label: 'SEEN', cls: 'bg-slate-700 text-slate-300' },
  scene:      { label: 'ALWAYS THERE', cls: 'bg-slate-700 text-slate-300' },
  people:     { label: 'RHYTHM', cls: 'bg-indigo-500/60 text-white' },
};

/** Wraps a card's image in a link to its incident when one is known, else a
 *  plain container (no dead links). Keeps sibling controls — the enrol button —
 *  outside, so only the picture navigates. */
function CropLink({ incidentId, className, children }:
                  { incidentId?: string | null; className?: string; children: React.ReactNode }) {
  if (incidentId) {
    return <Link to={`/incidents/${incidentId}`} className={`${className || ''} group no-underline`}>{children}</Link>;
  }
  return <div className={className}>{children}</div>;
}

/** Explicit sentences about what is happening — familiar vs new, in words. */
function FindingsList({ findings }: { findings: PatternFinding[] }) {
  return (
    <ul className="space-y-1.5">
      {findings.map((f, i) => {
        const b = FINDING_BADGE[f.kind] || FINDING_BADGE.occasional;
        return (
          <li key={i} className="flex items-start gap-2 text-xs">
            <span className={`mt-0.5 text-[8px] font-bold tracking-wider px-1.5 py-0.5 rounded flex-none ${b.cls} ${f.kind === 'new' ? 'vg-live' : ''}`}>
              {b.label}
            </span>
            <span className="text-slate-400 leading-relaxed">{f.text}</span>
          </li>
        );
      })}
    </ul>
  );
}

/** Your named vehicles — the persistent known-cars database. A named car lives
 *  here for good (this is where it "goes" after you name it), with its photo,
 *  plate and when it was last seen; click through for its full history. */
function NamedVehiclesPanel({ vehicles, onOpen }: { vehicles: import('../lib/types').NamedVehicle[]; onOpen: (entityId: string) => void }) {
  if (!vehicles.length) return null;
  return (
    <ul className="space-y-1.5">
      {vehicles.map((v, i) => (
        <li key={v.entity_id || i} className="flex items-center gap-2 text-xs flex-wrap">
          {v.frame_url && v.bbox
            ? <button onClick={() => onOpen(v.entity_id)} className="w-9 h-9 flex-none rounded overflow-hidden bg-slate-900 border border-slate-700 hover:border-emerald-500">
                <CropImg src={v.frame_url} alt={v.label}
                         bbox={v.bbox as [number, number, number, number]} pad={0.3}
                         className="w-full h-full" />
              </button>
            : <span className="w-9 h-9 flex-none rounded bg-slate-800 border border-slate-700 flex items-center justify-center text-[8px] text-slate-600">no pic</span>}
          <span className="text-[8px] font-bold tracking-wider px-1.5 py-0.5 rounded flex-none bg-emerald-600/80 text-white">YOURS</span>
          <button onClick={() => onOpen(v.entity_id)}
                  className="text-emerald-200 hover:text-white font-medium text-left underline decoration-dotted underline-offset-2">
            {v.label}
          </button>
          {v.plate && (
            <span className="font-mono text-[10px] font-bold text-slate-200 bg-slate-800 border border-slate-600 rounded px-1.5 py-0.5 tracking-wider flex-none">{v.plate}</span>
          )}
          <span className="text-slate-500">
            {v.seen_recently
              ? <>seen {v.passes ?? v.count} time{(v.passes ?? v.count) === 1 ? '' : 's'} · {v.cameras.join(', ')}</>
              : <>not seen recently</>}
          </span>
          <span className="text-slate-600 ml-auto font-mono text-[10px]">{v.last_seen ? timeAgo(v.last_seen) : ''}</span>
        </li>
      ))}
      <li className="text-[10px] text-slate-600 pt-1">
        These stay listed even when idle or when nothing is recording — it's your saved list, not a live feed.
      </li>
    </ul>
  );
}

/** The cars that are NOT the usual scene — new or occasional, unnamed — each
 *  saying how often it came down the road and when. New cars lead. Every row
 *  clicks through to that vehicle's full history (every sighting, with times). */
function OutOfOrdinaryPanel({ vehicles, onOpen }: { vehicles: import('../lib/types').OutOfOrdinaryVehicle[]; onOpen: (entityId: string) => void }) {
  if (!vehicles.length) return null;
  return (
    <ul className="space-y-1.5">
      {vehicles.map((v, i) => {
        const b = FINDING_BADGE[v.familiarity] || FINDING_BADGE.occasional;
        const when = v.busiest_hour_local !== null
          ? `mostly around ${String(v.busiest_hour_local).padStart(2, '0')}:00` : '';
        // "How often" is distinct visits (passes). Fall back to a plain "seen"
        // phrasing if we couldn't compute passes — never claim a sighting count.
        const times = v.passes != null
          ? `Came past ${v.passes}×`
          : 'Seen here';
        return (
          <li key={v.entity_id || i} className="flex items-center gap-2 text-xs flex-wrap">
            {v.frame_url && v.bbox
              ? <button onClick={() => onOpen(v.entity_id)} className="w-9 h-9 flex-none rounded overflow-hidden bg-slate-900 border border-slate-700 hover:border-indigo-500">
                  <CropImg src={v.frame_url} alt={v.descriptor || 'vehicle'}
                           bbox={v.bbox as [number, number, number, number]} pad={0.3}
                           className="w-full h-full" />
                </button>
              : null}
            <span className={`text-[8px] font-bold tracking-wider px-1.5 py-0.5 rounded flex-none ${b.cls} ${v.familiarity === 'new' ? 'vg-live' : ''}`}>
              {b.label}
            </span>
            {v.plate && (
              <span className="font-mono text-[10px] font-bold text-slate-200 bg-slate-800 border border-slate-600 rounded px-1.5 py-0.5 tracking-wider flex-none">{v.plate}</span>
            )}
            <button onClick={() => onOpen(v.entity_id)}
                    className="text-slate-300 hover:text-white text-left underline decoration-dotted underline-offset-2">
              {v.descriptor ? `${v.descriptor} · ` : ''}{times} over {v.days} day{v.days === 1 ? '' : 's'}
              {v.cameras.length > 0 && ` · ${v.cameras.join(', ')}`}
              {when && ` · ${when}`}
            </button>
            <span className="text-slate-600 ml-auto font-mono text-[10px]">{timeAgo(v.last_seen)}</span>
          </li>
        );
      })}
      <li className="text-[10px] text-slate-600 pt-1">
        The usual cars — your own, the regulars, anything you've named — are left out on purpose. Click a row for every sighting and time.
      </li>
    </ul>
  );
}

/** One recurring-vehicle row with the owner's "name it" control — the vehicle
 *  analog of enrolling a face: identity only ever comes from the owner. */
function RecurringVehicleRow({ v, onSaved, onOpen }: { v: RecurringVehicle; onSaved: () => void; onOpen: () => void }) {
  const canName = hasRole('supervisor') || hasRole('admin');
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);

  async function save() {
    setBusy(true);
    try {
      await api.setVehicleLabel(v.entity_id, name.trim());
      setNaming(false);
      onSaved();
    } catch { /* row keeps old state */ } finally { setBusy(false); }
  }

  const fam = FINDING_BADGE[v.familiarity] || FINDING_BADGE.occasional;
  return (
    <li className="flex items-center gap-2 text-xs flex-wrap">
      {v.frame_url && v.bbox
        ? <button onClick={onOpen} className="w-9 h-9 flex-none rounded overflow-hidden bg-slate-900 border border-slate-700 hover:border-indigo-500">
            <CropImg src={v.frame_url} alt={v.label}
                     bbox={v.bbox as [number, number, number, number]} pad={0.3}
                     className="w-full h-full" />
          </button>
        : null}
      <span className={`text-[8px] font-bold tracking-wider px-1.5 py-0.5 rounded flex-none ${fam.cls}`}>{fam.label}</span>
      <button onClick={onOpen} className="text-slate-300 font-medium hover:text-white underline decoration-dotted underline-offset-2">
        {v.owner_label ? `“${v.owner_label}”` : v.label}
      </button>
      <button onClick={onOpen} className="text-slate-500 hover:text-slate-300 text-left">
        seen {v.passes ?? v.count} time{(v.passes ?? v.count) === 1 ? '' : 's'} over {v.days} day{v.days === 1 ? '' : 's'} · {v.cameras.join(', ')}
        {v.busiest_hour_utc !== null && ` · mostly around ${String((v.busiest_hour_utc + 2) % 24).padStart(2, '0')}:00`}
      </button>
      {canName && !naming && (
        <button onClick={() => { setNaming(true); setName(v.owner_label || ''); }}
                className="text-[10px] text-indigo-400 hover:text-indigo-300">
          {v.owner_label ? 'rename' : 'name it'}
        </button>
      )}
      {naming && (
        <span className="flex items-center gap-1">
          <input autoFocus value={name} onChange={e => setName(e.target.value)}
                 onKeyDown={e => { if (e.key === 'Enter') save(); if (e.key === 'Escape') setNaming(false); }}
                 placeholder="e.g. Paul's Fortuner"
                 className="w-36 bg-slate-900 border border-slate-700 rounded px-1.5 py-0.5 text-[11px] text-slate-200 placeholder:text-slate-600 focus:border-indigo-500 outline-none" />
          <button onClick={save} disabled={busy}
                  className="text-[10px] bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded px-1.5 py-0.5">
            {busy ? '…' : 'Save'}
          </button>
          <button onClick={() => setNaming(false)} className="text-[10px] text-slate-500">✕</button>
        </span>
      )}
      <span className="text-slate-600 ml-auto font-mono text-[10px]">{timeAgo(v.last_seen)}</span>
    </li>
  );
}

/** Honest vehicle description: the badge (make/model) is shown ONLY at high VLM
 *  confidence — otherwise colour + body ("White SUV"). Type falls back to the
 *  free D-FINE class (truck/bus/motorcycle) when the VLM didn't run. Colour may
 *  come from the crop's own pixels (HSV). Never a guessed model. */
function vehicleTitle(v: DashboardVehicle): string {
  const colour = v.colour ? v.colour[0].toUpperCase() + v.colour.slice(1) : '';
  const badge = v.attr_confidence === 'high' && v.make
    ? [v.make, v.model].filter(Boolean).join(' ')
    : '';
  // Prefer the VLM body; else the detector's own class (a real, free type);
  // 'car' stays generic ("vehicle") since it adds nothing over the word.
  const detType = v.det_class && v.det_class !== 'car' ? v.det_class : '';
  const body = badge || v.body || detType || (colour ? 'vehicle' : '');
  const title = [colour, body].filter(Boolean).join(' ').trim();
  return title ? title.charAt(0).toUpperCase() + title.slice(1) : 'Vehicle';
}

function VehicleCard({ v, i }: { v: DashboardVehicle; i: number }) {
  return (
    <div className="vg-rise rounded-lg overflow-hidden bg-black border border-slate-800 hover:border-cyan-500/60 transition-all duration-300"
         style={{ animationDelay: `${340 + i * 40}ms` }}>
      <CropLink incidentId={v.incident_id} className="relative block aspect-video bg-slate-900">
        <CropImg src={v.frame_url} alt={vehicleTitle(v)}
                 bbox={v.bbox as [number, number, number, number]} pad={0.25}
                 className="w-full h-full" />
        <span className="absolute bottom-1 right-1.5 text-[8px] px-1 py-0.5 rounded bg-black/80 text-slate-400 font-mono">
          {timeAgo(v.ts)}
        </span>
        {v.region?.out_of_area && (
          <span className="absolute top-1 left-1 text-[8px] font-bold tracking-wider px-1.5 py-0.5 rounded bg-amber-400 text-black vg-live">
            OUT OF PROVINCE
          </span>
        )}
        {v.incident_id && (
          <span className="absolute top-1 right-1.5 text-[8px] px-1 py-0.5 rounded bg-black/70 text-indigo-300">details →</span>
        )}
      </CropLink>
      <div className="px-2 py-1.5 border-t border-slate-800/70">
        <div className="text-[11px] font-medium text-slate-200 truncate">{vehicleTitle(v)}</div>
        {v.plate && <div className="text-[10px] font-mono text-cyan-400 truncate">{v.plate}</div>}
        {v.region && (
          <div className={`text-[9px] truncate ${v.region.out_of_area ? 'text-amber-400' : 'text-slate-500'}`}
               title={v.region.basis || undefined}>
            {v.region.town ? `${v.region.town}, ${v.region.province}` : v.region.province}
            {v.region.out_of_area ? ' · out of area' : v.region.province === 'Western Cape' ? ' · local' : ''}
          </div>
        )}
        <div className="text-[9px] text-slate-600 truncate">{v.camera_name}</div>
      </div>
    </div>
  );
}

function DetectionCard({ row, i }: { row: DashboardRow; i: number }) {
  const flagged = row.watchlist_hit || row.hotlist_hit;
  return (
    <Link to="/incidents"
          className="vg-rise group rounded-lg overflow-hidden bg-black border border-slate-800 hover:border-indigo-500 hover:shadow-[0_0_22px_-4px_rgba(99,102,241,.85)] transition-all duration-300 no-underline"
          style={{ animationDelay: `${420 + i * 40}ms` }}>
      <div className="relative aspect-video bg-slate-900">
        {row.snapshot_url
          ? <AuthImg src={row.snapshot_url} alt={row.event_type}
                     className="w-full h-full object-cover opacity-90 group-hover:opacity-100 group-hover:scale-[1.05] transition-all duration-500" />
          : <div className="w-full h-full flex items-center justify-center text-[10px] text-slate-700">no frame</div>}
        <div className="absolute inset-0 bg-gradient-to-t from-black/80 to-transparent" />
        {flagged && (
          <span className="absolute top-1.5 left-1.5 text-[8px] font-bold tracking-wider px-1.5 py-0.5 rounded bg-amber-400 text-black">
            {row.watchlist_hit ? 'WATCHLIST' : 'HOTLIST'}
          </span>
        )}
        <span className="absolute bottom-1 right-1.5 text-[8px] px-1 py-0.5 rounded bg-black/80 text-slate-400 font-mono">
          {timeAgo(row.ts)}
        </span>
      </div>
      <div className="px-2 py-1.5 border-t border-slate-800/70">
        <div className="text-[10px] font-medium text-slate-200 truncate">{typeMeta(row.event_type).label}</div>
        <div className="text-[9px] text-slate-500 truncate">{row.camera_name}</div>
        {row.plates.length > 0 && (
          <div className="mt-0.5 text-[9px] font-mono text-cyan-400 truncate">{row.plates.join(', ')}</div>
        )}
      </div>
    </Link>
  );
}

/** Dependency-free area chart that draws itself in. Real hourly series. */
function AreaChart({ series }: { series: Array<{ hour: string; events: number; alerts: number }> }) {
  if (!series.length) return <p className="text-xs text-slate-600 py-12 text-center">No events in this window.</p>;
  const W = 720, H = 190, P = 26;
  const max = Math.max(1, ...series.map(s => s.events));
  const x = (i: number) => P + (i * (W - P * 2)) / Math.max(1, series.length - 1);
  const y = (v: number) => H - P - (v / max) * (H - P * 2);
  const line = series.map((s, i) => `${i ? 'L' : 'M'}${x(i)},${y(s.events)}`).join(' ');
  const area = `${line} L${x(series.length - 1)},${H - P} L${x(0)},${H - P} Z`;
  const alertLine = series.map((s, i) => `${i ? 'L' : 'M'}${x(i)},${y(s.alerts)}`).join(' ');
  const last = series[series.length - 1];

  return (
    <div className="overflow-x-auto">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full min-w-[420px]" role="img" aria-label="Events over time">
        <defs>
          <linearGradient id="vgEv" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#818cf8" stopOpacity="0.45" />
            <stop offset="100%" stopColor="#818cf8" stopOpacity="0" />
          </linearGradient>
          <filter id="vgBlur"><feGaussianBlur stdDeviation="3.5" /></filter>
        </defs>
        {[0, 0.5, 1].map(f => (
          <line key={f} x1={P} x2={W - P} y1={y(max * f)} y2={y(max * f)} stroke="#1e293b" strokeWidth="1" />
        ))}
        <path d={area} fill="url(#vgEv)" />
        <path d={line} fill="none" stroke="#818cf8" strokeWidth="4" opacity="0.5" filter="url(#vgBlur)" />
        <path className="vg-draw" d={line} fill="none" stroke="#a5b4fc" strokeWidth="2" strokeLinecap="round" />
        <path className="vg-draw" d={alertLine} fill="none" stroke="#fbbf24" strokeWidth="1.5" strokeDasharray="3 3" />
        <circle cx={x(series.length - 1)} cy={y(last.events)} r="3.5" fill="#a5b4fc">
          <animate attributeName="r" values="3.5;6;3.5" dur="1.9s" repeatCount="indefinite" />
          <animate attributeName="opacity" values="1;.4;1" dur="1.9s" repeatCount="indefinite" />
        </circle>
        <text x={P} y={16} fill="#475569" fontSize="9" fontFamily="monospace">PEAK {max}/H</text>
      </svg>
      <div className="flex gap-4 mt-1 text-[10px] text-slate-600">
        <span><span className="inline-block w-2 h-2 rounded-full bg-indigo-400 mr-1" />Events</span>
        <span><span className="inline-block w-2 h-2 rounded-full bg-amber-400 mr-1" />Alerts</span>
      </div>
    </div>
  );
}

/** Dependency-free donut, real type split, arcs sweeping in. */
function Donut({ items, total }: { items: Array<{ type: string; count: number }>; total: number }) {
  if (!items.length || total === 0) return <p className="text-xs text-slate-600 py-12 text-center">No events in this window.</p>;
  const R = 52, C = 2 * Math.PI * R;
  const shown = useCountUp(total);
  let offset = 0;
  return (
    <div className="flex items-center gap-4">
      <svg viewBox="0 0 140 140" className="w-32 h-32 flex-none" role="img" aria-label="Events by type">
        <g transform="translate(70,70) rotate(-90)">
          <circle r={R} fill="none" stroke="#0f172a" strokeWidth="14" />
          {items.map(it => {
            const frac = it.count / total;
            const el = (
              <circle key={it.type} r={R} fill="none" stroke={typeMeta(it.type).color}
                      strokeWidth="14" strokeLinecap="round"
                      strokeDasharray={`${frac * C} ${C - frac * C}`} strokeDashoffset={-offset}
                      style={{ filter: `drop-shadow(0 0 5px ${typeMeta(it.type).color}90)`,
                               transition: 'stroke-dasharray .9s cubic-bezier(.2,.7,.3,1)' }} />
            );
            offset += frac * C;
            return el;
          })}
        </g>
        <text x="70" y="68" textAnchor="middle" fill="#fff" fontSize="21" fontWeight="600">{shown}</text>
        <text x="70" y="84" textAnchor="middle" fill="#475569" fontSize="8" letterSpacing="1.5">EVENTS</text>
      </svg>
      <ul className="space-y-1.5 min-w-0 flex-1">
        {items.map(it => (
          <li key={it.type} className="flex items-center gap-2 text-xs">
            <span className="w-2 h-2 rounded-full flex-none"
                  style={{ background: typeMeta(it.type).color, boxShadow: `0 0 6px ${typeMeta(it.type).color}` }} />
            <span className="text-slate-400 truncate">{typeMeta(it.type).label}</span>
            <span className="text-slate-600 tabular-nums ml-auto font-mono">{Math.round((it.count / total) * 100)}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function SkeletonRow() {
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
      {[0, 1, 2, 3].map(i => (
        <div key={i} className="h-24 rounded-xl bg-slate-900/60 border border-slate-800/80 relative overflow-hidden vg-scan" />
      ))}
    </div>
  );
}

/** Honest empty state — animated, but it never pretends there's data. */
function EmptyState() {
  return (
    <div className="vg-rise relative rounded-xl bg-slate-900/60 border border-slate-800/80 p-10 text-center overflow-hidden">
      <div className="vg-glow absolute inset-x-0 -top-24 h-48 bg-indigo-600/20 blur-3xl" />
      <div className="relative">
        <div className="inline-flex items-center gap-2 text-[10px] font-medium tracking-widest text-slate-500 uppercase mb-3">
          <span className="vg-live w-1.5 h-1.5 rounded-full bg-slate-500" /> Standing by
        </div>
        <p className="text-white font-medium">No camera intelligence yet</p>
        <p className="text-sm text-slate-500 mt-2 max-w-xl mx-auto leading-relaxed">
          This dashboard only ever shows real detections from your cameras, so it stays
          empty until the recorder sends its first motion frame. Nothing here is simulated.
        </p>
        <div className="mt-4 text-xs text-slate-600">
          Check a recorder is online on <Link to="/recorders" className="text-indigo-400 hover:text-indigo-300">Recorders</Link>,
          and your cameras are linked on <Link to="/sites" className="text-indigo-400 hover:text-indigo-300">Sites</Link>.
        </div>
      </div>
    </div>
  );
}
