import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../lib/api';
import { canPerformAction, hasRole } from '../lib/auth';
import type { IncidentDetail, IncidentExplanation } from '../lib/types';

export function IncidentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [incident, setIncident] = useState<IncidentDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [showDismissModal, setShowDismissModal] = useState(false);
  const [dismissReason, setDismissReason] = useState('');
  const [dismissNotes, setDismissNotes] = useState('');
  const [showApproveModal, setShowApproveModal] = useState(false);
  const [approveNotes, setApproveNotes] = useState('');
  const [exportPath, setExportPath] = useState<string | null>(null);
  const [explanation, setExplanation] = useState<IncidentExplanation | null>(null);
  const [explanationLoading, setExplanationLoading] = useState(false);

  useEffect(() => {
    if (id) {
      loadIncident(id);
      loadExplanation(id);
    }
  }, [id]);

  async function loadIncident(incidentId: string) {
    setLoading(true);
    try {
      const data = await api.getIncident(incidentId);
      setIncident(data);
    } catch (error) {
      console.error('Failed to load incident:', error);
    } finally {
      setLoading(false);
    }
  }

  async function loadExplanation(incidentId: string) {
    setExplanationLoading(true);
    try {
      setExplanation(await api.getIncidentExplanation(incidentId));
    } catch (error) {
      console.error('Failed to load explanation:', error);
      setExplanation(null);
    } finally {
      setExplanationLoading(false);
    }
  }

  async function handleAction(action: string) {
    if (!incident) return;

    // Check permission
    if (!canPerformAction(action)) {
      alert('You do not have permission to perform this action');
      return;
    }

    if (action === 'dismissed' && !dismissReason) {
      setShowDismissModal(true);
      return;
    }

    // Special handling for watchlist confirmation (supervisor only)
    if (action === 'confirm_watchlist_match') {
      if (!hasRole(['supervisor', 'admin'])) {
        alert('Watchlist confirmation requires supervisor role');
        return;
      }
      
      const confirmation = window.confirm(
        'CONFIRM WATCHLIST MATCH\n\n' +
        'Have you visually verified the match against the watchlist photo?\n\n' +
        'This action will be recorded in the audit log.'
      );
      
      if (!confirmation) {
        return;
      }
    }

    try {
      await api.recordDecision(incident.incident_id, {
        action_taken: action,
        operator_notes: action === 'dismissed' ? dismissNotes : `Action: ${action}`,
        was_true_positive: action !== 'dismissed',
        dismiss_reason: action === 'dismissed' ? dismissReason : undefined,
      });
      
      navigate('/incidents');
    } catch (error) {
      console.error('Failed to record decision:', error);
      alert('Failed to record decision');
    }
  }

  async function handleApprove() {
    if (!incident) return;

    try {
      await api.approveIncident(incident.incident_id, approveNotes);
      alert('Incident approved successfully');
      setShowApproveModal(false);
      // Reload incident to see updated status
      await loadIncident(incident.incident_id);
    } catch (error) {
      console.error('Failed to approve incident:', error);
      alert('Failed to approve incident');
    }
  }

  async function handleExport() {
    if (!incident) return;

    try {
      const result = await api.exportEvidence(incident.incident_id);
      setExportPath(result.export_path);
      alert(`Evidence pack exported to: ${result.export_path}`);
    } catch (error) {
      console.error('Failed to export evidence:', error);
      alert('Failed to export evidence pack');
    }
  }

  if (loading) {
    return <div className="px-4 py-8 text-center">Loading incident...</div>;
  }

  if (!incident) {
    return <div className="px-4 py-8 text-center">Incident not found</div>;
  }

  return (
    <div className="px-4 sm:px-6 lg:px-8">
      {/* Header */}
      <div className="mb-6">
        <button
          onClick={() => navigate('/incidents')}
          className="text-sm text-gray-500 hover:text-gray-700 mb-2"
        >
          ← Back to Incidents
        </button>
        <h1 className="text-2xl font-semibold text-gray-900">{incident.incident_id}</h1>
        <div className="mt-2 flex items-center gap-4">
          <span className={`inline-flex rounded-full px-3 py-1 text-sm font-semibold ${
            incident.status === 'new' ? 'bg-green-100 text-green-800' :
            incident.status === 'triage' ? 'bg-yellow-100 text-yellow-800' :
            incident.status === 'escalated' ? 'bg-red-100 text-red-800' :
            'bg-gray-100 text-gray-800'
          }`}>
            {incident.status}
          </span>
          <span className="text-sm text-gray-500">
            Created: {new Date(incident.created_ts).toLocaleString()}
          </span>
        </div>
      </div>

      {/* Hotlist Plate Match Banner */}
      {incident.events.some(e => e.event_type === 'hotlist_plate_match') && (
        <div className="mb-6 rounded-md bg-red-100 border-2 border-red-500 p-6">
          <div className="flex">
            <div className="flex-shrink-0">
              <svg className="h-8 w-8 text-red-600" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" />
              </svg>
            </div>
            <div className="ml-4 flex-1">
              <h3 className="text-lg font-bold text-red-900">🚨 POSSIBLE HOTLIST PLATE MATCH - VERIFY</h3>
              <p className="mt-2 text-sm text-red-800 font-medium">
                Automated detection suggests a possible stolen vehicle hotlist match. Verify the plate crop and full snapshot carefully before taking any action. DO NOT IMPOUND without supervisor approval.
              </p>
              {incident.events.filter(e => e.event_type === 'hotlist_plate_match').map((event, idx) => (
                <div key={idx} className="mt-4 bg-red-50 rounded p-4">
                  <div className="grid grid-cols-2 gap-4 text-sm">
                    <div>
                      <span className="font-medium text-red-900">Plate:</span>
                      <span className="ml-2 text-red-800 font-mono text-lg">{event.metadata?.plate_text}</span>
                    </div>
                    <div>
                      <span className="font-medium text-red-900">Confidence:</span>
                      <span className="ml-2 text-red-800">{(event.metadata?.ocr_confidence * 100).toFixed(1)}%</span>
                    </div>
                    <div className="col-span-2">
                      <span className="font-medium text-red-900">Reason:</span>
                      <span className="ml-2 text-red-800">{event.metadata?.hotlist_reason}</span>
                    </div>
                    {event.metadata?.hotlist_source && (
                      <div className="col-span-2">
                        <span className="font-medium text-red-900">Source:</span>
                        <span className="ml-2 text-red-800">{event.metadata.hotlist_source}</span>
                      </div>
                    )}
                  </div>
                  {event.metadata?.plate_crop_url && (
                    <div className="mt-3">
                      <a
                        href={event.metadata.plate_crop_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center text-sm font-medium text-red-700 hover:text-red-900"
                      >
                        🚗 View Plate Crop →
                      </a>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Red Light Violation Banner */}
      {incident.events.some(e => e.event_type === 'red_light_violation') && (
        <div className="mb-6 rounded-md bg-orange-100 border-2 border-orange-500 p-6">
          <div className="flex">
            <div className="flex-shrink-0">
              <svg className="h-8 w-8 text-orange-600" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-12a1 1 0 10-2 0v4a1 1 0 00.293.707l2.828 2.829a1 1 0 101.415-1.415L11 9.586V6z" clipRule="evenodd" />
              </svg>
            </div>
            <div className="ml-4 flex-1">
              <h3 className="text-lg font-bold text-orange-900">🚦 POSSIBLE RED LIGHT VIOLATION - VERIFY</h3>
              <p className="mt-2 text-sm text-orange-800 font-medium">
                Automated detection suggests a potential red light violation. Review the annotated snapshot and video clip carefully before making any decision.
              </p>
              {incident.events.filter(e => e.event_type === 'red_light_violation').map((event, idx) => (
                <div key={idx} className="mt-4 bg-orange-50 rounded p-4">
                  <div className="grid grid-cols-2 gap-4 text-sm">
                    <div>
                      <span className="font-medium text-orange-900">Light State:</span>
                      <span className="ml-2 text-orange-800">{event.metadata?.light_state?.toUpperCase()}</span>
                    </div>
                    <div>
                      <span className="font-medium text-orange-900">Confidence:</span>
                      <span className="ml-2 text-orange-800">{(event.metadata?.light_confidence * 100).toFixed(1)}%</span>
                    </div>
                    {event.metadata?.camera_location && (
                      <div className="col-span-2">
                        <span className="font-medium text-orange-900">Location:</span>
                        <span className="ml-2 text-orange-800">{event.metadata.camera_location}</span>
                      </div>
                    )}
                  </div>
                  {event.snapshot_url && (
                    <div className="mt-3">
                      <a
                        href={event.snapshot_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center text-sm font-medium text-orange-700 hover:text-orange-900"
                      >
                        📷 View Annotated Snapshot →
                      </a>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Watchlist Match Banner */}
      {incident.events.some(e => e.event_type === 'watchlist_match') && (
        <div className="mb-6 rounded-md bg-yellow-100 border-2 border-yellow-500 p-6">
          <div className="flex">
            <div className="flex-shrink-0">
              <svg className="h-8 w-8 text-yellow-600" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" />
              </svg>
            </div>
            <div className="ml-4 flex-1">
              <h3 className="text-lg font-bold text-yellow-900">⚠️ WATCHLIST MATCH - VERIFY VISUALLY</h3>
              <p className="mt-2 text-sm text-yellow-800 font-medium">
                This incident contains a possible watchlist match. Visual verification is REQUIRED before any action.
                Do NOT assume identity based on automated matching alone.
              </p>
              {incident.events.filter(e => e.event_type === 'watchlist_match').map((event, idx) => (
                <div key={idx} className="mt-4 bg-yellow-50 rounded p-4">
                  <p className="text-sm font-medium text-yellow-900 mb-2">Top Candidates:</p>
                  {event.metadata?.top_candidates?.map((candidate: any, i: number) => (
                    <div key={i} className="flex items-center justify-between py-2 border-b border-yellow-200 last:border-0">
                      <div>
                        <span className="font-mono text-sm text-yellow-900">{candidate.person_id}</span>
                        <span className="ml-3 text-sm text-yellow-800">{candidate.label}</span>
                      </div>
                      <span className="text-sm font-semibold text-yellow-900">
                        {(candidate.score * 100).toFixed(1)}% similarity
                      </span>
                    </div>
                  ))}
                  {event.metadata?.face_crop_url && (
                    <div className="mt-3">
                      <a
                        href={event.metadata.face_crop_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center text-sm font-medium text-yellow-700 hover:text-yellow-900"
                      >
                        👤 View Detected Face →
                      </a>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Plate-Vehicle Mismatch Banner */}
      {incident.events.some(e => e.event_type === 'plate_vehicle_mismatch') && (
        <div className="mb-6 rounded-md bg-red-100 border-2 border-red-500 p-6">
          <div className="flex">
            <div className="flex-shrink-0">
              <svg className="h-8 w-8 text-red-600" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" />
              </svg>
            </div>
            <div className="ml-4 flex-1">
              <h3 className="text-lg font-bold text-red-900">🚨 POSSIBLE VISUAL MISMATCH - VERIFY</h3>
              <p className="mt-2 text-sm text-red-800 font-medium">
                The observed vehicle make/model does not match the registered plate. This MAY indicate a swapped plate or data error.
                NEVER assume theft or fraud without human verification and investigation.
              </p>
              {incident.events.filter(e => e.event_type === 'plate_vehicle_mismatch').map((event, idx) => (
                <div key={idx} className="mt-4 bg-red-50 rounded p-4">
                  <div className="grid grid-cols-2 gap-4 text-sm mb-3">
                    <div className="col-span-2">
                      <span className="font-bold text-red-900">Plate:</span>
                      <span className="ml-2 font-mono text-lg text-red-900">{event.metadata?.plate_text}</span>
                      <span className="ml-2 text-red-700">({(event.metadata?.plate_confidence * 100).toFixed(1)}% conf.)</span>
                    </div>
                    <div className="col-span-2 border-t border-red-200 pt-3">
                      <div className="flex justify-between items-start">
                        <div className="flex-1">
                          <p className="font-semibold text-red-900 mb-1">Expected (Registry):</p>
                          <p className="text-red-800 text-base">
                            {event.metadata?.expected_make} {event.metadata?.expected_model}
                          </p>
                        </div>
                        <div className="flex-1 ml-6">
                          <p className="font-semibold text-red-900 mb-1">Observed (Video):</p>
                          <p className="text-red-800 text-base">
                            {event.metadata?.observed_make} {event.metadata?.observed_model}
                            <span className="ml-2 text-sm text-red-700">({(event.metadata?.observed_confidence * 100).toFixed(1)}% conf.)</span>
                          </p>
                        </div>
                      </div>
                    </div>
                    <div className="col-span-2 border-t border-red-200 pt-3">
                      <span className="font-medium text-red-900">Mismatch Score:</span>
                      <span className="ml-2 text-red-800 font-bold">{(event.metadata?.mismatch_score * 100).toFixed(1)}%</span>
                      {event.metadata?.explanation && (
                        <p className="mt-1 text-sm text-red-700 italic">{event.metadata.explanation}</p>
                      )}
                    </div>
                  </div>
                  
                  {/* Evidence Links */}
                  <div className="flex gap-3 flex-wrap mt-3 pt-3 border-t border-red-200">
                    {event.metadata?.plate_crop_url && (
                      <a
                        href={event.metadata.plate_crop_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center text-sm font-medium text-red-700 hover:text-red-900 underline"
                      >
                        📄 View Plate Crop
                      </a>
                    )}
                    {event.metadata?.vehicle_crop_url && (
                      <a
                        href={event.metadata.vehicle_crop_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center text-sm font-medium text-red-700 hover:text-red-900 underline"
                      >
                        🚗 View Vehicle Crop
                      </a>
                    )}
                    {event.metadata?.annotated_snapshot_url && (
                      <a
                        href={event.metadata.annotated_snapshot_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center text-sm font-medium text-red-700 hover:text-red-900 underline font-bold"
                      >
                        📷 View Annotated Snapshot (Both) →
                      </a>
                    )}
                  </div>
                  
                  <div className="mt-3 pt-3 border-t border-red-200 bg-red-100 rounded p-3">
                    <p className="text-sm font-bold text-red-900">⚠️ DO NOT IMPOUND OR SEIZE without supervisor approval and investigation</p>
                    <p className="text-xs text-red-700 mt-1">False positives can occur due to OCR errors, classifier mistakes, or registry data issues.</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Validation Violations */}
      {incident.validation && incident.validation.violations.length > 0 && (
        <div className="mb-6 rounded-md bg-red-50 p-4">
          <div className="flex">
            <div className="flex-shrink-0">
              <svg className="h-5 w-5 text-red-400" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.28 7.22a.75.75 0 00-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 101.06 1.06L10 11.06l1.72 1.72a.75.75 0 101.06-1.06L11.06 10l1.72-1.72a.75.75 0 00-1.06-1.06L10 8.94 8.28 7.22z" clipRule="evenodd" />
              </svg>
            </div>
            <div className="ml-3">
              <h3 className="text-sm font-medium text-red-800">Validation Violations</h3>
              <div className="mt-2 text-sm text-red-700">
                <ul className="list-disc space-y-1 pl-5">
                  {incident.validation.violations.map((v, i) => (
                    <li key={i}>{v}</li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        </div>
      )}

      {incident.validation && incident.validation.warnings.length > 0 && (
        <div className="mb-6 rounded-md bg-yellow-50 p-4">
          <div className="flex">
            <div className="flex-shrink-0">
              <svg className="h-5 w-5 text-yellow-400" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" />
              </svg>
            </div>
            <div className="ml-3">
              <h3 className="text-sm font-medium text-yellow-800">Warnings</h3>
              <div className="mt-2 text-sm text-yellow-700">
                <ul className="list-disc space-y-1 pl-5">
                  {incident.validation.warnings.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Events Timeline (Replay Timeline) */}
        <div className="bg-white shadow rounded-lg p-6">
          <h2 className="text-lg font-medium text-gray-900 mb-4">Replay Timeline</h2>
          <p className="text-sm text-gray-600 mb-4">Ordered events with exact ingestion times</p>
          <div className="space-y-4">
            {incident.events.map((event) => (
              <div key={event.event_id} className="border-l-2 border-blue-300 pl-4 relative">
                <div className="absolute -left-2 top-0 w-3 h-3 rounded-full bg-blue-500"></div>
                <div className="flex justify-between items-start">
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <p className="font-medium text-gray-900">{event.event_type}</p>
                      <span className="text-xs text-gray-400 font-mono">#{event.event_id}</span>
                    </div>
                    <p className="text-xs text-gray-500 mt-1 font-mono">
                      🕐 {new Date(event.ts).toLocaleString()}
                    </p>
                    <p className="text-sm text-gray-500 mt-1">
                      📹 {event.camera_id} • 📍 {event.zone_id}
                    </p>
                    <p className="text-sm text-gray-600 mt-1">
                      Confidence: {(event.confidence * 100).toFixed(0)}% • 
                      Severity: {event.severity}/5
                    </p>
                    {event.metadata && Object.keys(event.metadata).length > 0 && (
                      <details className="mt-2">
                        <summary className="text-xs text-gray-500 cursor-pointer hover:text-gray-700">
                          View metadata
                        </summary>
                        <pre className="mt-1 text-xs bg-gray-50 p-2 rounded overflow-x-auto max-h-32">
                          {JSON.stringify(event.metadata, null, 2)}
                        </pre>
                      </details>
                    )}
                  </div>
                </div>
                {(event.clip_url || event.snapshot_url) && (
                  <div className="mt-2 flex gap-3">
                    {event.clip_url && (
                      <a href={event.clip_url} target="_blank" rel="noopener noreferrer" className="text-sm text-blue-600 hover:text-blue-800 font-medium">
                        📹 View Clip →
                      </a>
                    )}
                    {event.snapshot_url && (
                      <a href={event.snapshot_url} target="_blank" rel="noopener noreferrer" className="text-sm text-blue-600 hover:text-blue-800 font-medium">
                        📷 View Snapshot →
                      </a>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Incident Plan & Alert */}
        <div className="space-y-6">
          {/* Why flagged — grounded, cited, human-in-the-loop explainer */}
          {(explanationLoading || explanation) && (
            <div className="bg-white shadow rounded-lg p-6 border-l-4 border-indigo-400">
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-lg font-medium text-gray-900">Why was this flagged?</h2>
                {explanation && (
                  <span className="text-[10px] uppercase tracking-wider text-gray-400" title="How the explanation was phrased">
                    {explanation.method}
                  </span>
                )}
              </div>

              {explanationLoading && !explanation && (
                <p className="text-sm text-gray-500">Generating explanation…</p>
              )}

              {explanation && (
                <>
                  <p className="text-sm text-gray-800 whitespace-pre-wrap">{explanation.rationale}</p>

                  {explanation.reasons.length > 0 && (
                    <ul className="mt-4 space-y-2">
                      {explanation.reasons.map((r, i) => (
                        <li key={i} className="flex gap-2 text-sm">
                          <span className="mt-0.5 inline-block whitespace-nowrap rounded bg-indigo-50 px-2 py-0.5 text-[11px] font-medium text-indigo-700">
                            {r.factor}
                          </span>
                          <span className="text-gray-700">{r.detail}</span>
                        </li>
                      ))}
                    </ul>
                  )}

                  <p className="mt-4 text-xs italic text-gray-400">{explanation.disclaimer}</p>
                </>
              )}
            </div>
          )}

          {incident.plan && (
            <div className="bg-white shadow rounded-lg p-6">
              <h2 className="text-lg font-medium text-gray-900 mb-4">Incident Plan</h2>
              <dl className="space-y-3">
                <div>
                  <dt className="text-sm font-medium text-gray-500">Summary</dt>
                  <dd className="mt-1 text-sm text-gray-900">{incident.plan.summary}</dd>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <dt className="text-sm font-medium text-gray-500">Severity</dt>
                    <dd className="mt-1">
                      <span className={`inline-flex rounded px-2 py-1 text-sm font-semibold ${
                        incident.plan.severity >= 4 ? 'bg-red-100 text-red-800' :
                        incident.plan.severity >= 3 ? 'bg-orange-100 text-orange-800' :
                        'bg-gray-100 text-gray-800'
                      }`}>
                        {incident.plan.severity}/5
                      </span>
                    </dd>
                  </div>
                  <div>
                    <dt className="text-sm font-medium text-gray-500">Confidence</dt>
                    <dd className="mt-1 text-sm text-gray-900">
                      {(incident.plan.confidence * 100).toFixed(0)}%
                    </dd>
                  </div>
                </div>
                <div>
                  <dt className="text-sm font-medium text-gray-500">Recommended Action</dt>
                  <dd className="mt-1">
                    <span className="inline-flex rounded-full bg-blue-100 px-3 py-1 text-sm font-semibold text-blue-800">
                      {incident.plan.recommended_next_step}
                    </span>
                    {incident.plan.requires_human_approval && (
                      <span className="ml-2 inline-flex rounded-full bg-yellow-100 px-3 py-1 text-sm font-semibold text-yellow-800">
                        Requires Approval
                      </span>
                    )}
                  </dd>
                </div>
                {incident.plan.uncertainty_notes && (
                  <div>
                    <dt className="text-sm font-medium text-gray-500">Notes</dt>
                    <dd className="mt-1 text-sm text-gray-900">{incident.plan.uncertainty_notes}</dd>
                  </div>
                )}
                {incident.plan.action_risk_flags.length > 0 && (
                  <div>
                    <dt className="text-sm font-medium text-gray-500">Risk Flags</dt>
                    <dd className="mt-1">
                      {incident.plan.action_risk_flags.map((flag, i) => (
                        <span key={i} className="inline-flex rounded-full bg-red-100 px-2 py-1 text-xs font-semibold text-red-800 mr-2">
                          {flag}
                        </span>
                      ))}
                    </dd>
                  </div>
                )}
              </dl>
            </div>
          )}

          {incident.alert && (
            <div className="bg-white shadow rounded-lg p-6">
              <h2 className="text-lg font-medium text-gray-900 mb-4">Alert Message</h2>
              <div className="space-y-3">
                <div>
                  <h3 className="font-medium text-gray-900">{incident.alert.title}</h3>
                  <p className="mt-2 text-sm text-gray-700 whitespace-pre-wrap">{incident.alert.body}</p>
                </div>
                {incident.alert.operator_actions.length > 0 && (
                  <div>
                    <h4 className="text-sm font-medium text-gray-500 mb-2">Operator Actions:</h4>
                    <ul className="list-disc list-inside text-sm text-gray-700 space-y-1">
                      {incident.alert.operator_actions.map((action, i) => (
                        <li key={i}>{action}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {incident.alert.disclaimer && (
                  <div className="mt-3 rounded-md bg-yellow-50 p-3">
                    <p className="text-sm text-yellow-800">{incident.alert.disclaimer}</p>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Action Buttons */}
      <div className="mt-8 flex justify-between items-center">
        <div className="flex gap-3">
          {exportPath && (
            <div className="text-sm text-gray-600 bg-green-50 px-4 py-2 rounded-md">
              Evidence exported: <code className="text-xs bg-green-100 px-2 py-1 rounded">{exportPath}</code>
            </div>
          )}
        </div>
        <div className="flex gap-3">
          {/* Export Evidence (all roles) */}
          <button
            onClick={handleExport}
            className="px-4 py-2 bg-purple-600 text-white rounded-md hover:bg-purple-700 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:ring-offset-2"
          >
            Export Evidence
          </button>

          {/* Confirm Watchlist Match (supervisor only) */}
          {hasRole(['supervisor', 'admin']) && incident.events.some(e => e.event_type === 'watchlist_match') && (
            <button
              onClick={() => handleAction('confirm_watchlist_match')}
              className="px-4 py-2 bg-orange-600 text-white rounded-md hover:bg-orange-700 focus:outline-none focus:ring-2 focus:ring-orange-500 focus:ring-offset-2"
            >
              Confirm Match (Supervisor)
            </button>
          )}

          {/* Approve (supervisor only) */}
          {hasRole(['supervisor', 'admin']) && incident.plan?.requires_human_approval && (
            <button
              onClick={() => setShowApproveModal(true)}
              className="px-4 py-2 bg-yellow-600 text-white rounded-md hover:bg-yellow-700 focus:outline-none focus:ring-2 focus:ring-yellow-500 focus:ring-offset-2"
            >
              Approve
            </button>
          )}

          {/* Confirm (operator+) */}
          {canPerformAction('confirm') && (
            <button
              onClick={() => handleAction('confirmed')}
              className="px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-2"
            >
              Confirm
            </button>
          )}

          {/* Dismiss (operator+) */}
          {canPerformAction('dismiss') && (
            <button
              onClick={() => setShowDismissModal(true)}
              className="px-4 py-2 bg-gray-600 text-white rounded-md hover:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-gray-500 focus:ring-offset-2"
            >
              Dismiss
            </button>
          )}

          {/* Escalate (supervisor+) */}
          {canPerformAction('escalate') && (
            <button
              onClick={() => handleAction('escalated')}
              className="px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2"
            >
              Escalate
            </button>
          )}

          {/* Close (operator+) */}
          {canPerformAction('close') && (
            <button
              onClick={() => handleAction('closed')}
              className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
            >
              Close
            </button>
          )}
        </div>
      </div>

      {/* Dismiss Modal */}
      {showDismissModal && (
        <div className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 max-w-md w-full">
            <h3 className="text-lg font-medium text-gray-900 mb-4">Dismiss Incident</h3>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Dismiss Reason <span className="text-red-500">*</span>
                </label>
                <select
                  value={dismissReason}
                  onChange={(e) => setDismissReason(e.target.value)}
                  className="w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
                >
                  <option value="">Select reason...</option>
                  <option value="false_positive_motion">False Positive - Motion</option>
                  <option value="normal_behavior">Normal Behavior</option>
                  <option value="camera_fault">Camera Fault</option>
                  <option value="weather">Weather</option>
                  <option value="unknown">Unknown</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Notes (optional)
                </label>
                <textarea
                  value={dismissNotes}
                  onChange={(e) => setDismissNotes(e.target.value)}
                  rows={3}
                  className="w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
                  placeholder="Additional details..."
                />
              </div>
              <div className="flex justify-end gap-3">
                <button
                  onClick={() => setShowDismissModal(false)}
                  className="px-4 py-2 bg-gray-100 text-gray-700 rounded-md hover:bg-gray-200"
                >
                  Cancel
                </button>
                <button
                  onClick={() => {
                    setShowDismissModal(false);
                    handleAction('dismissed');
                  }}
                  disabled={!dismissReason}
                  className="px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
                >
                  Dismiss
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Approve Modal (Supervisor only) */}
      {showApproveModal && (
        <div className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 max-w-md w-full">
            <h3 className="text-lg font-medium text-gray-900 mb-4">Approve Incident</h3>
            <p className="text-sm text-gray-600 mb-4">
              This action will authorize the recommended next step for this incident.
            </p>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Approval Notes (optional)
                </label>
                <textarea
                  value={approveNotes}
                  onChange={(e) => setApproveNotes(e.target.value)}
                  rows={3}
                  className="w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
                  placeholder="Reason for approval or additional context..."
                />
              </div>
              <div className="flex justify-end gap-3">
                <button
                  onClick={() => setShowApproveModal(false)}
                  className="px-4 py-2 bg-gray-100 text-gray-700 rounded-md hover:bg-gray-200"
                >
                  Cancel
                </button>
                <button
                  onClick={handleApprove}
                  className="px-4 py-2 bg-yellow-600 text-white rounded-md hover:bg-yellow-700"
                >
                  Approve
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
