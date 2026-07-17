import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { hasRole } from '../lib/auth';
import type { AiConfigResponse, CostSummary } from '../lib/types';

const SERVICE_LABEL: Record<string, string> = {
  vision: 'Scene analysis (vision)',
  llm_text: 'Text (explainer, brief, reports)',
};

function usd(n: number): string {
  return '$' + n.toLocaleString(undefined, { minimumFractionDigits: n < 1 ? 4 : 2, maximumFractionDigits: 4 });
}

/**
 * API credits — remaining balance and projected runout. The balance is ENTERED
 * by the owner (Anthropic exposes no balance API); spend since, burn rate, and
 * the runout date are measured from our own tracked usage. When no balance has
 * been entered we prompt for it — never invent a figure.
 */
function CreditsPanel({ data, onSaved }: { data: CostSummary; onSaved: () => void }) {
  const c = data.credits;
  const isAdmin = hasRole('admin');
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function save() {
    const n = parseFloat(value);
    if (isNaN(n) || n < 0) { setErr('Enter the balance in USD'); return; }
    setBusy(true);
    setErr(null);
    try {
      await api.setApiCredits(n);
      setEditing(false);
      setValue('');
      onSaved();
    } catch (e: any) {
      setErr(e?.message || 'Failed to save');
    } finally {
      setBusy(false);
    }
  }

  const hasBalance = c && c.balance_usd !== null;
  const low = hasBalance && c.days_left !== null && c.days_left <= 7;
  const warn = hasBalance && c.days_left !== null && c.days_left > 7 && c.days_left <= 30;

  return (
    <div className={`shadow rounded-lg p-6 mb-6 border ${
      low ? 'bg-red-50 border-red-200' : warn ? 'bg-amber-50 border-amber-200' : 'bg-white border-transparent'
    }`}>
      <div className="flex items-start justify-between">
        <h2 className="text-lg font-medium text-gray-900">API credits</h2>
        {isAdmin && !editing && (
          <button onClick={() => { setEditing(true); setValue(hasBalance ? String(c.balance_usd) : ''); }}
                  className="text-sm text-blue-600 hover:text-blue-800">
            {hasBalance ? 'Update balance' : 'Enter balance'}
          </button>
        )}
      </div>

      {!hasBalance && !editing && (
        <p className="mt-2 text-sm text-gray-600">
          Anthropic doesn't expose the account balance via API. Enter the credit balance from{' '}
          <a href="https://console.anthropic.com" target="_blank" rel="noreferrer" className="text-blue-600">
            console.anthropic.com
          </a>{' '}
          and Vantage will burn it down against tracked spend and project when it runs out.
        </p>
      )}

      {editing && (
        <div className="mt-3 flex items-center gap-2">
          <span className="text-gray-500">$</span>
          <input autoFocus type="number" min="0" step="0.01" value={value}
                 onChange={e => setValue(e.target.value)}
                 onKeyDown={e => { if (e.key === 'Enter') save(); if (e.key === 'Escape') setEditing(false); }}
                 placeholder="e.g. 250.00"
                 className="w-40 rounded-md border-gray-300 shadow-sm text-sm" />
          <button onClick={save} disabled={busy}
                  className="px-3 py-1.5 text-sm font-medium rounded-md text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-50">
            {busy ? 'Saving…' : 'Save'}
          </button>
          <button onClick={() => setEditing(false)} className="text-sm text-gray-500">Cancel</button>
          {err && <span className="text-sm text-red-600">{err}</span>}
        </div>
      )}

      {hasBalance && (
        <>
          <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wide">Remaining</p>
              <p className={`text-2xl font-semibold ${low ? 'text-red-700' : warn ? 'text-amber-700' : 'text-gray-900'}`}>
                {usd(Math.max(0, c.remaining_usd ?? 0))}
              </p>
              {(c.remaining_usd ?? 0) < 0 && (
                <p className="text-xs text-red-600">balance exhausted (est.)</p>
              )}
            </div>
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wide">Daily burn (7d avg)</p>
              <p className="text-2xl font-semibold text-gray-900">
                {c.daily_burn_usd !== null ? usd(c.daily_burn_usd) : '—'}
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wide">Days left</p>
              <p className={`text-2xl font-semibold ${low ? 'text-red-700' : warn ? 'text-amber-700' : 'text-gray-900'}`}>
                {c.days_left !== null ? Math.floor(c.days_left) : '—'}
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wide">Runs out</p>
              <p className={`text-2xl font-semibold ${low ? 'text-red-700' : warn ? 'text-amber-700' : 'text-gray-900'}`}>
                {c.runout_date ?? '—'}
              </p>
            </div>
          </div>
          <p className="mt-3 text-xs text-gray-400">
            Balance {usd(c.balance_usd!)} entered {c.set_at ? new Date(c.set_at + 'Z').toLocaleString() : ''} by {c.set_by}
            {' · '}spent {usd(c.spent_since_usd ?? 0)} since{' · '}projection from tracked spend at published rates
            {c.days_left === null && c.daily_burn_usd === null && ' · no usage tracked yet, so no projection'}
          </p>
        </>
      )}
    </div>
  );
}

/**
 * AI spend controls — the three dials that decide what the vision bill is:
 * which model narrates, how often a camera may spend, and whether plain
 * vehicle frames earn a paid call at all. Admin-only, audited, applies
 * without a restart.
 */
function AiControlsPanel() {
  const isAdmin = hasRole('admin');
  const [data, setData] = useState<AiConfigResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.getAiConfig().then(setData).catch(() => {});
  }, []);

  async function update(change: Partial<import('../lib/types').AiConfig>) {
    setBusy(true);
    setErr(null);
    try {
      setData(await api.setAiConfig(change));
    } catch (e: any) {
      setErr(e?.message || 'Failed to save');
    } finally {
      setBusy(false);
    }
  }

  if (!data) return null;
  const c = data.config;
  const gaps = [8, 30, 60, 120, 300];

  return (
    <div className="bg-white shadow rounded-lg p-6 mb-6">
      <h2 className="text-lg font-medium text-gray-900">AI spend controls</h2>
      <p className="text-sm text-gray-500 mb-4">
        These dials directly set the vision bill. Changes apply immediately{isAdmin ? '' : ' (admin only)'}.
      </p>

      <div className="space-y-5">
        <div>
          <p className="text-sm font-medium text-gray-700 mb-2">Vision model</p>
          <div className="space-y-2">
            {Object.entries(data.vision_models).map(([id, m]) => (
              <label key={id} className={`flex items-center gap-3 p-2 rounded-md border ${
                c.vision_model === id ? 'border-blue-500 bg-blue-50' : 'border-gray-200'
              } ${isAdmin ? 'cursor-pointer' : 'opacity-70'}`}>
                <input type="radio" name="vision_model" checked={c.vision_model === id}
                       disabled={!isAdmin || busy}
                       onChange={() => update({ vision_model: id })} />
                <span className="text-sm text-gray-900 flex-1">{m.label}</span>
                <span className="text-xs text-gray-500 font-mono">${m.in_usd}/${m.out_usd} per MTok</span>
              </label>
            ))}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-6">
          <label className="text-sm text-gray-700">
            Paid vision calls per camera at most every{' '}
            <select value={c.paid_min_gap_seconds} disabled={!isAdmin || busy}
                    onChange={e => update({ paid_min_gap_seconds: parseInt(e.target.value) })}
                    className="rounded-md border-gray-300 text-sm">
              {gaps.map(g => <option key={g} value={g}>{g >= 60 ? `${g / 60} min` : `${g}s`}</option>)}
            </select>
          </label>

          <label className={`flex items-center gap-2 text-sm text-gray-700 ${isAdmin ? 'cursor-pointer' : 'opacity-70'}`}>
            <input type="checkbox" checked={c.narrate_vehicles} disabled={!isAdmin || busy}
                   onChange={e => update({ narrate_vehicles: e.target.checked })} />
            Narrate vehicle-only frames
            <span className="text-xs text-gray-400">(people & hotlist/watchlist always narrated)</span>
          </label>
        </div>

        {err && <p className="text-sm text-red-600">{err}</p>}
        <p className="text-xs text-gray-400">
          The free local detector still runs on every motion frame regardless — these dials only cap the
          paid narration on top of it.
        </p>
      </div>
    </div>
  );
}

export function CostsPage() {
  const [data, setData] = useState<CostSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  function load() {
    api.getCostSummary().then(setData).catch(e => setError(e.message || 'Failed to load'));
  }

  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, []);

  if (error) return <div className="max-w-4xl mx-auto px-4 py-6 text-red-600">{error}</div>;
  if (!data) return <div className="max-w-4xl mx-auto px-4 py-6 text-gray-500">Loading…</div>;

  const services = Object.entries(data.by_service).sort((a, b) => b[1].usd - a[1].usd);
  const maxDay = Math.max(1e-9, ...data.by_day.map(d => d.usd));

  return (
    <div className="max-w-4xl mx-auto px-4 py-6">
      <h1 className="text-2xl font-semibold text-gray-900">Costs</h1>
      <p className="text-sm text-gray-500 mb-4">Estimated AI spend over the last {data.window_days} days.</p>

      <CreditsPanel data={data} onSaved={load} />

      <AiControlsPanel />

      <div className="bg-white shadow rounded-lg p-6 mb-6">
        <p className="text-sm text-gray-500">Estimated total</p>
        <p className="text-4xl font-semibold text-gray-900 mt-1">{usd(data.total_usd)}</p>
        <p className="text-xs text-gray-400 mt-2">{data.note}</p>
      </div>

      {/* By service */}
      <div className="bg-white shadow rounded-lg p-6 mb-6">
        <h2 className="text-lg font-medium text-gray-900 mb-3">By service</h2>
        {services.length === 0 ? (
          <p className="text-sm text-gray-500">No AI usage recorded yet in this window.</p>
        ) : (
          <table className="min-w-full text-sm">
            <thead>
              <tr className="text-left text-gray-500 border-b border-gray-100">
                <th className="py-2 pr-4 font-medium">Service</th>
                <th className="py-2 pr-4 font-medium text-right">Calls</th>
                <th className="py-2 pr-4 font-medium text-right">Tokens (in / out)</th>
                <th className="py-2 font-medium text-right">Cost</th>
              </tr>
            </thead>
            <tbody>
              {services.map(([svc, v]) => (
                <tr key={svc} className="border-b border-gray-50">
                  <td className="py-2 pr-4 text-gray-700">{SERVICE_LABEL[svc] || svc}</td>
                  <td className="py-2 pr-4 text-gray-600 text-right">{v.calls.toLocaleString()}</td>
                  <td className="py-2 pr-4 text-gray-500 text-right">{v.input_tokens.toLocaleString()} / {v.output_tokens.toLocaleString()}</td>
                  <td className="py-2 text-gray-900 text-right font-medium">{usd(v.usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Per day */}
      {data.by_day.length > 0 && (
        <div className="bg-white shadow rounded-lg p-6">
          <h2 className="text-lg font-medium text-gray-900 mb-3">Per day</h2>
          <div className="space-y-1.5">
            {data.by_day.map(d => (
              <div key={d.day} className="flex items-center gap-3 text-sm">
                <span className="w-24 text-gray-500 flex-none">{d.day}</span>
                <div className="flex-1 bg-gray-100 rounded h-4 overflow-hidden">
                  <div className="bg-indigo-500 h-4" style={{ width: `${(d.usd / maxDay) * 100}%` }} />
                </div>
                <span className="w-20 text-right text-gray-700 flex-none">{usd(d.usd)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
