import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { hasRole } from '../lib/auth';

type Bridge = { bridge_id: string; name: string; online: boolean; site_hint: string; last_seen: string | null };

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
          The always-on PC that records your cameras and runs the live view. One per network.
        </p>
      </div>

      {/* What it is */}
      <div className="rounded-lg bg-blue-50 border border-blue-100 p-4 mb-6 text-sm text-gray-700">
        Vantage runs in the cloud, so it can't reach your cameras directly — a small program on a
        computer on the <span className="font-medium">same network as your cameras</span> does the
        recording and live streaming, and sends the cloud only what it needs. That computer is your
        <span className="font-medium"> recorder</span>. Use any always-on machine (a spare PC, a mini-PC, a Mac).
      </div>

      {/* Set up a recorder — clear numbered steps */}
      {isAdmin && (
        <div className="bg-white shadow rounded-lg p-6 mb-6">
          <h2 className="text-lg font-medium text-gray-900 mb-4">Set up a recorder</h2>
          <ol className="space-y-5">
            <li className="flex gap-3">
              <span className="flex-none w-7 h-7 rounded-full bg-indigo-600 text-white font-semibold flex items-center justify-center">1</span>
              <div>
                <p className="font-medium text-gray-900">Prepare the PC (once)</p>
                <p className="text-sm text-gray-500 mt-0.5">
                  On the always-on computer, install two free tools:
                </p>
                <ul className="text-sm text-gray-600 list-disc list-inside mt-1 space-y-0.5">
                  <li><span className="font-medium">Python 3</span> — python.org/downloads (tick “Add to PATH” on Windows)</li>
                  <li><span className="font-medium">ffmpeg</span> — Windows: <code className="bg-gray-100 px-1 rounded">winget install Gyan.FFmpeg</code> · Mac: <code className="bg-gray-100 px-1 rounded">brew install ffmpeg</code></li>
                </ul>
              </div>
            </li>
            <li className="flex gap-3">
              <span className="flex-none w-7 h-7 rounded-full bg-indigo-600 text-white font-semibold flex items-center justify-center">2</span>
              <div>
                <p className="font-medium text-gray-900">Download the recorder</p>
                <p className="text-sm text-gray-500 mt-0.5">One file, already paired to your account — nothing to type in.</p>
                <button
                  onClick={handleDownload} disabled={downloading}
                  className="mt-2 px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-md hover:bg-indigo-700 disabled:opacity-50"
                >
                  {downloading ? 'Preparing…' : 'Download the recorder'}
                </button>
              </div>
            </li>
            <li className="flex gap-3">
              <span className="flex-none w-7 h-7 rounded-full bg-indigo-600 text-white font-semibold flex items-center justify-center">3</span>
              <div>
                <p className="font-medium text-gray-900">Run it</p>
                <p className="text-sm text-gray-500 mt-0.5">
                  Open a terminal in the download folder and run:
                </p>
                <pre className="mt-1 bg-gray-900 text-gray-100 text-xs rounded-md p-3 overflow-x-auto">python vantage_recorder.pyz --dir vantage-rec --max-gb 200 --max-days 30</pre>
                <p className="text-xs text-gray-500 mt-1">
                  (<code className="bg-gray-100 px-1 rounded">--max-gb</code> / <code className="bg-gray-100 px-1 rounded">--max-days</code> bound the disk it uses.) It pairs itself and appears below. Leave it running — set it to auto-start on boot for a permanent recorder.
                </p>
              </div>
            </li>
          </ol>
        </div>
      )}

      {/* Connected recorders */}
      <div className="bg-white shadow rounded-lg p-6 mb-6">
        <h2 className="text-lg font-medium text-gray-900 mb-1">Your recorders</h2>
        {bridges.length === 0 ? (
          <p className="text-sm text-gray-500">No recorder connected yet. Follow the steps above; it appears here the moment it starts.</p>
        ) : (
          <ul className="divide-y divide-gray-100">
            {bridges.map(b => (
              <li key={b.bridge_id} className="flex items-center gap-3 py-2.5">
                <span className={`w-2.5 h-2.5 rounded-full ${b.online ? 'bg-green-500' : 'bg-gray-300'}`} />
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium text-gray-900 truncate">{b.name || b.bridge_id}</div>
                  <div className="text-xs text-gray-500">
                    {b.online ? 'Online — recording' : 'Offline'}{b.site_hint ? ` · ${b.site_hint}` : ''}
                  </div>
                </div>
                {isAdmin && (
                  <div className="flex items-center gap-3">
                    <button onClick={() => handleRename(b.bridge_id, b.name)} className="text-xs text-blue-600 hover:text-blue-800">Rename</button>
                    <button onClick={() => handleRemove(b.bridge_id, b.name || b.bridge_id)} className="text-xs text-red-500 hover:text-red-700">Remove</button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
        {bridges.length > 0 && (
          <p className="text-xs text-gray-400 mt-3">Swapping PCs? Run the recorder on the new one, then Remove the old — its access is revoked immediately.</p>
        )}
      </div>

      {/* Find candidate recording PCs on the LAN */}
      <div className="bg-white shadow rounded-lg p-6">
        <div className="flex items-center justify-between mb-1">
          <h2 className="text-lg font-medium text-gray-900">Computers on your network</h2>
          {isAdmin && (
            <button
              onClick={handleScan}
              disabled={scanning || !anyOnline}
              title={!anyOnline ? 'Start a recorder first' : undefined}
              className="px-3 py-1.5 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
            >
              {scanning ? 'Scanning…' : 'Scan for computers'}
            </button>
          )}
        </div>
        <p className="text-sm text-gray-500 mb-3">
          Machines that could be a recorder. A running recorder scans its network and lists them; any always-on one is a good choice — set it up with the steps above.
          {!anyOnline && ' (Start a recorder first — the scan runs from it.)'}
        </p>
        {computers.length > 0 ? (
          <ul className="space-y-1.5">
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
          <p className="text-sm text-gray-400">{scanNote || 'No scan run yet — hit “Scan for computers”.'}</p>
        )}
        {computers.length > 0 && scanNote && <p className="text-xs text-gray-400 mt-2">{scanNote}</p>}
      </div>
    </div>
  );
}
