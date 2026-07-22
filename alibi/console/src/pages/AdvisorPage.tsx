import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../lib/api';
import type { Site, SiteBrief, AdvisorResult, Recommendation } from '../lib/types';

/**
 * Security Advisor — the client-facing page.
 *
 *  * The BRIEF: what happened in the window, as deterministic cited findings plus
 *    a narrative. Every finding names the incidents behind it.
 *  * The RECOMMENDATIONS: how to improve, derived from observed state, each citing
 *    the fact that triggered it. A healthy system shows none.
 *
 * Nothing here is generic advice and nothing is invented — if we don't know, we
 * say nothing rather than fill the page.
 */

const PRIORITY: Record<string, { label: string; dot: string; cls: string }> = {
  critical: { label: 'Now',    dot: 'bg-red-500',    cls: 'border-red-200 bg-red-50' },
  high:     { label: 'Soon',   dot: 'bg-amber-500',  cls: 'border-amber-200 bg-amber-50' },
  medium:   { label: 'Worth doing', dot: 'bg-blue-400', cls: 'border-blue-100 bg-blue-50/50' },
  low:      { label: 'Nice to have', dot: 'bg-gray-300', cls: 'border-gray-200 bg-white' },
};

export function AdvisorPage() {
  const [sites, setSites] = useState<Site[]>([]);
  const [siteId, setSiteId] = useState<string>('');
  const [brief, setBrief] = useState<SiteBrief | null>(null);
  const [advisor, setAdvisor] = useState<AdvisorResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.listSites()
      .then(d => {
        setSites(d.sites);
        if (d.sites.length) setSiteId(d.sites[0].site_id);
        else setLoading(false);
      })
      .catch(e => { setErr(e?.message || 'Failed to load sites'); setLoading(false); });
  }, []);

  useEffect(() => {
    if (!siteId) return;
    setLoading(true);
    setErr(null);
    // Both calls used to be .catch(() => null), so any failure rendered as an
    // empty page with no explanation — indistinguishable from "nothing to say".
    // Report what actually broke; a page that stays silent about its own
    // errors is the hardest kind to diagnose.
    Promise.allSettled([
      api.getSiteBrief(siteId),
      api.getAdvisor(siteId),
    ]).then(([b, a]) => {
      setBrief(b.status === 'fulfilled' ? b.value : null);
      setAdvisor(a.status === 'fulfilled' ? a.value : null);
      const broke: string[] = [];
      if (b.status === 'rejected') broke.push(`brief (${b.reason?.message || 'failed'})`);
      if (a.status === 'rejected') broke.push(`recommendations (${a.reason?.message || 'failed'})`);
      setErr(broke.length ? `Could not load ${broke.join(' and ')}.` : null);
      setLoading(false);
    });
  }, [siteId]);

  const site = sites.find(s => s.site_id === siteId);

  return (
    <div className="max-w-5xl mx-auto px-4 py-6">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Security Advisor</h1>
          <p className="text-sm text-gray-500">
            What happened, what it means, and what to do next — all cited, nothing invented.
          </p>
        </div>
        {sites.length > 1 && (
          <select value={siteId} onChange={e => setSiteId(e.target.value)}
                  className="rounded-md border border-gray-300 px-2 py-1.5 text-sm">
            {sites.map(s => <option key={s.site_id} value={s.site_id}>{s.name}</option>)}
          </select>
        )}
      </div>

      {err && <div className="mb-4 p-3 bg-red-50 text-red-700 text-sm rounded-md">{err}</div>}

      {!loading && sites.length === 0 && (
        <div className="bg-white shadow rounded-lg p-8 text-center">
          <p className="text-gray-900 font-medium">No sites yet</p>
          <p className="text-sm text-gray-500 mt-2">
            The advisor reports per site. Add one on <Link to="/sites" className="text-blue-600 underline">Sites</Link> to get a brief.
          </p>
        </div>
      )}

      {loading && <p className="text-gray-500 py-8">Loading…</p>}

      {!loading && site && (
        <>
          {/* The brief */}
          <div className="bg-white shadow rounded-lg p-5 mb-4">
            <div className="flex items-baseline justify-between mb-2">
              <h2 className="text-lg font-medium text-gray-900">
                Brief — {site.name}
              </h2>
              {brief && (
                <span className="text-xs text-gray-400">
                  last {brief.window_hours}h · {brief.incident_count} incident{brief.incident_count === 1 ? '' : 's'}
                </span>
              )}
            </div>

            {!brief ? (
              <p className="text-sm text-gray-500">No brief available for this site yet.</p>
            ) : (
              <>
                <p className="text-sm text-gray-800 leading-relaxed">{brief.narrative}</p>

                {brief.findings?.length > 0 && (
                  <div className="mt-4">
                    <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1.5">Findings</p>
                    <ul className="space-y-1.5">
                      {brief.findings.map((f, i) => (
                        <li key={i} className="flex items-start gap-2 text-sm">
                          <span className={`mt-1.5 w-1.5 h-1.5 rounded-full flex-none ${
                            f.severity_hint === 'attention' ? 'bg-amber-500' : 'bg-gray-300'
                          }`} />
                          <span className="text-gray-700">
                            {f.detail}
                            {f.incident_ids?.length > 0 && (
                              <Link to="/incidents" className="ml-1.5 text-xs text-blue-600 hover:text-blue-800">
                                ({f.incident_ids.length} incident{f.incident_ids.length === 1 ? '' : 's'})
                              </Link>
                            )}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {brief.coverage && (
                  <div className="mt-4 grid grid-cols-2 sm:grid-cols-3 gap-2">
                    <Cover label="Cameras on this site" value={brief.coverage.cameras_configured?.length || 0} />
                    <Cover label="Saw activity" value={brief.coverage.cameras_with_activity?.length || 0} />
                    <Cover label="Quiet" value={brief.coverage.quiet_cameras?.length || 0}
                           warn={(brief.coverage.quiet_cameras?.length || 0) > 0 && brief.incident_count > 0} />
                  </div>
                )}

                <p className="mt-4 text-[11px] text-gray-400">{brief.disclaimer}</p>
              </>
            )}
          </div>

          {/* Recommendations */}
          <div className="bg-white shadow rounded-lg p-5">
            <h2 className="text-lg font-medium text-gray-900">Recommendations</h2>
            <p className="text-sm text-gray-500 mb-3">
              {advisor?.summary
                || (advisor ? 'Nothing needs attention right now.' : 'Recommendations unavailable.')}
            </p>

            {!advisor ? (
              <p className="text-sm text-gray-500">Couldn't load recommendations.</p>
            ) : advisor.recommendations.length === 0 ? (
              <div className="rounded-md bg-green-50 border border-green-200 p-4 text-sm text-green-900">
                Nothing to improve right now — your setup looks sound. We only speak up when
                something real needs attention.
              </div>
            ) : (
              <ul className="space-y-2">
                {advisor.recommendations.map(r => <RecCard key={r.key} rec={r} />)}
              </ul>
            )}

            {advisor && (
              <p className="mt-3 text-[11px] text-gray-400">{advisor.note}</p>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function Cover({ label, value, warn }: { label: string; value: number; warn?: boolean }) {
  return (
    <div className={`rounded-md p-2 text-center ${warn ? 'bg-amber-50 border border-amber-200' : 'bg-gray-50'}`}>
      <div className={`text-lg font-semibold ${warn ? 'text-amber-700' : 'text-gray-900'}`}>{value}</div>
      <div className="text-[10px] text-gray-500">{label}</div>
    </div>
  );
}

function RecCard({ rec }: { rec: Recommendation }) {
  const p = PRIORITY[rec.priority] || PRIORITY.low;
  return (
    <li className={`rounded-lg border p-3 ${p.cls}`}>
      <div className="flex items-start gap-2">
        <span className={`mt-1.5 w-2 h-2 rounded-full flex-none ${p.dot}`} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium text-gray-900">{rec.title}</span>
            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-white/70 border border-gray-200 text-gray-600">
              {p.label}
            </span>
          </div>
          <p className="text-xs text-gray-700 mt-0.5">{rec.detail}</p>
          <p className="text-[11px] text-gray-500 mt-1.5">
            <span className="text-gray-400">Because:</span> {rec.evidence}
          </p>
          {rec.action && (
            <div className="mt-1.5 flex items-center gap-2">
              <span className="text-xs text-gray-700">{rec.action}</span>
              {rec.link && (
                <Link to={rec.link} className="text-xs font-medium text-blue-600 hover:text-blue-800">Go →</Link>
              )}
            </div>
          )}
        </div>
      </div>
    </li>
  );
}
