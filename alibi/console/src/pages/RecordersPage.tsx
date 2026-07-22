import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { hasRole } from '../lib/auth';

type FileEntry = { name: string; bytes: number; mtime: number; kind: string };
type CamStorage = { bytes: number; files: number; recent?: FileEntry[] };
type Storage = {
  dir: string; total_bytes: number; files: number;
  oldest: number | null; newest: number | null;
  disk?: { total: number; used: number; free: number };
  caps?: { max_gb?: number; max_days?: number; min_free_percent?: number };
  cameras: Record<string, CamStorage>;
} | null;
type Bridge = { bridge_id: string; name: string; online: boolean; site_hint: string; last_seen: string | null; storage?: Storage };

function fmtBytes(n: number): string {
  if (!n) return '0 B';
  const u = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.min(u.length - 1, Math.floor(Math.log(n) / Math.log(1024)));
  return `${(n / Math.pow(1024, i)).toFixed(i ? 1 : 0)} ${u[i]}`;
}

function fmtWhen(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}


/**
 * A phone is a real camera. The bridge protocol is plain HTTP, so a web page
 * on the handset can speak it — no app, nothing opened on the router — and its
 * frames go through the same pipeline as every other camera.
 *
 * The code is single-use and expires, so it is safe to show on screen.
 */
function PhoneCameraCard() {
  const [code, setCode] = useState<string | null>(null);
  const [mins, setMins] = useState<number>(0);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const url = `${window.location.origin}/phone`;

  async function makeCode() {
    setBusy(true);
    setErr(null);
    try {
      const r = await api.pairBridge();
      setCode(r.code);
      setMins(r.expires_in_minutes);
    } catch (e: any) {
      setErr(e?.message || 'Could not create a code');
    } finally { setBusy(false); }
  }

  return (
    <div className="bg-white shadow rounded-lg p-4 mb-6">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-sm font-medium text-gray-900">Use a phone as a camera</p>
          <p className="text-xs text-gray-500 mt-0.5">
            An old handset on a windowsill counts. It feeds the same system as your
            other cameras — no app to install, nothing to open on your router.
          </p>
        </div>
        {hasRole('admin') && (
          <button onClick={makeCode} disabled={busy}
                  className="flex-none text-xs font-medium bg-gray-800 hover:bg-gray-700 disabled:opacity-50 text-white rounded px-3 py-1.5">
            {busy ? 'Working…' : code ? 'New code' : 'Add a phone'}
          </button>
        )}
      </div>
      {!hasRole('admin') && (
        <p className="mt-2 text-xs text-gray-400">Adding a camera requires the admin role.</p>
      )}
      {err && <p className="mt-2 text-xs text-red-600">{err}</p>}
      {code && (
        <div className="mt-3 rounded-md bg-indigo-50 border border-indigo-200 p-3">
          <p className="text-xs text-indigo-800">On the phone, open</p>
          <p className="font-mono text-sm text-indigo-900 break-all">{url}</p>
          <p className="text-xs text-indigo-800 mt-2">and enter this code:</p>
          <p className="font-mono text-3xl tracking-[0.3em] text-indigo-900 mt-1">{code}</p>
          <p className="text-[11px] text-indigo-700/80 mt-2">
            Single use, expires in {mins} minutes. Then tap Start watching and leave
            the page open.
          </p>
        </div>
      )}
    </div>
  );
}

export function RecordersPage() {
  const isAdmin = hasRole('admin');
  const [bridges, setBridges] = useState<Bridge[]>([]);
  const [downloading, setDownloading] = useState(false);
  const [computers, setComputers] = useState<Array<Record<string, any>>>([]);
  const [scanning, setScanning] = useState(false);
  const [scanNote, setScanNote] = useState<string | null>(null);
  const [openCam, setOpenCam] = useState<Set<string>>(new Set());

  function toggleCam(key: string) {
    setOpenCam(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  }

  async function loadBridges() {
    try {
      const data = await api.listBridges();
      setBridges(data.bridges);
    } catch { /* non-fatal */ }
  }

  // Surface any computers a connected recorder's last LAN scan turned up —
  // candidate machines to run the recorder on.
  async function loadCandidates(list: Bridge[]) {
    const online = list.find(b => b.online);
    if (!online) return;
    try {
      const { job } = await api.getLatestBridgeScan(online.bridge_id);
      const results = job?.results || [];
      setComputers(results.filter((r: any) => r.is_computer === true));
    } catch { /* none */ }
  }

  const [localVision, setLocalVision] = useState<boolean | null>(null);
  const [lvBusy, setLvBusy] = useState(false);
  const [lvErr, setLvErr] = useState<string | null>(null);

  useEffect(() => {
    loadBridges();
    api.getRecorderSettings()
      .then(s => { setLocalVision(!!s.local_vision); setLvErr(null); })
      .catch(e => setLvErr(e?.message || 'Settings unavailable'));
    const t = setInterval(loadBridges, 5000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => { loadCandidates(bridges); }, [bridges]);

  async function toggleLocalVision(next: boolean) {
    setLvBusy(true);
    try {
      const s = await api.setRecorderSettings({ local_vision: next });
      setLocalVision(!!s.local_vision);
      setLvErr(null);
    } catch (e: any) {
      setLvErr(e?.message || 'Could not change it');
    } finally { setLvBusy(false); }
  }

  async function handleDownload() {
    setDownloading(true);
    try { await api.downloadRecorder(); }
    catch { alert('Failed to download the recorder'); }
    finally { setDownloading(false); }
  }

  const isMac = /Mac/i.test(navigator.platform || navigator.userAgent);
  // Video is the disk hog, so it's capped to a shared 10GB across all cameras
  // (oldest deleted first); motion stills + the cloud intelligence are tiny.
  const cmdLines = isMac
    ? 'cd ~/Downloads\npython3 vantage_recorder.pyz --dir ~/vantage-rec'
    : 'cd %USERPROFILE%\\Downloads\npython vantage_recorder.pyz --dir vantage-rec';
  const [launching, setLaunching] = useState(false);
  const [copied, setCopied] = useState(false);
  function copyCmd() {
    navigator.clipboard?.writeText(cmdLines).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }).catch(() => {});
  }
  async function handleUseThisComputer() {
    setLaunching(true);
    try { await api.downloadRecorderLauncher(isMac ? 'mac' : 'windows'); }
    catch { alert('Failed to prepare the launcher'); }
    finally { setLaunching(false); }
  }

  async function handleRename(bridgeId: string, current: string) {
    const name = prompt('Name this recording PC (e.g. "Office PC", "Mac (temporary)")', current);
    if (!name || name.trim() === current) return;
    try { await api.renameBridge(bridgeId, name.trim()); await loadBridges(); }
    catch (e: any) { alert(e.message || 'Failed to rename'); }
  }

  async function handleRemove(bridgeId: string, label: string) {
    if (!confirm(`Remove "${label}"? It stops recording immediately and must be re-added to record again.`)) return;
    try { await api.removeBridge(bridgeId); await loadBridges(); }
    catch (e: any) { alert(e.message || 'Failed to remove'); }
  }

  async function handleScan() {
    const online = bridges.find(b => b.online);
    if (!online) { setScanNote('Start a recorder first — the scan runs from a recorder on your network.'); return; }
    setScanning(true);
    setScanNote(null);
    try {
      const { job_id } = await api.scanViaBridge(online.bridge_id);
      const deadline = Date.now() + 180000;
      // Poll until the recorder reports back.
      // eslint-disable-next-line no-constant-condition
      while (true) {
        await new Promise(r => setTimeout(r, 2000));
        let status;
        try { status = await api.getBridgeScanStatus(job_id); } catch { continue; }
        if (status.status === 'done') {
          const pcs = (status.results || []).filter((r: any) => r.is_computer === true);
          setComputers(pcs);
          setScanNote(pcs.length === 0
            ? 'No candidate computers found. Only machines with file-sharing or remote-access enabled show up — the recorder itself is excluded.'
            : null);
          break;
        }
        if (status.status === 'error' || Date.now() > deadline) {
          setScanNote('Scan didn’t complete. Make sure the recorder is online and try again.');
          break;
        }
      }
    } catch (e: any) {
      setScanNote(e.message || 'Scan failed');
    } finally {
      setScanning(false);
    }
  }

  const anyOnline = bridges.some(b => b.online);

  return (
    <div className="max-w-4xl mx-auto px-4 py-6">
      <div className="mb-4">
        <h1 className="text-2xl font-semibold text-gray-900">Recorders</h1>
        <p className="text-sm text-gray-500">
          The always-on computer on your camera network that records and streams. One per network.
        </p>
      </div>

      {/* Who describes the pictures: your PC for free, or the cloud for money.
          Always rendered — this used to vanish entirely when the settings call
          failed, which looks identical to the feature not existing. */}
      <div className="bg-white shadow rounded-lg p-4 mb-6">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="text-sm font-medium text-gray-900">Who describes what the cameras see</p>
            <p className="text-xs text-gray-500 mt-0.5">
              {lvErr
                ? 'Could not read the current setting.'
                : localVision === null
                  ? 'Checking…'
                  : localVision
                    ? 'Ollama on your PC — free, but slow without a GPU.'
                    : 'Claude in the cloud — fast, costs a little per shot, and the picture leaves your network.'}
            </p>
          </div>
          <div className="flex flex-none items-center gap-2">
            <button
              onClick={() => toggleLocalVision(false)}
              disabled={lvBusy || !hasRole('supervisor') || localVision === null}
              title={!hasRole('supervisor') ? 'Supervisor or admin only' : 'Describe in the cloud'}
              className={`px-3 py-1.5 text-xs font-medium rounded-l-md border disabled:opacity-50 ${
                localVision === false
                  ? 'bg-indigo-600 border-indigo-600 text-white'
                  : 'bg-white border-gray-300 text-gray-600 hover:bg-gray-50'}`}
            >
              Cloud
            </button>
            <button
              onClick={() => toggleLocalVision(true)}
              disabled={lvBusy || !hasRole('supervisor') || localVision === null}
              title={!hasRole('supervisor') ? 'Supervisor or admin only' : 'Describe on your own PC with Ollama'}
              className={`-ml-2 px-3 py-1.5 text-xs font-medium rounded-r-md border disabled:opacity-50 ${
                localVision === true
                  ? 'bg-indigo-600 border-indigo-600 text-white'
                  : 'bg-white border-gray-300 text-gray-600 hover:bg-gray-50'}`}
            >
              Ollama (free)
            </button>
          </div>
        </div>
        {lvErr && (
          <p className="mt-2 text-xs text-red-600">
            {lvErr} — the recorder keeps whatever it was last told.
          </p>
        )}
        {localVision && (
          <p className="mt-2 text-xs text-gray-500">
            Needs Ollama running on the recorder PC with a vision model pulled
            (<code className="bg-gray-100 px-1 rounded">ollama pull llama3.2-vision</code>).
            If it isn't there, shots go undescribed rather than falling back to paid calls.
          </p>
        )}
      </div>

      <PhoneCameraCard />

      {/* Your recorders — the day-to-day view, with storage */}
      <div className="bg-white shadow rounded-lg p-6 mb-6">
        <h2 className="text-lg font-medium text-gray-900 mb-2">Your recorders</h2>
        {bridges.length === 0 ? (
          <p className="text-sm text-gray-500">None yet. Add one below.</p>
        ) : (
          <div className="space-y-4">
            {bridges.map(b => {
              const s = b.storage;
              const camCount = s ? Object.keys(s.cameras || {}).length : 0;
              return (
                <div key={b.bridge_id} className="rounded-lg border border-gray-100 p-3">
                  <div className="flex items-center gap-3">
                    <span className={`w-2.5 h-2.5 rounded-full flex-none ${b.online ? 'bg-green-500' : 'bg-gray-300'}`} />
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-medium text-gray-900 truncate">{b.name || b.bridge_id}</div>
                      <div className="text-xs text-gray-500">
                        {b.online ? 'Online — recording' : 'Offline'}{b.site_hint ? ` · ${b.site_hint}` : ''}
                      </div>
                    </div>
                    {isAdmin && (
                      <div className="flex items-center gap-3 flex-none">
                        <button onClick={() => handleRename(b.bridge_id, b.name)} className="text-xs text-blue-600 hover:text-blue-800">Rename</button>
                        <button onClick={() => handleRemove(b.bridge_id, b.name || b.bridge_id)} className="text-xs text-red-500 hover:text-red-700">Remove</button>
                      </div>
                    )}
                  </div>
                  {/* Storage the recorder reported */}
                  {s ? (
                    <div className="mt-2 pl-5 text-xs text-gray-600">
                      <div>
                        Using <span className="font-medium">{fmtBytes(s.total_bytes)}</span> in {s.files.toLocaleString()} file{s.files === 1 ? '' : 's'}
                        {camCount > 0 && ` across ${camCount} camera${camCount === 1 ? '' : 's'}`}
                        {s.oldest && s.newest && (
                          <> · {new Date(s.oldest * 1000).toLocaleDateString()} → {new Date(s.newest * 1000).toLocaleDateString()}</>
                        )}
                      </div>

                      {/* Folder on the recording PC */}
                      <div className="text-gray-400 font-mono truncate mt-0.5" title={s.dir}>📁 {s.dir}</div>

                      {/* Disk headroom on that PC's drive */}
                      {s.disk && s.disk.total > 0 && (
                        <div className="mt-1.5">
                          <div className="flex items-center justify-between text-gray-500">
                            <span>💽 Disk: <span className="font-medium">{fmtBytes(s.disk.free)}</span> free of {fmtBytes(s.disk.total)}</span>
                            <span className="text-gray-400">{Math.round((s.disk.used / s.disk.total) * 100)}% full</span>
                          </div>
                          <div className="mt-0.5 h-1.5 w-full rounded-full bg-gray-100 overflow-hidden">
                            <div
                              className={`h-full ${s.disk.used / s.disk.total > 0.9 ? 'bg-red-500' : 'bg-indigo-500'}`}
                              style={{ width: `${Math.min(100, (s.disk.used / s.disk.total) * 100)}%` }}
                            />
                          </div>
                        </div>
                      )}

                      {/* Retention cap — how much is kept before old footage rolls off */}
                      {s.caps && (s.caps.max_gb || s.caps.max_days || s.caps.min_free_percent) && (
                        <div className="mt-1 text-gray-500">
                          ♻️ Auto-cleanup:
                          {s.caps.max_gb ? ` ${s.caps.max_gb} GB/camera` : ''}
                          {s.caps.max_gb && s.caps.max_days ? ' ·' : ''}
                          {s.caps.max_days ? ` ${s.caps.max_days}-day cap` : ''}
                          {(s.caps.max_gb || s.caps.max_days) && s.caps.min_free_percent ? ' ·' : ''}
                          {s.caps.min_free_percent ? ` always keep ${s.caps.min_free_percent}% free` : ''}
                          {' '}— oldest footage is deleted automatically.
                        </div>
                      )}

                      {/* Per-camera, expandable to the actual recent files */}
                      {camCount > 0 && (
                        <ul className="mt-1.5 space-y-1">
                          {Object.entries(s.cameras).map(([cid, v]) => {
                            const key = `${b.bridge_id}:${cid}`;
                            const open = openCam.has(key);
                            const recent = v.recent || [];
                            return (
                              <li key={cid}>
                                <button
                                  onClick={() => toggleCam(key)}
                                  className="flex w-full items-center gap-1 text-left text-gray-600 hover:text-gray-900"
                                >
                                  <span className="text-gray-400">{open ? '▾' : '▸'}</span>
                                  <span>📷 {cid}</span>
                                  <span className="text-gray-400">— {fmtBytes(v.bytes)} · {v.files} files</span>
                                </button>
                                {open && (
                                  recent.length > 0 ? (
                                    <div className="ml-4 mt-1 overflow-x-auto rounded border border-gray-100">
                                      <table className="min-w-full text-[11px]">
                                        <tbody>
                                          {recent.map((f, i) => (
                                            <tr key={`${f.name}-${i}`} className="border-b border-gray-50 last:border-0">
                                              <td className="px-2 py-1 text-gray-400 w-14">
                                                {f.kind === 'motion'
                                                  ? <span title="motion still">🟠 still</span>
                                                  : <span title="recording clip">🎞️ clip</span>}
                                              </td>
                                              <td className="px-2 py-1 font-mono text-gray-600 truncate max-w-[16rem]" title={f.name}>{f.name}</td>
                                              <td className="px-2 py-1 text-gray-500 whitespace-nowrap text-right w-20">{fmtBytes(f.bytes)}</td>
                                              <td className="px-2 py-1 text-gray-400 whitespace-nowrap text-right w-28">{fmtWhen(f.mtime)}</td>
                                            </tr>
                                          ))}
                                        </tbody>
                                      </table>
                                      {v.files > recent.length && (
                                        <div className="px-2 py-1 text-[11px] text-gray-400">Newest {recent.length} shown · {v.files - recent.length} more on the recorder’s disk.</div>
                                      )}
                                    </div>
                                  ) : (
                                    <div className="ml-4 mt-1 text-[11px] text-gray-400">No files yet.</div>
                                  )
                                )}
                              </li>
                            );
                          })}
                        </ul>
                      )}
                    </div>
                  ) : (
                    <p className="mt-2 pl-5 text-xs text-gray-400">{b.online ? 'Reporting storage…' : 'No storage reported.'}</p>
                  )}
                </div>
              );
            })}
          </div>
        )}
        {bridges.length > 0 && (
          <p className="text-xs text-gray-400 mt-3">Swapping computers? Add the new one below, then Remove the old — its access is revoked at once.</p>
        )}
      </div>

      {/* Add a recorder — real terminal steps, visible */}
      {isAdmin && (
        <div className="bg-white shadow rounded-lg p-6">
          <h2 className="text-lg font-medium text-gray-900">Add a recorder</h2>
          <p className="mt-1 text-sm text-gray-500">Use any always-on computer on your camera network — the one you're on now works.</p>

          <div className="mt-4">
            <p className="text-sm font-medium text-gray-900">Set up this computer ({isMac ? 'Mac' : 'Windows'})</p>
            <ol className="mt-2 space-y-3 text-sm text-gray-700">
              <li>
                <span className="font-medium">1. Install Python 3 and ffmpeg</span> (once).{' '}
                {isMac
                  ? <>Mac: <code className="bg-gray-100 px-1 rounded">brew install python ffmpeg</code></>
                  : <>Windows: install Python from python.org (tick “Add to PATH”), then <code className="bg-gray-100 px-1 rounded">winget install Gyan.FFmpeg</code></>}
              </li>
              <li>
                <span className="font-medium">2. Download the recorder</span> (saves to your Downloads):
                <button onClick={handleDownload} disabled={downloading} className="ml-2 px-3 py-1 text-xs font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 disabled:opacity-50">
                  {downloading ? 'Preparing…' : 'Download the recorder'}
                </button>
              </li>
              <li>
                <span className="font-medium">3. Open Terminal and run these two lines:</span>
                <div className="relative mt-1">
                  <pre className="bg-gray-900 text-gray-100 text-xs rounded-md p-3 pr-16 overflow-x-auto whitespace-pre">{cmdLines}</pre>
                  <button
                    onClick={copyCmd}
                    className="absolute top-2 right-2 px-2 py-1 text-xs font-medium rounded bg-gray-700 text-gray-100 hover:bg-gray-600"
                  >
                    {copied ? 'Copied ✓' : 'Copy'}
                  </button>
                </div>
                <span className="text-xs text-gray-500">You should see <code className="bg-gray-100 px-1 rounded">paired as brg_…</code>. Leave the window open — it appears under “Your recorders” above.</span>
                <div className="mt-1.5 text-xs text-gray-500 leading-relaxed">
                  <span className="font-medium text-gray-700">Disk use:</span> recorded video is capped at a shared
                  <code className="bg-gray-100 px-1 rounded mx-1">10&nbsp;GB</code> across all your cameras — once full, the
                  <em>oldest clip is deleted first</em>. That never loses intelligence: the AI is read from the motion
                  snapshots the moment they’re captured and stored on the server, so a deleted clip is only the raw tape.
                  Change the cap with <code className="bg-gray-100 px-1 rounded mx-1">--video-max-gb&nbsp;20</code>, or add
                  <code className="bg-gray-100 px-1 rounded mx-1">--no-video</code> to keep only snapshots + AI (smallest footprint).
                </div>
              </li>
              <li>
                <span className="font-medium">4. Optional — free scene descriptions</span> (no AI cost).{' '}
                Install <a href="https://ollama.com/download" target="_blank" rel="noreferrer" className="text-indigo-600 underline">Ollama</a>
                {isMac ? <> (or <code className="bg-gray-100 px-1 rounded">brew install ollama</code>)</> : null}, then pull the vision model once:
                <div className="mt-1">
                  <pre className="bg-gray-900 text-gray-100 text-xs rounded-md p-3 overflow-x-auto whitespace-pre">ollama pull llama3.2-vision</pre>
                </div>
                <span className="text-xs text-gray-500">The recorder auto-detects it and describes every camera shot on this computer — free and private. Without it, the cloud narrates as before.</span>
              </li>
            </ol>
            <p className="mt-3 text-xs text-gray-400">
              Prefer not to use Terminal?{' '}
              <button onClick={handleUseThisComputer} disabled={launching} className="text-indigo-600 underline disabled:opacity-50">
                {launching ? 'Preparing…' : 'get a double-click launcher'}
              </button>
              {isMac ? ' (first run: System Settings → Privacy & Security → Open Anyway).' : ' (if SmartScreen warns: More info → Run anyway).'}
            </p>
          </div>

          {/* Different computer + find one — visible, not hidden */}
          <div className="mt-5 border-t border-gray-100 pt-4 space-y-4">
            <p className="text-sm text-gray-600">
              <span className="font-medium text-gray-900">A different computer?</span> Do the same three steps on it (drop the <code className="bg-gray-100 px-1 rounded">~/</code> from the paths on Windows).
            </p>
            <div>
              <div className="flex items-center justify-between">
                <p className="text-sm font-medium text-gray-900">Find a computer on the network</p>
                <button
                  onClick={handleScan} disabled={scanning || !anyOnline}
                  title={!anyOnline ? 'Start a recorder first' : undefined}
                  className="px-3 py-1.5 text-xs font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
                >
                  {scanning ? 'Scanning…' : 'Scan for computers'}
                </button>
              </div>
              {computers.length > 0 ? (
                <ul className="mt-2 space-y-1.5">
                  {computers.map((c, i) => (
                    <li key={`pc-${c.ip}-${i}`} className="flex items-center gap-3 rounded-md border border-gray-100 bg-gray-50 px-3 py-2">
                      <span className="text-lg" role="img" aria-label="computer">🖥️</span>
                      <div className="min-w-0">
                        <div className="text-sm font-medium text-gray-900 truncate">{c.name && !String(c.name).startsWith('Camera (') ? c.name : 'Computer'}</div>
                        <div className="text-xs text-gray-500">at {c.ip}</div>
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className={`mt-2 text-xs ${!anyOnline ? 'text-amber-600' : 'text-gray-400'}`}>
                  {scanNote || (!anyOnline
                    ? 'Your recorder is offline — start it (steps above) and this scan will work. The scan runs on the recorder, on your network.'
                    : 'Runs a scan from your recorder and lists computers that could host one.')}
                </p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
