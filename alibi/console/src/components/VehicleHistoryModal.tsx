import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { hasRole } from '../lib/auth';
import { AuthImg } from './AuthImg';
import { CropImg } from './CropImg';
import type { VehicleHistory } from '../lib/types';

/**
 * One recurring vehicle in full — shared by the Overview and the Vehicles page.
 *
 * Shows the actual car (full evidence photo), its plate, how often and when it
 * has been seen, EVERY appearance with its own snapshot + time, and lets the
 * owner correct/enrich it: a name plus anything they know about it. Naming keys
 * on the PLATE where one was read, so the name and the notes follow the car
 * across the appearance-clusters ReID splits it into.
 *
 * Continuity from your own cameras — never an identity claim.
 */

function timeAgo(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso.endsWith('Z') ? iso : iso + 'Z').getTime()) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

const FAM_BADGE: Record<string, { label: string; cls: string }> = {
  new: { label: 'NEW', cls: 'bg-amber-400 text-black' },
  regular: { label: 'PATTERN', cls: 'bg-indigo-500/80 text-white' },
  resident: { label: 'FAMILIAR', cls: 'bg-emerald-600/80 text-white' },
  occasional: { label: 'SEEN', cls: 'bg-slate-700 text-slate-300' },
};

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-slate-800/60 p-2">
      <div className="text-lg font-semibold text-white truncate">{value}</div>
      <div className="text-[10px] text-slate-500">{label}</div>
    </div>
  );
}

/**
 * One snapshot's context. Two clearly separate things:
 *   ✨ what the AI read in this picture (generated on demand, never invented —
 *      if no model actually looked, it says so), and
 *   ✎ the owner's own note about it, with their name on it.
 */
function SnapshotContext({ frameId, canEdit, onChanged, onClose }: {
  frameId: string; canEdit: boolean; onChanged: () => void; onClose: () => void;
}) {
  const [ctx, setCtx] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [note, setNote] = useState('');
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    setCtx(null); setMsg(null); setEditing(false);
    api.getFrameContext(frameId)
      .then(c => { setCtx(c); setNote(c.note || ''); })
      .catch(() => setCtx({}));
  }, [frameId]);

  async function analyse() {
    setBusy(true); setMsg(null);
    try {
      const r = await api.describeFrame(frameId);
      setCtx((c: any) => ({ ...(c || {}), ...r }));
      if (!r.description) setMsg(r.reason || 'No vision model produced a description.');
      onChanged();
    } catch (e: any) {
      setMsg(e?.message || 'Could not analyse this snapshot');
    } finally { setBusy(false); }
  }

  async function saveNote() {
    setBusy(true); setMsg(null);
    try {
      const r = await api.setFrameNote(frameId, note);
      setCtx((c: any) => ({ ...(c || {}), ...r, note: r.note ?? null }));
      setEditing(false);
      onChanged();
    } catch (e: any) {
      setMsg(e?.message || 'Could not save the note');
    } finally { setBusy(false); }
  }

  return (
    <div className="mt-2 rounded-md border border-slate-700 bg-slate-800/50 p-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] text-slate-400 uppercase tracking-wide">This snapshot</span>
        <button onClick={onClose} className="text-[11px] text-slate-500 hover:text-slate-300">close</button>
      </div>

      {/* AI reading */}
      <div className="mb-2">
        <div className="text-[10px] text-slate-500 mb-0.5">✨ What the AI sees</div>
        {ctx?.description
          ? <p className="text-xs text-slate-200 whitespace-pre-wrap">{ctx.description}</p>
          : <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs text-slate-500">Not analysed yet.</span>
              {canEdit && (
                <button onClick={analyse} disabled={busy}
                        className="text-[11px] font-medium bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded px-2 py-1">
                  {busy ? 'Analysing…' : 'Analyse this snapshot'}
                </button>
              )}
            </div>}
      </div>

      {/* Owner's note */}
      <div>
        <div className="text-[10px] text-slate-500 mb-0.5">✎ Your note</div>
        {!editing ? (
          <div className="flex items-start justify-between gap-2">
            <p className="text-xs text-slate-300 whitespace-pre-wrap min-w-0">
              {ctx?.note || <span className="text-slate-500">Nothing recorded.</span>}
              {ctx?.note_by && <span className="text-[10px] text-slate-500"> — {ctx.note_by}</span>}
            </p>
            <button onClick={() => setEditing(true)}
                    className="flex-none text-[11px] text-indigo-400 hover:text-indigo-300">
              {ctx?.note ? 'Edit' : 'Add'}
            </button>
          </div>
        ) : (
          <div>
            <textarea value={note} onChange={e => setNote(e.target.value)} rows={2} autoFocus
                      placeholder="What do you know about this moment?"
                      className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200 placeholder:text-slate-600 focus:border-indigo-500 outline-none resize-y" />
            <div className="mt-1 flex items-center gap-2">
              <button onClick={saveNote} disabled={busy}
                      className="text-[11px] font-medium bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded px-2 py-1">
                {busy ? 'Saving…' : 'Save'}
              </button>
              <button onClick={() => { setEditing(false); setNote(ctx?.note || ''); }}
                      className="text-[11px] text-slate-500">Cancel</button>
            </div>
          </div>
        )}
      </div>
      {msg && <p className="mt-1.5 text-[10px] text-amber-400">{msg}</p>}
    </div>
  );
}

export function VehicleHistoryModal({ entityId, onClose, onSaved }: {
  entityId: string; onClose: () => void; onSaved: () => void;
}) {
  const [h, setH] = useState<VehicleHistory | null>(null);
  const [win, setWin] = useState('7d');
  const [err, setErr] = useState<string | null>(null);
  const canEdit = hasRole('supervisor') || hasRole('admin');

  const [editing, setEditing] = useState(false);
  const [name, setName] = useState('');
  const [details, setDetails] = useState('');
  const [busy, setBusy] = useState(false);
  const [saveErr, setSaveErr] = useState<string | null>(null);

  const PAGE = 12;
  const [framesOffset, setFramesOffset] = useState(0);
  const [openFrame, setOpenFrame] = useState<string | null>(null);

  useEffect(() => { setFramesOffset(0); }, [entityId, win]);

  useEffect(() => {
    setH(null); setErr(null);
    api.getVehicleHistory(entityId, win, framesOffset, PAGE)
      .then(r => {
        setH(r);
        setName(r.owner_label || '');
        setDetails(r.owner_details || '');
      })
      .catch(e => setErr(e?.message || 'Could not load history'));
  }, [entityId, win, framesOffset]);

  function refreshFrames() {
    api.getVehicleHistory(entityId, win, framesOffset, PAGE).then(setH).catch(() => {});
  }

  async function save(label: string) {
    if (!label.trim()) return;
    setBusy(true); setSaveErr(null);
    try {
      // Key to the plate when we have one, so the name + notes follow the car.
      await api.setVehicleLabel(entityId, label.trim(), h?.plate, details.trim());
      onSaved();
    } catch (e: any) {
      setSaveErr(e?.message || 'Could not save');
    } finally { setBusy(false); }
  }

  const maxDay = h ? Math.max(1, ...h.per_day.map(d => d.count)) : 1;
  const fam = h ? (FAM_BADGE[h.familiarity] || FAM_BADGE.occasional) : null;
  const descriptor = h
    ? [h.colour && h.colour !== 'unknown' ? h.colour[0].toUpperCase() + h.colour.slice(1) : '', h.body || '']
        .filter(Boolean).join(' ')
    : '';
  const title = h?.owner_label ? `“${h.owner_label}”` : (descriptor || 'Recurring vehicle');
  const ownerDetails = h?.owner_details as string | undefined;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div className="bg-slate-900 border border-slate-700 rounded-xl shadow-xl max-w-2xl w-full max-h-[88vh] overflow-y-auto"
           onClick={e => e.stopPropagation()}>
        <div className="flex items-start justify-between p-4 border-b border-slate-800">
          <div className="flex items-center gap-2 min-w-0">
            {fam && <span className={`text-[8px] font-bold tracking-wider px-1.5 py-0.5 rounded flex-none ${fam.cls}`}>{fam.label}</span>}
            <h2 className="text-sm font-semibold text-white truncate">{title}</h2>
          </div>
          <div className="flex items-center gap-2 flex-none">
            <div className="flex items-center gap-0.5 p-0.5 rounded bg-slate-800">
              {['24h', '7d', '30d'].map(w => (
                <button key={w} onClick={() => setWin(w)}
                        className={`px-2 py-0.5 text-[10px] rounded ${win === w ? 'bg-indigo-500 text-white' : 'text-slate-400'}`}>
                  {w.toUpperCase()}
                </button>
              ))}
            </div>
            <button onClick={onClose} className="text-slate-500 hover:text-slate-300 text-sm">✕</button>
          </div>
        </div>

        <div className="p-4">
          {err && <p className="text-sm text-red-400">{err}</p>}
          {!h && !err && <p className="text-sm text-slate-500">Loading…</p>}
          {h && (
            <>
              {h.frame_url && (
                <a href={h.frame_url} target="_blank" rel="noreferrer"
                   className="block mb-3 rounded-lg overflow-hidden bg-black border border-slate-800">
                  <AuthImg src={h.frame_url} alt="vehicle" className="w-full max-h-72 object-contain" />
                </a>
              )}

              {/* The plate — the one stable identity a car has. */}
              <div className="mb-3 flex items-center gap-2">
                <span className="text-[10px] text-slate-500 uppercase tracking-wide">Plate</span>
                {h.plate
                  ? <span className="font-mono text-sm font-bold text-white bg-slate-800 border border-slate-600 rounded px-2 py-0.5 tracking-wider">
                      {h.plate}{h.plate_region ? <span className="ml-2 text-[10px] font-normal text-slate-400">{h.plate_region}</span> : null}
                    </span>
                  : <span className="text-xs text-slate-500">not captured yet</span>}
              </div>

              {/* What the owner knows — editable. */}
              {!editing && (
                <div className="mb-3 rounded-md bg-slate-800/50 border border-slate-700 p-3">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-xs font-medium text-slate-200">
                        {h.owner_label ? h.owner_label : 'Not named yet'}
                      </p>
                      <p className="text-[11px] text-slate-400 mt-0.5 whitespace-pre-wrap">
                        {ownerDetails || 'No details recorded. Add what you know — who it belongs to, why it’s here, anything worth remembering.'}
                      </p>
                    </div>
                    {canEdit && (
                      <button onClick={() => setEditing(true)}
                              className="flex-none text-[11px] text-indigo-400 hover:text-indigo-300 border border-indigo-500/40 rounded px-2 py-1">
                        {h.owner_label ? 'Edit' : 'Name & add details'}
                      </button>
                    )}
                  </div>
                </div>
              )}
              {editing && (
                <div className="mb-3 rounded-md bg-indigo-500/10 border border-indigo-500/30 p-3">
                  <input autoFocus value={name} onChange={e => setName(e.target.value)}
                         placeholder="Name (e.g. Arnold's Haval, the gardener's bakkie)"
                         className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm text-slate-200 placeholder:text-slate-600 focus:border-indigo-500 outline-none" />
                  <textarea value={details} onChange={e => setDetails(e.target.value)} rows={3}
                            placeholder="Anything you know — whose it is, when it usually comes, distinguishing features…"
                            className="mt-2 w-full bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm text-slate-200 placeholder:text-slate-600 focus:border-indigo-500 outline-none resize-y" />
                  <div className="mt-2 flex items-center gap-2">
                    <button onClick={() => save(name)} disabled={busy || !name.trim()}
                            className="text-xs font-medium bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded px-3 py-1.5">
                      {busy ? 'Saving…' : 'Save'}
                    </button>
                    <button onClick={() => setEditing(false)} className="text-xs text-slate-400 hover:text-slate-200 px-1">Cancel</button>
                    {saveErr && <span className="text-[11px] text-red-400">{saveErr}</span>}
                  </div>
                  {h.plate && (
                    <p className="mt-1.5 text-[10px] text-indigo-300/70">
                      Saved against plate {h.plate}, so it follows this car wherever it's seen.
                    </p>
                  )}
                </div>
              )}

              <div className="grid grid-cols-3 gap-2 text-center mb-3">
                <Stat label="Sightings" value={String(h.count)} />
                <Stat label="Days seen" value={String(h.days)} />
                <Stat label="Cameras" value={String(h.cameras.length)} />
              </div>
              <p className="text-xs text-slate-400 mb-3">
                First seen {new Date(h.first_seen.endsWith('Z') ? h.first_seen : h.first_seen + 'Z').toLocaleString()} ·
                last {timeAgo(h.last_seen)}. Appearance match from your own cameras — continuity, not identity.
              </p>

              {h.per_day.length > 0 && (
                <div className="mb-3">
                  <div className="text-[10px] text-slate-500 uppercase tracking-wide mb-1">Sightings per day</div>
                  <div className="flex items-end gap-1 h-16">
                    {h.per_day.map(d => (
                      <div key={d.day} className="flex-1 bg-cyan-500/70 rounded-t" title={`${d.day}: ${d.count}`}
                           style={{ height: `${Math.max(6, (d.count / maxDay) * 100)}%` }} />
                    ))}
                  </div>
                </div>
              )}

              {/* EVERY appearance — its own snapshot, camera and time. */}
              {h.frames && h.frames.length > 0 && (() => {
                const total = h.frames_total ?? h.frames.length;
                const from = (h.frames_offset ?? 0) + 1;
                const to = (h.frames_offset ?? 0) + h.frames.length;
                return (
                <div className="mb-3">
                  <div className="flex items-center justify-between mb-1">
                    <div className="text-[10px] text-slate-500 uppercase tracking-wide">
                      Its appearances{' '}
                      <span className="normal-case tracking-normal text-slate-600">
                        — {from}–{to} of {total}, newest first
                      </span>
                    </div>
                    {total > PAGE && (
                      <div className="flex items-center gap-1">
                        <button disabled={(h.frames_offset ?? 0) <= 0}
                                onClick={() => setFramesOffset(o => Math.max(0, o - PAGE))}
                                className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 disabled:opacity-40">‹ newer</button>
                        <button disabled={to >= total}
                                onClick={() => setFramesOffset(o => o + PAGE)}
                                className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 disabled:opacity-40">older ›</button>
                      </div>
                    )}
                  </div>
                  <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
                    {h.frames.map((f, i) => (
                      <button key={f.frame_id || i} onClick={() => setOpenFrame(f.frame_id || null)}
                              className={`text-left rounded overflow-hidden border bg-slate-900 hover:border-indigo-500 ${
                                openFrame && openFrame === f.frame_id ? 'border-indigo-500' : 'border-slate-800'}`}>
                        <div className="aspect-square relative">
                          <CropImg src={f.frame_url} alt={f.camera_id}
                                   bbox={f.bbox as [number, number, number, number]} pad={0.3}
                                   className="w-full h-full" />
                          {(f.description || f.note) && (
                            <span className="absolute top-1 right-1 text-[8px] px-1 rounded bg-black/80 text-emerald-300">
                              {f.note ? '✎' : '✨'}
                            </span>
                          )}
                        </div>
                        <div className="px-1 py-0.5">
                          <div className="text-[8px] text-slate-400 truncate">
                            {new Date(String(f.ts).endsWith('Z') ? f.ts : f.ts + 'Z')
                              .toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                          </div>
                          <div className="text-[8px] text-slate-600 truncate">{f.camera_id}</div>
                        </div>
                      </button>
                    ))}
                  </div>
                  {openFrame && (
                    <SnapshotContext frameId={openFrame} canEdit={canEdit}
                                     onChanged={refreshFrames}
                                     onClose={() => setOpenFrame(null)} />
                  )}
                </div>
                );
              })()}

              <p className="text-[10px] text-slate-600">
                Cameras: {h.cameras.join(', ')}. Vehicles are grouped by appearance, which can split
                the same car across clusters — naming it is the reliable way to teach the system it's yours.
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
