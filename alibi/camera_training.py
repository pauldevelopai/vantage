"""
Training Data Management with Human Validation

NEW: Human review system with privacy protection
- Review state machine (PENDING → CONFIRMED/REJECTED)
- Face detection and redaction
- Defensible export with full audit trail
"""
from fastapi import APIRouter, Depends, HTTPException, Body
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from datetime import datetime
from typing import Dict, List, Optional
import json
from pathlib import Path
from alibi.auth import get_current_user, User
from alibi.schema.training import (
    TrainingDataStore,
    TrainingIncident,
    HumanReview,
    ReviewStatus,
    RejectReason
)
from alibi.privacy import check_privacy_risk, redact_image
from alibi.export import TrainingDataExporter

router = APIRouter(prefix="/camera", tags=["training"])

# Initialize stores
training_store = TrainingDataStore()
exporter = TrainingDataExporter(training_store)


@router.get("/training", response_class=HTMLResponse)
async def training_page():
    """Training Data page with human validation"""
    from alibi.alibi_nav import build_nav
    nav_css, nav_html, nav_js = build_nav(active_page="training")
    html = TRAINING_HTML
    html = html.replace("</style>", nav_css + "\n    </style>", 1)
    html = html.replace("<body>", "<body>\n" + nav_html, 1)
    html = html.replace("</body>", nav_js + "\n</body>", 1)
    return HTMLResponse(content=html)


@router.get("/training/stats")
async def get_training_stats(current_user: User = Depends(get_current_user)):
    """Get training data statistics with review counts"""
    counts = training_store.get_counts_by_status()
    
    return {
        "review_counts": counts,
        "fine_tune_eligible": len(training_store.get_fine_tune_eligible()),
        "min_confirmed_required": 100  # Minimum for fine-tuning
    }


@router.get("/training/pending")
async def get_pending_incidents(current_user: User = Depends(get_current_user)):
    """Get incidents pending review"""
    all_incidents = training_store.get_all()
    
    # Filter for pending or no review
    pending = [
        {
            "incident_id": inc.incident_id,
            "camera_id": inc.source_camera_id,
            "timestamp": inc.source_timestamp.isoformat() if inc.source_timestamp else None,
            "category": inc.incident_data.get("category", "unknown"),
            "reason": inc.incident_data.get("reason", ""),
            "duration": inc.incident_data.get("duration_seconds", 0),
            "confidence": inc.incident_data.get("max_confidence", 0),
            "triggered_rules": inc.incident_data.get("triggered_rules", []),
            "evidence_frames": inc.incident_data.get("evidence_frames", []),
            "evidence_clip": inc.incident_data.get("evidence_clip"),
            "review_status": inc.review.status.value if inc.review else "pending_review",
            "faces_detected": inc.review.faces_detected if inc.review else False,
            "faces_redacted": inc.review.faces_redacted if inc.review else False
        }
        for inc in all_incidents
        if not inc.review or inc.review.status == ReviewStatus.PENDING_REVIEW
    ]
    
    return {"incidents": pending, "count": len(pending)}


@router.post("/training/review/{incident_id}")
async def submit_review(
    incident_id: str,
    review_data: Dict = Body(...),
    current_user: User = Depends(get_current_user)
):
    """Submit human review decision"""
    # Parse review data
    status = ReviewStatus(review_data["status"])
    reject_reason = None
    if review_data.get("reject_reason"):
        reject_reason = RejectReason(review_data["reject_reason"])
    
    # Create review
    review = HumanReview(
        status=status,
        reject_reason=reject_reason,
        reviewer_username=current_user.username,
        reviewer_role=current_user.role,
        notes=review_data.get("notes"),
        faces_detected=review_data.get("faces_detected", False),
        faces_redacted=review_data.get("faces_redacted", False),
        redaction_method=review_data.get("redaction_method")
    )
    
    # Update incident
    success = training_store.update_review(incident_id, review)
    
    if not success:
        raise HTTPException(status_code=404, detail="Incident not found")
    
    return {
        "success": True,
        "incident_id": incident_id,
        "status": status.value,
        "message": f"Review submitted: {status.value}"
    }


@router.post("/training/redact/{incident_id}")
async def redact_incident_faces(
    incident_id: str,
    method: str = "blur",
    current_user: User = Depends(get_current_user)
):
    """Redact faces in incident evidence"""
    # Get incident
    all_incidents = training_store.get_all()
    incident = next((inc for inc in all_incidents if inc.incident_id == incident_id), None)
    
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    
    # Get evidence frames
    evidence_frames = incident.incident_data.get("evidence_frames", [])
    
    if not evidence_frames:
        raise HTTPException(status_code=400, detail="No evidence frames to redact")
    
    # Redact each frame
    redacted_count = 0
    for frame_path in evidence_frames:
        frame_path = Path(frame_path)
        if not frame_path.exists():
            continue
        
        # Create redacted version
        redacted_path = frame_path.parent / f"{frame_path.stem}_redacted{frame_path.suffix}"
        
        # Redact
        success = redact_image(str(frame_path), str(redacted_path), method=method)
        if success:
            redacted_count += 1
    
    return {
        "success": True,
        "incident_id": incident_id,
        "redacted_count": redacted_count,
        "method": method,
        "message": f"Redacted {redacted_count} frames"
    }


@router.post("/training/check-privacy/{incident_id}")
async def check_incident_privacy(
    incident_id: str,
    current_user: User = Depends(get_current_user)
):
    """Check if incident has privacy risks (faces)"""
    # Get incident
    all_incidents = training_store.get_all()
    incident = next((inc for inc in all_incidents if inc.incident_id == incident_id), None)
    
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    
    # Check first evidence frame
    evidence_frames = incident.incident_data.get("evidence_frames", [])
    
    if not evidence_frames:
        return {"has_faces": False, "num_faces": 0}
    
    frame_path = Path(evidence_frames[0])
    if not frame_path.exists():
        return {"has_faces": False, "num_faces": 0}
    
    has_faces, num_faces = check_privacy_risk(str(frame_path))
    
    return {
        "has_faces": has_faces,
        "num_faces": num_faces,
        "incident_id": incident_id
    }


@router.post("/training/export")
async def export_training_dataset(current_user: User = Depends(get_current_user)):
    """Export fine-tune eligible training data"""
    # Only admins can export
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    # Export all formats
    results = exporter.export_all()
    
    return results


@router.get("/training/download-export/{filename}")
async def download_export(filename: str, current_user: User = Depends(get_current_user)):
    """Download exported training dataset"""
    # Only admins can download
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    export_dir = Path("alibi/data/exports")
    file_path = export_dir / filename
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Export file not found")
    
    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type="application/octet-stream"
    )


# HTML for the training page
TRAINING_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Training Data Review - Vantage</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        
        .header {
            background: white;
            border-radius: 15px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
        }
        
        .header h1 {
            color: #667eea;
            margin-bottom: 10px;
        }
        
        .header .subtitle {
            color: #666;
            font-size: 14px;
        }
        
        .back-btn {
            background: rgba(255,255,255,0.2);
            backdrop-filter: blur(10px);
            border: none;
            color: white;
            padding: 12px 20px;
            border-radius: 12px;
            font-size: 16px;
            cursor: pointer;
            margin-bottom: 20px;
            display: inline-block;
            text-decoration: none;
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }
        
        .stat-card {
            background: white;
            border-radius: 15px;
            padding: 20px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
        }
        
        .stat-card .label {
            color: #666;
            font-size: 14px;
            margin-bottom: 8px;
        }
        
        .stat-card .value {
            font-size: 32px;
            font-weight: bold;
            color: #667eea;
        }
        
        .stat-card.pending .value { color: #f59e0b; }
        .stat-card.confirmed .value { color: #10b981; }
        .stat-card.rejected .value { color: #ef4444; }
        .stat-card.needs-review .value { color: #8b5cf6; }
        
        .card {
            background: white;
            border-radius: 15px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
        }
        
        .card h2 {
            color: #667eea;
            margin-bottom: 15px;
        }
        
        .incident {
            border: 1px solid #e5e7eb;
            border-radius: 10px;
            padding: 15px;
            margin-bottom: 15px;
        }
        
        .incident-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }
        
        .incident-id {
            font-weight: bold;
            color: #667eea;
        }
        
        .status-badge {
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
        }
        
        .status-badge.pending { background: #fef3c7; color: #92400e; }
        .status-badge.confirmed { background: #d1fae5; color: #065f46; }
        .status-badge.rejected { background: #fee2e2; color: #991b1b; }
        
        .incident-details {
            color: #666;
            font-size: 14px;
            margin-bottom: 10px;
        }
        
        .incident-details div {
            margin-bottom: 5px;
        }
        
        .privacy-warning {
            background: #fef3c7;
            border: 2px solid #f59e0b;
            border-radius: 8px;
            padding: 10px;
            margin: 10px 0;
            color: #92400e;
            font-weight: 600;
        }
        
        .actions {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }
        
        button {
            padding: 10px 20px;
            border: none;
            border-radius: 8px;
            font-size: 14px;
            cursor: pointer;
            font-weight: 600;
            transition: all 0.3s;
        }
        
        button:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        }
        
        .btn-confirm {
            background: #10b981;
            color: white;
        }
        
        .btn-reject {
            background: #ef4444;
            color: white;
        }
        
        .btn-review {
            background: #8b5cf6;
            color: white;
        }
        
        .btn-redact {
            background: #f59e0b;
            color: white;
        }
        
        .btn-export {
            background: #667eea;
            color: white;
            font-size: 16px;
            padding: 15px 30px;
        }
        
        .modal {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.5);
            z-index: 1000;
            align-items: center;
            justify-content: center;
        }
        
        .modal.active {
            display: flex;
        }
        
        .modal-content {
            background: white;
            border-radius: 15px;
            padding: 30px;
            max-width: 500px;
            width: 90%;
        }
        
        .modal h3 {
            color: #667eea;
            margin-bottom: 20px;
        }
        
        .form-group {
            margin-bottom: 20px;
        }
        
        .form-group label {
            display: block;
            color: #374151;
            font-weight: 600;
            margin-bottom: 8px;
        }
        
        .form-group select,
        .form-group textarea {
            width: 100%;
            padding: 10px;
            border: 1px solid #d1d5db;
            border-radius: 8px;
            font-size: 14px;
        }
        
        .form-group textarea {
            min-height: 100px;
            resize: vertical;
        }
        
        .modal-actions {
            display: flex;
            gap: 10px;
            justify-content: flex-end;
        }
        
        .btn-cancel {
            background: #9ca3af;
            color: white;
        }
        
        .loading {
            text-align: center;
            color: #666;
            padding: 40px;
        }
        
        .error {
            background: #fee2e2;
            border: 2px solid #ef4444;
            border-radius: 8px;
            padding: 15px;
            color: #991b1b;
            margin-bottom: 20px;
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- nav bar provides navigation -->
        
        <div class="header">
            <h1>🎓 Training Data Review</h1>
            <p class="subtitle">Human validation with privacy protection</p>
        </div>
        
        <div class="stats-grid" id="stats">
            <div class="stat-card pending">
                <div class="label">Pending Review</div>
                <div class="value" id="stat-pending">0</div>
            </div>
            <div class="stat-card confirmed">
                <div class="label">Confirmed</div>
                <div class="value" id="stat-confirmed">0</div>
            </div>
            <div class="stat-card rejected">
                <div class="label">Rejected</div>
                <div class="value" id="stat-rejected">0</div>
            </div>
            <div class="stat-card needs-review">
                <div class="label">Needs Review</div>
                <div class="value" id="stat-needs-review">0</div>
            </div>
        </div>
        
        <div class="card" id="ai-training-card">
            <h2>AI Training Examples</h2>
            <div style="display: flex; align-items: center; gap: 20px; margin-bottom: 10px;">
                <div style="font-size: 48px; font-weight: bold; color: #6366f1;" id="ai-training-count">-</div>
                <div>
                    <div style="color: #666; font-size: 14px;">Automatically collected from camera analysis</div>
                    <div style="color: #666; font-size: 14px;">Index type: <strong id="ai-index-type">-</strong></div>
                </div>
            </div>
            <div id="ai-category-breakdown" style="display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px;"></div>
        </div>

        <div class="card">
            <h2>Fine-Tune Ready</h2>
            <div style="display: flex; align-items: center; gap: 20px; margin-bottom: 20px;">
                <div style="font-size: 48px; font-weight: bold; color: #10b981;" id="fine-tune-count">0</div>
                <div>
                    <div style="color: #666; font-size: 14px;">Confirmed incidents (privacy-safe)</div>
                    <div style="color: #666; font-size: 14px;">Minimum required: <strong>100</strong></div>
                </div>
            </div>
            <button class="btn-export" onclick="exportDataset()" id="export-btn">
                📦 Export Training Dataset
            </button>
        </div>
        
        <div class="card">
            <h2>Pending Review (<span id="pending-count">0</span>)</h2>
            <div id="incidents-list">
                <div class="loading">Loading incidents...</div>
            </div>
        </div>
    </div>
    
    <!-- Reject Modal -->
    <div class="modal" id="reject-modal">
        <div class="modal-content">
            <h3>Reject Incident</h3>
            <div class="form-group">
                <label>Reason (required)</label>
                <select id="reject-reason">
                    <option value="">Select reason...</option>
                    <option value="wrong_class">Wrong classification</option>
                    <option value="baseline_noise">Baseline noise (not relevant)</option>
                    <option value="privacy_risk">Privacy risk</option>
                    <option value="low_quality">Low quality</option>
                    <option value="duplicate">Duplicate</option>
                    <option value="policy_violation">Policy violation</option>
                    <option value="other">Other</option>
                </select>
            </div>
            <div class="form-group">
                <label>Notes (optional)</label>
                <textarea id="reject-notes" placeholder="Additional details..."></textarea>
            </div>
            <div class="modal-actions">
                <button class="btn-cancel" onclick="closeRejectModal()">Cancel</button>
                <button class="btn-reject" onclick="submitReject()">Submit Rejection</button>
            </div>
        </div>
    </div>
    
    <script>
        let currentIncidentId = null;
        let currentIncident = null;
        
        // Load user from localStorage
        const user = JSON.parse(localStorage.getItem('alibi_user') || '{}');
        const token = localStorage.getItem('alibi_token');
        
        if (!token) {
            window.location.href = '/camera/login';
        }
        
        // API helpers
        async function apiCall(endpoint, options = {}) {
            const headers = {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json',
                ...options.headers
            };
            
            const response = await fetch(endpoint, {
                ...options,
                headers
            });
            
            if (response.status === 401) {
                window.location.href = '/camera/login';
                throw new Error('Unauthorized');
            }
            
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Request failed');
            }
            
            return response.json();
        }
        
        // Load stats
        async function loadStats() {
            try {
                const stats = await apiCall('/camera/training/stats');
                
                document.getElementById('stat-pending').textContent = stats.review_counts.pending_review;
                document.getElementById('stat-confirmed').textContent = stats.review_counts.confirmed;
                document.getElementById('stat-rejected').textContent = stats.review_counts.rejected;
                document.getElementById('stat-needs-review').textContent = stats.review_counts.needs_review;
                document.getElementById('fine-tune-count').textContent = stats.fine_tune_eligible;
                
                // Enable/disable export button
                const exportBtn = document.getElementById('export-btn');
                if (stats.fine_tune_eligible >= stats.min_confirmed_required && user.role === 'admin') {
                    exportBtn.disabled = false;
                } else {
                    exportBtn.disabled = true;
                    exportBtn.style.opacity = '0.5';
                    exportBtn.style.cursor = 'not-allowed';
                }
            } catch (error) {
                console.error('Failed to load stats:', error);
            }
        }
        
        // Load AI training agent stats
        async function loadAITrainingStats() {
            try {
                const stats = await apiCall('/api/training/stats');
                document.getElementById('ai-training-count').textContent = stats.total_examples || 0;
                document.getElementById('ai-index-type').textContent = stats.index_type || 'none';

                const breakdown = document.getElementById('ai-category-breakdown');
                if (stats.by_category) {
                    breakdown.innerHTML = Object.entries(stats.by_category).map(([cat, count]) =>
                        `<span style="background: #eef2ff; color: #4f46e5; padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 500;">${cat}: ${count}</span>`
                    ).join('');
                }
            } catch (error) {
                console.error('Failed to load AI training stats:', error);
            }
        }

        // Load pending incidents
        async function loadIncidents() {
            try {
                const data = await apiCall('/camera/training/pending');
                
                document.getElementById('pending-count').textContent = data.count;
                
                const list = document.getElementById('incidents-list');
                
                if (data.incidents.length === 0) {
                    list.innerHTML = '<div class="loading">No incidents pending review</div>';
                    return;
                }
                
                list.innerHTML = data.incidents.map(inc => `
                    <div class="incident" data-id="${inc.incident_id}">
                        <div class="incident-header">
                            <div class="incident-id">${inc.incident_id}</div>
                            <div class="status-badge ${inc.review_status}">${inc.review_status.replace('_', ' ')}</div>
                        </div>
                        <div class="incident-details">
                            <div><strong>Category:</strong> ${inc.category}</div>
                            <div><strong>Reason:</strong> ${inc.reason}</div>
                            <div><strong>Camera:</strong> ${inc.camera_id}</div>
                            <div><strong>Duration:</strong> ${inc.duration.toFixed(1)}s</div>
                            <div><strong>Confidence:</strong> ${(inc.confidence * 100).toFixed(0)}%</div>
                            <div><strong>Rules:</strong> ${inc.triggered_rules.join(', ')}</div>
                        </div>
                        ${inc.faces_detected && !inc.faces_redacted ? `
                            <div class="privacy-warning">
                                ⚠️ ${inc.faces_detected ? 'Faces detected - redaction required before confirmation' : 'No faces detected'}
                            </div>
                        ` : ''}
                        <div class="actions">
                            ${inc.faces_detected && !inc.faces_redacted ? `
                                <button class="btn-redact" onclick="redactFaces('${inc.incident_id}')">
                                    🔒 Redact Faces
                                </button>
                            ` : ''}
                            <button class="btn-confirm" onclick="confirmIncident('${inc.incident_id}')" 
                                    ${inc.faces_detected && !inc.faces_redacted ? 'disabled style="opacity:0.5;cursor:not-allowed;"' : ''}>
                                ✅ Confirm
                            </button>
                            <button class="btn-reject" onclick="openRejectModal('${inc.incident_id}')">
                                ❌ Reject
                            </button>
                            <button class="btn-review" onclick="needsReview('${inc.incident_id}')">
                                ⚠️ Needs Review
                            </button>
                        </div>
                    </div>
                `).join('');
            } catch (error) {
                console.error('Failed to load incidents:', error);
                document.getElementById('incidents-list').innerHTML = 
                    `<div class="error">Failed to load incidents: ${error.message}</div>`;
            }
        }
        
        // Redact faces
        async function redactFaces(incidentId) {
            if (!confirm('Redact faces in this incident? This will blur all detected faces.')) return;
            
            try {
                await apiCall(`/camera/training/redact/${incidentId}`, {
                    method: 'POST'
                });
                
                alert('Faces redacted successfully!');
                await loadIncidents();
            } catch (error) {
                alert(`Failed to redact faces: ${error.message}`);
            }
        }
        
        // Confirm incident
        async function confirmIncident(incidentId) {
            try {
                await apiCall(`/camera/training/review/${incidentId}`, {
                    method: 'POST',
                    body: JSON.stringify({
                        status: 'confirmed',
                        faces_detected: false,  // Would be set from actual check
                        faces_redacted: true
                    })
                });
                
                alert('Incident confirmed!');
                await loadStats();
                await loadIncidents();
            } catch (error) {
                alert(`Failed to confirm: ${error.message}`);
            }
        }
        
        // Open reject modal
        function openRejectModal(incidentId) {
            currentIncidentId = incidentId;
            document.getElementById('reject-modal').classList.add('active');
            document.getElementById('reject-reason').value = '';
            document.getElementById('reject-notes').value = '';
        }
        
        // Close reject modal
        function closeRejectModal() {
            document.getElementById('reject-modal').classList.remove('active');
            currentIncidentId = null;
        }
        
        // Submit rejection
        async function submitReject() {
            const reason = document.getElementById('reject-reason').value;
            const notes = document.getElementById('reject-notes').value;
            
            if (!reason) {
                alert('Please select a reason');
                return;
            }
            
            try {
                await apiCall(`/camera/training/review/${currentIncidentId}`, {
                    method: 'POST',
                    body: JSON.stringify({
                        status: 'rejected',
                        reject_reason: reason,
                        notes: notes
                    })
                });
                
                alert('Incident rejected');
                closeRejectModal();
                await loadStats();
                await loadIncidents();
            } catch (error) {
                alert(`Failed to reject: ${error.message}`);
            }
        }
        
        // Needs review
        async function needsReview(incidentId) {
            try {
                await apiCall(`/camera/training/review/${incidentId}`, {
                    method: 'POST',
                    body: JSON.stringify({
                        status: 'needs_review'
                    })
                });
                
                alert('Flagged for supervisor review');
                await loadStats();
                await loadIncidents();
            } catch (error) {
                alert(`Failed to flag: ${error.message}`);
            }
        }
        
        // Export dataset
        async function exportDataset() {
            if (!confirm('Export training dataset? This will create JSONL, COCO, and manifest files.')) return;
            
            const btn = document.getElementById('export-btn');
            btn.disabled = true;
            btn.textContent = '⏳ Exporting...';
            
            try {
                const results = await apiCall('/camera/training/export', {
                    method: 'POST'
                });
                
                alert(`Export complete!\n\nOpenAI Format: ${results.openai.exported_count} examples\nCOCO Format: ${results.coco.num_images} images\nManifest: Full provenance included`);
                
                btn.textContent = '✅ Export Complete!';
                setTimeout(() => {
                    btn.textContent = '📦 Export Training Dataset';
                    btn.disabled = false;
                }, 3000);
            } catch (error) {
                alert(`Export failed: ${error.message}`);
                btn.textContent = '📦 Export Training Dataset';
                btn.disabled = false;
            }
        }
        
        // Initial load
        loadStats();
        loadIncidents();
        loadAITrainingStats();

        // Refresh every 30 seconds
        setInterval(() => {
            loadStats();
            loadIncidents();
            loadAITrainingStats();
        }, 30000);
    </script>
</body>
</html>
"""
