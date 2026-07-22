// PatternsPage — surfaces the Phase-2 pattern engine in the Control Room:
// "what's been happening" over a window, and "which incidents was a plate near".
import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { WINDOWS as SHARED_WINDOWS } from '../components/TimeWindow';

// The shared four, plus the finer grain this page alone needs.
const WINDOWS = [
  { key: '1h', label: 'Last hour', short: '1H' },
  ...SHARED_WINDOWS,
];

export default function PatternsPage() {
  const [window, setWindow] = useState('24h');
  const [activity, setActivity] = useState<any>(null);
  const [err, setErr] = useState('');

  const [plate, setPlate] = useState('');
  const [plateResult, setPlateResult] = useState<any>(null);
  const [plateErr, setPlateErr] = useState('');
  const [plateLoading, setPlateLoading] = useState(false);

  useEffect(() => {
    setErr('');
    setActivity(null);
    api.getActivity(window).then(setActivity).catch((e) => setErr(e.message));
  }, [window]);

  const lookupPlate = async () => {
    const p = plate.trim();
    if (!p) return;
    setPlateErr(''); setPlateResult(null); setPlateLoading(true);
    try {
      setPlateResult(await api.getPlateIncidents(p, 30));
    } catch (e: any) {
      setPlateErr(e.message);
    } finally {
      setPlateLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: 24 }}>
      <h1 style={{ fontSize: 24, fontWeight: 700, marginBottom: 16 }}>Patterns</h1>

      {/* Activity window */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        {WINDOWS.map((w) => (
          <button
            key={w.key}
            onClick={() => setWindow(w.key)}
            style={{
              padding: '8px 14px', borderRadius: 8, cursor: 'pointer',
              border: '1px solid #33384a',
              background: window === w.key ? '#4f46e5' : 'transparent',
              color: window === w.key ? '#fff' : '#c7cbd6', fontWeight: 600,
            }}
          >{w.label}</button>
        ))}
      </div>

      {err && <div style={banner('#3b1d1d', '#f8b4b4')}>{err}</div>}

      {activity && (
        <div style={card}>
          <p style={{ fontSize: 15, lineHeight: 1.5, marginBottom: 14 }}>{activity.narrative}</p>
          <div style={statRow}>
            <Stat label="People sightings" value={activity.people_sightings} />
            <Stat label="Vehicle sightings" value={activity.vehicle_sightings} />
            <Stat label="Plate reads" value={activity.plate_reads} />
            <Stat label="Watchlist matches" value={activity.watchlist_matches} highlight={activity.watchlist_matches > 0} />
          </div>
          <div style={{ marginTop: 12, fontSize: 13, color: '#8b90a0' }}>
            {activity.busiest_camera && <span>Busiest camera: <b style={{ color: '#c7cbd6' }}>{activity.busiest_camera}</b>. </span>}
            {activity.busiest_hour != null && <span>Most active around {String(activity.busiest_hour).padStart(2, '0')}:00.</span>}
          </div>
        </div>
      )}

      {/* Plate co-occurrence */}
      <h2 style={{ fontSize: 18, fontWeight: 700, margin: '28px 0 10px' }}>Plate — near which incidents?</h2>
      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <input
          value={plate}
          onChange={(e) => setPlate(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && lookupPlate()}
          placeholder="e.g. N12345W"
          style={{ ...inp, flex: 1 }}
        />
        <button onClick={lookupPlate} disabled={plateLoading} style={btn}>
          {plateLoading ? 'Checking…' : 'Check'}
        </button>
      </div>
      {plateErr && <div style={banner('#3b1d1d', '#f8b4b4')}>{plateErr}</div>}
      {plateResult && (
        <div style={card}>
          <p style={{ marginBottom: plateResult.hits?.length ? 12 : 0 }}>{plateResult.summary}</p>
          {plateResult.hits?.map((h: any) => (
            <div key={h.incident_id + h.incident_ts} style={{ fontSize: 13, color: '#c7cbd6', padding: '6px 0', borderTop: '1px solid #262a38' }}>
              Incident <b>{h.incident_id}</b> at <b>{h.camera_id}</b> — {new Date(h.incident_ts).toLocaleString()} (±{Math.round(h.gap_seconds / 60)} min)
            </div>
          ))}
        </div>
      )}

      <p style={{ fontSize: 12, color: '#6b7080', marginTop: 20 }}>
        Patterns surface observed activity for review. Proximity to an incident is a lead, not involvement — a person confirms.
      </p>
    </div>
  );
}

function Stat({ label, value, highlight }: { label: string; value: number; highlight?: boolean }) {
  return (
    <div style={{ minWidth: 120 }}>
      <div style={{ fontSize: 28, fontWeight: 700, color: highlight ? '#f0a35e' : '#fff' }}>{value ?? 0}</div>
      <div style={{ fontSize: 12, color: '#8b90a0' }}>{label}</div>
    </div>
  );
}

const card: React.CSSProperties = { background: '#1a1d27', border: '1px solid #262a38', borderRadius: 12, padding: 18 };
const statRow: React.CSSProperties = { display: 'flex', gap: 28, flexWrap: 'wrap' };
const banner = (bg: string, fg: string): React.CSSProperties => ({ background: bg, color: fg, padding: '10px 14px', borderRadius: 8, marginBottom: 14, fontSize: 13 });
const inp: React.CSSProperties = { padding: '9px 12px', borderRadius: 8, border: '1px solid #33384a', background: '#12141c', color: '#e5e7eb', fontSize: 14 };
const btn: React.CSSProperties = { padding: '9px 18px', borderRadius: 8, border: 'none', background: '#4f46e5', color: '#fff', fontWeight: 600, cursor: 'pointer' };
