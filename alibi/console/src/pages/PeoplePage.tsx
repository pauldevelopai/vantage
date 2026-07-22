import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { hasRole } from '../lib/auth';
import { AuthImg } from '../components/AuthImg';
import { CropImg } from '../components/CropImg';
import type { PersonRow, PersonHistoryResult } from '../lib/types';
import { TimeWindow, windowPhrase, type Win } from '../components/TimeWindow';

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
  const [win, setWin] = useState<Win>('7d');

  async function load(w: Win = win) {
    try {
      const d = await api.getRecentPeople(w);
      setRows(d.people);
      setErr(null);
    } catch (e: any) {
      setErr(e?.message || 'Failed to load people');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setLoading(true);
    load(win);
    const t = setInterval(() => load(win), 20000);
    return () => clearInterval(t);
  }, [win]);

  return (
    <div className="max-w-6xl mx-auto px-4 py-6">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">People</h1>
          <p className="text-sm text-gray-500">
            People your cameras have seen — {windowPhrase(win)}. Click any one of them. Where a face
            was captured you get their history and can name them; where only a body was detected
            you can run the face pass over that shot and name them if a face is recoverable.
          </p>
        </div>
        <TimeWindow value={win} onChange={setWin} className="flex-none mt-1" />
      </div>

      {err && <div className="my-4 p-3 bg-red-50 text-red-700 text-sm rounded-md">{err}</div>}
      {loading && <p className="text-gray-500 py-8">Loading…</p>}

      {!loading && rows.length === 0 && (
        <div className="bg-white shadow rounded-lg p-8 text-center">
          <p className="text-gray-900 font-medium">
            {win === 'all' ? 'Nobody on record yet' : `Nobody seen ${windowPhrase(win)}`}
          </p>
          <p className="text-sm text-gray-500 mt-2 max-w-lg mx-auto">
            This only ever shows real people your own cameras recorded — so it stays empty
            until the recorder sends motion frames containing them. Nothing here is simulated.
            {win !== 'all' && ' Try a longer period.'}
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
            // EVERY person is clickable. Rows without a face used to be dead
            // ends; now opening one lets you run the face pass over that person
            // and name them if a face can be recovered.
            return (
              <button key={p.sighting_id || idx} onClick={() => setSelected(p)}
                      className="text-left rounded-lg overflow-hidden bg-white border border-gray-200 hover:border-indigo-500 hover:shadow transition">
                {inner}
              </button>
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
  const canEditPerson = hasRole('supervisor') || hasRole('admin');
  const [name, setName] = useState('');
  const [details, setDetails] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveErr, setSaveErr] = useState<string | null>(null);
  const [editingPerson, setEditingPerson] = useState(false);

  // A body-only row has no face embedding, so there is nothing to name and no
  // history to search. Recovering a face from that person's box turns it into a
  // real face sighting — from then on this panel behaves like any other.
  const [recovered, setRecovered] = useState<{ token: string; preview: string | null; score: number } | null>(null);
  const [recovering, setRecovering] = useState(false);
  const [recoverMsg, setRecoverMsg] = useState<string | null>(null);
  const sid = person.sighting_id;
  const canEnrol = !enrolled && !!sid && canEditPerson;
  const frameId = (person.image_url || '').split('/').pop()?.replace('.jpg', '') || '';

  async function recoverFace() {
    if (!frameId || !person.bbox) return;
    setRecovering(true);
    setRecoverMsg(null);
    try {
      const r = await api.recoverFace(frameId, person.bbox as number[], person.camera_id, person.ts);
      if (r.found) {
        setRecovered({ token: r.token, preview: r.face_preview || null, score: r.score });
      } else {
        setRecoverMsg(r.reason || 'No readable face in this shot.');
      }
    } catch (e: any) {
      setRecoverMsg(e?.message || 'Could not check this shot for a face');
    } finally {
      setRecovering(false);
    }
  }

  /** Save only once the operator has looked at the crop and agrees it's a face.
   *  Naming someone already enrolled adds this view to their gallery rather
   *  than creating a second them — that is how recognition improves. */
  async function confirmRecovered() {
    if (!recovered || !name.trim()) return;
    setSaving(true);
    setSaveErr(null);
    try {
      const r = await api.confirmFace(recovered.token, name.trim(), details.trim());
      if (r?.extended_existing) {
        setRecovered(null);
        setRecoverMsg(`Added another view of ${r.label} — ${r.views} now on file. ` +
                      `They'll be easier to spot at this angle.`);
        setTimeout(onEnrolled, 2200);
      } else {
        onEnrolled();
      }
    } catch (e: any) {
      setSaveErr(e?.message || 'Could not save');
    } finally {
      setSaving(false);
    }
  }

  /** A wrong answer teaches as much as a right one — it tells this camera
   *  where the line between a face and a patch of texture falls. */
  async function rejectRecovered() {
    const tok = recovered?.token;
    setRecovered(null);
    setRecoverMsg("Noted — that wasn't a face. This camera will bear it in mind.");
    if (tok) { try { await api.rejectFace(tok); } catch { /* teaching is best-effort */ } }
  }

  async function updatePerson() {
    if (!name.trim() || !person.matched_person_id) return;
    setSaving(true);
    setSaveErr(null);
    try {
      await api.updateWatchlistPerson(person.matched_person_id,
                                      { label: name.trim(), details: details.trim() });
      onEnrolled();
    } catch (e: any) {
      setSaveErr(e?.message || 'Could not save');
    } finally {
      setSaving(false);
    }
  }

  async function enrol() {
    if (!name.trim() || !sid) return;
    setSaving(true);
    setSaveErr(null);
    try {
      await api.enrollFaceFromSighting(sid, name.trim(), details.trim());
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
    if (!sid) { setLoading(false); return; }
    api.getPersonHistory(sid)
      .then(r => setH(r))
      .catch(e => setErr(e?.message || 'Could not look this person up'))
      .finally(() => setLoading(false));
  }, [sid]);

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
          {/* Recognised — who they are, the details on file, and ALWAYS editable.
              Renaming re-appends the same face embedding, so the new name shows
              on this face and every past and future sighting of it at once. */}
          {enrolled && !editingPerson && (
            <div className="mb-4 rounded-md bg-emerald-50 border border-emerald-200 p-3">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-emerald-900">Recognised as {person.matched_label}</p>
                  {person.matched_details
                    ? <p className="text-xs text-emerald-800 mt-1 whitespace-pre-wrap">{person.matched_details}</p>
                    : <p className="text-xs text-emerald-700/70 mt-1">No details on file yet.</p>}
                </div>
                {canEditPerson && (
                  <button onClick={() => { setEditingPerson(true); setName(person.matched_label || ''); setDetails(person.matched_details || ''); }}
                          className="flex-none text-xs text-emerald-800 hover:text-emerald-900 border border-emerald-300 rounded px-2 py-1">
                    Edit
                  </button>
                )}
              </div>
            </div>
          )}
          {enrolled && editingPerson && (
            <div className="mb-4 rounded-md bg-emerald-50 border border-emerald-300 p-3">
              <p className="text-sm font-medium text-emerald-900 mb-2">Edit this person</p>
              <input autoFocus value={name} onChange={e => setName(e.target.value)}
                     placeholder="Name"
                     className="w-full bg-white border border-emerald-200 rounded px-2 py-1.5 text-sm text-gray-800 focus:border-emerald-500 outline-none" />
              <textarea value={details} onChange={e => setDetails(e.target.value)} rows={2}
                        placeholder="Details — who they are, why they're here, anything worth noting"
                        className="mt-2 w-full bg-white border border-emerald-200 rounded px-2 py-1.5 text-sm text-gray-800 focus:border-emerald-500 outline-none resize-y" />
              <div className="mt-2 flex items-center gap-2">
                <button onClick={updatePerson} disabled={saving || !name.trim()}
                        className="text-xs font-medium bg-emerald-700 hover:bg-emerald-600 disabled:opacity-50 text-white rounded px-3 py-1.5">
                  {saving ? 'Saving…' : 'Save'}
                </button>
                <button onClick={() => setEditingPerson(false)} className="text-xs text-gray-500">Cancel</button>
                {saveErr && <span className="text-xs text-red-600">{saveErr}</span>}
              </div>
              <p className="mt-1.5 text-[11px] text-emerald-800/70">
                The new name applies to this face everywhere — every past and future sighting of it.
              </p>
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
          {/* Body-only row: no face was captured, so there is nothing to name
              yet. Run the face pass over just this person's box — if a face is
              in there the row becomes nameable, and is matched against everyone
              already enrolled. If not, we say so rather than pretend. */}
          {!enrolled && !sid && !recovered && canEditPerson && (
            <div className="mb-4 rounded-md bg-gray-50 border border-gray-200 p-3">
              <p className="text-sm font-medium text-gray-800">No face captured in this shot</p>
              <p className="text-[11px] text-gray-500 mb-2">
                The cameras detected the person but not a face, so there's nothing to
                recognise them by yet. Check this shot again — this looks harder than the
                live pass does, and will show you whatever it finds.
              </p>
              <button onClick={recoverFace} disabled={recovering || !frameId || !person.bbox}
                      className="text-xs font-medium bg-gray-800 hover:bg-gray-700 disabled:opacity-50 text-white rounded px-3 py-1.5">
                {recovering ? 'Looking…' : 'Look for a face in this shot'}
              </button>
              {recoverMsg && <p className="mt-2 text-xs text-gray-600">{recoverMsg}</p>}
            </div>
          )}

          {/* We looked harder than the live pipeline, so YOU decide whether this
              is really a face before it goes into the recognition database — a
              wrong crop enrolled here would poison every future match. */}
          {recovered && !enrolled && (
            <div className="mb-4 rounded-md bg-indigo-50 border border-indigo-200 p-3">
              <p className="text-sm font-medium text-indigo-900">Is this a face?</p>
              <p className="text-[11px] text-indigo-700/80 mb-2">
                This is what we found in that shot{recovered.score < 0.5 && ' — a faint one, so check it'}.
                If it's the person's face, name them and it goes into the recognition database.
                If it isn't, discard it.
              </p>
              <div className="flex gap-3">
                {recovered.preview && (
                  <img src={recovered.preview} alt="Recovered face"
                       className="w-24 h-24 flex-none object-cover rounded-md border border-indigo-300 bg-white"
                       style={{ imageRendering: 'pixelated' }} />
                )}
                <div className="min-w-0 flex-1">
                  <input autoFocus value={name} onChange={e => setName(e.target.value)}
                         onKeyDown={e => { if (e.key === 'Enter') confirmRecovered(); }}
                         placeholder="Name (e.g. Lorraine)"
                         className="w-full bg-white border border-indigo-200 rounded px-2 py-1.5 text-sm text-gray-800 focus:border-indigo-500 outline-none" />
                  <textarea value={details} onChange={e => setDetails(e.target.value)} rows={2}
                            placeholder="Details (optional) — who they are, why they're here"
                            className="mt-2 w-full bg-white border border-indigo-200 rounded px-2 py-1.5 text-sm text-gray-800 focus:border-indigo-500 outline-none resize-y" />
                </div>
              </div>
              <div className="mt-2 flex items-center gap-2">
                <button onClick={confirmRecovered} disabled={saving || !name.trim()}
                        className="text-xs font-medium bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded px-3 py-1.5">
                  {saving ? 'Saving…' : 'Yes — save to recognition database'}
                </button>
                <button onClick={rejectRecovered}
                        className="text-xs text-gray-500 hover:text-gray-700">
                  Not a face
                </button>
                {saveErr && <span className="text-xs text-red-600">{saveErr}</span>}
              </div>
            </div>
          )}
          {!enrolled && !canEditPerson && (
            <p className="mb-4 text-[11px] text-gray-400">
              Naming a person requires the supervisor or admin role.
            </p>
          )}

          {/* Context is always available, face or no face — what you know about
              this shot is worth keeping even when nobody can be identified. */}
          {frameId && canEditPerson && <FrameNote frameId={frameId} />}

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
              {!loading && !err && !sid && (
                <p className="text-sm text-gray-500">
                  History links people by face, so there's nothing to search on this one yet.
                  Recover a face from this shot and their earlier appearances will be searched too.
                </p>
              )}
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

/** What the owner knows about this shot. Kept against the frame, so it stands
 *  whether or not anyone in it can be identified. */
function FrameNote({ frameId }: { frameId: string }) {
  const [note, setNote] = useState('');
  const [saved, setSaved] = useState('');
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.getFrameContext(frameId)
      .then(r => { setSaved(r?.note || ''); setNote(r?.note || ''); })
      .catch(() => {});
  }, [frameId]);

  async function save() {
    setBusy(true);
    try {
      await api.setFrameNote(frameId, note.trim());
      setSaved(note.trim());
      setEditing(false);
    } finally {
      setBusy(false);
    }
  }

  if (!editing) {
    return (
      <div className="mb-4 flex items-start justify-between gap-2 rounded-md border border-gray-200 p-3">
        <div className="min-w-0">
          <p className="text-xs font-medium text-gray-700">Your notes on this shot</p>
          {saved
            ? <p className="text-xs text-gray-600 mt-1 whitespace-pre-wrap">{saved}</p>
            : <p className="text-[11px] text-gray-400 mt-1">Nothing noted yet.</p>}
        </div>
        <button onClick={() => setEditing(true)}
                className="flex-none text-xs text-gray-600 hover:text-gray-900 border border-gray-300 rounded px-2 py-1">
          {saved ? 'Edit' : 'Add'}
        </button>
      </div>
    );
  }

  return (
    <div className="mb-4 rounded-md border border-gray-300 p-3">
      <p className="text-xs font-medium text-gray-700 mb-2">Your notes on this shot</p>
      <textarea autoFocus value={note} onChange={e => setNote(e.target.value)} rows={2}
                placeholder="What you know — who this is, why they were here, anything worth remembering"
                className="w-full bg-white border border-gray-200 rounded px-2 py-1.5 text-sm text-gray-800 focus:border-indigo-500 outline-none resize-y" />
      <div className="mt-2 flex items-center gap-2">
        <button onClick={save} disabled={busy}
                className="text-xs font-medium bg-gray-800 hover:bg-gray-700 disabled:opacity-50 text-white rounded px-3 py-1.5">
          {busy ? 'Saving…' : 'Save'}
        </button>
        <button onClick={() => { setNote(saved); setEditing(false); }} className="text-xs text-gray-500">Cancel</button>
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
