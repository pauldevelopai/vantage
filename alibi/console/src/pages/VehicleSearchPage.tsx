import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { CropImg } from '../components/CropImg';
import type { TrailEntry } from '../lib/types';

interface VehicleSighting {
  sighting_id: string;
  camera_id: string;
  ts: string;
  bbox: number[];
  color: string;
  make: string;
  model: string;
  confidence: number;
  snapshot_url?: string;
  clip_url?: string;
  metadata?: Record<string, any>;
}

export function VehicleSearchPage() {
  const [plate, setPlate] = useState('');
  const [make, setMake] = useState('');
  const [model, setModel] = useState('');
  const [color, setColor] = useState('');
  const [cameraId, setCameraId] = useState('');
  const [fromTs, setFromTs] = useState('');
  const [toTs, setToTs] = useState('');

  const [results, setResults] = useState<VehicleSighting[]>([]);
  const [searching, setSearching] = useState(false);
  const [searched, setSearched] = useState(false);

  // The distinct vehicles the Overview KPI counts — loaded up front.
  const [distinct, setDistinct] = useState<any[]>([]);
  const [loadingDistinct, setLoadingDistinct] = useState(true);
  useEffect(() => {
    api.getDistinctVehicles('7d')
      .then(d => setDistinct(d.vehicles || []))
      .catch(() => setDistinct([]))
      .finally(() => setLoadingDistinct(false));
  }, []);

  // Trail state
  const [trail, setTrail] = useState<TrailEntry[]>([]);
  const [trailPlate, setTrailPlate] = useState('');
  const [trailLoading, setTrailLoading] = useState(false);

  // Surface data immediately: recent sightings load on open, no search needed.
  useEffect(() => {
    handleSearch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleSearch() {
    setSearching(true);
    setSearched(true);

    try {
      const response = await api.searchVehicles({
        plate: plate || undefined,
        make: make || undefined,
        model: model || undefined,
        color: color || undefined,
        camera_id: cameraId || undefined,
        from_ts: fromTs || undefined,
        to_ts: toTs || undefined,
      });
      
      setResults(response.sightings || []);
    } catch (error) {
      console.error('Search failed:', error);
      alert('Search failed');
    } finally {
      setSearching(false);
    }
  }

  async function handleViewTrail(plateText: string) {
    setTrailLoading(true);
    setTrailPlate(plateText);
    try {
      const data = await api.getEntityTrail('plate', plateText);
      setTrail(data.trail || []);
    } catch (error) {
      console.error('Failed to load trail:', error);
      setTrail([]);
    } finally {
      setTrailLoading(false);
    }
  }

  function handleClear() {
    setPlate('');
    setMake('');
    setModel('');
    setColor('');
    setCameraId('');
    setFromTs('');
    setToTs('');
    setResults([]);
    setSearched(false);
  }

  return (
    <div className="px-4 sm:px-6 lg:px-8">
      <div className="sm:flex sm:items-center">
        <div className="sm:flex-auto">
          <h1 className="text-2xl font-semibold text-gray-900">Vehicles</h1>
          <p className="mt-2 text-sm text-gray-700">
            The distinct vehicles your cameras have seen — then a full search over every sighting.
          </p>
        </div>
      </div>

      {/* The DISTINCT vehicles — this is what the Overview's "distinct vehicles"
          KPI counts, so landing here must show exactly those cars. */}
      <div className="mt-6 bg-white shadow sm:rounded-lg p-6">
        <div className="flex items-baseline justify-between mb-4">
          <h2 className="text-lg font-medium text-gray-900">
            Distinct vehicles{distinct.length > 0 ? ` (${distinct.length})` : ''}
          </h2>
          <span className="text-xs text-gray-500">grouped by appearance · last 7 days</span>
        </div>
        {loadingDistinct ? (
          <p className="text-sm text-gray-500">Loading…</p>
        ) : distinct.length === 0 ? (
          <p className="text-sm text-gray-500">No vehicles clustered yet.</p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {distinct.map((v: any) => (
              <div key={v.entity_id} className="rounded-lg border border-gray-200 overflow-hidden bg-white">
                <div className="aspect-video bg-gray-100">
                  {v.frame_url && v.bbox
                    ? <CropImg src={v.frame_url} alt={v.descriptor || 'vehicle'}
                               bbox={v.bbox as [number, number, number, number]} pad={0.3}
                               className="w-full h-full" />
                    : <div className="w-full h-full flex items-center justify-center text-xs text-gray-400">no photo</div>}
                </div>
                <div className="p-3">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${
                      v.owner_label ? 'bg-emerald-100 text-emerald-800'
                      : v.familiarity === 'new' ? 'bg-amber-100 text-amber-800'
                      : 'bg-gray-100 text-gray-700'}`}>
                      {v.owner_label ? 'YOURS' : String(v.familiarity || '').toUpperCase()}
                    </span>
                    <span className="text-sm font-medium text-gray-900 truncate">
                      {v.owner_label || v.descriptor || 'Unnamed vehicle'}
                    </span>
                    {v.plate && (
                      <span className="font-mono text-[11px] font-bold text-gray-800 bg-gray-100 border border-gray-300 rounded px-1.5 py-0.5 tracking-wider">
                        {v.plate}
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-xs text-gray-600">
                    Came past {v.passes ?? '—'}× over {v.days} day{v.days === 1 ? '' : 's'}
                    {v.cameras?.length > 0 && ` · ${v.cameras.join(', ')}`}
                  </p>
                  <p className="mt-0.5 text-[11px] text-gray-400">
                    last seen {v.last_seen ? new Date(v.last_seen.endsWith('Z') ? v.last_seen : v.last_seen + 'Z').toLocaleString() : '—'}
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}
        <p className="mt-3 text-[11px] text-gray-400">
          Grouped by appearance from your own cameras — continuity, never an identity claim.
          Name one on the Overview and it reads as yours everywhere.
        </p>
      </div>

      {/* Search Form */}
      <div className="mt-8 bg-white shadow sm:rounded-lg p-6">
        <h2 className="text-lg font-medium text-gray-900 mb-4">Search Criteria</h2>
        
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {/* License Plate */}
          <div className="sm:col-span-2 lg:col-span-3">
            <label htmlFor="plate" className="block text-sm font-medium text-gray-700">
              License Plate
            </label>
            <input
              type="text"
              id="plate"
              value={plate}
              onChange={(e) => setPlate(e.target.value)}
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm font-mono text-lg tracking-wider"
              placeholder="e.g., N 12345 W"
            />
            <p className="mt-1 text-xs text-gray-500">Partial match, spaces ignored. When set, overrides make/model/color filters.</p>
          </div>

          {/* Make */}
          <div>
            <label htmlFor="make" className="block text-sm font-medium text-gray-700">
              Make
            </label>
            <input
              type="text"
              id="make"
              value={make}
              onChange={(e) => setMake(e.target.value)}
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
              placeholder="e.g., Mazda"
            />
            <p className="mt-1 text-xs text-gray-500">Partial match, case-insensitive</p>
          </div>

          {/* Model */}
          <div>
            <label htmlFor="model" className="block text-sm font-medium text-gray-700">
              Model
            </label>
            <input
              type="text"
              id="model"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
              placeholder="e.g., Demio"
            />
            <p className="mt-1 text-xs text-gray-500">Partial match, case-insensitive</p>
          </div>

          {/* Color */}
          <div>
            <label htmlFor="color" className="block text-sm font-medium text-gray-700">
              Color
            </label>
            <select
              id="color"
              value={color}
              onChange={(e) => setColor(e.target.value)}
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
            >
              <option value="">Any</option>
              <option value="white">White</option>
              <option value="black">Black</option>
              <option value="gray">Gray</option>
              <option value="silver">Silver</option>
              <option value="red">Red</option>
              <option value="blue">Blue</option>
              <option value="green">Green</option>
              <option value="yellow">Yellow</option>
              <option value="orange">Orange</option>
              <option value="brown">Brown</option>
              <option value="purple">Purple</option>
              <option value="pink">Pink</option>
            </select>
            <p className="mt-1 text-xs text-gray-500">Exact color match</p>
          </div>

          {/* Camera ID */}
          <div>
            <label htmlFor="camera_id" className="block text-sm font-medium text-gray-700">
              Camera ID
            </label>
            <input
              type="text"
              id="camera_id"
              value={cameraId}
              onChange={(e) => setCameraId(e.target.value)}
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
              placeholder="e.g., cam_001"
            />
          </div>

          {/* From Timestamp */}
          <div>
            <label htmlFor="from_ts" className="block text-sm font-medium text-gray-700">
              From Date/Time
            </label>
            <input
              type="datetime-local"
              id="from_ts"
              value={fromTs}
              onChange={(e) => setFromTs(e.target.value ? new Date(e.target.value).toISOString() : '')}
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
            />
          </div>

          {/* To Timestamp */}
          <div>
            <label htmlFor="to_ts" className="block text-sm font-medium text-gray-700">
              To Date/Time
            </label>
            <input
              type="datetime-local"
              id="to_ts"
              value={toTs}
              onChange={(e) => setToTs(e.target.value ? new Date(e.target.value).toISOString() : '')}
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
            />
          </div>
        </div>

        {/* Action Buttons */}
        <div className="mt-6 flex gap-4">
          <button
            onClick={handleSearch}
            disabled={searching}
            className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50"
          >
            {searching ? 'Searching...' : 'Search'}
          </button>
          <button
            onClick={handleClear}
            className="inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
          >
            Clear
          </button>
        </div>
      </div>

      {/* Results */}
      {searched && (
        <div className="mt-8">
          <h2 className="text-lg font-medium text-gray-900 mb-4">
            Results ({results.length})
          </h2>

          {results.length === 0 ? (
            <div className="text-center py-12 bg-white shadow sm:rounded-lg">
              <p className="text-gray-500">No vehicle sightings found matching your criteria.</p>
            </div>
          ) : (
            <div className="bg-white shadow overflow-hidden sm:rounded-md">
              <ul className="divide-y divide-gray-200">
                {results.map((sighting) => (
                  <li key={sighting.sighting_id} className="px-6 py-4 hover:bg-gray-50">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center min-w-0 flex-1">
                        {/* Thumbnail */}
                        {sighting.snapshot_url && (
                          <div className="flex-shrink-0">
                            <a
                              href={sighting.snapshot_url}
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              <img
                                src={sighting.snapshot_url}
                                alt="Vehicle"
                                className="h-20 w-32 object-cover rounded border border-gray-200"
                              />
                            </a>
                          </div>
                        )}

                        {/* Details */}
                        <div className="ml-4 flex-1">
                          <div className="flex items-center flex-wrap gap-1">
                            {sighting.metadata?.plate_text && (
                              <span className="inline-flex items-center px-2.5 py-0.5 rounded text-sm font-mono font-bold bg-blue-100 text-blue-800 tracking-wider mr-2">
                                {sighting.metadata.plate_text}
                              </span>
                            )}
                            <h3 className="text-sm font-medium text-gray-900">
                              {sighting.make !== 'unknown' && sighting.model !== 'unknown'
                                ? `${sighting.make} ${sighting.model}`
                                : 'Vehicle'}
                            </h3>
                            {sighting.color !== 'unknown' && (
                              <span
                                className="ml-2 inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-800 capitalize"
                              >
                                {sighting.color}
                              </span>
                            )}
                          </div>
                          
                          <div className="mt-1 flex items-center text-sm text-gray-500">
                            <span>{sighting.camera_id}</span>
                            <span className="mx-2">•</span>
                            <span>{new Date(sighting.ts).toLocaleString()}</span>
                            <span className="mx-2">•</span>
                            <span>Confidence: {(sighting.confidence * 100).toFixed(0)}%</span>
                          </div>

                          {sighting.metadata?.color_confidence && (
                            <div className="mt-1 text-xs text-gray-400">
                              Color confidence: {(sighting.metadata.color_confidence * 100).toFixed(0)}%
                            </div>
                          )}
                        </div>
                      </div>

                      {/* Actions */}
                      <div className="ml-4 flex-shrink-0 flex gap-2">
                        {sighting.metadata?.plate_text && (
                          <button
                            onClick={() => handleViewTrail(sighting.metadata!.plate_text)}
                            className="inline-flex items-center px-3 py-2 border border-blue-300 shadow-sm text-sm leading-4 font-medium rounded-md text-blue-700 bg-blue-50 hover:bg-blue-100 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
                          >
                            View Trail
                          </button>
                        )}
                        {sighting.snapshot_url && (
                          <a
                            href={sighting.snapshot_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center px-3 py-2 border border-gray-300 shadow-sm text-sm leading-4 font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
                          >
                            View Snapshot
                          </a>
                        )}
                        {sighting.clip_url && (
                          <a
                            href={sighting.clip_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center px-3 py-2 border border-gray-300 shadow-sm text-sm leading-4 font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
                          >
                            View Clip
                          </a>
                        )}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Trail Panel */}
      {trailPlate && (
        <div className="mt-8">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-medium text-gray-900">
              Camera Trail: <span className="font-mono">{trailPlate}</span>
            </h2>
            <button
              onClick={() => { setTrailPlate(''); setTrail([]); }}
              className="text-sm text-gray-500 hover:text-gray-700"
            >
              Close
            </button>
          </div>

          {trailLoading ? (
            <div className="text-center py-8 bg-white shadow sm:rounded-lg">
              <p className="text-gray-500">Loading trail...</p>
            </div>
          ) : trail.length === 0 ? (
            <div className="text-center py-8 bg-white shadow sm:rounded-lg">
              <p className="text-gray-500">No cross-camera trail found for this plate.</p>
            </div>
          ) : (
            <div className="bg-white shadow sm:rounded-lg overflow-hidden">
              <ul className="divide-y divide-gray-200">
                {trail.map((entry, i) => (
                  <li key={i} className="px-6 py-3 flex items-center gap-4">
                    <div className="flex-shrink-0 w-8 h-8 rounded-full bg-blue-100 text-blue-800 flex items-center justify-center text-sm font-medium">
                      {i + 1}
                    </div>
                    <div>
                      <span className="font-medium text-gray-900">{entry.camera_id}</span>
                      <span className="ml-3 text-sm text-gray-500">
                        {new Date(entry.timestamp).toLocaleString()}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
