import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { hasRole } from '../lib/auth';
import type { UserSource, CatalogueEntry, SourceVocab } from '../lib/types';

/**
 * Intel — the data feeding the brain.
 *
 *  1. Connected: sources actually supplying records (real counts).
 *  2. Add a source: the owner declares one as they gain access. The backend refuses
 *     anything without an allowed (non-personal) domain, a lawful basis and a
 *     retention period — and refuses personal data at ingest, fail-closed.
 *  3. Available later: the researched roadmap. Honest about status — nothing here
 *     pretends to be connected.
 */

const DOMAIN_LABEL: Record<string, string> = {
  places_context: 'Area & crime context',
  detection_reference: 'Detection reference',
};

const STATUS_META: Record<string, { label: string; cls: string; blurb: string }> = {
  available: { label: 'Can do now',   cls: 'bg-green-100 text-green-800 border-green-200', blurb: 'No blocker — we can connect this.' },
  gated:     { label: 'Needs a deal', cls: 'bg-blue-100 text-blue-800 border-blue-200',    blurb: 'Real and reachable, but needs a commercial or partner agreement.' },
  blocked:   { label: 'Closed to us', cls: 'bg-gray-100 text-gray-600 border-gray-200',    blurb: 'A real route exists but is not open to a private company.' },
  rejected:  { label: 'Won’t use',    cls: 'bg-red-100 text-red-800 border-red-200',       blurb: 'We could connect it, and deliberately do not.' },
};

const ML_STATUS_META: Record<string, { label: string; cls: string }> = {
  active:      { label: 'ACTIVE',      cls: 'bg-green-100 text-green-800' },
  planned:     { label: 'PLANNED',     cls: 'bg-gray-100 text-gray-600' },
  unavailable: { label: 'UNAVAILABLE', cls: 'bg-red-100 text-red-700' },
};

/** The honest module inventory: what runs, what it does, what's blocked. */
function MlStatusSection() {
  const [ml, setMl] = useState<any>(null);
  useEffect(() => { api.getMlStatus().then(setMl).catch(() => {}); }, []);
  if (!ml) return null;
  return (
    <>
      <div className="flex items-baseline justify-between mt-8 mb-2">
        <h2 className="text-lg font-medium text-gray-900">Vision stack</h2>
        <span className="text-xs text-gray-500">open-source models on your box · one paid narrator</span>
      </div>
      <div className="bg-white shadow rounded-lg divide-y divide-gray-100">
        {ml.vision_stack.map((m: any) => {
          const meta = ML_STATUS_META[m.status] || ML_STATUS_META.planned;
          return (
            <div key={m.name} className="p-3 flex items-start gap-3">
              <span className={`mt-0.5 text-[9px] font-bold tracking-wider px-1.5 py-0.5 rounded flex-none ${meta.cls}`}>{meta.label}</span>
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium text-gray-900">{m.name}
                  {m.kind === 'paid_api' && <span className="ml-2 text-[10px] text-amber-700 bg-amber-50 px-1.5 py-0.5 rounded">paid</span>}
                </div>
                <div className="text-xs text-gray-500">{m.purpose} · {m.detail}</div>
              </div>
            </div>
          );
        })}
      </div>

      <div className="flex items-baseline justify-between mt-8 mb-2">
        <h2 className="text-lg font-medium text-gray-900">Data engine feeds</h2>
        <span className="text-xs text-gray-500">Apify + curated reference · normalise → guard → tag → store</span>
      </div>
      <div className="bg-white shadow rounded-lg divide-y divide-gray-100">
        {ml.data_feeds.map((f: any) => (
          <div key={f.source_id} className="p-3 flex items-start gap-3">
            <span className={`mt-0.5 text-[9px] font-bold tracking-wider px-1.5 py-0.5 rounded flex-none ${
              f.records > 0 ? 'bg-green-100 text-green-800' : f.blocked ? 'bg-amber-100 text-amber-800' : 'bg-gray-100 text-gray-600'
            }`}>
              {f.records > 0 ? `${f.records} RECORDS` : f.blocked ? 'BLOCKED' : 'EMPTY'}
            </span>
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium text-gray-900 font-mono">{f.source_id}</div>
              <div className="text-xs text-gray-500">{f.description}</div>
              <div className="text-[11px] text-gray-400 mt-0.5">
                {f.actor ? `actor: ${f.actor}` : 'no actor'} · {f.lawful_basis} · retention {f.retention_days}d
                {f.blocked && <span className="text-amber-700"> · {f.blocked}</span>}
              </div>
            </div>
          </div>
        ))}
      </div>
    </>
  );
}

export function IntelPage() {
  const isAdmin = hasRole('admin');
  const [vocab, setVocab] = useState<SourceVocab | null>(null);
  const [engine, setEngine] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [feeding, setFeeding] = useState<UserSource | null>(null);

  async function load() {
    try {
      const [v, e] = await Promise.all([api.getIntelSources(), api.getIntelligenceData()]);
      setVocab(v);
      setEngine(e);
      setError(null);
    } catch (e: any) {
      setError(e?.message || 'Failed to load');
    }
  }

  useEffect(() => { load(); }, []);

  if (error) return <div className="max-w-5xl mx-auto px-4 py-6 text-red-600">{error}</div>;
  if (!vocab) return <div className="max-w-5xl mx-auto px-4 py-6 text-gray-500">Loading…</div>;

  const builtIn = engine?.sources || [];
  const liveRecords = engine?.stats?.total_live_records ?? 0;

  return (
    <div className="max-w-5xl mx-auto px-4 py-6">
      <div className="flex items-start justify-between gap-4 mb-2">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Intel</h1>
          <p className="text-sm text-gray-500">
            The data feeding the brain — what your cameras see, put in context.
          </p>
        </div>
        {isAdmin && (
          <button onClick={() => setShowAdd(v => !v)}
                  className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 flex-none">
            {showAdd ? 'Cancel' : 'Add a source'}
          </button>
        )}
      </div>

      <div className="rounded-lg bg-amber-50 border border-amber-200 p-3 mb-5 text-sm text-amber-900">
        <span className="font-medium">Data boundary:</span> {vocab.boundary}
      </div>

      {showAdd && isAdmin && <AddSourceForm vocab={vocab} onDone={() => { setShowAdd(false); load(); }} />}

      <MlStatusSection />

      {/* 1. Connected */}
      <div className="flex items-baseline justify-between mt-6 mb-2">
        <h2 className="text-lg font-medium text-gray-900">Connected sources</h2>
        <span className="text-xs text-gray-400">{liveRecords.toLocaleString()} live record{liveRecords === 1 ? '' : 's'} in the engine</span>
      </div>

      {vocab.sources.length === 0 && builtIn.length === 0 ? (
        <p className="text-sm text-gray-500 bg-white border border-gray-200 rounded-lg p-6 text-center">
          Nothing connected yet. Add a source above, or start with one marked “Can do now” below.
        </p>
      ) : (
        <div className="space-y-2">
          {vocab.sources.map(s => (
            <div key={s.source_id} className="bg-white border border-gray-200 rounded-lg p-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-medium text-gray-900">{s.name}</span>
                    <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-gray-100 text-gray-600">
                      {DOMAIN_LABEL[s.domain] || s.domain}
                    </span>
                    {!s.enabled && <span className="text-[10px] text-gray-400">paused</span>}
                  </div>
                  {s.description && <p className="text-xs text-gray-500 mt-0.5">{s.description}</p>}
                  <p className="text-[11px] text-gray-400 mt-1">
                    <span className="font-medium text-gray-500">{s.record_count.toLocaleString()}</span> records ·
                    kept {s.retention_days} days · basis: {s.lawful_basis.replace(/_/g, ' ')}
                    {s.endpoint ? ` · ${s.endpoint}` : ''}
                  </p>
                </div>
                {isAdmin && (
                  <div className="flex items-center gap-3 flex-none">
                    <button onClick={() => setFeeding(s)} className="text-xs text-blue-600 hover:text-blue-800">Feed data</button>
                    <button
                      onClick={async () => {
                        if (!confirm(`Remove "${s.name}"? Records already stored are kept until they expire.`)) return;
                        try { await api.deleteIntelSource(s.source_id); load(); } catch (e: any) { alert(e.message); }
                      }}
                      className="text-xs text-red-500 hover:text-red-700">Remove</button>
                  </div>
                )}
              </div>
            </div>
          ))}

          {builtIn.map((s: any) => (
            <div key={s.source_id} className="bg-white border border-gray-200 rounded-lg p-3">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-sm font-medium text-gray-900">{s.source_id}</span>
                <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-gray-100 text-gray-600">
                  {DOMAIN_LABEL[s.domain] || s.domain}
                </span>
                <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-indigo-50 text-indigo-700">built in</span>
              </div>
              <p className="text-xs text-gray-500 mt-0.5">{s.description}</p>
              <p className="text-[11px] text-gray-400 mt-1">
                kept {s.retention_days} days{s.apify_actor ? ` · via ${s.apify_actor}` : ''}
              </p>
            </div>
          ))}
        </div>
      )}

      {/* 2. Roadmap */}
      <h2 className="text-lg font-medium text-gray-900 mt-8 mb-1">Available later</h2>
      <p className="text-sm text-gray-500 mb-3">
        Routes we've researched but haven't connected. Nothing here is live — this is the honest state of each.
      </p>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {vocab.catalogue.map(c => <CatalogueCard key={c.key} entry={c} />)}
      </div>

      {feeding && <FeedModal source={feeding} onClose={() => setFeeding(null)} onDone={() => { setFeeding(null); load(); }} />}
    </div>
  );
}

function CatalogueCard({ entry }: { entry: CatalogueEntry }) {
  const meta = STATUS_META[entry.status] || STATUS_META.blocked;
  return (
    <div className={`bg-white border rounded-lg p-3 ${entry.recommended ? 'border-blue-300 ring-1 ring-blue-100' : 'border-gray-200'}`}>
      <div className="flex items-start justify-between gap-2">
        <span className="text-sm font-medium text-gray-900">{entry.name}</span>
        <span className={`text-[10px] px-1.5 py-0.5 rounded-full border flex-none ${meta.cls}`} title={meta.blurb}>
          {meta.label}
        </span>
      </div>
      <p className="text-xs text-gray-600 mt-1">{entry.provides}</p>
      <p className="text-xs text-gray-500 mt-1"><span className="text-gray-400">Why:</span> {entry.why}</p>
      <p className="text-[11px] text-gray-500 mt-2 bg-gray-50 rounded p-2">{entry.requirement}</p>
      {entry.url && (
        <a href={entry.url} target="_blank" rel="noreferrer"
           className="inline-block mt-2 text-[11px] text-blue-600 hover:text-blue-800 break-all">{entry.url} ↗</a>
      )}
      {entry.recommended && <p className="mt-2 text-[11px] font-medium text-blue-700">★ Recommended next step</p>}
    </div>
  );
}

function AddSourceForm({ vocab, onDone }: { vocab: SourceVocab; onDone: () => void }) {
  const [f, setF] = useState({
    name: '', domain: vocab.domains[0]?.value || '', lawful_basis: vocab.lawful_bases[0]?.value || '',
    retention_days: 365, description: '', endpoint: '', notes: '',
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true); setErr(null);
    try {
      await api.createIntelSource(f);
      onDone();
    } catch (e: any) {
      setErr(e?.message || 'Could not add the source');
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={submit} className="bg-white shadow rounded-lg p-5 border-l-4 border-blue-400">
      <h2 className="text-lg font-medium text-gray-900 mb-1">Add a data source</h2>
      <p className="text-xs text-gray-500 mb-4">
        Every source must say what kind of data it is, why we may lawfully hold it, and how long we keep it.
        Personal data is refused — there is no domain for it.
      </p>
      {err && <div className="mb-3 p-2 bg-red-50 text-red-700 text-xs rounded">{err}</div>}

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700">Name</label>
          <input required value={f.name} onChange={e => setF(v => ({ ...v, name: e.target.value }))}
                 placeholder="e.g. SAPS crime stats — Parkview"
                 className="mt-1 w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700">Kind of data</label>
          <select value={f.domain} onChange={e => setF(v => ({ ...v, domain: e.target.value }))}
                  className="mt-1 w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm">
            {vocab.domains.map(d => <option key={d.value} value={d.value}>{DOMAIN_LABEL[d.value] || d.label}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700">Lawful basis</label>
          <select value={f.lawful_basis} onChange={e => setF(v => ({ ...v, lawful_basis: e.target.value }))}
                  className="mt-1 w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm">
            {vocab.lawful_bases.map(b => <option key={b.value} value={b.value}>{b.label}</option>)}
          </select>
          <p className="mt-1 text-[11px] text-gray-400">Why we're allowed to hold it.</p>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700">Keep for (days)</label>
          <input type="number" min={1} required value={f.retention_days}
                 onChange={e => setF(v => ({ ...v, retention_days: Number(e.target.value) }))}
                 className="mt-1 w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm" />
          <p className="mt-1 text-[11px] text-gray-400">Records expire automatically. There is no “forever”.</p>
        </div>
      </div>

      <div className="mt-4">
        <label className="block text-sm font-medium text-gray-700">Description</label>
        <input value={f.description} onChange={e => setF(v => ({ ...v, description: e.target.value }))}
               placeholder="What this source gives the AI"
               className="mt-1 w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm" />
      </div>
      <div className="mt-4">
        <label className="block text-sm font-medium text-gray-700">Feed URL <span className="text-gray-400">(optional)</span></label>
        <input value={f.endpoint} onChange={e => setF(v => ({ ...v, endpoint: e.target.value }))}
               placeholder="https://… — if you've licensed an API"
               className="mt-1 w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm" />
      </div>

      <button type="submit" disabled={saving}
              className="mt-4 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50">
        {saving ? 'Adding…' : 'Add source'}
      </button>
    </form>
  );
}

/** Paste records into a declared source. Personal data is refused at ingest. */
function FeedModal({ source, onClose, onDone }: { source: UserSource; onClose: () => void; onDone: () => void }) {
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  async function submit() {
    setBusy(true); setErr(null); setOk(null);
    let records: any[];
    try {
      const parsed = JSON.parse(text);
      records = Array.isArray(parsed) ? parsed : [parsed];
    } catch {
      setErr('That isn’t valid JSON. Paste an object, or an array of objects.');
      setBusy(false);
      return;
    }
    try {
      const r = await api.feedIntelSource(source.source_id, records);
      setOk(`Stored ${r.written} record${r.written === 1 ? '' : 's'}.` +
            (r.rejected?.length ? ` ${r.rejected.length} refused.` : ''));
      if (r.rejected?.length) setErr(r.rejected[0]);
      else setTimeout(onDone, 900);
    } catch (e: any) {
      setErr(e?.message || 'Could not store those records');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl max-w-lg w-full" onClick={e => e.stopPropagation()}>
        <div className="p-4 border-b border-gray-100">
          <h2 className="text-lg font-medium text-gray-900">Feed data into “{source.name}”</h2>
          <p className="text-xs text-gray-500 mt-0.5">
            Stored as {DOMAIN_LABEL[source.domain] || source.domain}, kept {source.retention_days} days.
            Anything person-identifying is refused.
          </p>
        </div>
        <div className="p-4">
          <textarea value={text} onChange={e => setText(e.target.value)} rows={8}
            placeholder={'[\n  {"precinct": "Parkview", "quarter": "2026Q1", "burglary": 42}\n]'}
            className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-xs font-mono" />
          {err && <p className="mt-2 text-xs text-red-600">{err}</p>}
          {ok && <p className="mt-2 text-xs text-green-700">{ok}</p>}
          <div className="mt-3 flex items-center gap-2">
            <button onClick={submit} disabled={busy || !text.trim()}
                    className="px-3 py-1.5 bg-blue-600 text-white text-sm rounded-md hover:bg-blue-700 disabled:opacity-50">
              {busy ? 'Storing…' : 'Store records'}
            </button>
            <button onClick={onClose} className="px-3 py-1.5 text-sm text-gray-600">Close</button>
          </div>
        </div>
      </div>
    </div>
  );
}
