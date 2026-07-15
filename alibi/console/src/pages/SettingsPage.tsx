import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../lib/api';
import { hasRole } from '../lib/auth';
import type { Settings } from '../lib/types';

export function SettingsPage() {
  const navigate = useNavigate();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  // Check admin role
  useEffect(() => {
    if (!hasRole('admin')) {
      alert('Settings page is restricted to administrators only');
      navigate('/incidents');
    }
  }, [navigate]);

  useEffect(() => {
    loadSettings();
  }, []);

  async function loadSettings() {
    setLoading(true);
    try {
      const data = await api.getSettings();
      setSettings(data);
    } catch (error) {
      console.error('Failed to load settings:', error);
    } finally {
      setLoading(false);
    }
  }

  async function saveSettings() {
    if (!settings) return;

    setSaving(true);
    try {
      await api.updateSettings(settings);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (error) {
      console.error('Failed to save settings:', error);
      alert('Failed to save settings');
    } finally {
      setSaving(false);
    }
  }

  if (loading || !settings) {
    return <div className="px-4 py-8 text-center">Loading settings...</div>;
  }

  return (
    <div className="px-4 sm:px-6 lg:px-8 max-w-4xl">
      <div className="sm:flex sm:items-center sm:justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Settings</h1>
          <p className="mt-2 text-sm text-gray-700">
            Configure Vantage system thresholds and behavior
          </p>
        </div>
      </div>

      {saved && (
        <div className="mb-6 rounded-md bg-green-50 p-4">
          <div className="flex">
            <div className="flex-shrink-0">
              <svg className="h-5 w-5 text-green-400" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.857-9.809a.75.75 0 00-1.214-.882l-3.483 4.79-1.88-1.88a.75.75 0 10-1.06 1.061l2.5 2.5a.75.75 0 001.137-.089l4-5.5z" clipRule="evenodd" />
              </svg>
            </div>
            <div className="ml-3">
              <p className="text-sm font-medium text-green-800">Settings saved successfully!</p>
            </div>
          </div>
        </div>
      )}

      <div className="space-y-6">
        {/* Thresholds */}
        <div className="bg-white shadow rounded-lg p-6">
          <h2 className="text-lg font-medium text-gray-900 mb-4">Thresholds</h2>
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Minimum Confidence for Notify
              </label>
              <input
                type="number"
                min="0"
                max="1"
                step="0.05"
                value={settings.thresholds.min_confidence_for_notify}
                onChange={(e) => setSettings({
                  ...settings,
                  thresholds: {
                    ...settings.thresholds,
                    min_confidence_for_notify: parseFloat(e.target.value),
                  }
                })}
                className="w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
              />
              <p className="mt-1 text-sm text-gray-500">
                Confidence threshold below which incidents will only be monitored (0.0 - 1.0)
              </p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                High Severity Threshold
              </label>
              <input
                type="number"
                min="1"
                max="5"
                value={settings.thresholds.high_severity_threshold}
                onChange={(e) => setSettings({
                  ...settings,
                  thresholds: {
                    ...settings.thresholds,
                    high_severity_threshold: parseInt(e.target.value),
                  }
                })}
                className="w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
              />
              <p className="mt-1 text-sm text-gray-500">
                Severity level at or above which human approval is required (1-5)
              </p>
            </div>
          </div>
        </div>

        {/* Grouping Windows */}
        <div className="bg-white shadow rounded-lg p-6">
          <h2 className="text-lg font-medium text-gray-900 mb-4">Incident Grouping Windows</h2>
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Merge Window (seconds)
              </label>
              <input
                type="number"
                min="0"
                value={settings.incident_grouping.merge_window_seconds}
                onChange={(e) => setSettings({
                  ...settings,
                  incident_grouping: {
                    ...settings.incident_grouping,
                    merge_window_seconds: parseInt(e.target.value),
                  }
                })}
                className="w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
              />
              <p className="mt-1 text-sm text-gray-500">
                Time window for merging related events into the same incident
              </p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Deduplication Window (seconds)
              </label>
              <input
                type="number"
                min="0"
                value={settings.incident_grouping.dedup_window_seconds}
                onChange={(e) => setSettings({
                  ...settings,
                  incident_grouping: {
                    ...settings.incident_grouping,
                    dedup_window_seconds: parseInt(e.target.value),
                  }
                })}
                className="w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
              />
              <p className="mt-1 text-sm text-gray-500">
                Time window for detecting duplicate events
              </p>
            </div>
          </div>
        </div>

        {/* Event Type Compatibility */}
        <div className="bg-white shadow rounded-lg p-6">
          <h2 className="text-lg font-medium text-gray-900 mb-4">Compatible Event Types</h2>
          <p className="text-sm text-gray-600 mb-4">
            Event types in the same group can be merged into a single incident
          </p>
          <div className="space-y-3">
            {Object.entries(settings.incident_grouping.compatible_event_types).map(([key, types]) => (
              <div key={key} className="bg-gray-50 rounded p-3">
                <p className="text-sm font-medium text-gray-900 mb-1 capitalize">{key}</p>
                <p className="text-sm text-gray-600">{types.join(', ')}</p>
              </div>
            ))}
          </div>
          <p className="mt-3 text-sm text-gray-500">
            Note: Editing event type groups requires direct API call with full structure
          </p>
        </div>

        {/* Save Button */}
        <div className="flex justify-end gap-3">
          <button
            onClick={loadSettings}
            className="px-4 py-2 bg-gray-100 text-gray-700 rounded-md hover:bg-gray-200"
          >
            Reset
          </button>
          <button
            onClick={saveSettings}
            disabled={saving}
            className="px-6 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
          >
            {saving ? 'Saving...' : 'Save Settings'}
          </button>
        </div>
      </div>
    </div>
  );
}
