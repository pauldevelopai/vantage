import { useState, useEffect, useRef } from 'react';
import { api } from '../lib/api';
import { hasRole } from '../lib/auth';
import { CropImg } from '../components/CropImg';

/**
 * Faces — the people who belong here (renamed from "Watchlist": that read as
 * law-enforcement; this is the owner's own enrolled people).
 *
 * Every face shot is a crop of a REAL evidence frame from the owner's cameras;
 * last-seen / times-seen come from the camera sighting archive. The page gets
 * strong by USE: each enrolment (here by upload, or one click on an unknown
 * face on the Overview) makes the next sighting say a name instead of
 * "Unknown person".
 */

interface FaceEntry {
  person_id: string;
  label: string;
  added_ts: string;
  source_ref: string;
  metadata?: Record<string, any>;
  times_seen?: number;
  last_seen?: string | null;
  face?: { frame_url: string; bbox: number[] } | null;
}

interface SearchCandidate {
  person_id: string;
  label: string;
  score: number;
}

function timeAgo(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso.endsWith('Z') ? iso : iso + 'Z').getTime()) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function FacesPage({ embedded = false }: { embedded?: boolean } = {}) {
  const [entries, setEntries] = useState<FaceEntry[]>([]);
  const [loading, setLoading] = useState(true);

  // Enroll form (by upload — for people not yet caught on camera)
  const [personId, setPersonId] = useState('');
  const [label, setLabel] = useState('');
  const [sourceRef, setSourceRef] = useState('');
  const [enrollFile, setEnrollFile] = useState<File | null>(null);
  const [enrolling, setEnrolling] = useState(false);
  const [enrollMessage, setEnrollMessage] = useState('');
  const enrollFileRef = useRef<HTMLInputElement>(null);

  // Search
  const [searchFile, setSearchFile] = useState<File | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchResults, setSearchResults] = useState<SearchCandidate[] | null>(null);
  const [searchMatch, setSearchMatch] = useState(false);
  const [searchBestScore, setSearchBestScore] = useState(0);
  const searchFileRef = useRef<HTMLInputElement>(null);

  const isAdmin = hasRole('admin');
  const isSupervisor = hasRole('supervisor') || isAdmin;

  useEffect(() => {
    loadFaces();
  }, []);

  async function loadFaces() {
    try {
      const data = await api.getWatchlist();
      setEntries(data.entries || []);
    } catch (error) {
      console.error('Failed to load faces:', error);
    } finally {
      setLoading(false);
    }
  }

  async function handleEnroll() {
    if (!enrollFile || !personId || !label) {
      setEnrollMessage('Person ID, name, and photo are required.');
      return;
    }
    setEnrolling(true);
    setEnrollMessage('');
    try {
      const formData = new FormData();
      formData.append('person_id', personId);
      formData.append('label', label);
      formData.append('source_ref', sourceRef);
      formData.append('image', enrollFile);

      await api.enrollWatchlistFace(formData);
      setEnrollMessage(`Enrolled "${label}" (${personId}) successfully.`);
      setPersonId('');
      setLabel('');
      setSourceRef('');
      setEnrollFile(null);
      if (enrollFileRef.current) enrollFileRef.current.value = '';
      loadFaces();
    } catch (error: any) {
      setEnrollMessage(`Enrollment failed: ${error.message}`);
    } finally {
      setEnrolling(false);
    }
  }

  async function handleRemove(pid: string) {
    if (!confirm(`Remove ${pid} from Faces?`)) return;
    try {
      await api.removeWatchlistEntry(pid);
      loadFaces();
    } catch (error: any) {
      alert(`Remove failed: ${error.message}`);
    }
  }

  async function handleSearch() {
    if (!searchFile) return;
    setSearching(true);
    setSearchResults(null);
    try {
      const formData = new FormData();
      formData.append('image', searchFile);

      const data = await api.searchWatchlistByFace(formData);
      setSearchResults(data.candidates || []);
      setSearchMatch(data.match);
      setSearchBestScore(data.best_score || 0);
    } catch (error: any) {
      alert(`Search failed: ${error.message}`);
    } finally {
      setSearching(false);
    }
  }

  return (
    <div className={embedded ? "" : "px-4 sm:px-6 lg:px-8"}>
{!embedded &&       <div className="sm:flex sm:items-center">
        <div className="sm:flex-auto">
          <h1 className="text-2xl font-semibold text-gray-900">Faces</h1>
          <p className="mt-2 text-sm text-gray-700">
            The people who belong here. Enrolled people are named when your cameras see them;
            everyone else stays "Unknown person". Enrol from a photo below, or with one click
            on an unknown face on the Overview.
          </p>
        </div>
      </div>}

      {/* Enrolled people — face cards from real camera sightings */}
      <div className="mt-8">
        <h2 className="text-lg font-medium text-gray-900 mb-4">
          Enrolled People ({entries.length})
        </h2>

        {loading ? (
          <div className="text-center py-12 bg-white shadow sm:rounded-lg">
            <p className="text-gray-500">Loading faces…</p>
          </div>
        ) : entries.length === 0 ? (
          <div className="text-center py-12 bg-white shadow sm:rounded-lg">
            <p className="text-gray-500">No one is enrolled yet.</p>
            <p className="text-sm text-gray-400 mt-1">
              Enrol someone below, or click "Add to Faces" on an unknown face on the Overview.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
            {entries.map((entry) => (
              <div key={entry.person_id} className="bg-white shadow sm:rounded-lg overflow-hidden">
                <div className="aspect-square bg-gray-100">
                  {entry.face?.frame_url ? (
                    <CropImg src={entry.face.frame_url}
                             alt={entry.label}
                             bbox={entry.face.bbox as [number, number, number, number]}
                             pad={0.45}
                             className="w-full h-full" />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center text-xs text-gray-400 px-3 text-center">
                      not seen on camera yet
                    </div>
                  )}
                </div>
                <div className="p-3">
                  <div className="text-sm font-medium text-gray-900 truncate">{entry.label}</div>
                  <div className="text-xs text-gray-500 mt-0.5">
                    {entry.times_seen
                      ? <>seen {entry.times_seen}× · last {entry.last_seen ? timeAgo(entry.last_seen) : '—'}</>
                      : 'not seen on camera yet'}
                  </div>
                  <div className="text-[10px] text-gray-400 font-mono mt-1 truncate">{entry.person_id}</div>
                  {isAdmin && (
                    <button
                      onClick={() => handleRemove(entry.person_id)}
                      className="mt-2 text-xs text-red-600 hover:text-red-900 font-medium"
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

      <div className="mt-8 grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Enroll by upload — for people not yet caught on camera */}
        {isSupervisor && (
          <div className="bg-white shadow sm:rounded-lg p-6">
            <h2 className="text-lg font-medium text-gray-900 mb-1">Enrol from a photo</h2>
            <p className="text-sm text-gray-500 mb-4">
              For someone your cameras haven't seen yet. Once enrolled, sightings of them are named.
            </p>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700">Person ID</label>
                <input
                  type="text"
                  value={personId}
                  onChange={(e) => setPersonId(e.target.value)}
                  className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm font-mono"
                  placeholder="e.g., paul-home"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">Name</label>
                <input
                  type="text"
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                  className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
                  placeholder="e.g., Paul McNally"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">Source Reference (optional)</label>
                <input
                  type="text"
                  value={sourceRef}
                  onChange={(e) => setSourceRef(e.target.value)}
                  className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
                  placeholder="e.g., household member"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">Face Photo</label>
                <input
                  ref={enrollFileRef}
                  type="file"
                  accept="image/*"
                  onChange={(e) => setEnrollFile(e.target.files?.[0] || null)}
                  className="mt-1 block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-md file:border-0 file:text-sm file:font-medium file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100"
                />
              </div>
              <button
                onClick={handleEnroll}
                disabled={enrolling || !enrollFile || !personId || !label}
                className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-50"
              >
                {enrolling ? 'Enrolling…' : 'Enrol'}
              </button>
              {enrollMessage && (
                <p className={`text-sm ${enrollMessage.includes('failed') ? 'text-red-600' : 'text-green-600'}`}>
                  {enrollMessage}
                </p>
              )}
            </div>
          </div>
        )}

        {/* Search by Photo */}
        {isSupervisor && (
          <div className="bg-white shadow sm:rounded-lg p-6">
            <h2 className="text-lg font-medium text-gray-900 mb-4">Search by Photo</h2>
            <p className="text-sm text-gray-500 mb-4">
              Upload a photo to check if the face appears to match anyone enrolled.
            </p>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700">Photo</label>
                <input
                  ref={searchFileRef}
                  type="file"
                  accept="image/*"
                  onChange={(e) => {
                    setSearchFile(e.target.files?.[0] || null);
                    setSearchResults(null);
                  }}
                  className="mt-1 block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-md file:border-0 file:text-sm file:font-medium file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100"
                />
              </div>
              <button
                onClick={handleSearch}
                disabled={searching || !searchFile}
                className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-50"
              >
                {searching ? 'Searching…' : 'Search Faces'}
              </button>
            </div>

            {searchResults !== null && (
              <div className="mt-4">
                {searchMatch ? (
                  <div className="rounded-md bg-red-50 p-4">
                    <h3 className="text-sm font-medium text-red-800">
                      Potential Match Found (Score: {(searchBestScore * 100).toFixed(1)}%)
                    </h3>
                    <p className="mt-1 text-xs text-red-600">
                      This is a similarity score, not a positive identification. Human verification required.
                    </p>
                  </div>
                ) : (
                  <div className="rounded-md bg-green-50 p-4">
                    <p className="text-sm text-green-700">No match found.</p>
                  </div>
                )}

                {searchResults.length > 0 && (
                  <ul className="mt-3 divide-y divide-gray-200">
                    {searchResults.map((c) => (
                      <li key={c.person_id} className="py-2 flex justify-between items-center">
                        <div>
                          <span className="text-sm font-medium text-gray-900">{c.label}</span>
                          <span className="ml-2 text-xs text-gray-500 font-mono">{c.person_id}</span>
                        </div>
                        <span
                          className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                            c.score >= 0.6
                              ? 'bg-red-100 text-red-800'
                              : c.score >= 0.4
                              ? 'bg-yellow-100 text-yellow-800'
                              : 'bg-gray-100 text-gray-800'
                          }`}
                        >
                          {(c.score * 100).toFixed(1)}%
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
