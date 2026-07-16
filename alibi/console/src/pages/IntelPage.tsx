import { useEffect, useState } from 'react';
import { api } from '../lib/api';

type Data = Awaited<ReturnType<typeof api.getIntelligenceData>>;

const DOMAIN_LABEL: Record<string, string> = {
  places_context: 'Area & crime context',
  detection_reference: 'Detection reference',
};

export function IntelPage() {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getIntelligenceData().then(setData).catch(e => setError(e.message || 'Failed to load'));
  }, []);

  if (error) return <div className="max-w-4xl mx-auto px-4 py-6 text-red-600">{error}</div>;
  if (!data) return <div className="max-w-4xl mx-auto px-4 py-6 text-gray-500">Loading…</div>;

  return (
    <div className="max-w-4xl mx-auto px-4 py-6">
      <h1 className="text-2xl font-semibold text-gray-900">External intelligence</h1>
      <p className="text-sm text-gray-500 mb-4">
        Non-personal crime, area, and reference data the engine harvests to give context to what your cameras see.
      </p>

      <div className="rounded-lg bg-amber-50 border border-amber-200 p-3 mb-6 text-sm text-amber-900">
        <span className="font-medium">Data boundary:</span> {data.boundary}
      </div>

      {/* What we harvest */}
      <div className="bg-white shadow rounded-lg p-6 mb-6">
        <h2 className="text-lg font-medium text-gray-900 mb-1">What we harvest</h2>
        <p className="text-sm text-gray-500 mb-3">Sources the engine is configured to collect from, on a schedule.</p>
        <div className="divide-y divide-gray-100">
          {data.sources.map(s => (
            <div key={s.source_id} className="py-2.5">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-medium text-gray-900 text-sm">{s.source_id}</span>
                <span className="text-xs px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-700">{DOMAIN_LABEL[s.domain] || s.domain}</span>
                <span className="text-xs text-gray-400">kept {s.retention_days}d</span>
              </div>
              <p className="text-sm text-gray-600 mt-0.5">{s.description}</p>
            </div>
          ))}
        </div>
      </div>

      {/* What's live now */}
      <div className="bg-white shadow rounded-lg p-6">
        <h2 className="text-lg font-medium text-gray-900 mb-1">In the engine now</h2>
        <p className="text-sm text-gray-500 mb-3">
          {data.stats.total_live_records} live record{data.stats.total_live_records === 1 ? '' : 's'}.
          {data.stats.total_live_records === 0 && ' Nothing harvested yet — the scheduled refresh populates this.'}
        </p>
        {data.records.length > 0 && (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="text-left text-gray-500 border-b border-gray-100">
                  <th className="py-2 pr-4 font-medium">Source</th>
                  <th className="py-2 pr-4 font-medium">Detail</th>
                  <th className="py-2 pr-4 font-medium">Ingested</th>
                </tr>
              </thead>
              <tbody>
                {data.records.map((r, i) => (
                  <tr key={i} className="border-b border-gray-50">
                    <td className="py-2 pr-4 text-gray-700 whitespace-nowrap">{r.source_id}</td>
                    <td className="py-2 pr-4 text-gray-600">{summarisePayload(r.payload)}</td>
                    <td className="py-2 pr-4 text-gray-400 whitespace-nowrap">{new Date(r.ingested_at).toLocaleDateString()}</td>
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

function summarisePayload(p: Record<string, any>): string {
  if (!p) return '';
  if (p.area && p.count != null) return `${p.area}: ${p.count} ${p.crime_category || 'incidents'}${p.period ? ` (${p.period})` : ''}`;
  if (p.place_name) return `${p.place_name}${p.category ? ` — ${p.category}` : ''}`;
  const keys = Object.keys(p).slice(0, 3);
  return keys.map(k => `${k}: ${p[k]}`).join(' · ');
}
