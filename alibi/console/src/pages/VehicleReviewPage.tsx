import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { CropImg } from '../components/CropImg';

/**
 * Make/model review queue — the local-data loop.
 *
 * The client-facing surfaces stay VLM-or-absent; this is a back-office page
 * where a reviewer confirms or corrects the make/model the VLM guessed on a
 * real crop. Confirmed rows become locally-labelled training data for a future
 * SA-tuned classifier. Nothing here is shown to a client.
 */

interface ReviewItem {
  item_id: string;
  ts: string;
  camera_id: string;
  frame_url: string;
  bbox: number[];
  claimed: { colour?: string; make?: string; model?: string; body?: string; confidence?: string };
}

function claimText(c: ReviewItem['claimed']): string {
  const parts = [c.colour, c.make, c.model || c.body].filter(Boolean);
  return parts.length ? parts.join(' ') : 'unlabelled vehicle';
}

export function VehicleReviewPage() {
  const [pending, setPending] = useState<ReviewItem[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [corpus, setCorpus] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [form, setForm] = useState<{ make: string; model: string; colour: string }>({ make: '', model: '', colour: '' });

  function load() {
    api.getVehicleReview()
      .then(d => { setPending(d.pending || []); setCounts(d.counts || {}); setCorpus(d.corpus_size || 0); setErr(null); })
      .catch(e => setErr(e?.message || 'Failed to load'));
  }
  useEffect(() => { load(); }, []);

  async function decide(item: ReviewItem, decision: 'confirm' | 'reject', correction?: boolean) {
    setBusy(item.item_id);
    try {
      const body: any = { decision };
      if (decision === 'confirm' && correction) {
        body.make = form.make || undefined; body.model = form.model || undefined; body.colour = form.colour || undefined;
      }
      await api.decideVehicleReview(item.item_id, body);
      setEditing(null);
      setPending(p => p.filter(x => x.item_id !== item.item_id));
      setCorpus(c => decision === 'confirm' ? c + 1 : c);
    } catch (e: any) { setErr(e?.message || 'Failed'); } finally { setBusy(null); }
  }

  return (
    <div className="max-w-6xl mx-auto px-4 py-6">
      <div className="mb-4">
        <h1 className="text-2xl font-semibold text-gray-900">Vehicle review</h1>
        <p className="text-sm text-gray-500">
          Confirm or correct the make/model the AI guessed on real crops. Confirmed rows build a
          locally-labelled dataset for an SA-tuned classifier. Back-office only — never shown to clients.
        </p>
        <div className="mt-2 flex gap-4 text-xs text-gray-600">
          <span><b className="text-gray-900">{counts.pending || 0}</b> pending</span>
          <span><b className="text-gray-900">{counts.confirmed || 0}</b> confirmed</span>
          <span><b className="text-gray-900">{counts.rejected || 0}</b> rejected</span>
          <span className="text-emerald-600"><b>{corpus}</b> in training corpus</span>
        </div>
      </div>

      {err && <div className="my-3 p-3 bg-red-50 text-red-700 text-sm rounded-md">{err}</div>}

      {pending.length === 0 ? (
        <div className="bg-white shadow rounded-lg p-8 text-center text-gray-500">
          Nothing to review right now. Items appear here as the AI describes vehicles on real frames.
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {pending.map(item => (
            <div key={item.item_id} className="bg-white shadow rounded-lg overflow-hidden">
              <div className="aspect-video bg-gray-100">
                <CropImg src={item.frame_url} alt="vehicle" bbox={item.bbox as [number, number, number, number]}
                         pad={0.25} className="w-full h-full" />
              </div>
              <div className="p-3">
                <div className="text-sm font-medium text-gray-900">AI guess: {claimText(item.claimed)}</div>
                <div className="text-[11px] text-gray-400">
                  {item.claimed.confidence ? `confidence ${item.claimed.confidence}` : ''} · {item.camera_id}
                </div>

                {editing === item.item_id ? (
                  <div className="mt-2 space-y-1.5">
                    <div className="flex gap-1.5">
                      <input value={form.make} onChange={e => setForm(f => ({ ...f, make: e.target.value }))}
                             placeholder="make" className="w-1/2 border-gray-300 rounded text-xs px-1.5 py-1" />
                      <input value={form.model} onChange={e => setForm(f => ({ ...f, model: e.target.value }))}
                             placeholder="model" className="w-1/2 border-gray-300 rounded text-xs px-1.5 py-1" />
                    </div>
                    <input value={form.colour} onChange={e => setForm(f => ({ ...f, colour: e.target.value }))}
                           placeholder="colour" className="w-full border-gray-300 rounded text-xs px-1.5 py-1" />
                    <div className="flex gap-1.5">
                      <button disabled={busy === item.item_id} onClick={() => decide(item, 'confirm', true)}
                              className="flex-1 text-xs bg-blue-600 hover:bg-blue-700 text-white rounded px-2 py-1">Save label</button>
                      <button onClick={() => setEditing(null)} className="text-xs text-gray-500 px-2">Cancel</button>
                    </div>
                  </div>
                ) : (
                  <div className="mt-2 flex gap-1.5">
                    <button disabled={busy === item.item_id} onClick={() => decide(item, 'confirm')}
                            className="text-xs bg-emerald-600 hover:bg-emerald-700 text-white rounded px-2.5 py-1">Correct ✓</button>
                    <button onClick={() => { setEditing(item.item_id); setForm({ make: item.claimed.make || '', model: item.claimed.model || '', colour: item.claimed.colour || '' }); }}
                            className="text-xs bg-gray-100 hover:bg-gray-200 text-gray-700 rounded px-2.5 py-1">Fix label</button>
                    <button disabled={busy === item.item_id} onClick={() => decide(item, 'reject')}
                            className="text-xs text-red-600 hover:text-red-800 px-2">Not a vehicle</button>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
