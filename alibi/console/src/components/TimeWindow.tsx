/**
 * How far back the page is looking — the same four choices everywhere.
 *
 * Overview, People, Vehicles and Patterns each had their own idea of a time
 * range (or none at all, in People's case, which was stuck on 7 days). One
 * control, one vocabulary, matching alibi/time_window.py on the server.
 *
 * "All" applies no cutoff. It shows everything still held — which is not the
 * same as everything that ever happened, because stores prune. Where that
 * distinction matters, say so next to the data, not in the button.
 */

export type Win = '24h' | '7d' | '30d' | 'all';

export const WINDOWS: { key: Win; short: string; label: string }[] = [
  { key: '24h', short: '24H', label: 'Last 24 hours' },
  { key: '7d', short: '7D', label: 'Last 7 days' },
  { key: '30d', short: '30D', label: 'Last 30 days' },
  { key: 'all', short: 'All', label: 'All time' },
];

/** The period, named for a human — for headings and empty states. */
export function windowLabel(w: Win): string {
  return WINDOWS.find(x => x.key === w)?.label ?? 'Last 24 hours';
}

/** Lower-case fragment that reads inside a sentence ("nothing seen in the last 24 hours"). */
export function windowPhrase(w: Win): string {
  return w === 'all' ? 'at any point on record' : windowLabel(w).toLowerCase();
}

export function TimeWindow({ value, onChange, className = '' }: {
  value: Win;
  onChange: (w: Win) => void;
  className?: string;
}) {
  return (
    <div role="group" aria-label="Time period"
         className={`inline-flex rounded-md border border-gray-300 dark:border-gray-700 overflow-hidden ${className}`}>
      {WINDOWS.map(w => (
        <button key={w.key} onClick={() => onChange(w.key)}
                aria-pressed={value === w.key}
                title={w.label}
                className={`px-2.5 py-1 text-xs font-medium transition ${
                  value === w.key
                    ? 'bg-indigo-600 text-white'
                    : 'bg-transparent text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
                }`}>
          {w.short}
        </button>
      ))}
    </div>
  );
}
