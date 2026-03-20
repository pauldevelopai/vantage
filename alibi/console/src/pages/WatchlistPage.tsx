import { useState, useEffect, useRef } from 'react';
import { api } from '../lib/api';
import { hasRole } from '../lib/auth';

interface WatchlistEntry {
  person_id: string;
  label: string;
  added_ts: string;
  source_ref: string;
  metadata?: Record<string, any>;
}

interface SearchCandidate {
  person_id: string;
  label: string;
  score: number;
}

export function WatchlistPage() {
  const [entries, setEntries] = useState<WatchlistEntry[]>([]);
  const [loading, setLoading] = useState(true);

  // Enroll form
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
    loadWatchlist();
  }, []);

  async function loadWatchlist() {
    try {
      const data = await api.getWatchlist();
      setEntries(data.entries || []);
    } catch (error) {
      console.error('Failed to load watchlist:', error);
    } finally {
      setLoading(false);
    }
  }

  async function handleEnroll() {
    if (!enrollFile || !personId || !label) {
      setEnrollMessage('Person ID, label, and image are required.');
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
      loadWatchlist();
    } catch (error: any) {
      setEnrollMessage(`Enrollment failed: ${error.message}`);
    } finally {
      setEnrolling(false);
    }
  }

  async function handleRemove(pid: string) {
    if (!confirm(`Remove ${pid} from watchlist?`)) return;
    try {
      await api.removeWatchlistEntry(pid);
      loadWatchlist();
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
    <div className="px-4 sm:px-6 lg:px-8">
      <div className="sm:flex sm:items-center">
        <div className="sm:flex-auto">
          <h1 className="text-2xl font-semibold text-gray-900">Watchlist</h1>
          <p className="mt-2 text-sm text-gray-700">
            Manage the face recognition watchlist. Enroll persons of interest, search by photo, and view enrolled entries.
          </p>
        </div>
      </div>

      <div className="mt-8 grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Enroll Form */}
        {isSupervisor && (
          <div className="bg-white shadow sm:rounded-lg p-6">
            <h2 className="text-lg font-medium text-gray-900 mb-4">Enroll Face</h2>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700">Person ID</label>
                <input
                  type="text"
                  value={personId}
                  onChange={(e) => setPersonId(e.target.value)}
                  className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm font-mono"
                  placeholder="e.g., SUSPECT_001"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">Name / Label</label>
                <input
                  type="text"
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                  className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
                  placeholder="e.g., John Doe"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">Source Reference</label>
                <input
                  type="text"
                  value={sourceRef}
                  onChange={(e) => setSourceRef(e.target.value)}
                  className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
                  placeholder="e.g., Case #2024-1234"
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
                {enrolling ? 'Enrolling...' : 'Enroll'}
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
              Upload a photo to check if the face appears to match anyone on the watchlist.
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
                {searching ? 'Searching...' : 'Search Watchlist'}
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
                    <p className="text-sm text-green-700">No watchlist match found.</p>
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

      {/* Enrolled Entries Table */}
      <div className="mt-8">
        <h2 className="text-lg font-medium text-gray-900 mb-4">
          Enrolled Entries ({entries.length})
        </h2>

        {loading ? (
          <div className="text-center py-12 bg-white shadow sm:rounded-lg">
            <p className="text-gray-500">Loading watchlist...</p>
          </div>
        ) : entries.length === 0 ? (
          <div className="text-center py-12 bg-white shadow sm:rounded-lg">
            <p className="text-gray-500">No entries in the watchlist.</p>
          </div>
        ) : (
          <div className="bg-white shadow overflow-hidden sm:rounded-md">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Person ID</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Label</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Source</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Added</th>
                  {isAdmin && (
                    <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Actions</th>
                  )}
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {entries.map((entry) => (
                  <tr key={entry.person_id} className="hover:bg-gray-50">
                    <td className="px-6 py-4 whitespace-nowrap text-sm font-mono text-gray-900">{entry.person_id}</td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{entry.label}</td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{entry.source_ref || '-'}</td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {new Date(entry.added_ts).toLocaleString()}
                    </td>
                    {isAdmin && (
                      <td className="px-6 py-4 whitespace-nowrap text-right text-sm">
                        <button
                          onClick={() => handleRemove(entry.person_id)}
                          className="text-red-600 hover:text-red-900 font-medium"
                        >
                          Remove
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
