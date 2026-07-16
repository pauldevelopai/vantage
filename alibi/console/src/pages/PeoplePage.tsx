import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { AuthImg } from '../components/AuthImg';
import type { PersonRow, PersonHistoryResult } from '../lib/types';

/**
 * People — "who has been here, and where have they been before?"
 *
 * Answered ONLY from this deployment's own cameras. Each card is a real face
 * sighting with the evidence still behind it. Clicking one runs the person-history
 * engine: a cosine search over our own sighting archive.
 *
 * Unknown people stay unknown. We surface CONTINUITY ("seen 4 times since Tuesday,
 * at 2 cameras"), never a guessed identity — an identity only ever comes from a
 * watchlist entry the owner deliberately enrolled.
 */

function when(iso: string): string {
  const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z');
  const s = Math.max(0, (Date.now() - d.getTime()) / 1000);
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return d.toLocaleString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' });
}

export function PeoplePage() {
  const [rows, setRows] = useState<PersonRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [selected, setSelected] = useState<PersonRow | null>(null);

  async function load() {
    try {
      const d = await api.getRecentPeople(168);
      setRows(d.people);
      setErr(null);
    } catch (e: any) {
      setErr(e?.message || 'Failed to load people');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    const t = setInterval(load, 20000);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="max-w-6xl mx-auto px-4 py-6">
      <div className="mb-4">
        <h1 className="text-2xl font-semibold text-gray-900">People</h1>
        <p className="text-sm text-gray-500">
          Faces your cameras have seen in the last 7 days. Click anyone to see where else they've been.
        </p>
      </div>

      {err && <div className="my-4 p-3 bg-red-50 text-red-700 text-sm rounded-md">{err}</div>}
      {loading && <p className="text-gray-500 py-8">Loading…</p>}

      {!loading && rows.length === 0 && (
        <div className="bg-white shadow rounded-lg p-8 text-center">
          <p className="text-gray-900 font-medium">No faces seen yet</p>
          <p className="text-sm text-gray-500 mt-2 max-w-lg mx-auto">
            This only ever shows real faces your own cameras recorded — so it stays empty
            until the recorder sends motion frames containing people. Nothing here is simulated.
          </p>
        </div>
      )}

      {rows.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3">
          {rows.map(p => (
            <button
              key={p.sighting_id}
              onClick={() => setSelected(p)}
              className="text-left rounded-lg overflow-hidden bg-white border border-gray-200 hover:border-indigo-500 hover:shadow transition"
            >
              <div className="relative aspect-square bg-gray-100">
                {p.image_url
                  ? <AuthImg src={p.image_url} alt="Face sighting" className="w-full h-full object-cover" />
                  : <div className="w-full h-full flex items-center justify-center text-[10px] text-gray-400">no image</div>}
                {p.matched_label && (
                  <span className="absolute top-1 left-1 text-[9px] px-1.5 py-0.5 rounded-full bg-amber-500 text-black font-medium">
                    {p.matched_label}
                  </span>
                )}
              </div>
              <div className="px-2 py-1.5">
                <div className="text-[11px] font-medium text-gray-800 truncate">
                  {p.matched_label || 'Unknown person'}
                </div>
                <div className="text-[10px] text-gray-500 truncate">{p.camera_name} · {when(p.ts)}</div>
              </div>
            </button>
          ))}
        </div>
      )}

      {selected && <HistoryPanel person={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

/** "Where have they been?" — the person-history engine over our own sightings. */
function HistoryPanel({ person, onClose }: { person: PersonRow; onClose: () => void }) {
  const [h, setH] = useState<PersonHistoryResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    setH(null);
    setErr(null);
    api.getPersonHistory(person.sighting_id)
      .then(r => setH(r))
      .catch(e => setErr(e?.message || 'Could not look this person up'))
      .finally(() => setLoading(false));
  }, [person.sighting_id]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[85vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        <div className="flex items-start justify-between p-4 border-b border-gray-100">
          <div>
            <h2 className="text-lg font-medium text-gray-900">
              {person.matched_label || 'Unknown person'}
            </h2>
            <p className="text-xs text-gray-500">
              Seen at {person.camera_name} · {when(person.ts)}
            </p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-sm">Close</button>
        </div>

        <div className="p-4">
          <div className="flex gap-4">
            <div className="w-40 flex-none">
              {person.image_url && (
                <AuthImg src={person.image_url} alt="Sighting" className="w-full rounded-md border border-gray-200" />
              )}
              <p className="mt-1 text-[10px] text-gray-400">The evidence frame this sighting came from.</p>
            </div>

            <div className="min-w-0 flex-1">
              {loading && <p className="text-sm text-gray-500">Searching earlier sightings…</p>}
              {err && <p className="text-sm text-red-600">{err}</p>}
              {h && (
                <>
                  <p className="text-sm text-gray-800">{h.summary}</p>
                  {!h.seen_before ? (
                    <p className="mt-3 text-sm text-gray-500">
                      No earlier appearance found on your cameras. This looks like a first visit —
                      or the earlier views were too different to link confidently.
                    </p>
                  ) : (
                    <>
                      <div className="mt-3 grid grid-cols-3 gap-2 text-center">
                        <Stat label="Times seen" value={String(h.times_seen)} />
                        <Stat label="Cameras" value={String(h.distinct_cameras.length)} />
                        <Stat label="First seen" value={h.first_seen ? when(h.first_seen) : '—'} />
                      </div>
                      <ul className="mt-3 space-y-1.5 max-h-56 overflow-y-auto">
                        {h.prior_sightings.map((s, i) => (
                          <li key={i} className="flex items-center justify-between text-xs border-b border-gray-50 pb-1">
                            <span className="text-gray-700">{s.camera_id}</span>
                            <span className="text-gray-400">{when(s.ts)}</span>
                            <span className="text-gray-400 tabular-nums">{Math.round(s.score * 100)}% alike</span>
                          </li>
                        ))}
                      </ul>
                    </>
                  )}
                  {h.watchlist_person_id && (
                    <p className="mt-3 text-xs text-amber-700 bg-amber-50 rounded p-2">
                      An earlier sighting matched a watchlist entry you enrolled. Worth a human review.
                    </p>
                  )}
                  <p className="mt-3 text-[11px] text-gray-400">
                    Matches are by appearance similarity across your own cameras only, and are a
                    prompt for a human to look — never proof of identity.
                  </p>
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-gray-50 p-2">
      <div className="text-sm font-semibold text-gray-900 truncate">{value}</div>
      <div className="text-[10px] text-gray-500">{label}</div>
    </div>
  );
}
