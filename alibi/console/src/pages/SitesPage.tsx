import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { hasRole } from '../lib/auth';
import { LivePlayer } from '../components/LivePlayer';
import type { Site, Posture, SubjectType, Camera } from '../lib/types';

const SUBJECT_META: Record<SubjectType, { label: string; icon: string; badge: string }> = {
  home:          { label: 'Home',          icon: '🏠', badge: 'bg-green-100 text-green-800' },
  office:        { label: 'Office',        icon: '🏢', badge: 'bg-blue-100 text-blue-800' },
  neighbourhood: { label: 'Neighbourhood', icon: '🏘️', badge: 'bg-purple-100 text-purple-800' },
};

const SUBJECT_ORDER: SubjectType[] = ['home', 'office', 'neighbourhood'];

export function SitesPage() {
  const isAdmin = hasRole('admin');

  const [sites, setSites] = useState<Site[]>([]);
  const [postures, setPostures] = useState<Record<SubjectType, Posture> | null>(null);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Add-a-site form
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState<{
    name: string; subject_type: SubjectType; area: string; address: string; notes: string;
    open: string; close: string; context: string;
  }>({ name: '', subject_type: 'home', area: '', address: '', notes: '', open: '', close: '', context: '' });

  async function loadSites() {
    try {
      const data = await api.listSites();
      setSites(data.sites);
      setError(null);
    } catch (e: any) {
      setError(e.message || 'Failed to load sites');
    } finally {
      setLoading(false);
    }
  }

  async function loadPostures() {
    try {
      const data = await api.getSitePostures();
      setPostures(data.postures);
    } catch { /* postures are advisory; page still works without them */ }
  }

  useEffect(() => {
    loadSites();
    loadPostures();
    api.listCameras().then(d => setCameras(d.cameras)).catch(() => {});
  }, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!form.name.trim()) return;
    setSaving(true);
    try {
      await api.createSite({
        name: form.name.trim(),
        subject_type: form.subject_type,
        area: form.area.trim(),
        address: form.address.trim(),
        notes: form.notes.trim(),
        context: form.context.trim(),
        normal_hours: (form.open || form.close) ? { open: form.open, close: form.close } : {},
      });
      setForm({ name: '', subject_type: 'home', area: '', address: '', notes: '', open: '', close: '', context: '' });
      setShowForm(false);
      await loadSites();
    } catch (e: any) {
      alert(e.message || 'Failed to create site');
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(site: Site) {
    if (!confirm(`Delete site "${site.name}"? This does not delete its cameras.`)) return;
    try {
      await api.deleteSite(site.site_id);
      await loadSites();
    } catch (e: any) {
      alert(e.message || 'Failed to delete site');
    }
  }

  const previewPosture = postures?.[form.subject_type] || null;

  return (
    <div className="max-w-5xl mx-auto px-4 py-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Sites</h1>
          <p className="text-sm text-gray-500">What Vantage is protecting — and the intelligence tuned to each.</p>
        </div>
        {isAdmin && (
          <button
            onClick={() => setShowForm(v => !v)}
            className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700"
          >
            {showForm ? 'Cancel' : 'Add a site'}
          </button>
        )}
      </div>

      {error && <div className="my-4 p-3 bg-red-50 text-red-700 text-sm rounded-md">{error}</div>}

      {/* Add-a-site form */}
      {showForm && isAdmin && (
        <form onSubmit={handleCreate} className="bg-white shadow rounded-lg p-6 my-4 border-l-4 border-blue-400">
          <h2 className="text-lg font-medium text-gray-900 mb-4">Add a site</h2>

          {/* Subject type — the choice that tailors the intelligence */}
          <label className="block text-sm font-medium text-gray-700 mb-2">What are you protecting?</label>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
            {SUBJECT_ORDER.map(st => {
              const meta = SUBJECT_META[st];
              const selected = form.subject_type === st;
              return (
                <button
                  type="button"
                  key={st}
                  onClick={() => setForm(f => ({ ...f, subject_type: st }))}
                  className={`text-left p-3 rounded-lg border-2 transition ${
                    selected ? 'border-blue-500 bg-blue-50' : 'border-gray-200 hover:border-gray-300'
                  }`}
                >
                  <div className="text-lg">{meta.icon} <span className="font-medium text-gray-900">{meta.label}</span></div>
                  <div className="text-xs text-gray-500 mt-1">
                    {postures?.[st]?.summary || ''}
                  </div>
                </button>
              );
            })}
          </div>

          {/* What the AI will focus on for this choice */}
          {previewPosture && (
            <div className="mb-4 p-3 bg-gray-50 rounded-md text-sm">
              <p className="text-gray-700 font-medium mb-1">The AI will focus on:</p>
              <ul className="list-disc list-inside text-gray-600 space-y-0.5">
                {previewPosture.focus.slice(0, 4).map((f, i) => <li key={i}>{f}</li>)}
              </ul>
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700">Name</label>
              <input
                type="text" value={form.name} required
                onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                placeholder="e.g. My house"
                className="mt-1 w-full rounded-md border-gray-300 shadow-sm text-sm p-2 border"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">Area / suburb <span className="text-gray-400">(links area context)</span></label>
              <input
                type="text" value={form.area}
                onChange={e => setForm(f => ({ ...f, area: e.target.value }))}
                placeholder="e.g. Parkview"
                className="mt-1 w-full rounded-md border-gray-300 shadow-sm text-sm p-2 border"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">Address <span className="text-gray-400">(optional)</span></label>
              <input
                type="text" value={form.address}
                onChange={e => setForm(f => ({ ...f, address: e.target.value }))}
                className="mt-1 w-full rounded-md border-gray-300 shadow-sm text-sm p-2 border"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">Normal hours <span className="text-gray-400">(optional)</span></label>
              <div className="flex items-center gap-2 mt-1">
                <input type="time" value={form.open} onChange={e => setForm(f => ({ ...f, open: e.target.value }))} className="rounded-md border-gray-300 shadow-sm text-sm p-2 border" />
                <span className="text-gray-400 text-sm">to</span>
                <input type="time" value={form.close} onChange={e => setForm(f => ({ ...f, close: e.target.value }))} className="rounded-md border-gray-300 shadow-sm text-sm p-2 border" />
              </div>
              <p className="mt-1 text-xs text-gray-500">When the site is normally active — activity outside this is weighted higher.</p>
            </div>
          </div>

          <div className="mt-4">
            <label className="block text-sm font-medium text-gray-700">Context for the AI <span className="text-gray-400">(optional, helps the intelligence)</span></label>
            <textarea
              value={form.context} rows={3}
              onChange={e => setForm(f => ({ ...f, context: e.target.value }))}
              placeholder="Who's normally here, known vehicles, routines, specific concerns. e.g. 'Two residents; usually empty 8am–5pm weekdays; known cars: white Toyota, blue bakkie; watch the back gate.'"
              className="mt-1 w-full rounded-md border-gray-300 shadow-sm text-sm p-2 border"
            />
            <p className="mt-1 text-xs text-gray-500">Background only — it helps judge what's normal vs worth a look. Never used to accuse anyone.</p>
          </div>

          <div className="mt-4">
            <button
              type="submit" disabled={saving}
              className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50"
            >
              {saving ? 'Creating…' : 'Create site'}
            </button>
          </div>
        </form>
      )}

      {/* Sites list */}
      {loading ? (
        <p className="text-gray-500 py-8">Loading sites…</p>
      ) : sites.length === 0 ? (
        <div className="bg-white shadow rounded-lg p-8 my-4 text-center">
          <p className="text-gray-900 font-medium">No sites yet</p>
          <p className="text-sm text-gray-500 mt-1">
            {isAdmin ? 'Add a site to tell Vantage what it’s protecting — a home, an office, or a neighbourhood.'
                     : 'No sites have been set up yet.'}
          </p>
        </div>
      ) : (
        <div className="space-y-4 my-4">
          {sites.map(site => (
            <SiteCard key={site.site_id} site={site} cameras={cameras} isAdmin={isAdmin} onDelete={() => handleDelete(site)} onChanged={loadSites} />
          ))}
        </div>
      )}

      <p className="text-xs text-gray-400 mt-6">
        The recording PC lives on its own page now — see <span className="font-medium">Recorders</span> in the top nav.
      </p>
    </div>
  );
}

function SiteCard({ site, cameras, isAdmin, onDelete, onChanged }: { site: Site; cameras: Camera[]; isAdmin: boolean; onDelete: () => void; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const [live, setLive] = useState(false);
  const [editCams, setEditCams] = useState(false);
  const [editInfo, setEditInfo] = useState(false);
  const [info, setInfo] = useState({
    area: site.area || '', context: site.context || '',
    open: site.normal_hours?.open || '', close: site.normal_hours?.close || '',
  });
  const [savingInfo, setSavingInfo] = useState(false);
  const meta = SUBJECT_META[site.subject_type];
  const p = site.posture;

  async function saveInfo() {
    setSavingInfo(true);
    try {
      await api.updateSite(site.site_id, {
        area: info.area,
        context: info.context,
        normal_hours: (info.open || info.close) ? { open: info.open, close: info.close } : {},
      });
      setEditInfo(false);
      onChanged();
    } catch (e: any) {
      alert(e.message || 'Failed to save');
    } finally {
      setSavingInfo(false);
    }
  }

  // The site's cameras, in registration order.
  const siteCameras = site.camera_ids
    .map(id => cameras.find(c => c.camera_id === id))
    .filter((c): c is Camera => !!c);

  async function toggleCamera(cameraId: string, on: boolean) {
    const next = on
      ? [...site.camera_ids, cameraId]
      : site.camera_ids.filter(id => id !== cameraId);
    try {
      await api.updateSite(site.site_id, { camera_ids: next });
      onChanged();
    } catch (e: any) {
      alert(e.message || 'Failed to update site cameras');
    }
  }

  // Detect stale ids the site references but no camera matches.
  const staleCount = site.camera_ids.filter(id => !cameras.some(c => c.camera_id === id)).length;

  return (
    <div className="bg-white shadow rounded-lg p-5">
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-lg font-medium text-gray-900">{site.name}</h3>
            <span className={`text-xs px-2 py-0.5 rounded-full ${meta.badge}`}>{meta.icon} {meta.label}</span>
          </div>
          <p className="text-sm text-gray-500 mt-0.5">
            {site.area || 'No area set'}
            {site.address ? ` · ${site.address}` : ''}
            {` · ${site.camera_ids.length} camera${site.camera_ids.length === 1 ? '' : 's'}`}
          </p>
          {p?.summary && <p className="text-sm text-gray-600 mt-2">{p.summary}</p>}
        </div>
        <div className="flex items-center gap-3">
          {siteCameras.length > 0 && (
            <button
              onClick={() => setLive(v => !v)}
              className="text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 rounded-md px-3 py-1.5"
            >
              {live ? 'Stop live' : '▶ Live feeds'}
            </button>
          )}
          {isAdmin && (
            <button onClick={() => setEditCams(v => !v)} className="text-sm text-gray-700 hover:text-gray-900">
              {editCams ? 'Done' : 'Cameras'}
            </button>
          )}
          {isAdmin && (
            <button onClick={() => setEditInfo(v => !v)} className="text-sm text-gray-700 hover:text-gray-900">
              {editInfo ? 'Close' : 'Info'}
            </button>
          )}
          <button onClick={() => setOpen(v => !v)} className="text-sm text-blue-600 hover:text-blue-800">
            {open ? 'Hide' : 'What the AI focuses on'}
          </button>
          {isAdmin && (
            <button onClick={onDelete} className="text-sm text-red-500 hover:text-red-700">Delete</button>
          )}
        </div>
      </div>

      {staleCount > 0 && !editCams && (
        <p className="mt-2 text-xs text-amber-600">
          {staleCount} assigned camera{staleCount === 1 ? '' : 's'} no longer exist. Click <span className="font-medium">Cameras</span> to fix which cameras this site watches.
        </p>
      )}

      {editCams && (
        <div className="mt-4 rounded-md border border-gray-200 bg-gray-50 p-3">
          <p className="text-sm font-medium text-gray-900 mb-1">Which cameras does this site watch?</p>
          {cameras.length === 0 ? (
            <p className="text-sm text-gray-500">No cameras added yet — add them on the Cameras page first.</p>
          ) : (
            <div className="space-y-1.5">
              {cameras.map(c => (
                <label key={c.camera_id} className="flex items-center gap-2 text-sm text-gray-700">
                  <input
                    type="checkbox"
                    checked={site.camera_ids.includes(c.camera_id)}
                    onChange={e => toggleCamera(c.camera_id, e.target.checked)}
                  />
                  📷 {c.name} <span className="text-xs text-gray-400">{c.camera_id}</span>
                </label>
              ))}
            </div>
          )}
        </div>
      )}

      {live && (
        <div className="mt-4">
          {siteCameras.length === 0 ? (
            <p className="text-sm text-gray-400">This site has cameras assigned, but none are loaded yet.</p>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {siteCameras.map(c => <LivePlayer key={c.camera_id} cameraId={c.camera_id} name={c.name} />)}
            </div>
          )}
          <p className="mt-2 text-xs text-gray-400">Live only while open — streaming stops when you click Stop live or leave.</p>
        </div>
      )}

      {editInfo && (
        <div className="mt-4 rounded-md border border-gray-200 bg-gray-50 p-3 space-y-3">
          <div>
            <label className="block text-xs font-medium text-gray-700">Area / suburb <span className="text-gray-400">(links area crime context)</span></label>
            <input value={info.area} onChange={e => setInfo(v => ({ ...v, area: e.target.value }))} placeholder="Parkview" className="mt-1 w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700">Normal hours</label>
            <div className="flex items-center gap-2 mt-1">
              <input type="time" value={info.open} onChange={e => setInfo(v => ({ ...v, open: e.target.value }))} className="rounded-md border border-gray-300 px-2 py-1.5 text-sm" />
              <span className="text-gray-400 text-sm">to</span>
              <input type="time" value={info.close} onChange={e => setInfo(v => ({ ...v, close: e.target.value }))} className="rounded-md border border-gray-300 px-2 py-1.5 text-sm" />
            </div>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700">Context for the AI</label>
            <textarea value={info.context} rows={3} onChange={e => setInfo(v => ({ ...v, context: e.target.value }))}
              placeholder="Who's normally here, known vehicles, routines, concerns…"
              className="mt-1 w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm" />
            <p className="text-xs text-gray-400 mt-1">Background that helps judge what's normal — never used to accuse anyone.</p>
          </div>
          <button onClick={saveInfo} disabled={savingInfo} className="px-3 py-1.5 text-sm text-white bg-blue-600 rounded-md hover:bg-blue-700 disabled:opacity-50">
            {savingInfo ? 'Saving…' : 'Save'}
          </button>
        </div>
      )}

      {open && p && (
        <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">
          <PostureList title="Focus" items={p.focus} tone="text-gray-700" />
          <PostureList title="Normal here" items={p.normal} tone="text-gray-700" />
          <PostureList title="Worth a human look" items={p.review_triggers} tone="text-amber-700" />
          <PostureList title="The security brief covers" items={p.brief_sections} tone="text-gray-700" />
        </div>
      )}
    </div>
  );
}

function PostureList({ title, items, tone }: { title: string; items: string[]; tone: string }) {
  return (
    <div>
      <p className="font-medium text-gray-900 mb-1">{title}</p>
      <ul className={`list-disc list-inside space-y-0.5 ${tone}`}>
        {items.map((x, i) => <li key={i}>{x}</li>)}
      </ul>
    </div>
  );
}
