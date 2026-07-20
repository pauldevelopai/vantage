import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { hasRole } from '../lib/auth';
import { AuthImg } from '../components/AuthImg';
import { CropImg } from '../components/CropImg';
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
          People your cameras have seen in the last 7 days. Face sightings are clickable —
          the history engine links appearances by face, so it activates the first time
          someone comes close enough for one. Until then you'll see person shots with no history.
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
          {rows.map((p, idx) => {
            const isFace = p.source !== 'detection' && !!p.sighting_id;
            const inner = (
              <>
                <div className="relative aspect-square bg-gray-100">
                  {p.image_url && p.bbox
                    ? <CropImg src={p.image_url} alt={isFace ? 'Face sighting' : 'Person'}
                               bbox={p.bbox as [number, number, number, number]}
                               pad={isFace ? 0.45 : 0.2} className="w-full h-full" />
                    : p.image_url
                      ? <AuthImg src={p.image_url} alt="Sighting" className="w-full h-full object-cover" />
                      : <div className="w-full h-full flex items-center justify-center text-[10px] text-gray-400">no image</div>}
                  {p.matched_label && (
                    <span className="absolute top-1 left-1 text-[9px] px-1.5 py-0.5 rounded-full bg-amber-500 text-black font-medium">
                      {p.matched_label}
                    </span>
                  )}
                </div>
                <div className="px-2 py-1.5">
                  <div className="text-[11px] font-medium text-gray-800 truncate">
                    {p.matched_label || (isFace ? 'Unknown person' : 'Person')}
                  </div>
                  <div className="text-[10px] text-gray-500 truncate">
                    {isFace ? '' : 'no face captured · '}{p.camera_name} · {when(p.ts)}
                  </div>
                </div>
              </>
            );
            return isFace ? (
              <button key={p.sighting_id || idx} onClick={() => setSelected(p)}
                      className="text-left rounded-lg overflow-hidden bg-white border border-gray-200 hover:border-indigo-500 hover:shadow transition">
                {inner}
              </button>
            ) : (
              <div key={idx} className="rounded-lg overflow-hidden bg-white border border-gray-200"
                   title="History links by face — appears once someone comes close enough for one">
                {inner}
              </div>
            );
          })}
        </div>
      )}

      {selected && <HistoryPanel person={selected} onClose={() => setSelected(null)}
                                 onEnrolled={() => { setSelected(null); load(); }} />}
    </div>
  );
}

/** "Where have they been?" — the person-history engine over our own sightings,
 *  plus the enrolment control: give an unknown face a name + details and it goes
 *  into the recognition DB, so the next time they come up the cameras say who it
 *  is. Enrolment needs a face embedding, which every clickable row here has. */
function HistoryPanel({ person, onClose, onEnrolled }: { person: PersonRow; onClose: () => void; onEnrolled: () => void }) {
  const [h, setH] = useState<PersonHistoryResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const enrolled = !!person.matched_label;
  const canEnrol = !enrolled && !!person.sighting_id && (hasRole('supervisor') || hasRole('admin'));
  const [name, setName] = useState('');
  const [details, setDetails] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveErr, setSaveErr] = useState<string | null>(null);

  async function enrol() {
    if (!name.trim() || !person.sighting_id) return;
    setSaving(true);
    setSaveErr(null);
    try {
      await api.enrollFaceFromSighting(person.sighting_id, name.trim(), details.trim());
      onEnrolled();
    } catch (e: any) {
      setSaveErr(e?.message || 'Could not save');
    } finally {
      setSaving(false);
    }
  }

  useEffect(() => {
    setLoading(true);
    setH(null);
    setErr(null);
    if (!person.sighting_id) { setLoading(false); return; }
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
          {/* Recognised — show who they are and the details on file. */}
          {enrolled && (
            <div className="mb-4 rounded-md bg-emerald-50 border border-emerald-200 p-3">
              <p className="text-sm font-medium text-emerald-900">Recognised as {person.matched_label}</p>
              {person.matched_details
                ? <p className="text-xs text-emerald-800 mt-1 whitespace-pre-wrap">{person.matched_details}</p>
                : <p className="text-xs text-emerald-700/70 mt-1">No details on file. Manage this person on the Faces page.</p>}
            </div>
          )}

          {/* Not recognised — name them and add details to build the DB. */}
          {canEnrol && (
            <div className="mb-4 rounded-md bg-indigo-50 border border-indigo-200 p-3">
              <p className="text-sm font-medium text-indigo-900">Name this person</p>
              <p className="text-[11px] text-indigo-700/80 mb-2">
                Adds their face to your recognition database — next time they appear, the cameras will say who it is.
              </p>
              <input autoFocus value={name} onChange={e => setName(e.target.value)}
                     onKeyDown={e => { if (e.key === 'Enter') enrol(); }}
                     placeholder="Name (e.g. Thabo — gardener)"
                     className="w-full bg-white border border-indigo-200 rounded px-2 py-1.5 text-sm text-gray-800 placeholder:text-gray-400 focus:border-indigo-500 outline-none" />
              <textarea value={details} onChange={e => setDetails(e.target.value)} rows={2}
                        placeholder="Details (optional) — who they are, why they're here, anything worth noting"
                        className="mt-2 w-full bg-white border border-indigo-200 rounded px-2 py-1.5 text-sm text-gray-800 placeholder:text-gray-400 focus:border-indigo-500 outline-none resize-y" />
              <div className="mt-2 flex items-center gap-2">
                <button onClick={enrol} disabled={saving || !name.trim()}
                        className="text-xs font-medium bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded px-3 py-1.5">
                  {saving ? 'Saving…' : 'Save to recognition database'}
                </button>
                {saveErr && <span className="text-xs text-red-600">{saveErr}</span>}
              </div>
            </div>
          )}
          {!enrolled && !canEnrol && (
            <p className="mb-4 text-[11px] text-gray-400">
              Naming a person requires the supervisor or admin role.
            </p>
          )}

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
                      {/* Every prior appearance WITH its evidence crop — history
                          a human can check with their eyes, not text rows. */}
                      <div className="mt-3 grid grid-cols-3 sm:grid-cols-4 gap-2 max-h-72 overflow-y-auto pr-1">
                        {h.prior_sightings.map((s, i) => (
                          <div key={s.sighting_id || i} className="rounded-md overflow-hidden border border-gray-200 bg-gray-50">
                            <div className="aspect-square bg-gray-100">
                              {s.frame_url && s.bbox
                                ? <CropImg src={s.frame_url} alt={`Sighting at ${s.camera_id}`}
                                           bbox={s.bbox as [number, number, number, number]} pad={0.45}
                                           className="w-full h-full" />
                                : <div className="w-full h-full flex items-center justify-center text-[9px] text-gray-400">no frame</div>}
                            </div>
                            <div className="px-1.5 py-1">
                              <div className="text-[10px] text-gray-700 truncate">{s.camera_id}</div>
                              <div className="text-[9px] text-gray-400 flex justify-between">
                                <span>{when(s.ts)}</span>
                                <span className="tabular-nums">{Math.round(s.score * 100)}%</span>
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
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
