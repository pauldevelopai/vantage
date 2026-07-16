import { useEffect, useRef, useState } from 'react';
import Hls from 'hls.js';
import { api } from '../lib/api';
import { hasRole, getToken } from '../lib/auth';
import type { Camera, Site } from '../lib/types';

const SOURCE_TYPE_OPTIONS = [
  { value: 'rtsp', label: 'RTSP Direct' },
  { value: 'onvif', label: 'ONVIF' },
  { value: 'milestone', label: 'Milestone XProtect' },
  { value: 'genetec', label: 'Genetec Security Center' },
];

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
  is_computer?: boolean;   // a computer/NAS — a candidate recording PC
  found_by?: string[];
}

function CameraLiveView({ camera, onClose }: { camera: Camera; onClose: () => void }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [status, setStatus] = useState<'connecting' | 'live' | 'error'>('connecting');
  const [message, setMessage] = useState('Starting the stream from your recording PC…');

  useEffect(() => {
    let hls: Hls | null = null;
    let cancelled = false;
    const token = getToken();
    const src = `/api/cameras/${camera.camera_id}/hls/index.m3u8`;

    // Heartbeat so the agent keeps streaming while this is open.
    api.watchCamera(camera.camera_id).catch(() => {});
    const beat = setInterval(() => api.watchCamera(camera.camera_id).catch(() => {}), 5000);

    // If nothing plays within ~30s, the recording PC probably isn't running.
    const giveUp = setTimeout(() => {
      if (!cancelled && status !== 'live') {
        setStatus('error');
        setMessage('No video yet. Make sure the recorder is running on the camera’s network.');
      }
    }, 30000);

    if (!Hls.isSupported()) {
      setStatus('error');
      setMessage('This browser can’t play the live stream.');
    } else {
      hls = new Hls({
        xhrSetup: (xhr: XMLHttpRequest) => {
          if (token) xhr.setRequestHeader('Authorization', 'Bearer ' + token);
        },
        liveDurationInfinity: true,
        lowLatencyMode: true,
      });
      hls.loadSource(src);
      hls.attachMedia(videoRef.current!);
      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        if (cancelled) return;
        clearTimeout(giveUp);          // playing now — cancel the "no video" fallback
        setStatus('live');
        videoRef.current?.play().catch(() => {});
      });
      hls.on(Hls.Events.ERROR, (_evt, data) => {
        if (!data.fatal || cancelled) return;
        // The playlist isn't there yet while the agent spins ffmpeg up — retry.
        if (data.type === Hls.ErrorTypes.NETWORK_ERROR) {
          setTimeout(() => { if (!cancelled && hls) hls.loadSource(src); }, 1500);
        } else if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
          hls?.recoverMediaError();
        } else {
          setStatus('error');
          setMessage('Live stream error.');
        }
      });
    }

    return () => {
      cancelled = true;
      clearInterval(beat);
      clearTimeout(giveUp);
      if (hls) hls.destroy();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [camera.camera_id]);

  return (
    <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-gray-900 rounded-lg overflow-hidden max-w-4xl w-full" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-4 py-3 bg-gray-800">
          <div className="text-white font-medium flex items-center gap-2">
            {camera.name}
            {status === 'live' && <span className="text-xs px-2 py-0.5 rounded-full bg-red-600 text-white">● LIVE</span>}
          </div>
          <button onClick={onClose} className="text-gray-300 hover:text-white text-sm">Close ✕</button>
        </div>
        <div className="relative bg-black aspect-video flex items-center justify-center">
          <video ref={videoRef} className="w-full h-full" muted playsInline controls />
          {status !== 'live' && (
            <div className="absolute inset-0 flex flex-col items-center justify-center text-center px-6 bg-black/60">
              {status === 'connecting' && (
                <svg className="animate-spin h-6 w-6 text-white mb-3" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" /></svg>
              )}
              <p className="text-sm text-gray-200">{message}</p>
            </div>
          )}
        </div>
        <p className="px-4 py-2 text-xs text-gray-400 bg-gray-800">
          Live only while this is open — streaming stops when you close it.
        </p>
      </div>
    </div>
  );
}

function EditCameraModal({ camera, onClose, onSaved }: { camera: Camera; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(camera.name);
  const [source, setSource] = useState(camera.source);
  const [area, setArea] = useState(camera.area || '');
  const [enabled, setEnabled] = useState(camera.enabled);
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    try {
      await api.updateCamera(camera.camera_id, { name, source, area, enabled });
      onSaved();
      onClose();
    } catch (e: any) {
      alert(e.message || 'Failed to save');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl w-full max-w-lg p-6" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-medium text-gray-900">Edit camera</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-sm">Close ✕</button>
        </div>
        <div className="space-y-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
            <input value={name} onChange={e => setName(e.target.value)} className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm" />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Stream URL (RTSP, incl. login)</label>
            <input value={source} onChange={e => setSource(e.target.value)} className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm font-mono" />
            <p className="text-xs text-gray-400 mt-1">e.g. rtsp://admin:pass@192.168.3.91:554/cam/realmonitor?channel=1&amp;subtype=0</p>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Area / Suburb</label>
            <input value={area} onChange={e => setArea(e.target.value)} placeholder="Sandton" className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm" />
          </div>
          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} />
            Enabled (recording + live view)
          </label>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-700 bg-gray-100 rounded-md hover:bg-gray-200">Cancel</button>
          <button onClick={save} disabled={saving} className="px-4 py-2 text-sm text-white bg-blue-600 rounded-md hover:bg-blue-700 disabled:opacity-50">{saving ? 'Saving…' : 'Save'}</button>
        </div>
      </div>
    </div>
  );
}

export function CamerasPage() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [loading, setLoading] = useState(true);
  const [liveCamera, setLiveCamera] = useState<Camera | null>(null);
  const [editCamera, setEditCamera] = useState<Camera | null>(null);
  const [sites, setSites] = useState<Site[]>([]);
  const [formSiteId, setFormSiteId] = useState('');   // link the added camera to a site
  const [showForm, setShowForm] = useState(false);

  // Network scan state
  const [scanning, setScanning] = useState(false);
  const [scanComplete, setScanComplete] = useState(false);
  const [discovered, setDiscovered] = useState<DiscoveredCamera[]>([]);
  // Shared camera credentials — applied when adding a discovered camera. Most
  // sites use one login across all cameras, so enter it once.
  const [camUser, setCamUser] = useState('admin');
  const [camPass, setCamPass] = useState('');
  const [addingCamera, setAddingCamera] = useState<string | null>(null);
  const [showScanResults, setShowScanResults] = useState(false);

  // Camera Bridge state (scan the user's own WiFi via a local agent)
  const [showOtherDevices, setShowOtherDevices] = useState(false);
  const [showBridge, setShowBridge] = useState(false);
  const [bridges, setBridges] = useState<Array<{ bridge_id: string; name: string; online: boolean; site_hint: string; last_seen: string | null }>>([]);

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
    api.listSites().then(d => setSites(d.sites)).catch(() => {});
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
        site_id: formSiteId,
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
        username: camUser.trim(),
        password: camPass,
        vendor: cam.vendor || '',
        manufacturer: cam.manufacturer || '',
        site_id: formSiteId,
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
    for (const cam of discoveredCameras.filter(d => !d.already_registered)) {
      await handleAddDiscovered(cam);
    }
  }

  // Respect the scanner's verdict: is_camera === false are NOT cameras (routers,
  // IoT, computers with a web port). Treat undefined as a camera for safety.
  const discoveredCameras = discovered.filter(d => d.is_camera !== false);
  const computers = discovered.filter(d => d.is_camera === false && d.is_computer === true);
  const otherDevices = discovered.filter(d => d.is_camera === false && d.is_computer !== true);
  const newDiscoveredCameras = discoveredCameras.filter(d => !d.already_registered);

  const renderDiscoveredRow = (cam: DiscoveredCamera, idx: number) => (
    <div
      key={`${cam.ip}-${idx}`}
      className={`border rounded-lg p-3 flex items-center justify-between ${
        cam.already_registered ? 'bg-gray-50 border-gray-200' : 'bg-green-50 border-green-200'
      }`}
    >
      <div className="flex items-center gap-3 min-w-0">
        <span className="flex-shrink-0 text-xl" role="img" aria-label="camera">📷</span>
        <div className="min-w-0">
          <span className="font-medium text-gray-900 text-sm truncate block">
            {cam.name && cam.name !== cam.ip ? cam.name : 'Camera'}
          </span>
          <div className="text-xs text-gray-500 mt-0.5">at {cam.ip}</div>
        </div>
      </div>

      <div className="flex-shrink-0 ml-3">
        {cam.already_registered ? (
          <span className="inline-flex items-center px-2.5 py-1 text-xs font-medium text-green-700 bg-green-100 rounded-md">
            ✓ Added
          </span>
        ) : (
          <button
            onClick={() => handleAddDiscovered(cam)}
            disabled={addingCamera === cam.ip || !camPass}
            title={!camPass ? 'Enter the camera password above first' : undefined}
            className="px-3 py-1.5 text-xs font-medium text-white bg-green-600 rounded-md hover:bg-green-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
          >
            {addingCamera === cam.ip ? 'Adding…' : 'Add'}
          </button>
        )}
      </div>
    </div>
  );

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
              ? 'No cameras added yet'
              : `${cameras.length} camera${cameras.length !== 1 ? 's' : ''} added`}
          </p>
        </div>
        {isAdmin && (
          <div className="mt-3 sm:mt-0 flex flex-col items-stretch sm:items-end gap-2">
            <div className="flex gap-2">
              <button
                onClick={() => setShowBridge(!showBridge)}
                className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-md hover:bg-indigo-700 flex items-center gap-2"
              >
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.111 16.404a5.5 5.5 0 017.778 0M12 20h.01m-7.08-7.071c3.904-3.905 10.236-3.905 14.141 0M1.394 9.393c5.857-5.858 15.355-5.858 21.213 0" /></svg>
                {showBridge ? 'Close' : 'Find my cameras'}
              </button>
              <button
                onClick={() => { resetForm(); setShowForm(!showForm); }}
                className="px-4 py-2 bg-white text-gray-700 text-sm font-medium rounded-md border border-gray-300 hover:bg-gray-50"
              >
                {showForm ? 'Cancel' : 'Add manually'}
              </button>
            </div>
            {/* Advanced: scan the network this server is on (on-premise installs only). */}
            <button
              onClick={handleScanNetwork}
              disabled={scanning}
              className="text-xs text-gray-400 hover:text-gray-600 disabled:opacity-50"
            >
              {scanning ? 'Scanning…' : 'Advanced: scan this server’s own network'}
            </button>
          </div>
        )}
      </div>

      {/* Camera Bridge — scan the WiFi where the user's cameras are */}
      {showBridge && isAdmin && (
        <div className="bg-white shadow rounded-lg p-6 mb-6 border-l-4 border-indigo-400">
          <h2 className="text-lg font-medium text-gray-900">Find cameras on your network</h2>
          <p className="mt-1 text-sm text-gray-500">
            Your <span className="font-medium">recorder</span> scans the network it's on and finds the cameras.
            Start it (on the <a href="/recorders" className="text-indigo-600 underline">Recorders</a> page), then scan here.
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
                  <p className="text-xs text-gray-400">Recorder connected. Found cameras appear below.</p>
                </div>
              );
            }
            return (
              <div className="mt-4 rounded-md border border-gray-200 bg-gray-50 p-4 text-sm text-gray-600">
                <p>
                  No recorder is online yet. Set one up on the{' '}
                  <a href="/recorders" className="text-indigo-600 underline font-medium">Recorders</a> page —
                  once it's running, come back here and a <span className="font-medium">Scan this network</span> button appears.
                </p>
                <p className="mt-2 text-gray-500">
                  In a hurry, or the scan can't reach a camera? Use <span className="font-medium">Add manually</span> (top right) with the camera's address.
                </p>
                {bridges.length > 0 && (
                  <p className="mt-2 text-xs text-gray-400">A recorder is paired but currently offline — start it.</p>
                )}
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
              <label className="block text-sm font-medium text-gray-700 mb-1">Site</label>
              <select
                value={formSiteId}
                onChange={(e) => setFormSiteId(e.target.value)}
                className="w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm"
              >
                <option value="">No site</option>
                {sites.map(s => <option key={s.site_id} value={s.site_id}>{s.name}</option>)}
              </select>
              <p className="mt-1 text-xs text-gray-500">
                Links this camera to a site so its security brief covers it. {sites.length === 0 && 'Create a site first (Sites page).'}
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
                  Found {discoveredCameras.length} camera{discoveredCameras.length !== 1 ? 's' : ''}
                  {newDiscoveredCameras.length > 0 && ` — ${newDiscoveredCameras.length} new`}
                  {otherDevices.length > 0 && `, ${otherDevices.length} other device${otherDevices.length !== 1 ? 's' : ''}`}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              {scanComplete && newDiscoveredCameras.length > 1 && (
                <button
                  onClick={handleAddAllDiscovered}
                  className="px-3 py-1.5 text-xs font-medium text-white bg-green-600 rounded-md hover:bg-green-700"
                >
                  Add All New ({newDiscoveredCameras.length})
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

          {discoveredCameras.length === 0 && scanComplete && (
            <div className="text-center py-8 text-gray-500">
              <p>No cameras found on the local network.</p>
              <p className="text-xs text-gray-400 mt-1">Ensure cameras are powered on and connected to the same network.</p>
            </div>
          )}

          {discoveredCameras.length > 0 && (
            <div className="space-y-2">
              {/* Shared camera credentials — applied when adding a camera. Most
                  sites use one login across all cameras, so enter it once. */}
              <div className="rounded-lg border border-blue-200 bg-blue-50 p-3">
                <p className="text-sm font-medium text-gray-900">Camera login</p>
                <p className="text-xs text-gray-500 mb-2">
                  Entered once and used when you add a camera below. Most cameras share one login.
                </p>
                <div className="flex flex-wrap gap-2">
                  <input
                    type="text"
                    value={camUser}
                    onChange={e => setCamUser(e.target.value)}
                    placeholder="Username (usually admin)"
                    autoComplete="off"
                    className="flex-1 min-w-[140px] rounded-md border border-gray-300 px-2 py-1.5 text-sm"
                  />
                  <input
                    type="password"
                    value={camPass}
                    onChange={e => setCamPass(e.target.value)}
                    placeholder="Password"
                    autoComplete="new-password"
                    className="flex-1 min-w-[140px] rounded-md border border-gray-300 px-2 py-1.5 text-sm"
                  />
                  <select
                    value={formSiteId}
                    onChange={e => setFormSiteId(e.target.value)}
                    className="flex-1 min-w-[140px] rounded-md border border-gray-300 px-2 py-1.5 text-sm bg-white"
                    title="Link added cameras to a site"
                  >
                    <option value="">No site</option>
                    {sites.map(s => <option key={s.site_id} value={s.site_id}>{s.name}</option>)}
                  </select>
                </div>
                {!camPass && (
                  <p className="text-xs text-amber-600 mt-1">
                    Without a password the camera stream won't connect — enter it before adding.
                  </p>
                )}
              </div>
              {discoveredCameras.map((cam, idx) => renderDiscoveredRow(cam, idx))}
            </div>
          )}

          {/* Computers/NAS on the network — candidate recording PCs. */}
          {computers.length > 0 && (
            <div className="mt-4 rounded-lg border border-gray-200 bg-white p-3">
              <p className="text-sm font-medium text-gray-900">
                Computers on your network ({computers.length})
              </p>
              <p className="text-xs text-gray-500 mb-2">
                Any always-on one of these can be your <span className="font-medium">recording PC</span> — install the recorder on it (Sites → Add the recording PC).
              </p>
              <div className="space-y-1.5">
                {computers.map((c, idx) => (
                  <div key={`pc-${c.ip}-${idx}`} className="flex items-center gap-3 rounded-md border border-gray-100 bg-gray-50 px-3 py-2">
                    <span className="text-lg" role="img" aria-label="computer">🖥️</span>
                    <div className="min-w-0">
                      <div className="text-sm font-medium text-gray-900 truncate">
                        {c.name && !c.name.startsWith('Camera (') ? c.name : 'Computer'}
                      </div>
                      <div className="text-xs text-gray-500">at {c.ip}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Non-cameras the scan turned up (routers, IoT) — hidden by
              default so they're not mistaken for cameras. */}
          {otherDevices.length > 0 && (
            <div className="mt-3">
              <button
                onClick={() => setShowOtherDevices(v => !v)}
                className="text-xs text-gray-500 hover:text-gray-700"
              >
                {showOtherDevices ? '▾' : '▸'} {otherDevices.length} other device{otherDevices.length !== 1 ? 's' : ''} on the network (not cameras)
              </button>
              {showOtherDevices && (
                <div className="space-y-2 mt-2 opacity-70">
                  <p className="text-xs text-gray-400">
                    These responded on a web/RTSP port but didn't look like cameras. Add one only if you know it is a camera the scanner missed.
                  </p>
                  {otherDevices.map((cam, idx) => renderDiscoveredRow(cam, idx))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Camera List */}
      {cameras.length === 0 ? (
        <div className="text-center py-12 bg-white rounded-lg shadow">
          <p className="text-gray-500">No cameras yet</p>
          {isAdmin && <p className="text-sm text-gray-400 mt-1">Click <span className="font-medium">Find my cameras</span> to discover the cameras on your network.</p>}
        </div>
      ) : (
        <div className="space-y-3">
          {cameras.map(cam => (
            <div key={cam.camera_id} className="bg-white shadow rounded-lg p-4 flex items-center justify-between">
              <div className="flex items-center gap-4 min-w-0">
                <span className="flex-shrink-0 text-2xl" role="img" aria-label="camera">📷</span>
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-gray-900 truncate">{cam.name}</span>
                    {cam.area && (
                      <span className="inline-flex items-center rounded-full bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-700">
                        {cam.area}
                      </span>
                    )}
                  </div>
                  <div className="text-sm text-gray-500 truncate">
                    {cam.location || 'Added — your recording PC handles the video'}
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-2 flex-shrink-0 ml-4">
                <button
                  onClick={() => setLiveCamera(cam)}
                  className="px-3 py-1.5 text-xs font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 flex items-center gap-1"
                >
                  <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" /></svg>
                  Watch live
                </button>
                {isAdmin && (
                  <button
                    onClick={() => setEditCamera(cam)}
                    className="px-3 py-1.5 text-xs font-medium text-gray-700 bg-gray-100 rounded-md hover:bg-gray-200"
                  >
                    Edit
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

      {liveCamera && (
        <CameraLiveView camera={liveCamera} onClose={() => setLiveCamera(null)} />
      )}
      {editCamera && (
        <EditCameraModal camera={editCamera} onClose={() => setEditCamera(null)} onSaved={loadCameras} />
      )}
    </div>
  );
}
