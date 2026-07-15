import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { hasRole } from '../lib/auth';
import type { Camera } from '../lib/types';

const SOURCE_TYPE_OPTIONS = [
  { value: 'rtsp', label: 'RTSP Direct' },
  { value: 'onvif', label: 'ONVIF' },
  { value: 'milestone', label: 'Milestone XProtect' },
  { value: 'genetec', label: 'Genetec Security Center' },
];

const STATUS_DOT: Record<string, string> = {
  online: 'bg-green-400',
  offline: 'bg-red-400',
  unknown: 'bg-gray-400',
};

const SOURCE_BADGE: Record<string, string> = {
  rtsp: 'bg-blue-100 text-blue-800',
  onvif: 'bg-purple-100 text-purple-800',
  milestone: 'bg-orange-100 text-orange-800',
  genetec: 'bg-teal-100 text-teal-800',
  mobile: 'bg-green-100 text-green-800',
};

interface DiscoveredCamera {
  ip: string;
  port: number;
  source_type: string;
  rtsp_url: string;
  name: string;
  manufacturer: string;
  model: string;
  resolution: string;
  discovery_method: string;
  already_registered: boolean;
  // Multi-strategy signal (added by the upgraded scanner)
  vendor?: string;
  open_ports?: number[];
  rtsp_confirmed?: boolean;
  confidence?: number;
  is_camera?: boolean;
  found_by?: string[];
}

const DISCOVERY_BADGE: Record<string, string> = {
  onvif: 'bg-purple-100 text-purple-800',
  rtsp_scan: 'bg-blue-100 text-blue-800',
  mdns: 'bg-green-100 text-green-800',
};

export function CamerasPage() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<Record<string, any> | null>(null);

  // Network scan state
  const [scanning, setScanning] = useState(false);
  const [scanComplete, setScanComplete] = useState(false);
  const [discovered, setDiscovered] = useState<DiscoveredCamera[]>([]);
  const [addingCamera, setAddingCamera] = useState<string | null>(null);
  const [showScanResults, setShowScanResults] = useState(false);

  // Camera Bridge state (scan the user's own WiFi via a local agent)
  const [showBridge, setShowBridge] = useState(false);
  const [bridges, setBridges] = useState<Array<{ bridge_id: string; name: string; online: boolean; site_hint: string; last_seen: string | null }>>([]);
  const [downloadingAgent, setDownloadingAgent] = useState(false);

  // Form state
  const [formId, setFormId] = useState('');
  const [formName, setFormName] = useState('');
  const [formLocation, setFormLocation] = useState('');
  const [formArea, setFormArea] = useState('');
  const [formSourceType, setFormSourceType] = useState('rtsp');
  const [formSource, setFormSource] = useState('');
  const [formHost, setFormHost] = useState('');
  const [formPort, setFormPort] = useState('554');
  const [formGuid, setFormGuid] = useState('');
  const [formUsername, setFormUsername] = useState('');
  const [formPassword, setFormPassword] = useState('');
  const [saving, setSaving] = useState(false);

  const isAdmin = hasRole('admin');

  useEffect(() => {
    loadCameras();
  }, []);

  async function loadCameras() {
    setLoading(true);
    try {
      const data = await api.listCameras();
      setCameras(data.cameras);
    } catch (error) {
      console.error('Failed to load cameras:', error);
    } finally {
      setLoading(false);
    }
  }

  function resetForm() {
    setFormId('');
    setFormName('');
    setFormLocation('');
    setFormArea('');
    setFormSourceType('rtsp');
    setFormSource('');
    setFormHost('');
    setFormPort('554');
    setFormGuid('');
    setFormUsername('');
    setFormPassword('');
    setTestResult(null);
  }

  async function handleAdd() {
    if (!formId || !formName) return;
    setSaving(true);
    try {
      const vms_config: Record<string, any> = {};
      let source = formSource;

      if (formSourceType !== 'rtsp') {
        vms_config.host = formHost;
        vms_config.port = parseInt(formPort) || 554;
        vms_config.camera_guid = formGuid;
        if (formUsername) vms_config.username = formUsername;
        if (formPassword) vms_config.password = formPassword;
        source = '';  // URL built from vms_config
      }

      await api.addCamera({
        camera_id: formId,
        name: formName,
        source,
        source_type: formSourceType,
        location: formLocation,
        area: formArea,
        vms_config,
      });
      resetForm();
      setShowForm(false);
      loadCameras();
    } catch (error) {
      console.error('Failed to add camera:', error);
      alert('Failed to add camera');
    } finally {
      setSaving(false);
    }
  }

  async function handleTest(cameraId: string) {
    setTesting(cameraId);
    setTestResult(null);
    try {
      const result = await api.testCamera(cameraId);
      setTestResult({ cameraId, ...result });
    } catch (error) {
      setTestResult({ cameraId, ok: false, error: 'Test request failed' });
    } finally {
      setTesting(null);
    }
  }

  async function handleDelete(cameraId: string) {
    if (!confirm(`Remove camera "${cameraId}"?`)) return;
    try {
      await api.deleteCamera(cameraId);
      loadCameras();
    } catch (error) {
      console.error('Failed to delete camera:', error);
    }
  }

  async function handleScanNetwork() {
    setScanning(true);
    setScanComplete(false);
    setDiscovered([]);
    setShowScanResults(true);

    try {
      await api.scanCameras();

      // Poll for results
      const poll = async () => {
        try {
          const status = await api.getScanStatus();
          setDiscovered(status.discovered || []);

          if (status.status === 'completed' || status.status === 'idle') {
            setScanning(false);
            setScanComplete(true);
          } else {
            setTimeout(poll, 1500);
          }
        } catch {
          setScanning(false);
          setScanComplete(true);
        }
      };

      setTimeout(poll, 2000);
    } catch (error) {
      console.error('Failed to start network scan:', error);
      setScanning(false);
      alert('Failed to start network scan');
    }
  }

  async function loadBridges() {
    try {
      const data = await api.listBridges();
      setBridges(data.bridges);
    } catch (error) {
      console.error('Failed to load bridges:', error);
    }
  }

  // While the bridge panel is open, poll so a newly-started agent appears.
  useEffect(() => {
    if (!showBridge) return;
    loadBridges();
    const t = setInterval(loadBridges, 5000);
    return () => clearInterval(t);
  }, [showBridge]);

  // When a bridge is online and we've no results shown yet, surface its last
  // completed scan — so cameras appear even if the live scan-poll never finished
  // (e.g. the tab was reloaded or froze mid-scan).
  useEffect(() => {
    if (!showBridge || scanning || discovered.length > 0) return;
    const online = bridges.find(b => b.online);
    if (online) loadLatestBridgeScan(online.bridge_id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showBridge, bridges, scanning]);

  async function handleDownloadAgent() {
    setDownloadingAgent(true);
    try {
      await api.downloadBridgeAgent();
    } catch (error) {
      console.error('Failed to download agent:', error);
      alert('Failed to download the Vantage Bridge agent');
    } finally {
      setDownloadingAgent(false);
    }
  }

  // Show the last completed scan for a bridge (resilient to a frozen poll / reload).
  async function loadLatestBridgeScan(bridgeId: string) {
    try {
      const { job } = await api.getLatestBridgeScan(bridgeId);
      if (job && job.results && job.results.length > 0) {
        setDiscovered(job.results as DiscoveredCamera[]);
        setShowScanResults(true);
        setScanComplete(true);
      }
    } catch {
      /* no prior scan — fine */
    }
  }

  async function handleBridgeScan(bridgeId: string) {
    setScanning(true);
    setScanComplete(false);
    setDiscovered([]);
    setShowScanResults(true);
    let jobId: string;
    try {
      const res = await api.scanViaBridge(bridgeId);
      jobId = res.job_id;
    } catch (error: any) {
      setScanning(false);
      alert(error?.message || 'Failed to start the scan');
      return;
    }

    const startedAt = Date.now();
    const poll = async () => {
      if (Date.now() - startedAt > 180000) {   // 3-min ceiling
        setScanning(false);
        setScanComplete(true);
        // Fall back to whatever the bridge last reported.
        loadLatestBridgeScan(bridgeId);
        return;
      }
      try {
        const status = await api.getBridgeScanStatus(jobId);
        if (status.status === 'done') {
          setDiscovered((status.results || []) as DiscoveredCamera[]);
          setScanning(false);
          setScanComplete(true);
          return;
        }
        if (status.status === 'error') {
          setScanning(false);
          setScanComplete(true);
          alert(`Scan failed on the bridge: ${status.error || 'unknown error'}`);
          return;
        }
      } catch {
        /* transient — keep polling rather than wedging */
      }
      setTimeout(poll, 2000);
    };
    setTimeout(poll, 2000);
  }

  async function handleAddDiscovered(cam: DiscoveredCamera) {
    setAddingCamera(cam.ip);
    try {
      await api.addDiscoveredCamera({
        ip: cam.ip,
        port: cam.port,
        rtsp_url: cam.rtsp_url,
        source_type: cam.source_type,
        name: cam.name || `Camera ${cam.ip}`,
        location: '',
      });
      // Mark as registered in local state
      setDiscovered(prev =>
        prev.map(d => d.ip === cam.ip ? { ...d, already_registered: true } : d)
      );
      loadCameras();
    } catch (error) {
      console.error('Failed to add discovered camera:', error);
      alert('Failed to add camera');
    } finally {
      setAddingCamera(null);
    }
  }

  async function handleAddAllDiscovered() {
    const newCameras = discovered.filter(d => !d.already_registered);
    for (const cam of newCameras) {
      await handleAddDiscovered(cam);
    }
  }

  const onlineCount = cameras.filter(c => c.status === 'online').length;
  const offlineCount = cameras.filter(c => c.status === 'offline').length;

  if (loading) {
    return <div className="px-4 py-8 text-center text-gray-500">Loading cameras...</div>;
  }

  return (
    <div className="px-4 sm:px-6 lg:px-8 max-w-5xl">
      {/* Header */}
      <div className="sm:flex sm:items-center sm:justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Cameras</h1>
          <p className="mt-1 text-sm text-gray-500">
            {cameras.length === 0
              ? 'No cameras registered yet'
              : `${cameras.length} camera${cameras.length !== 1 ? 's' : ''} — ${onlineCount} online${offlineCount > 0 ? `, ${offlineCount} offline` : ''}`}
          </p>
        </div>
        {isAdmin && (
          <div className="mt-3 sm:mt-0 flex gap-2">
            <button
              onClick={handleScanNetwork}
              disabled={scanning}
              title="Scan the network this Vantage server is on (for on-premise installs). For cloud, use 'Add cameras on my network'."
              className="px-4 py-2 bg-green-600 text-white text-sm font-medium rounded-md hover:bg-green-700 disabled:bg-green-300 disabled:cursor-not-allowed flex items-center gap-2"
            >
              {scanning ? (
                <>
                  <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" /></svg>
                  Scanning...
                </>
              ) : (
                <>
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.111 16.404a5.5 5.5 0 017.778 0M12 20h.01m-7.08-7.071c3.904-3.905 10.236-3.905 14.141 0M1.394 9.393c5.857-5.858 15.355-5.858 21.213 0" /></svg>
                  Scan Network
                </>
              )}
            </button>
            <button
              onClick={() => setShowBridge(!showBridge)}
              className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-md hover:bg-indigo-700 flex items-center gap-2"
              title="Discover cameras on the WiFi where your cameras actually are"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 18h.01M8 21h8a2 2 0 002-2V5a2 2 0 00-2-2H8a2 2 0 00-2 2v14a2 2 0 002 2z" /></svg>
              {showBridge ? 'Close' : 'Add cameras on my network'}
            </button>
            <button
              onClick={() => { resetForm(); setShowForm(!showForm); }}
              className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700"
            >
              {showForm ? 'Cancel' : 'Add Camera'}
            </button>
          </div>
        )}
      </div>

      {/* Camera Bridge — scan the WiFi where the user's cameras are */}
      {showBridge && isAdmin && (
        <div className="bg-white shadow rounded-lg p-6 mb-6 border-l-4 border-indigo-400">
          <h2 className="text-lg font-medium text-gray-900">Add cameras on your network</h2>
          <p className="mt-1 text-sm text-gray-500">
            Vantage runs in the cloud, so it can't see the WiFi your cameras are on.
            Run the small <span className="font-medium">Vantage Bridge</span> on a computer on
            that network — then scan from here and your cameras appear.
          </p>

          {(() => {
            const online = bridges.filter(b => b.online);
            if (online.length > 0) {
              return (
                <div className="mt-4 space-y-2">
                  {online.map(b => (
                    <div key={b.bridge_id} className="flex items-center justify-between rounded-md border border-green-200 bg-green-50 px-4 py-2.5">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="inline-block w-2 h-2 rounded-full bg-green-500" />
                          <span className="text-sm font-medium text-gray-900">{b.name}</span>
                          <span className="text-xs text-gray-500">{b.site_hint}</span>
                        </div>
                      </div>
                      <button
                        onClick={() => handleBridgeScan(b.bridge_id)}
                        disabled={scanning}
                        className="px-3 py-1.5 text-xs font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 disabled:bg-indigo-300"
                      >
                        {scanning ? 'Scanning…' : 'Scan this network'}
                      </button>
                    </div>
                  ))}
                  <p className="text-xs text-gray-400">Bridge connected. Results appear below the scan.</p>
                </div>
              );
            }
            return (
              <div className="mt-4 rounded-md border border-gray-200 bg-gray-50 p-4">
                <ol className="text-sm text-gray-700 space-y-2 list-decimal list-inside">
                  <li>
                    <button
                      onClick={handleDownloadAgent}
                      disabled={downloadingAgent}
                      className="inline-flex items-center px-3 py-1.5 text-xs font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 disabled:bg-indigo-300 align-middle mx-1"
                    >
                      {downloadingAgent ? 'Preparing…' : 'Download Vantage Bridge'}
                    </button>
                    onto a computer that's on the same WiFi as your cameras.
                  </li>
                  <li>Open it (<code className="text-xs bg-white px-1 rounded border">python3 vantage_bridge.py</code>). It pairs automatically — nothing to type.</li>
                  <li>This panel updates the moment it connects; then hit <span className="font-medium">Scan this network</span>.</li>
                </ol>
                <p className="mt-3 text-xs text-gray-400 flex items-center gap-1.5">
                  <svg className="animate-spin h-3 w-3" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" /></svg>
                  Waiting for a bridge to connect…
                  {bridges.length > 0 && ' (a paired bridge is currently offline)'}
                </p>
              </div>
            );
          })()}
        </div>
      )}

      {/* Add Camera Form */}
      {showForm && (
        <div className="bg-white shadow rounded-lg p-6 mb-6">
          <h2 className="text-lg font-medium text-gray-900 mb-4">Add Camera</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Camera ID</label>
              <input
                type="text"
                value={formId}
                onChange={(e) => setFormId(e.target.value.toLowerCase().replace(/[^a-z0-9-_]/g, '-'))}
                placeholder="entrance-north"
                className="w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
              <input
                type="text"
                value={formName}
                onChange={(e) => setFormName(e.target.value)}
                placeholder="North Entrance"
                className="w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Location</label>
              <input
                type="text"
                value={formLocation}
                onChange={(e) => setFormLocation(e.target.value)}
                placeholder="Building A, Gate 1"
                className="w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Area / Suburb
              </label>
              <input
                type="text"
                value={formArea}
                onChange={(e) => setFormArea(e.target.value)}
                placeholder="Sandton"
                className="w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm"
              />
              <p className="mt-1 text-xs text-gray-500">
                Optional. Enables area background (nearest police station, hospital,
                fire station) on this camera's incidents. Leave blank for none.
              </p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Source Type</label>
              <select
                value={formSourceType}
                onChange={(e) => setFormSourceType(e.target.value)}
                className="w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm"
              >
                {SOURCE_TYPE_OPTIONS.map(opt => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </div>

            {/* RTSP: just the URL */}
            {formSourceType === 'rtsp' && (
              <div className="sm:col-span-2">
                <label className="block text-sm font-medium text-gray-700 mb-1">RTSP URL</label>
                <input
                  type="text"
                  value={formSource}
                  onChange={(e) => setFormSource(e.target.value)}
                  placeholder="rtsp://192.168.1.100:554/stream1"
                  className="w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm font-mono"
                />
              </div>
            )}

            {/* VMS types: host, port, guid, credentials */}
            {formSourceType !== 'rtsp' && (
              <>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Host</label>
                  <input
                    type="text"
                    value={formHost}
                    onChange={(e) => setFormHost(e.target.value)}
                    placeholder="192.168.1.100"
                    className="w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Port</label>
                  <input
                    type="text"
                    value={formPort}
                    onChange={(e) => setFormPort(e.target.value)}
                    placeholder="554"
                    className="w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm"
                  />
                </div>
                {(formSourceType === 'milestone' || formSourceType === 'genetec') && (
                  <div className="sm:col-span-2">
                    <label className="block text-sm font-medium text-gray-700 mb-1">Camera GUID</label>
                    <input
                      type="text"
                      value={formGuid}
                      onChange={(e) => setFormGuid(e.target.value)}
                      placeholder="e.g. a1b2c3d4-e5f6-7890-abcd-ef1234567890"
                      className="w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm font-mono"
                    />
                  </div>
                )}
                {formSourceType === 'onvif' && (
                  <div className="sm:col-span-2">
                    <label className="block text-sm font-medium text-gray-700 mb-1">Stream Path (optional)</label>
                    <input
                      type="text"
                      value={formGuid}
                      onChange={(e) => setFormGuid(e.target.value)}
                      placeholder="stream1"
                      className="w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm font-mono"
                    />
                  </div>
                )}
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Username</label>
                  <input
                    type="text"
                    value={formUsername}
                    onChange={(e) => setFormUsername(e.target.value)}
                    className="w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
                  <input
                    type="password"
                    value={formPassword}
                    onChange={(e) => setFormPassword(e.target.value)}
                    className="w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm"
                  />
                </div>
              </>
            )}
          </div>
          <div className="mt-4 flex justify-end gap-3">
            <button
              onClick={() => { resetForm(); setShowForm(false); }}
              className="px-4 py-2 text-sm text-gray-700 bg-gray-100 rounded-md hover:bg-gray-200"
            >
              Cancel
            </button>
            <button
              onClick={handleAdd}
              disabled={saving || !formId || !formName}
              className="px-4 py-2 text-sm text-white bg-blue-600 rounded-md hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
            >
              {saving ? 'Adding...' : 'Add Camera'}
            </button>
          </div>
        </div>
      )}

      {/* Network Scan Results */}
      {showScanResults && (
        <div className="bg-white shadow rounded-lg p-6 mb-6">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              <h2 className="text-lg font-medium text-gray-900">
                {scanning ? 'Scanning Network...' : 'Discovered Cameras'}
              </h2>
              {scanning && (
                <span className="inline-flex items-center gap-1 text-sm text-green-600">
                  <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" /></svg>
                  Probing ONVIF, RTSP, mDNS...
                </span>
              )}
              {scanComplete && (
                <span className="text-sm text-gray-500">
                  Found {discovered.length} camera{discovered.length !== 1 ? 's' : ''}
                  {discovered.filter(d => !d.already_registered).length > 0 &&
                    ` — ${discovered.filter(d => !d.already_registered).length} new`
                  }
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              {scanComplete && discovered.filter(d => !d.already_registered).length > 1 && (
                <button
                  onClick={handleAddAllDiscovered}
                  className="px-3 py-1.5 text-xs font-medium text-white bg-green-600 rounded-md hover:bg-green-700"
                >
                  Add All New ({discovered.filter(d => !d.already_registered).length})
                </button>
              )}
              <button
                onClick={() => setShowScanResults(false)}
                className="px-3 py-1.5 text-xs font-medium text-gray-600 bg-gray-100 rounded-md hover:bg-gray-200"
              >
                Close
              </button>
            </div>
          </div>

          {discovered.length === 0 && scanning && (
            <div className="text-center py-8">
              <div className="inline-flex items-center gap-2 text-gray-500">
                <svg className="animate-pulse h-5 w-5 text-green-500" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M5.05 3.636a1 1 0 010 1.414 7 7 0 000 9.9 1 1 0 11-1.414 1.414 9 9 0 010-12.728 1 1 0 011.414 0zm9.9 0a1 1 0 011.414 0 9 9 0 010 12.728 1 1 0 01-1.414-1.414 7 7 0 000-9.9 1 1 0 010-1.414zM7.879 6.464a1 1 0 010 1.414 3 3 0 000 4.243 1 1 0 11-1.415 1.414 5 5 0 010-7.07 1 1 0 011.415 0zm4.242 0a1 1 0 011.415 0 5 5 0 010 7.072 1 1 0 01-1.415-1.415 3 3 0 000-4.242 1 1 0 010-1.415zM10 9a1 1 0 100 2 1 1 0 000-2z" clipRule="evenodd" /></svg>
                Scanning local network for cameras...
              </div>
              <p className="text-xs text-gray-400 mt-2">This may take 10-30 seconds depending on network size</p>
            </div>
          )}

          {discovered.length === 0 && scanComplete && (
            <div className="text-center py-8 text-gray-500">
              <p>No cameras found on the local network.</p>
              <p className="text-xs text-gray-400 mt-1">Ensure cameras are powered on and connected to the same network.</p>
            </div>
          )}

          {discovered.length > 0 && (
            <div className="space-y-2">
              {discovered.map((cam, idx) => (
                <div
                  key={`${cam.ip}-${idx}`}
                  className={`border rounded-lg p-3 flex items-center justify-between ${
                    cam.already_registered ? 'bg-gray-50 border-gray-200' : 'bg-green-50 border-green-200'
                  }`}
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <div className={`flex-shrink-0 w-2.5 h-2.5 rounded-full ${cam.already_registered ? 'bg-gray-400' : 'bg-green-500'}`} />
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-medium text-gray-900 text-sm">{cam.name || cam.ip}</span>
                        <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${DISCOVERY_BADGE[cam.discovery_method] || 'bg-gray-100 text-gray-800'}`}>
                          {cam.discovery_method === 'rtsp_scan' ? 'RTSP' : cam.discovery_method.toUpperCase()}
                        </span>
                        {typeof cam.confidence === 'number' && (
                          <span
                            title={cam.found_by?.length ? `Found by: ${cam.found_by.join(', ')}` : undefined}
                            className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                              cam.confidence >= 0.8 ? 'bg-green-100 text-green-800'
                                : cam.confidence >= 0.5 ? 'bg-yellow-100 text-yellow-800'
                                : 'bg-gray-100 text-gray-600'
                            }`}
                          >
                            {Math.round(cam.confidence * 100)}% match
                          </span>
                        )}
                        {cam.rtsp_confirmed && (
                          <span className="inline-flex items-center rounded-full bg-blue-100 text-blue-800 px-2 py-0.5 text-xs font-medium">
                            RTSP ✓
                          </span>
                        )}
                        {(cam.vendor || cam.manufacturer) && (
                          <span className="text-xs text-gray-500">{cam.vendor || cam.manufacturer} {cam.model}</span>
                        )}
                      </div>
                      <div className="text-xs text-gray-500 font-mono mt-0.5">
                        {cam.ip}:{cam.port}
                        {cam.open_ports && cam.open_ports.length > 0 && (
                          <span className="ml-2 text-gray-400">ports {cam.open_ports.join(', ')}</span>
                        )}
                        {cam.rtsp_url && <span className="ml-2 text-gray-400">{cam.rtsp_url}</span>}
                        {cam.resolution && <span className="ml-2">{cam.resolution}</span>}
                      </div>
                    </div>
                  </div>

                  <div className="flex-shrink-0 ml-3">
                    {cam.already_registered ? (
                      <span className="inline-flex items-center px-2.5 py-1 text-xs font-medium text-gray-500 bg-gray-100 rounded-md">
                        Already Added
                      </span>
                    ) : (
                      <button
                        onClick={() => handleAddDiscovered(cam)}
                        disabled={addingCamera === cam.ip}
                        className="px-3 py-1.5 text-xs font-medium text-white bg-green-600 rounded-md hover:bg-green-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
                      >
                        {addingCamera === cam.ip ? 'Adding...' : 'Add Camera'}
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Camera List */}
      {cameras.length === 0 ? (
        <div className="text-center py-12 bg-white rounded-lg shadow">
          <p className="text-gray-500">No cameras registered.</p>
          {isAdmin && <p className="text-sm text-gray-400 mt-1">Click "Scan Network" to auto-discover cameras, or "Add Camera" to register manually.</p>}
        </div>
      ) : (
        <div className="space-y-3">
          {cameras.map(cam => (
            <div key={cam.camera_id} className="bg-white shadow rounded-lg p-4 flex items-center justify-between">
              <div className="flex items-center gap-4 min-w-0">
                {/* Status dot */}
                <span className={`flex-shrink-0 w-3 h-3 rounded-full ${STATUS_DOT[cam.status] || STATUS_DOT.unknown}`} />

                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-gray-900 truncate">{cam.name}</span>
                    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${SOURCE_BADGE[cam.source_type] || 'bg-gray-100 text-gray-800'}`}>
                      {cam.source_type}
                    </span>
                    {cam.area && (
                      <span
                        className="inline-flex items-center rounded-full bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-700"
                        title="Area background is enabled for this camera's incidents"
                      >
                        {cam.area}
                      </span>
                    )}
                  </div>
                  <div className="text-sm text-gray-500 truncate">
                    {cam.location && <span>{cam.location}</span>}
                    {cam.location && cam.camera_id && <span className="mx-1">&middot;</span>}
                    <span className="font-mono text-xs">{cam.camera_id}</span>
                  </div>
                  {cam.last_seen && (
                    <div className="text-xs text-gray-400 mt-0.5">
                      Last seen: {new Date(cam.last_seen).toLocaleString()}
                    </div>
                  )}
                </div>
              </div>

              <div className="flex items-center gap-2 flex-shrink-0 ml-4">
                {/* Test result */}
                {testResult?.cameraId === cam.camera_id && (
                  <span className={`text-xs px-2 py-1 rounded ${testResult.ok ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
                    {testResult.ok ? `OK ${testResult.resolution}` : testResult.error}
                  </span>
                )}

                {isAdmin && cam.source_type !== 'mobile' && (
                  <button
                    onClick={() => handleTest(cam.camera_id)}
                    disabled={testing === cam.camera_id}
                    className="px-3 py-1.5 text-xs font-medium text-gray-700 bg-gray-100 rounded-md hover:bg-gray-200 disabled:opacity-50"
                  >
                    {testing === cam.camera_id ? 'Testing...' : 'Test'}
                  </button>
                )}
                {isAdmin && (
                  <button
                    onClick={() => handleDelete(cam.camera_id)}
                    className="px-3 py-1.5 text-xs font-medium text-red-600 bg-red-50 rounded-md hover:bg-red-100"
                  >
                    Remove
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
