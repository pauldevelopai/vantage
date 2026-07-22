import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../lib/api';
import { hasRole } from '../lib/auth';
import type { HotlistEntry } from '../lib/types';

/**
 * Hotlist — plates worth flagging.
 *
 * Every plate our cameras read is already checked against this list; a match raises
 * the incident to the review ceiling. Today the list is what YOU put in it — that's
 * the lawful, dependable v1. An official SAPS-sourced feed (NAVIC/Vumacam) would
 * populate this same store later; see Intel → Available later.
 *
 * Deliberately NOT wired to crowdsourced plate lists: their operators state the data
 * is unverified, and a false "stolen" flag raised against a real person at their gate
 * is a genuine safety risk.
 */

const REASONS = [
  { value: 'stolen', label: 'Reported stolen' },
  { value: 'wanted', label: 'Wanted / of interest' },
  { value: 'watch', label: 'Watch — tell me if it returns' },
  { value: 'banned', label: 'Not welcome on site' },
];

function reasonLabel(r: string) {
  return REASONS.find(x => x.value === r)?.label || r;
}

export function HotlistPage({ embedded = false }: { embedded?: boolean } = {}) {
  const canEdit = hasRole('supervisor') || hasRole('admin');
  const [entries, setEntries] = useState<HotlistEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [form, setForm] = useState({ plate: '', reason: 'stolen', source_ref: '' });
  const [saving, setSaving] = useState(false);
  const [q, setQ] = useState('');

  async function load() {
    try {
      const d = await api.getHotlistPlates();
      setEntries(d.entries || []);
      setErr(null);
    } catch (e: any) {
      setErr(e?.message || 'Failed to load the hotlist');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    if (!form.plate.trim()) return;
    setSaving(true);
    setErr(null);
    try {
      await api.addHotlistPlate({
        plate: form.plate.trim(),
        reason: form.reason,
        source_ref: form.source_ref.trim() || 'entered by owner',
      });
      setForm({ plate: '', reason: 'stolen', source_ref: '' });
      await load();
    } catch (e: any) {
      setErr(e?.message || 'Could not add that plate');
    } finally {
      setSaving(false);
    }
  }

  async function remove(plate: string) {
    if (!confirm(`Remove ${plate} from the hotlist? It will stop being flagged.`)) return;
    try { await api.removeHotlistPlate(plate); await load(); }
    catch (e: any) { setErr(e?.message || 'Could not remove that plate'); }
  }

  const shown = q.trim()
    ? entries.filter(e => e.plate.toLowerCase().includes(q.trim().toLowerCase()))
    : entries;

  return (
    <div className={embedded ? "" : 'max-w-4xl mx-auto px-4 py-6'}>
      {!embedded && <div className="mb-2">
        <h1 className="text-2xl font-semibold text-gray-900">Hotlist</h1>
        <p className="text-sm text-gray-500">
          Plates to flag. Every plate your cameras read is checked against this list — a match
          raises the incident for review.
        </p>
      </div>}

      <div className="rounded-lg bg-blue-50 border border-blue-200 p-3 mb-5 text-sm text-blue-900">
        This list is what you put in it — lawful and dependable, with no outside dependency.
        An official SAPS-sourced feed would fill this same list automatically; see{' '}
        <Link to="/intel" className="underline font-medium">Intel → Available later</Link>.
      </div>

      {err && <div className="mb-4 p-3 bg-red-50 text-red-700 text-sm rounded-md">{err}</div>}

      {canEdit && (
        <form onSubmit={add} className="bg-white shadow rounded-lg p-4 mb-6">
          <h2 className="text-sm font-medium text-gray-900 mb-3">Add a plate</h2>
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
            <div className="sm:col-span-1">
              <label className="block text-xs font-medium text-gray-700">Plate</label>
              <input
                value={form.plate}
                onChange={e => setForm(f => ({ ...f, plate: e.target.value.toUpperCase() }))}
                placeholder="CA 123 456"
                className="mt-1 w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm font-mono uppercase"
              />
            </div>
            <div className="sm:col-span-1">
              <label className="block text-xs font-medium text-gray-700">Why</label>
              <select
                value={form.reason}
                onChange={e => setForm(f => ({ ...f, reason: e.target.value }))}
                className="mt-1 w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm"
              >
                {REASONS.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
              </select>
            </div>
            <div className="sm:col-span-2">
              <label className="block text-xs font-medium text-gray-700">
                Reference <span className="text-gray-400">(case number, or where this came from)</span>
              </label>
              <input
                value={form.source_ref}
                onChange={e => setForm(f => ({ ...f, source_ref: e.target.value }))}
                placeholder="e.g. SAPS case 123/07/2026"
                className="mt-1 w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm"
              />
            </div>
          </div>
          <button type="submit" disabled={saving || !form.plate.trim()}
                  className="mt-3 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50">
            {saving ? 'Adding…' : 'Add to hotlist'}
          </button>
          <p className="mt-2 text-[11px] text-gray-400">
            Record where a plate came from. A flag prompts a human to look — it is never proof, and
            acting on an unverified plate can harm a real person.
          </p>
        </form>
      )}

      <div className="flex items-center justify-between mb-2">
        <h2 className="text-lg font-medium text-gray-900">
          Flagged plates {entries.length > 0 && <span className="text-sm text-gray-400">({entries.length})</span>}
        </h2>
        {entries.length > 5 && (
          <input value={q} onChange={e => setQ(e.target.value)} placeholder="Filter…"
                 className="rounded-md border border-gray-300 px-2 py-1 text-sm" />
        )}
      </div>

      {loading ? (
        <p className="text-gray-500 py-6">Loading…</p>
      ) : entries.length === 0 ? (
        <div className="bg-white shadow rounded-lg p-8 text-center">
          <p className="text-gray-900 font-medium">No plates flagged</p>
          <p className="text-sm text-gray-500 mt-2 max-w-lg mx-auto">
            Nothing is being watched for yet. Add a plate above and your cameras will flag it the
            moment they read it. This list is intentionally empty rather than pre-filled — we don't
            ship invented data.
          </p>
        </div>
      ) : (
        <div className="bg-white shadow rounded-lg overflow-hidden">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50">
              <tr className="text-left text-gray-500">
                <th className="py-2 px-4 font-medium">Plate</th>
                <th className="py-2 px-4 font-medium">Why</th>
                <th className="py-2 px-4 font-medium">Reference</th>
                <th className="py-2 px-4 font-medium">Added</th>
                {canEdit && <th className="py-2 px-4" />}
              </tr>
            </thead>
            <tbody>
              {shown.map(e => (
                <tr key={e.plate} className="border-t border-gray-100">
                  <td className="py-2 px-4 font-mono font-medium text-gray-900">{e.plate}</td>
                  <td className="py-2 px-4">
                    <span className={`text-xs px-2 py-0.5 rounded-full ${
                      e.reason === 'stolen' ? 'bg-red-100 text-red-800' : 'bg-amber-100 text-amber-800'
                    }`}>
                      {reasonLabel(e.reason)}
                    </span>
                  </td>
                  <td className="py-2 px-4 text-gray-600 truncate max-w-[16rem]" title={e.source_ref}>{e.source_ref}</td>
                  <td className="py-2 px-4 text-gray-400 whitespace-nowrap">
                    {e.added_ts ? new Date(e.added_ts + (e.added_ts.endsWith('Z') ? '' : 'Z')).toLocaleDateString() : '—'}
                  </td>
                  {canEdit && (
                    <td className="py-2 px-4 text-right">
                      <button onClick={() => remove(e.plate)} className="text-xs text-red-500 hover:text-red-700">Remove</button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
