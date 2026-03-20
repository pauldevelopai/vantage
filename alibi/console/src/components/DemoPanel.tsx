import React, { useState, useEffect } from 'react';
import { api } from '../lib/api';

interface SimulatorStatus {
  running: boolean;
  events_generated: number;
  incidents_created: number;
  rate_actual?: number;
  rate_target?: number;
  scenario?: string;
  seed?: number;
  elapsed_seconds?: number;
}

export const DemoPanel: React.FC = () => {
  const [isOpen, setIsOpen] = useState(false);
  const [status, setStatus] = useState<SimulatorStatus>({ running: false, events_generated: 0, incidents_created: 0 });
  const [scenario, setScenario] = useState('normal_day');
  const [rate, setRate] = useState(10);
  const [seed, setSeed] = useState('');
  const [replayData, setReplayData] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [message, setMessage] = useState('');

  // Poll status every 2 seconds
  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const statusData = await api.getSimulatorStatus();
        setStatus(statusData);
      } catch (err) {
        console.error('Failed to fetch simulator status:', err);
      }
    }, 2000);

    return () => clearInterval(interval);
  }, []);

  const handleStart = async () => {
    setIsLoading(true);
    setMessage('');
    
    try {
      await api.startSimulator({
        scenario,
        rate_per_min: rate,
        seed: seed ? parseInt(seed) : undefined,
      });
      setMessage('✅ Simulator started');
    } catch (err: any) {
      setMessage(`❌ Error: ${err.message}`);
    } finally {
      setIsLoading(false);
    }
  };

  const handleStop = async () => {
    setIsLoading(true);
    setMessage('');
    
    try {
      await api.stopSimulator();
      setMessage('✅ Simulator stopped');
    } catch (err: any) {
      setMessage(`❌ Error: ${err.message}`);
    } finally {
      setIsLoading(false);
    }
  };

  const handleReplay = async () => {
    if (!replayData.trim()) {
      setMessage('❌ Please paste JSONL data');
      return;
    }

    setIsLoading(true);
    setMessage('');
    
    try {
      const result = await api.replayEvents({ jsonl_data: replayData });
      setMessage(`✅ Replayed ${result.events_replayed} events → ${result.incidents_created} incidents`);
      if (result.errors.length > 0) {
        setMessage(prev => prev + `\n⚠️ ${result.errors.length} errors`);
      }
    } catch (err: any) {
      setMessage(`❌ Error: ${err.message}`);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="fixed right-0 top-[52px] h-[calc(100vh-52px)] z-40">
      {/* Toggle button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="absolute left-0 top-20 -translate-x-full bg-blue-600 text-white px-3 py-2 rounded-l-lg shadow-lg hover:bg-blue-700 transition-colors text-xs"
      >
        {isOpen ? '→' : '← Demo'}
      </button>

      {/* Panel */}
      <div
        className={`bg-white border-l border-gray-200 h-full w-96 shadow-xl transition-transform duration-300 overflow-y-auto ${
          isOpen ? 'translate-x-0' : 'translate-x-full'
        }`}
      >
        <div className="p-4 space-y-6">
          {/* Header */}
          <div>
            <h2 className="text-lg font-bold text-gray-900">Demo Controls</h2>
            <p className="text-sm text-gray-600">Event simulator and replay</p>
          </div>

          {/* Status */}
          <div className="bg-gray-50 rounded-lg p-4 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-gray-700">Status</span>
              <span className={`px-2 py-1 rounded text-xs font-medium ${
                status.running ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-800'
              }`}>
                {status.running ? '● Running' : '○ Stopped'}
              </span>
            </div>
            
            <div className="grid grid-cols-2 gap-2 text-sm">
              <div>
                <div className="text-gray-600">Events</div>
                <div className="font-mono font-bold text-gray-900">{status.events_generated}</div>
              </div>
              <div>
                <div className="text-gray-600">Incidents</div>
                <div className="font-mono font-bold text-gray-900">{status.incidents_created}</div>
              </div>
            </div>

            {status.running && status.rate_actual !== undefined && (
              <div className="text-xs text-gray-600 pt-2 border-t border-gray-200">
                Rate: {status.rate_actual.toFixed(1)}/{status.rate_target} events/min
                <br />
                Scenario: {status.scenario}
                {status.seed !== undefined && status.seed !== null && (
                  <><br />Seed: {status.seed}</>
                )}
              </div>
            )}
          </div>

          {/* Simulator controls */}
          <div className="space-y-3">
            <h3 className="text-sm font-semibold text-gray-900">Simulator</h3>
            
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Scenario
              </label>
              <select
                value={scenario}
                onChange={(e) => setScenario(e.target.value)}
                disabled={status.running || isLoading}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
              >
                <option value="quiet_shift">Quiet Shift</option>
                <option value="normal_day">Normal Day</option>
                <option value="busy_evening">Busy Evening</option>
                <option value="security_incident">Security Incident</option>
                <option value="mixed_events">Mixed Events</option>
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Rate (events/min): {rate}
              </label>
              <input
                type="range"
                min="1"
                max="60"
                value={rate}
                onChange={(e) => setRate(parseInt(e.target.value))}
                disabled={status.running || isLoading}
                className="w-full disabled:opacity-50"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Seed (optional)
              </label>
              <input
                type="number"
                value={seed}
                onChange={(e) => setSeed(e.target.value)}
                placeholder="Random"
                disabled={status.running || isLoading}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
              />
            </div>

            <div className="flex gap-2">
              <button
                onClick={handleStart}
                disabled={status.running || isLoading}
                className="flex-1 px-4 py-2 bg-green-600 text-white rounded-md text-sm font-medium hover:bg-green-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
              >
                Start
              </button>
              <button
                onClick={handleStop}
                disabled={!status.running || isLoading}
                className="flex-1 px-4 py-2 bg-red-600 text-white rounded-md text-sm font-medium hover:bg-red-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
              >
                Stop
              </button>
            </div>
          </div>

          {/* Replay controls */}
          <div className="space-y-3 pt-6 border-t border-gray-200">
            <h3 className="text-sm font-semibold text-gray-900">Replay JSONL</h3>
            
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Paste JSONL data
              </label>
              <textarea
                value={replayData}
                onChange={(e) => setReplayData(e.target.value)}
                disabled={isLoading}
                placeholder={'{"event_id":"evt_001",...}\n{"event_id":"evt_002",...}'}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-xs font-mono focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
                rows={6}
              />
            </div>

            <button
              onClick={handleReplay}
              disabled={isLoading || !replayData.trim()}
              className="w-full px-4 py-2 bg-blue-600 text-white rounded-md text-sm font-medium hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
            >
              Replay Events
            </button>
          </div>

          {/* Message */}
          {message && (
            <div className="bg-blue-50 border border-blue-200 rounded-md p-3 text-sm text-blue-900 whitespace-pre-line">
              {message}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
