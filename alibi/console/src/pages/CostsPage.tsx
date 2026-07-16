import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import type { CostSummary } from '../lib/types';

const SERVICE_LABEL: Record<string, string> = {
  vision: 'Scene analysis (vision)',
  llm_text: 'Text (explainer, brief, reports)',
};

function usd(n: number): string {
  return '$' + n.toLocaleString(undefined, { minimumFractionDigits: n < 1 ? 4 : 2, maximumFractionDigits: 4 });
}

export function CostsPage() {
  const [data, setData] = useState<CostSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getCostSummary().then(setData).catch(e => setError(e.message || 'Failed to load'));
  }, []);

  if (error) return <div className="max-w-4xl mx-auto px-4 py-6 text-red-600">{error}</div>;
  if (!data) return <div className="max-w-4xl mx-auto px-4 py-6 text-gray-500">Loading…</div>;

  const services = Object.entries(data.by_service).sort((a, b) => b[1].usd - a[1].usd);
  const maxDay = Math.max(1e-9, ...data.by_day.map(d => d.usd));

  return (
    <div className="max-w-4xl mx-auto px-4 py-6">
      <h1 className="text-2xl font-semibold text-gray-900">Costs</h1>
      <p className="text-sm text-gray-500 mb-4">Estimated AI spend over the last {data.window_days} days.</p>

      <div className="bg-white shadow rounded-lg p-6 mb-6">
        <p className="text-sm text-gray-500">Estimated total</p>
        <p className="text-4xl font-semibold text-gray-900 mt-1">{usd(data.total_usd)}</p>
        <p className="text-xs text-gray-400 mt-2">{data.note}</p>
      </div>

      {/* By service */}
      <div className="bg-white shadow rounded-lg p-6 mb-6">
        <h2 className="text-lg font-medium text-gray-900 mb-3">By service</h2>
        {services.length === 0 ? (
          <p className="text-sm text-gray-500">No AI usage recorded yet in this window.</p>
        ) : (
          <table className="min-w-full text-sm">
            <thead>
              <tr className="text-left text-gray-500 border-b border-gray-100">
                <th className="py-2 pr-4 font-medium">Service</th>
                <th className="py-2 pr-4 font-medium text-right">Calls</th>
                <th className="py-2 pr-4 font-medium text-right">Tokens (in / out)</th>
                <th className="py-2 font-medium text-right">Cost</th>
              </tr>
            </thead>
            <tbody>
              {services.map(([svc, v]) => (
                <tr key={svc} className="border-b border-gray-50">
                  <td className="py-2 pr-4 text-gray-700">{SERVICE_LABEL[svc] || svc}</td>
                  <td className="py-2 pr-4 text-gray-600 text-right">{v.calls.toLocaleString()}</td>
                  <td className="py-2 pr-4 text-gray-500 text-right">{v.input_tokens.toLocaleString()} / {v.output_tokens.toLocaleString()}</td>
                  <td className="py-2 text-gray-900 text-right font-medium">{usd(v.usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Per day */}
      {data.by_day.length > 0 && (
        <div className="bg-white shadow rounded-lg p-6">
          <h2 className="text-lg font-medium text-gray-900 mb-3">Per day</h2>
          <div className="space-y-1.5">
            {data.by_day.map(d => (
              <div key={d.day} className="flex items-center gap-3 text-sm">
                <span className="w-24 text-gray-500 flex-none">{d.day}</span>
                <div className="flex-1 bg-gray-100 rounded h-4 overflow-hidden">
                  <div className="bg-indigo-500 h-4" style={{ width: `${(d.usd / maxDay) * 100}%` }} />
                </div>
                <span className="w-20 text-right text-gray-700 flex-none">{usd(d.usd)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
