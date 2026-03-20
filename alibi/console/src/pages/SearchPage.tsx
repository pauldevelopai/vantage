import { useState, useRef } from 'react';
import { api } from '../lib/api';

const THREAT_BADGE: Record<string, string> = {
  safe: 'bg-green-100 text-green-800',
  caution: 'bg-yellow-100 text-yellow-800',
  warning: 'bg-orange-100 text-orange-800',
  critical: 'bg-red-100 text-red-800',
  info: 'bg-blue-100 text-blue-800',
};

const SOURCE_BADGE: Record<string, string> = {
  camera_analysis: 'bg-blue-100 text-blue-800',
  red_flag: 'bg-red-100 text-red-800',
  intelligence: 'bg-purple-100 text-purple-800',
};

const SOURCE_LABEL: Record<string, string> = {
  camera_analysis: 'Camera',
  red_flag: 'Red Flag',
  intelligence: 'Intel',
};

interface SearchResultItem {
  source: string;
  score: number;
  timestamp: string;
  camera_id: string;
  description: string;
  snapshot_url: string | null;
  thumbnail_url: string | null;
  detected_objects: string[];
  threat_level: string;
  metadata: Record<string, any>;
}

export function SearchPage() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResultItem[]>([]);
  const [searching, setSearching] = useState(false);
  const [searched, setSearched] = useState(false);
  const [total, setTotal] = useState(0);

  // Filters
  const [sourceFilter, setSourceFilter] = useState('');
  const [hoursFilter, setHoursFilter] = useState('');
  const [threatFilter, setThreatFilter] = useState('');

  const inputRef = useRef<HTMLInputElement>(null);

  async function handleSearch(e?: React.FormEvent) {
    e?.preventDefault();
    if (!query.trim()) return;

    setSearching(true);
    setSearched(false);

    try {
      const params: any = {
        query: query.trim(),
        limit: 50,
      };
      if (sourceFilter) params.source = sourceFilter;
      if (hoursFilter) params.hours = parseInt(hoursFilter);
      if (threatFilter) params.threat_level = threatFilter;

      const data = await api.semanticSearch(params);
      setResults(data.results);
      setTotal(data.total);
    } catch (error) {
      console.error('Search failed:', error);
    } finally {
      setSearching(false);
      setSearched(true);
    }
  }

  function handleQuickSearch(q: string) {
    setQuery(q);
    // Trigger search after state update
    setTimeout(() => {
      const params: any = { query: q, limit: 50 };
      if (sourceFilter) params.source = sourceFilter;
      if (hoursFilter) params.hours = parseInt(hoursFilter);
      if (threatFilter) params.threat_level = threatFilter;

      setSearching(true);
      setSearched(false);
      api.semanticSearch(params)
        .then(data => {
          setResults(data.results);
          setTotal(data.total);
        })
        .catch(console.error)
        .finally(() => {
          setSearching(false);
          setSearched(true);
        });
    }, 0);
  }

  return (
    <div className="px-4 sm:px-6 lg:px-8 max-w-5xl">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">Search</h1>
        <p className="mt-1 text-sm text-gray-500">
          Search across all camera analyses, red flags, and intelligence using natural language
        </p>
      </div>

      {/* Search Form */}
      <form onSubmit={handleSearch} className="mb-6">
        <div className="flex gap-2">
          <div className="relative flex-1">
            <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
              <svg className="h-5 w-5 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
            </div>
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder='Try "person near gate at night" or "suspicious vehicle"...'
              className="w-full pl-10 pr-4 py-3 rounded-lg border border-gray-300 shadow-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 text-sm"
              autoFocus
            />
          </div>
          <button
            type="submit"
            disabled={searching || !query.trim()}
            className="px-6 py-3 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {searching ? (
              <>
                <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" /></svg>
                Searching...
              </>
            ) : 'Search'}
          </button>
        </div>

        {/* Filters */}
        <div className="mt-3 flex flex-wrap gap-3">
          <select
            value={sourceFilter}
            onChange={(e) => setSourceFilter(e.target.value)}
            className="rounded-md border-gray-300 text-sm py-1.5"
          >
            <option value="">All Sources</option>
            <option value="camera_analysis">Camera Analyses</option>
            <option value="red_flag">Red Flags</option>
            <option value="intelligence">Intelligence Notes</option>
          </select>

          <select
            value={hoursFilter}
            onChange={(e) => setHoursFilter(e.target.value)}
            className="rounded-md border-gray-300 text-sm py-1.5"
          >
            <option value="">All Time</option>
            <option value="1">Last Hour</option>
            <option value="6">Last 6 Hours</option>
            <option value="24">Last 24 Hours</option>
            <option value="72">Last 3 Days</option>
            <option value="168">Last 7 Days</option>
          </select>

          <select
            value={threatFilter}
            onChange={(e) => setThreatFilter(e.target.value)}
            className="rounded-md border-gray-300 text-sm py-1.5"
          >
            <option value="">Any Threat Level</option>
            <option value="caution">Caution</option>
            <option value="warning">Warning</option>
            <option value="critical">Critical</option>
          </select>
        </div>
      </form>

      {/* Quick Search Suggestions */}
      {!searched && !searching && (
        <div className="mb-8">
          <p className="text-xs text-gray-400 uppercase tracking-wider mb-3">Quick searches</p>
          <div className="flex flex-wrap gap-2">
            {[
              'person walking at night',
              'suspicious vehicle',
              'group of people',
              'delivery truck',
              'person near fence',
              'running or fleeing',
              'weapon or threat',
              'unattended bag',
            ].map(q => (
              <button
                key={q}
                onClick={() => handleQuickSearch(q)}
                className="px-3 py-1.5 text-sm bg-gray-100 text-gray-700 rounded-full hover:bg-gray-200 transition-colors"
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Results */}
      {searching && (
        <div className="text-center py-12">
          <svg className="animate-spin h-8 w-8 mx-auto text-blue-500 mb-3" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" /></svg>
          <p className="text-gray-500">Searching across all security data...</p>
        </div>
      )}

      {searched && !searching && results.length === 0 && (
        <div className="text-center py-12 bg-white rounded-lg shadow">
          <svg className="h-12 w-12 mx-auto text-gray-300 mb-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <p className="text-gray-500">No results found for "{query}"</p>
          <p className="text-sm text-gray-400 mt-1">Try different keywords or broaden your filters</p>
        </div>
      )}

      {searched && !searching && results.length > 0 && (
        <>
          <p className="text-sm text-gray-500 mb-4">
            {total} result{total !== 1 ? 's' : ''} for "{query}"
          </p>

          <div className="space-y-3">
            {results.map((result, idx) => (
              <div
                key={`${result.timestamp}-${idx}`}
                className="bg-white shadow rounded-lg p-4 flex gap-4"
              >
                {/* Thumbnail */}
                {result.thumbnail_url ? (
                  <div className="flex-shrink-0 w-20 h-16 rounded overflow-hidden bg-gray-100">
                    <img
                      src={`/api${result.thumbnail_url}`}
                      alt=""
                      className="w-full h-full object-cover"
                      onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                    />
                  </div>
                ) : (
                  <div className="flex-shrink-0 w-20 h-16 rounded bg-gray-100 flex items-center justify-center">
                    <svg className="h-6 w-6 text-gray-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                    </svg>
                  </div>
                )}

                {/* Content */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap mb-1">
                    {/* Source badge */}
                    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${SOURCE_BADGE[result.source] || 'bg-gray-100 text-gray-800'}`}>
                      {SOURCE_LABEL[result.source] || result.source}
                    </span>

                    {/* Threat badge */}
                    {result.threat_level && result.threat_level !== 'safe' && (
                      <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${THREAT_BADGE[result.threat_level] || ''}`}>
                        {result.threat_level}
                      </span>
                    )}

                    {/* Score */}
                    <span className="text-xs text-gray-400">
                      {Math.round(result.score * 100)}% match
                    </span>

                    {/* Camera ID */}
                    {result.camera_id && (
                      <span className="text-xs text-gray-400 font-mono">
                        {result.camera_id}
                      </span>
                    )}
                  </div>

                  {/* Description */}
                  <p className="text-sm text-gray-900 line-clamp-2">{result.description}</p>

                  {/* Objects & Timestamp */}
                  <div className="mt-1 flex items-center gap-3 flex-wrap">
                    {result.detected_objects.length > 0 && (
                      <div className="flex gap-1 flex-wrap">
                        {result.detected_objects.slice(0, 5).map((obj, i) => (
                          <span key={i} className="inline-flex items-center rounded px-1.5 py-0.5 text-xs bg-gray-100 text-gray-600">
                            {obj}
                          </span>
                        ))}
                        {result.detected_objects.length > 5 && (
                          <span className="text-xs text-gray-400">+{result.detected_objects.length - 5} more</span>
                        )}
                      </div>
                    )}
                    <span className="text-xs text-gray-400">
                      {new Date(result.timestamp).toLocaleString()}
                    </span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
