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

export function CamerasPage() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<Record<string, any> | null>(null);

  // Form state
  const [formId, setFormId] = useState('');
  const [formName, setFormName] = useState('');
  const [formLocation, setFormLocation] = useState('');
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
          <button
            onClick={() => { resetForm(); setShowForm(!showForm); }}
            className="mt-3 sm:mt-0 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700"
          >
            {showForm ? 'Cancel' : 'Add Camera'}
          </button>
        )}
      </div>

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

      {/* Camera List */}
      {cameras.length === 0 ? (
        <div className="text-center py-12 bg-white rounded-lg shadow">
          <p className="text-gray-500">No cameras registered.</p>
          {isAdmin && <p className="text-sm text-gray-400 mt-1">Click "Add Camera" to register one, or open the mobile camera to auto-register.</p>}
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
