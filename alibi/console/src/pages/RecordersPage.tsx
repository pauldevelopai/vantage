import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { hasRole } from '../lib/auth';

type Storage = {
  dir: string; total_bytes: number; files: number;
  oldest: number | null; newest: number | null;
  cameras: Record<string, { bytes: number; files: number }>;
} | null;
type Bridge = { bridge_id: string; name: string; online: boolean; site_hint: string; last_seen: string | null; storage?: Storage };

function fmtBytes(n: number): string {
  if (!n) return '0 B';
  const u = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.min(u.length - 1, Math.floor(Math.log(n) / Math.log(1024)));
  return `${(n / Math.pow(1024, i)).toFixed(i ? 1 : 0)} ${u[i]}`;
}

export function RecordersPage() {
  const isAdmin = hasRole('admin');
  const [bridges, setBridges] = useState<Bridge[]>([]);
  const [downloading, setDownloading] = useState(false);
  const [computers, setComputers] = useState<Array<Record<string, any>>>([]);
  const [scanning, setScanning] = useState(false);
  const [scanNote, setScanNote] = useState<string | null>(null);

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

  useEffect(() => {
    loadBridges();
    const t = setInterval(loadBridges, 5000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => { loadCandidates(bridges); }, [bridges]);

  async function handleDownload() {
    setDownloading(true);
    try { await api.downloadRecorder(); }
    catch { alert('Failed to download the recorder'); }
    finally { setDownloading(false); }
  }

  const isMac = /Mac/i.test(navigator.platform || navigator.userAgent);
  const cmdLines = isMac
    ? 'cd ~/Downloads\npython3 vantage_recorder.pyz --dir ~/vantage-rec --max-gb 200 --max-days 30'
    : 'cd %USERPROFILE%\\Downloads\npython vantage_recorder.pyz --dir vantage-rec --max-gb 200 --max-days 30';
  const [launching, setLaunching] = useState(false);
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
                        <span className="font-medium">{fmtBytes(s.total_bytes)}</span> in {s.files.toLocaleString()} file{s.files === 1 ? '' : 's'}
                        {camCount > 0 && ` across ${camCount} camera${camCount === 1 ? '' : 's'}`}
                        {s.oldest && s.newest && (
                          <> · {new Date(s.oldest * 1000).toLocaleDateString()} → {new Date(s.newest * 1000).toLocaleDateString()}</>
                        )}
                      </div>
                      <div className="text-gray-400 font-mono truncate mt-0.5" title={s.dir}>📁 {s.dir}</div>
                      {camCount > 0 && (
                        <ul className="mt-1 space-y-0.5">
                          {Object.entries(s.cameras).map(([cid, v]) => (
                            <li key={cid} className="text-gray-500">📷 {cid} — {fmtBytes(v.bytes)} · {v.files} files</li>
                          ))}
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
                <pre className="mt-1 bg-gray-900 text-gray-100 text-xs rounded-md p-3 overflow-x-auto whitespace-pre">{cmdLines}</pre>
                <span className="text-xs text-gray-500">You should see <code className="bg-gray-100 px-1 rounded">paired as brg_…</code>. Leave the window open — it appears under “Your recorders” above.</span>
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
                <p className="mt-2 text-xs text-gray-400">{scanNote || 'Runs a scan from a connected recorder and lists computers that could host one.'}</p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
