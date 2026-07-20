"""
Vantage FastAPI Server

RESTful API for incident management.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
import asyncio
import json
from pathlib import Path
from pydantic import BaseModel, Field

from fastapi import FastAPI, HTTPException, status, Depends, UploadFile, File, Body, Form, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from alibi.schemas import (
    CameraEvent,
    Incident,
    IncidentStatus,
    IncidentPlan,
    RecommendedAction,
    Decision,
)
from alibi.alibi_store import get_store
from alibi.settings import get_settings
from alibi.incident_grouper import process_camera_event
from alibi.alibi_engine import (
    build_incident_plan,
    validate_incident_plan,
    compile_alert,
)
from alibi.config import VantageConfig
from alibi.sim.simulator_manager import get_simulator_manager
from alibi.sim.event_simulator import Scenario
from alibi.auth import (
    get_user_manager,
    get_current_user,
    get_current_user_from_token_query,
    require_role,
    create_access_token,
    Role,
    User,
    LoginRequest,
    LoginResponse,
    UserInfo,
    CreateUserRequest,
    ChangePasswordRequest,
)


# FastAPI app
app = FastAPI(
    title="Vantage API",
    description="AI-Assisted Incident Alert Management System",
    version="1.0.0",
)

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],  # Vite default ports
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Run data rotation on startup (clean old snapshots, compact JSONL)
@app.on_event("startup")
async def startup_data_rotation():
    try:
        from alibi.data_manager import get_data_manager
        manager = get_data_manager()
        results = manager.auto_rotate()
        print(f"[Startup] Data rotation complete: freed {results.get('total_freed_mb', 0)} MB")
    except Exception as e:
        print(f"[Startup] Data rotation skipped: {e}")


# Mount media directory for clips and snapshots (legacy/placeholder)
MEDIA_DIR = Path("alibi/data/media")
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(MEDIA_DIR)), name="media")

# Mount evidence directory for actual video worker captures
EVIDENCE_DIR = Path("alibi/data/evidence")
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
(EVIDENCE_DIR / "clips").mkdir(exist_ok=True)
(EVIDENCE_DIR / "snapshots").mkdir(exist_ok=True)
app.mount("/evidence", StaticFiles(directory=str(EVIDENCE_DIR)), name="evidence")

# Import and mount routers
from alibi.camera_training import router as camera_training_router
from alibi.bulk_training_import import router as bulk_import_router
from alibi.debug_training import router as debug_router
from alibi.data_collection_api import router as data_collection_router

app.include_router(camera_training_router)
app.include_router(bulk_import_router)
app.include_router(debug_router)
app.include_router(data_collection_router)

# Fix page for corrupted localStorage
from alibi.fix_training_page import FIX_PAGE_HTML
from alibi.clear_and_login import AUTO_FIX_HTML
from fastapi.responses import HTMLResponse

@app.get("/fix-training", response_class=HTMLResponse)
async def fix_training_page():
    """Auto-fix corrupted localStorage and redirect to login"""
    return HTMLResponse(content=FIX_PAGE_HTML)

@app.get("/clear-and-login", response_class=HTMLResponse)
async def clear_and_login_page():
    """Force clear all cached data and redirect to fresh login"""
    return HTMLResponse(content=AUTO_FIX_HTML)

# Mount camera snapshots directory for camera history feature
CAMERA_SNAPSHOTS_DIR = Path("alibi/data/camera_snapshots")
CAMERA_SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
(CAMERA_SNAPSHOTS_DIR / "thumbnails").mkdir(exist_ok=True)
app.mount("/camera_snapshots", StaticFiles(directory=str(CAMERA_SNAPSHOTS_DIR)), name="camera_snapshots")

# Include mobile camera router for streaming from ANY camera (phones, webcams, etc.)
from alibi.mobile_camera import router as mobile_camera_router
app.include_router(mobile_camera_router)

# Include enhanced mobile camera with security threat detection
from alibi.mobile_camera_enhanced import router as mobile_camera_enhanced_router
app.include_router(mobile_camera_enhanced_router)

# Include camera insights router for AI-powered analysis
from alibi.camera_insights import router as camera_insights_router
app.include_router(camera_insights_router)

# Include patterns router (Phase 2 — activity, co-occurrence, person history)
from alibi.patterns.api import router as patterns_router
app.include_router(patterns_router)

# Include camera training router for improving AI vision
from alibi.camera_training import router as camera_training_router
app.include_router(camera_training_router)

# Navigation injection helper
from alibi.alibi_nav import build_nav

def inject_nav(html: str, active_page: str) -> str:
    """Inject the shared nav bar into any HTML page."""
    nav_css, nav_html, nav_js = build_nav(active_page)
    html = html.replace("</style>", nav_css + "\n    </style>", 1)
    html = html.replace("<body>", "<body>\n" + nav_html, 1)
    html = html.replace("</body>", nav_js + "\n</body>", 1)
    return html

# Mobile home page
from alibi.mobile_home import MOBILE_HOME_HTML
from alibi.camera_test import CAMERA_TEST_HTML
from alibi.camera_history import CAMERA_HISTORY_HTML
from alibi.camera_analysis_store import get_camera_analysis_store
from fastapi.responses import HTMLResponse

@app.get("/mobile", response_class=HTMLResponse, tags=["Mobile"])
@app.get("/", response_class=HTMLResponse, tags=["Mobile"])
async def mobile_home():
    """
    Mobile-friendly home page with access to all Vantage features.
    
    This is the main entry point for iPhone/mobile users.
    Provides quick access to:
    - Live camera streaming
    - Incident monitoring
    - Reports and analytics
    - System settings (admin only)
    """
    return HTMLResponse(content=MOBILE_HOME_HTML)

@app.get("/camera-test", response_class=HTMLResponse, tags=["Debug"])
async def camera_test():
    """
    Simple camera test page for debugging camera access issues.
    
    This page will:
    - Check if camera API is available
    - Test camera permissions
    - Show detailed error messages
    - Display debug logs
    """
    return HTMLResponse(content=CAMERA_TEST_HTML)

@app.get("/camera/history", response_class=HTMLResponse, tags=["Mobile"])
async def camera_history():
    """
    Camera history page - browse analyzed snapshots with AI descriptions.
    
    Shows gallery of camera snapshots with:
    - AI-generated descriptions
    - Detected objects and activities
    - Safety concerns highlighted
    - Filterable by date and type
    """
    return HTMLResponse(content=inject_nav(CAMERA_HISTORY_HTML, "history"))

@app.post("/camera/cleanup", tags=["Camera"])
async def cleanup_old_snapshots(current_user: User = Depends(get_current_user)):
    """
    Cleanup old camera snapshots (older than retention policy).
    
    Deletes:
    - Snapshot images older than retention_days
    - Thumbnail images
    - JSONL records
    
    Returns number of files deleted.
    """
    store = get_camera_analysis_store()
    deleted = store.cleanup_old_snapshots()
    return {"deleted": deleted, "message": f"Cleaned up {deleted} old files"}


# Pydantic models for API

class CameraEventRequest(BaseModel):
    """Request model for camera event webhook"""
    event_id: str
    camera_id: str
    ts: str  # ISO format
    zone_id: str
    event_type: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    severity: int = Field(..., ge=1, le=5)
    clip_url: Optional[str] = None
    snapshot_url: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


class DecisionRequest(BaseModel):
    """Request model for operator decision"""
    action_taken: str  # "confirmed", "dismissed", "escalated", "closed"
    operator_notes: str
    was_true_positive: bool
    dismiss_reason: Optional[str] = None
    # The human's own words for WHAT happened ("attempted break-in") when
    # confirming. The system never declares a crime — a person does, and their
    # name goes on it. This label is what the Overview shows, attributed.
    label: Optional[str] = None


class IncidentSummary(BaseModel):
    """Summary response for incident list"""
    incident_id: str
    status: str
    created_ts: str
    updated_ts: str
    event_count: int
    max_severity: int
    avg_confidence: float
    recommended_action: Optional[str] = None
    requires_approval: Optional[bool] = None


class IncidentDetail(BaseModel):
    """Detailed response for single incident"""
    incident_id: str
    status: str
    created_ts: str
    updated_ts: str
    events: List[dict]
    plan: Optional[dict] = None
    alert: Optional[dict] = None
    validation: Optional[dict] = None


# API Endpoints

@app.get("/")
async def root():
    """API root endpoint"""
    return {
        "service": "Vantage API",
        "version": "1.0.0",
        "status": "operational",
    }


# Authentication endpoints

@app.post("/auth/login", response_model=LoginResponse, tags=["Authentication"])
async def login(request: LoginRequest):
    """
    Login and receive JWT token.
    
    Default users:
    - operator1 / operator123 (operator role)
    - supervisor1 / supervisor123 (supervisor role)
    - admin / admin123 (admin role)
    
    WARNING: Change default passwords immediately in production!
    """
    user_manager = get_user_manager()
    user = user_manager.authenticate(request.username, request.password)
    
    if not user:
        # Audit failed login
        store = get_store()
        store.append_audit("login_failed", {
            "username": request.username,
            "timestamp": datetime.utcnow().isoformat(),
        })
        
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    
    # Create access token
    access_token = create_access_token(user.username, user.role.value)
    
    # Audit successful login
    store = get_store()
    store.append_audit("login_success", {
        "username": user.username,
        "role": user.role.value,
        "timestamp": datetime.utcnow().isoformat(),
    })
    
    return LoginResponse(
        access_token=access_token,
        username=user.username,
        role=user.role.value,
        full_name=user.full_name,
    )


@app.get("/auth/me", response_model=UserInfo, tags=["Authentication"])
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """Get current authenticated user information"""
    return UserInfo(
        username=current_user.username,
        role=current_user.role.value,
        full_name=current_user.full_name,
        enabled=current_user.enabled,
        created_at=current_user.created_at,
        last_login=current_user.last_login,
    )


@app.post("/auth/change-password", tags=["Authentication"])
async def change_password(
    request: ChangePasswordRequest,
    current_user: User = Depends(get_current_user)
):
    """Change current user's password"""
    user_manager = get_user_manager()
    
    # Verify old password
    if not user_manager.verify_password(request.old_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect old password",
        )
    
    # Update password
    user_manager.update_password(current_user.username, request.new_password)
    
    # Audit password change
    store = get_store()
    store.append_audit("password_changed", {
        "username": current_user.username,
        "timestamp": datetime.utcnow().isoformat(),
    })
    
    return {"status": "success", "message": "Password changed successfully"}


@app.get("/auth/users", response_model=List[UserInfo], tags=["Authentication"])
async def list_users(current_user: User = Depends(require_role([Role.ADMIN]))):
    """List all users (admin only)"""
    user_manager = get_user_manager()
    
    return [
        UserInfo(
            username=u.username,
            role=u.role.value,
            full_name=u.full_name,
            enabled=u.enabled,
            created_at=u.created_at,
            last_login=u.last_login,
        )
        for u in user_manager.users.values()
    ]


@app.post("/auth/users", tags=["Authentication"])
async def create_user(
    request: CreateUserRequest,
    current_user: User = Depends(require_role([Role.ADMIN]))
):
    """Create new user (admin only)"""
    user_manager = get_user_manager()
    
    try:
        role = Role(request.role)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role. Must be one of: {[r.value for r in Role]}",
        )
    
    try:
        new_user = user_manager.create_user(
            username=request.username,
            password=request.password,
            role=role,
            full_name=request.full_name,
        )
        
        # Audit user creation
        store = get_store()
        store.append_audit("user_created", {
            "admin": current_user.username,
            "new_user": new_user.username,
            "role": new_user.role.value,
            "timestamp": datetime.utcnow().isoformat(),
        })
        
        return {"status": "success", "username": new_user.username}
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@app.delete("/auth/users/{username}", tags=["Authentication"])
async def disable_user(
    username: str,
    current_user: User = Depends(require_role([Role.ADMIN]))
):
    """Disable user account (admin only)"""
    user_manager = get_user_manager()
    
    try:
        user_manager.disable_user(username)
        
        # Audit user disable
        store = get_store()
        store.append_audit("user_disabled", {
            "admin": current_user.username,
            "disabled_user": username,
            "timestamp": datetime.utcnow().isoformat(),
        })
        
        return {"status": "success", "message": f"User {username} disabled"}
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@app.post("/webhook/camera-event", status_code=status.HTTP_201_CREATED)
async def receive_camera_event(
    event_request: CameraEventRequest,
    current_user: User = Depends(get_current_user)  # Authenticated camera systems only
):
    """
    Receive camera event from webhook.
    
    Processes the event:
    1. Validates schema
    2. Stores event
    3. Groups into incident (or creates new)
    4. Builds plan + validation + alert
    5. Stores incident with metadata
    """
    store = get_store()
    settings = get_settings()
    
    try:
        # Convert request to CameraEvent
        event = CameraEvent(
            event_id=event_request.event_id,
            camera_id=event_request.camera_id,
            ts=datetime.fromisoformat(event_request.ts),
            zone_id=event_request.zone_id,
            event_type=event_request.event_type,
            confidence=event_request.confidence,
            severity=event_request.severity,
            clip_url=event_request.clip_url,
            snapshot_url=event_request.snapshot_url,
            metadata=event_request.metadata,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid event data: {str(e)}"
        )
    
    # Store event
    store.append_event(event)
    
    # Audit log
    store.append_audit("event_received", {
        "event_id": event.event_id,
        "camera_id": event.camera_id,
        "zone_id": event.zone_id,
        "event_type": event.event_type,
    })
    
    # Process event into incident
    incident = process_camera_event(event, store, settings)
    
    # Build plan, validate, compile alert
    config = VantageConfig(
        min_confidence_for_notify=settings.min_confidence_for_notify,
        high_severity_threshold=settings.high_severity_threshold,
    )
    
    plan = build_incident_plan(incident, config)
    validation = validate_incident_plan(plan, incident, config)
    
    alert = None
    if validation.passed:
        alert = compile_alert(plan, incident, config)
    
    # Store incident with metadata
    metadata = {
        "plan": {
            "summary": plan.summary_1line,
            "severity": plan.severity,
            "confidence": plan.confidence,
            "uncertainty_notes": plan.uncertainty_notes,
            "recommended_next_step": plan.recommended_next_step.value,
            "requires_human_approval": plan.requires_human_approval,
            "action_risk_flags": plan.action_risk_flags,
            "evidence_refs": plan.evidence_refs,
        },
        "validation": {
            "status": validation.status.value,
            "passed": validation.passed,
            "violations": validation.violations,
            "warnings": validation.warnings,
        },
    }
    
    if alert:
        metadata["alert"] = {
            "title": alert.title,
            "body": alert.body,
            "operator_actions": alert.operator_actions,
            "evidence_refs": alert.evidence_refs,
            "disclaimer": alert.disclaimer,
        }
    
    store.upsert_incident(incident, metadata)
    
    # Audit log
    store.append_audit("incident_processed", {
        "incident_id": incident.incident_id,
        "event_id": event.event_id,
        "status": incident.status.value,
        "validation_passed": validation.passed,
    })
    
    return {
        "incident_id": incident.incident_id,
        "status": incident.status.value,
        "event_count": len(incident.events),
        "validation_passed": validation.passed,
        "recommended_action": plan.recommended_next_step.value,
    }


@app.get("/incidents", response_model=List[IncidentSummary])
async def list_incidents(
    status_filter: Optional[str] = None,
    since: Optional[str] = None,
    limit: int = 100,
    current_user: User = Depends(get_current_user)  # All police personnel can view
):
    """
    List incidents with summary information.
    
    Query params:
    - status: Filter by status (new, triage, dismissed, escalated, closed)
    - since: ISO timestamp - only return incidents updated after this time
    - limit: Maximum number of results (default 100)
    """
    store = get_store()
    
    # Get incidents with metadata
    incidents_data = store.list_incidents_with_metadata(status=status_filter, limit=limit)
    
    # Filter by since timestamp if provided
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            incidents_data = [
                inc for inc in incidents_data
                if datetime.fromisoformat(inc["updated_ts"]) > since_dt
            ]
        except ValueError:
            pass  # Ignore invalid timestamps
    
    summaries = []
    for incident_data in incidents_data:
        plan = incident_data.get("_metadata", {}).get("plan", {})
        
        # Calculate event count from event_ids
        event_count = len(incident_data.get("event_ids", []))
        
        summaries.append(IncidentSummary(
            incident_id=incident_data["incident_id"],
            status=incident_data["status"],
            created_ts=incident_data["created_ts"],
            updated_ts=incident_data["updated_ts"],
            event_count=event_count,
            max_severity=plan.get("severity", 0),
            avg_confidence=plan.get("confidence", 0.0),
            recommended_action=plan.get("recommended_next_step"),
            requires_approval=plan.get("requires_human_approval"),
        ))
    
    return summaries


@app.get("/incidents/{incident_id}", response_model=IncidentDetail)
async def get_incident(
    incident_id: str,
    current_user: User = Depends(get_current_user)  # All police personnel can view
):
    """
    Get full incident details including plan, alert, and validation.
    """
    store = get_store()
    
    incident_data = store.get_incident_with_metadata(incident_id)
    
    if not incident_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident {incident_id} not found"
        )
    
    # Load events
    event_ids = incident_data.get("event_ids", [])
    events = store.get_events_by_ids(event_ids)
    
    # Serialize events
    events_data = []
    for event in events:
        events_data.append({
            "event_id": event.event_id,
            "camera_id": event.camera_id,
            "ts": event.ts.isoformat(),
            "zone_id": event.zone_id,
            "event_type": event.event_type,
            "confidence": event.confidence,
            "severity": event.severity,
            "clip_url": event.clip_url,
            "snapshot_url": event.snapshot_url,
            "metadata": event.metadata,
        })
    
    metadata = incident_data.get("_metadata", {})
    
    return IncidentDetail(
        incident_id=incident_data["incident_id"],
        status=incident_data["status"],
        created_ts=incident_data["created_ts"],
        updated_ts=incident_data["updated_ts"],
        events=events_data,
        plan=metadata.get("plan"),
        alert=metadata.get("alert"),
        validation=metadata.get("validation"),
    )


def _plan_from_metadata(incident_id: str, plan_md: dict) -> IncidentPlan:
    """Rebuild an IncidentPlan from the stored plan metadata dict."""
    step = plan_md.get("recommended_next_step") or "notify"
    try:
        recommended = RecommendedAction(step)
    except ValueError:
        recommended = RecommendedAction.NOTIFY
    return IncidentPlan(
        incident_id=incident_id,
        summary_1line=plan_md.get("summary", ""),
        severity=int(plan_md.get("severity", 1)),
        confidence=float(plan_md.get("confidence", 0.0)),
        uncertainty_notes=plan_md.get("uncertainty_notes", ""),
        recommended_next_step=recommended,
        requires_human_approval=bool(plan_md.get("requires_human_approval", True)),
        action_risk_flags=plan_md.get("action_risk_flags", []) or [],
        evidence_refs=plan_md.get("evidence_refs", []) or [],
    )


@app.get("/incidents/{incident_id}/explanation", tags=["Incidents"])
async def get_incident_explanation(
    incident_id: str,
    current_user: User = Depends(get_current_user)  # All police personnel can view
):
    """
    "Why flagged" explainer: a grounded, cited, human-in-the-loop rationale for
    why this incident was flagged. Reasons are derived from the incident's real
    signals (each cited to an event/evidence/plan field); the prose is phrased by
    the LLM tier when available and safety-checked, else a deterministic template.
    """
    store = get_store()
    incident_data = store.get_incident_with_metadata(incident_id)
    if not incident_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident {incident_id} not found"
        )

    event_ids = incident_data.get("event_ids", [])
    events = store.get_events_by_ids(event_ids)

    incident = Incident(
        incident_id=incident_data["incident_id"],
        status=IncidentStatus(incident_data["status"]),
        created_ts=datetime.fromisoformat(incident_data["created_ts"]),
        updated_ts=datetime.fromisoformat(incident_data["updated_ts"]),
        events=events,
    )
    plan_md = incident_data.get("_metadata", {}).get("plan") or {}
    plan = _plan_from_metadata(incident_id, plan_md)

    # Area background (§9) — advisory context about the PLACE only. Never a
    # reason for the flag, never attributed to the detected individual.
    # Honest empty state when the camera has no area set or nothing is ingested.
    area_context = None
    try:
        from alibi.dataengine.context import get_area_context, resolve_area_for_camera
        camera_id = events[0].camera_id if events else None
        area = resolve_area_for_camera(camera_id) if camera_id else ""
        if area:
            ctx = get_area_context(area)
            area_context = ctx if not ctx.is_empty() else None
    except Exception:
        area_context = None  # fail-safe: explanation still works without context

    from alibi.explainer import explain_incident
    explanation = explain_incident(
        incident, plan, VantageConfig.from_env(), context=area_context
    )
    return explanation.to_dict()


@app.post("/incidents/{incident_id}/decision", status_code=status.HTTP_201_CREATED)
async def record_decision(
    incident_id: str,
    decision_request: DecisionRequest,
    current_user: User = Depends(require_role([Role.OPERATOR, Role.SUPERVISOR, Role.ADMIN]))  # Officers and above
):
    """
    Record operator decision on an incident.
    
    Valid actions: confirmed, dismissed, escalated, closed
    Requires: Operator role or higher
    """
    store = get_store()
    
    # Verify incident exists
    incident = store.get_incident(incident_id)
    if not incident:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident {incident_id} not found"
        )
    
    # Create decision record
    decision = Decision(
        incident_id=incident_id,
        decision_ts=datetime.utcnow(),
        action_taken=decision_request.action_taken,
        operator_notes=decision_request.operator_notes,
        was_true_positive=decision_request.was_true_positive,
        metadata={k: v for k, v in {
            "dismiss_reason": decision_request.dismiss_reason,
            "label": decision_request.label,
        }.items() if v},
    )
    
    # Store decision
    store.append_decision(decision)
    
    # Update incident status based on action
    status_map = {
        "confirmed": IncidentStatus.TRIAGE,
        "dismissed": IncidentStatus.DISMISSED,
        "escalated": IncidentStatus.ESCALATED,
        "closed": IncidentStatus.CLOSED,
    }
    
    new_status = status_map.get(decision_request.action_taken, IncidentStatus.TRIAGE)
    incident.status = new_status
    incident.updated_ts = datetime.utcnow()
    
    # Get existing metadata to preserve plan/alert/validation
    existing_data = store.get_incident_with_metadata(incident_id)
    existing_metadata = existing_data.get("_metadata", {}) if existing_data else {}

    # A human confirming WHAT happened, in their own words, with their name on
    # it. This — never a machine claim — is what lets the Overview show
    # "CONFIRMED · attempted break-in — admin".
    if decision_request.action_taken == "confirmed":
        existing_metadata["confirmed"] = {
            "by": current_user.username,
            "ts": decision.decision_ts.isoformat(),
            "label": (decision_request.label or "").strip() or None,
            "notes": decision_request.operator_notes,
        }

    # Re-store incident with preserved metadata (append-only)
    store.upsert_incident(incident, existing_metadata)
    
    # Audit log
    store.append_audit("decision_recorded", {
        "incident_id": incident_id,
        "action_taken": decision_request.action_taken,
        "was_true_positive": decision_request.was_true_positive,
        "new_status": new_status.value,
    })
    
    return {
        "incident_id": incident_id,
        "decision_recorded": True,
        "new_status": new_status.value,
        "timestamp": decision.decision_ts.isoformat(),
    }


@app.get("/decisions")
async def list_decisions(
    incident_id: Optional[str] = None,
    limit: int = 100,
    current_user: User = Depends(get_current_user)  # All personnel can view decisions
):
    """
    List operator decisions.
    
    Query params:
    - incident_id: Filter by incident (optional)
    - limit: Maximum number of results (default 100)
    """
    store = get_store()
    
    decisions = store.list_decisions(incident_id=incident_id, limit=limit)
    
    return [
        {
            "incident_id": d.incident_id,
            "decision_ts": d.decision_ts.isoformat(),
            "action_taken": d.action_taken,
            "operator_notes": d.operator_notes,
            "was_true_positive": d.was_true_positive,
            "metadata": d.metadata,
        }
        for d in decisions
    ]


# SSE and real-time endpoints

# Global for tracking last update time
_last_incident_update = datetime.utcnow()


async def incident_event_generator():
    """
    Server-Sent Events generator for incident updates.
    
    Emits:
    - heartbeat every 10 seconds
    - incident_upsert when incidents change
    """
    global _last_incident_update
    
    store = get_store()
    last_check = datetime.utcnow()
    
    while True:
        try:
            # Check for new/updated incidents
            current_time = datetime.utcnow()
            
            # Get incidents updated since last check
            incidents_data = store.list_incidents_with_metadata(limit=100)
            
            new_incidents = [
                inc for inc in incidents_data
                if datetime.fromisoformat(inc["updated_ts"]) > last_check
            ]
            
            # Emit incident updates
            for incident_data in new_incidents:
                plan = incident_data.get("_metadata", {}).get("plan", {})
                
                event = {
                    "type": "incident_upsert",
                    "incident_summary": {
                        "incident_id": incident_data["incident_id"],
                        "status": incident_data["status"],
                        "created_ts": incident_data["created_ts"],
                        "updated_ts": incident_data["updated_ts"],
                        "event_count": len(incident_data.get("event_ids", [])),
                        "max_severity": plan.get("severity", 0),
                        "avg_confidence": plan.get("confidence", 0.0),
                        "recommended_action": plan.get("recommended_next_step"),
                        "requires_approval": plan.get("requires_human_approval"),
                        "camera_id": incident_data.get("event_ids", [None])[0],  # Simplified
                        "zone_id": "unknown",  # Would need to join with events
                        "event_type": "unknown",  # Would need to join with events
                    }
                }
                
                yield f"data: {json.dumps(event)}\n\n"
            
            last_check = current_time
            
            # Heartbeat every 10 seconds
            await asyncio.sleep(10)
            
            heartbeat = {
                "type": "heartbeat",
                "timestamp": datetime.utcnow().isoformat()
            }
            yield f"data: {json.dumps(heartbeat)}\n\n"
            
        except Exception as e:
            print(f"Error in SSE generator: {e}")
            await asyncio.sleep(5)


@app.get("/stream/incidents")
async def stream_incidents(
    current_user: User = Depends(get_current_user_from_token_query)
):
    """
    Server-Sent Events endpoint for real-time incident updates.
    
    Auth: Requires ?token=xxx query param (EventSource doesn't support custom headers)
    
    Emits:
    - incident_upsert events when incidents are created/updated
    - heartbeat events every 10 seconds
    """
    return StreamingResponse(
        incident_event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


# Shift report endpoints

class ShiftReportRequest(BaseModel):
    """Request model for generating shift report"""
    start_ts: str
    end_ts: str


@app.post("/reports/shift")
async def generate_shift_report(
    report_request: ShiftReportRequest,
    current_user: User = Depends(get_current_user)  # All personnel can generate reports
):
    """
    Generate a shift report for a time range.
    
    Returns summary statistics and narrative.
    """
    store = get_store()
    
    try:
        start_dt = datetime.fromisoformat(report_request.start_ts)
        end_dt = datetime.fromisoformat(report_request.end_ts)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid timestamp format"
        )
    
    # Get all incidents in range
    all_incidents = store.list_incidents(limit=1000)
    incidents_in_range = [
        inc for inc in all_incidents
        if start_dt <= inc.created_ts <= end_dt
    ]
    
    # Get all decisions in range
    all_decisions = store.list_decisions(limit=1000)
    decisions_in_range = [
        dec for dec in all_decisions
        if start_dt <= dec.decision_ts <= end_dt
    ]
    
    # Generate report
    report = compile_shift_report(
        incidents_in_range,
        decisions_in_range,
        start_dt,
        end_dt
    )
    
    # Convert to JSON-serializable format
    return {
        "start_ts": report.start_ts.isoformat(),
        "end_ts": report.end_ts.isoformat(),
        "incidents_summary": report.incidents_summary,
        "total_incidents": report.total_incidents,
        "by_severity": report.by_severity,
        "by_action": report.by_action,
        "false_positive_count": report.false_positive_count,
        "false_positive_notes": report.false_positive_notes,
        "narrative": report.narrative,
        "kpis": report.kpis,
    }


# Metrics endpoints

@app.get("/metrics/summary")
async def get_metrics_summary(range: str = "24h", current_user: User = Depends(get_current_user)):
    """Get aggregated KPI metrics for the dashboard."""
    from alibi.metrics import get_metrics_aggregator
    aggregator = get_metrics_aggregator()
    return aggregator.compute_summary(range)


# ── Dashboard overview ──────────────────────────────────────────
#
# One call that assembles everything the Overview tab shows, straight from the
# REAL stored events: KPI counts, per-type split, an hourly series, the recent
# detections (each with its real evidence still), and per-camera latest frames.
# Empty stores return zeros and empty lists — the console renders an honest
# "nothing yet" rather than any placeholder data.

_DASH_RANGES = {"24h": 24, "7d": 24 * 7, "30d": 24 * 30}


def _dash_intel(ev) -> dict:
    return ((getattr(ev, "metadata", None) or {}).get("intel") or {})


def _display_names() -> dict:
    """camera_id -> a name that is actually distinguishable.

    Cameras added from a scan all take the vendor name, so a two-camera house ends
    up with two cameras both called "Dahua" — on the camera wall that's two
    identical tiles with no way to tell which is the driveway. Where a name is
    shared, disambiguate it with the tail of the camera id (its IP suffix)."""
    try:
        from alibi.cameras.camera_store import get_camera_store
        cams = get_camera_store().list_all()
    except Exception:
        return {}
    counts: dict = {}
    for c in cams:
        counts[c.name] = counts.get(c.name, 0) + 1
    names = {}
    for c in cams:
        if counts.get(c.name, 0) > 1:
            tail = c.camera_id.rsplit("-", 1)[-1]        # e.g. "91" from dahua-192-168-3-91
            names[c.camera_id] = f"{c.name} ·{tail}"
        else:
            names[c.camera_id] = c.name
    return names


def _field_reports_payload(recent_vehicles: list, cutoff, names: dict) -> list:
    """Recent human field reports for the Overview, each with a camera name and
    a corroborating camera sighting when one backs it up. Degrades to []."""
    try:
        from alibi.reports.field_reports import get_field_report_store, corroborating_sighting
        reports = get_field_report_store().list_recent(limit=12, since_iso=cutoff.isoformat())
        out = []
        for r in reports:
            d = r.to_dict()
            d["camera_name"] = names.get(r.camera_id, r.camera_id) if r.camera_id else None
            d["corroboration"] = corroborating_sighting(r, recent_vehicles)
            out.append(d)
        return out
    except Exception as e:
        print(f"[dashboard] field reports unavailable: {e}")
        return []


def _security_suggestions_payload(names: dict) -> list:
    """Gather the real facts and run the suggestion rules. Degrades to []."""
    try:
        from alibi.patterns.suggestions import security_suggestions
        from alibi.site_profile import get_site_profile_store
        sites = []
        try:
            sites = get_site_profile_store().list()
        except Exception:
            pass
        cameras = []
        cameras_with_area = 0
        try:
            from alibi.cameras.camera_store import get_camera_store
            cameras = get_camera_store().list_all()
            cameras_with_area = sum(1 for c in cameras if getattr(c, "area", ""))
        except Exception:
            pass
        enrolled = 0
        try:
            from alibi.watchlist.watchlist_store import WatchlistStore
            enrolled = len(WatchlistStore().get_all_metadata())
        except Exception:
            pass
        faces_ever = 0
        try:
            from alibi.watchlist.face_sighting_store import get_face_sighting_store
            faces_ever = get_face_sighting_store().count()
        except Exception:
            pass
        person_events = 0
        try:
            from datetime import timedelta as _td
            cutoff = datetime.utcnow() - _td(hours=24)
            for e in get_store().list_events(limit=5000):
                if getattr(e, "ts", None) and e.ts >= cutoff and e.event_type == "person_detected":
                    person_events += 1
        except Exception:
            pass
        hotlist_count = 0
        try:
            from alibi.plates.hotlist_store import HotlistStore
            hotlist_count = len(HotlistStore().load_all())
        except Exception:
            pass
        return security_suggestions(sites, cameras, enrolled, faces_ever,
                                    person_events, hotlist_count, cameras_with_area)
    except Exception as e:
        print(f"[dashboard] security suggestions unavailable: {e}")
        return []


@app.get("/dashboard/overview", tags=["Dashboard"])
async def dashboard_overview(range: str = "24h",
                             current_user: User = Depends(get_current_user)):
    """Real data for the Overview dashboard. No placeholders: an empty system
    returns zeros."""
    from collections import Counter
    from datetime import timedelta
    hours = _DASH_RANGES.get(range, 24)
    cutoff = datetime.utcnow() - timedelta(hours=hours)

    store = get_store()
    # Pull generously, then filter/sort here (the store's limit is file-order).
    events = [e for e in store.list_events(limit=5000)
              if getattr(e, "ts", None) and e.ts >= cutoff]
    events.sort(key=lambda e: e.ts, reverse=True)

    # Camera display names, disambiguated when several share a vendor name.
    names = _display_names()

    def _is_alert(ev) -> bool:
        i = _dash_intel(ev)
        return bool(ev.severity >= 4 or i.get("watchlist_hit") or i.get("hotlist_hit"))

    people = vehicles = 0
    by_type: Counter = Counter()
    buckets: dict = {}
    for e in events:
        i = _dash_intel(e)
        people += int(i.get("person_count") or 0)
        vehicles += int(i.get("vehicle_count") or 0)
        by_type[e.event_type] += 1
        key = e.ts.replace(minute=0, second=0, microsecond=0).isoformat()
        b = buckets.setdefault(key, {"hour": key, "events": 0, "alerts": 0})
        b["events"] += 1
        if _is_alert(e):
            b["alerts"] += 1

    def _row(e) -> dict:
        i = _dash_intel(e)
        md = getattr(e, "metadata", None) or {}
        return {
            "event_id": e.event_id,
            "camera_id": e.camera_id,
            "camera_name": names.get(e.camera_id, e.camera_id),
            "ts": e.ts.isoformat(),
            "event_type": e.event_type,
            "severity": e.severity,
            "confidence": e.confidence,
            "snapshot_url": e.snapshot_url,          # the REAL evidence still
            "description": md.get("description") or "",
            "people": int(i.get("person_count") or 0),
            "vehicles": int(i.get("vehicle_count") or 0),
            "plates": [p.get("display") or p.get("text") for p in (i.get("plates") or [])],
            "watchlist_hit": bool(i.get("watchlist_hit")),
            "watchlist_label": i.get("watchlist_label"),
            "hotlist_hit": bool(i.get("hotlist_hit")),
            "hotlist_reason": i.get("hotlist_reason"),
        }

    # Latest real frame per camera — the live wall, built from evidence stills.
    latest: dict = {}
    for e in events:
        if e.camera_id not in latest and e.snapshot_url:
            latest[e.camera_id] = _row(e)

    cameras = []
    for cid, nm in names.items():
        cameras.append({"camera_id": cid, "name": nm, "latest": latest.get(cid)})
    for cid, row in latest.items():          # cameras seen in events but not registered
        if cid not in names:
            cameras.append({"camera_id": cid, "name": cid, "latest": row})

    alerts = [_row(e) for e in events if _is_alert(e)][:20]

    # People strip — recent distinct faces, cropped client-side from evidence
    # frames. Enrolled people get their name; strangers get continuity ("seen
    # 4× since …"), NEVER a guessed identity. Degrades to an empty strip.
    recent_people = []
    try:
        from alibi.patterns.person_history import recent_people as _recent_people
        from alibi.watchlist.watchlist_store import WatchlistStore
        try:
            wl_entries = WatchlistStore().load_all()
            wl_labels = {e.person_id: e.label for e in wl_entries}
            wl_embeddings = {e.person_id: e.embedding for e in wl_entries if e.embedding}
        except Exception:
            wl_labels, wl_embeddings = {}, {}
        recent_people = _recent_people(cutoff.isoformat(), max_rows=12, labels=wl_labels,
                                       watchlist_embeddings=wl_embeddings)
        for p in recent_people:
            p["source"] = "face"
            p["camera_name"] = names.get(p["camera_id"], p["camera_id"])
    except Exception as e:
        print(f"[dashboard] recent_people unavailable: {e}")

    # People seen without a captured face: at pavement distance the detector
    # finds the PERSON but no face is readable — so fall back to real person
    # crops from the events. Labelled "Person", no name, no continuity claim
    # (there's no embedding to honestly link sightings with). This keeps the
    # "People detected" KPI and the strip telling the same story.
    if len(recent_people) < 12:
        def _piou(a, b) -> float:
            ax, ay, aw, ah = a
            bx, by, bw, bh = b
            ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
            iy = max(0, min(ay + ah, by + bh) - max(ay, by))
            inter = ix * iy
            union = aw * ah + bw * bh - inter
            return inter / union if union > 0 else 0.0

        seen_person_boxes: list = []
        for e in events:
            if len(recent_people) >= 12:
                break
            i = _dash_intel(e)
            if not e.snapshot_url:
                continue
            for d in (i.get("detections") or []):
                if d.get("class") != "person" or len(recent_people) >= 12:
                    continue
                bbox = d.get("bbox") or []
                if len(bbox) != 4:
                    continue
                # a person standing still across many frames is one tile
                if any(cam == e.camera_id and _piou(bbox, prev) > 0.5
                       for cam, prev in seen_person_boxes):
                    continue
                seen_person_boxes.append((e.camera_id, bbox))
                recent_people.append({
                    "sighting_id": None,
                    "source": "detection",
                    "frame_url": e.snapshot_url,
                    "bbox": bbox,
                    "camera_id": e.camera_id,
                    "camera_name": names.get(e.camera_id, e.camera_id),
                    "ts": e.ts.isoformat(),
                    "matched_label": None,
                    "times_seen": 0,
                    "first_seen": None,
                    "event_id": e.event_id,
                })

    # Vehicles strip — one row per detected vehicle in recent events, cropped
    # client-side from the evidence frame. Attributes are the VLM's structured
    # answer, attached only when the frame had exactly one vehicle (attaching
    # one car's description to another would be a quiet lie); otherwise — and
    # whenever the VLM couldn't read a field — they are simply absent.
    def _iou(a, b) -> float:
        ax, ay, aw, ah = a
        bx, by, bw, bh = b
        ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
        iy = max(0, min(ay + ah, by + bh) - max(ay, by))
        inter = ix * iy
        union = aw * ah + bw * bh - inter
        return inter / union if union > 0 else 0.0

    recent_vehicles = []
    seen_boxes: list = []                     # (camera_id, bbox) of picked rows
    for e in events:
        if len(recent_vehicles) >= 12:
            break
        i = _dash_intel(e)
        dets = [d for d in (i.get("detections") or [])
                if d.get("class") in ("car", "truck", "bus", "motorcycle")]
        if not dets or not e.snapshot_url:
            continue
        attrs_list = i.get("vehicle_attrs") or []
        attach = attrs_list[0] if (len(dets) == 1 and len(attrs_list) == 1) else None
        plate_objs = i.get("plates") or []
        plates = [p.get("display") or p.get("text") for p in plate_objs]
        # Registration region of the first read plate (province/town + whether
        # it's out of province for this site). Where the vehicle is registered.
        # Prefer the region stored at read-time; else decode now from the plate
        # string (pure + free) so plates read before this shipped still resolve.
        plate_region = next((p.get("region") for p in plate_objs if p.get("region")), None)
        if plate_region is None and plate_objs:
            try:
                from alibi.vehicles.plate_region import registration_note
                for p in plate_objs:
                    note = registration_note(p.get("text") or p.get("display") or "")
                    if note:
                        plate_region = note
                        break
            except Exception:
                plate_region = None
        for d in dets:
            if len(recent_vehicles) >= 12:
                break
            bbox = d.get("bbox") or []
            if len(bbox) != 4:
                continue
            # A parked car re-detected in every event is ONE vehicle, not a
            # strip full of the same car: skip near-identical boxes per camera.
            if any(cam == e.camera_id and _iou(bbox, prev) > 0.6
                   for cam, prev in seen_boxes):
                continue
            seen_boxes.append((e.camera_id, bbox))
            # Colour: the VLM's word when the frame earned one, else read
            # directly from the crop's pixels (HSV — deterministic, honest,
            # cached). Events from before VLM attributes existed still get a
            # real colour this way.
            colour = attach.get("colour") if attach else None
            if not colour and e.snapshot_url:
                try:
                    from alibi.cameras.frame_analyzer import vehicle_colour
                    fid = e.snapshot_url.rsplit("/", 1)[-1].replace(".jpg", "")
                    colour = vehicle_colour(fid, bbox)
                except Exception:
                    colour = None
            recent_vehicles.append({
                "event_id": e.event_id,
                "frame_url": e.snapshot_url,
                "bbox": bbox,
                "colour": colour,
                "make": attach.get("make") if attach else None,
                "model": attach.get("model") if attach else None,
                "body": attach.get("body") if attach else None,
                "attr_confidence": attach.get("confidence") if attach else None,
                "det_class": d.get("class"),   # free D-FINE type (car/truck/bus/motorcycle)
                "plate": plates[0] if plates else None,
                "region": plate_region,        # where the vehicle is registered
                "camera_id": e.camera_id,
                "camera_name": names.get(e.camera_id, e.camera_id),
                "ts": e.ts.isoformat(),
            })

    # Watching-for panel — the first site's posture triggers, each honestly
    # evaluated (or shown armed-but-not-evaluated). Reads as capability even
    # when nothing has fired, which is most of the time and is the point.
    watching_for = None
    try:
        from alibi.site_profile import get_site_profile_store
        from alibi.patterns.watching_for import evaluate_watching_for
        sites = get_site_profile_store().list()
        if sites:
            site = sites[0]
            face_sightings = []
            try:
                from alibi.watchlist.face_sighting_store import get_face_sighting_store
                face_sightings = [s for s in get_face_sighting_store().load_all()
                                  if s.ts >= cutoff.isoformat()]
            except Exception:
                pass
            watching_for = evaluate_watching_for(site, events, face_sightings)
            for t in watching_for["triggers"]:
                if t.get("camera_id"):
                    t["camera_name"] = names.get(t["camera_id"], t["camera_id"])
    except Exception as e:
        print(f"[dashboard] watching_for unavailable: {e}")

    # Patterns at a glance — WHEN each camera sees activity (hour-of-day, in
    # the site's local time), plus the busiest hour/camera. Derived entirely
    # from the same real events already loaded; an idle system shows zeros.
    patterns = None
    try:
        tz_name = "Africa/Johannesburg"
        try:
            from alibi.site_profile import get_site_profile_store
            _sites = get_site_profile_store().list()
            if _sites and _sites[0].timezone:
                tz_name = _sites[0].timezone
        except Exception:
            pass
        try:
            from zoneinfo import ZoneInfo
            from datetime import timezone as _tzmod
            _tz = ZoneInfo(tz_name)
        except Exception:
            _tz, tz_name = None, "UTC"

        by_cam_hour: dict = {}
        hour_totals = [0] * 24
        people_by_hour = [0] * 24
        vehicles_by_hour = [0] * 24
        for e in events:
            ts = e.ts
            if _tz is not None:
                ts = ts.replace(tzinfo=_tzmod.utc).astimezone(_tz)
            hr = ts.hour
            hour_totals[hr] += 1
            i = _dash_intel(e)
            if int(i.get("person_count") or 0) > 0:
                people_by_hour[hr] += 1
            if int(i.get("vehicle_count") or 0) > 0:
                vehicles_by_hour[hr] += 1
            row = by_cam_hour.setdefault(e.camera_id, [0] * 24)
            row[hr] += 1

        # NB: `range` here is the endpoint's query param (a string) — the
        # builtin is shadowed, so no range() calls in this function.
        busiest_hour = hour_totals.index(max(hour_totals)) if any(hour_totals) else None
        cam_totals = {cid: sum(hrs) for cid, hrs in by_cam_hour.items()}
        busiest_cam = max(cam_totals, key=cam_totals.get) if cam_totals else None
        patterns = {
            "tz": tz_name,
            "by_camera_hour": [
                {"camera_id": cid, "camera_name": names.get(cid, cid), "hours": hrs}
                for cid, hrs in by_cam_hour.items()
            ],
            "people_by_hour": people_by_hour,
            "vehicles_by_hour": vehicles_by_hour,
            "busiest_hour": busiest_hour,
            "busiest_camera": names.get(busiest_cam, busiest_cam) if busiest_cam else None,
        }
    except Exception as e:
        print(f"[dashboard] patterns unavailable: {e}")

    # Situations — the incidents in this window, tiered honestly:
    #   confirmed : a HUMAN said what happened, in their words, name attached
    #   review    : the system flagged it as worth a look NOW (high severity,
    #               watchlist/hotlist, safety concern, escalated)
    #   noted     : everything else that raised an incident
    # The machine's ceiling is "review" — "confirmed" (and any crime word in
    # its label) only ever comes from a person.
    situations = []
    try:
        event_by_id = {e.event_id: e for e in events}
        incidents_data = store.list_incidents_with_metadata(limit=300)
        for inc in incidents_data:
            try:
                upd = datetime.fromisoformat(inc["updated_ts"])
            except (ValueError, TypeError, KeyError):
                continue
            if upd < cutoff:
                continue
            md = inc.get("_metadata", {}) or {}
            confirmed = md.get("confirmed")
            plan = md.get("plan", {}) or {}
            inc_events = [event_by_id[eid] for eid in inc.get("event_ids", [])
                          if eid in event_by_id]
            newest = max(inc_events, key=lambda e: e.ts) if inc_events else None
            sev = max([int(plan.get("severity") or 0)] +
                      [int(getattr(e, "severity", 0) or 0) for e in inc_events])
            flagged = any(_is_alert(e) for e in inc_events)
            if confirmed:
                tier = "confirmed"
            elif flagged or sev >= 4 or inc.get("status") == "escalated":
                tier = "review"
            else:
                tier = "noted"
            desc = ""
            if newest is not None:
                desc = str((getattr(newest, "metadata", None) or {}).get("description") or "")
            situations.append({
                "incident_id": inc["incident_id"],
                "kind": tier,                    # confirmed | review | noted (for ranking)
                "tier": tier,
                "status": inc.get("status"),
                "severity": sev,
                "ts": inc["updated_ts"],
                "camera_id": newest.camera_id if newest else None,
                "camera_name": names.get(newest.camera_id, newest.camera_id) if newest else None,
                "title": str(plan.get("summary_1line") or "").strip() or None,
                "event_type": newest.event_type if newest else inc.get("event_type"),
                "description": desc,
                "snapshot_url": newest.snapshot_url if newest else None,
                "confirmed": confirmed,
            })
    except Exception as e:
        print(f"[dashboard] situations unavailable: {e}")

    # "268 vehicles detected" is sightings, not vehicles — the parked SUV is
    # most of them. Appearance ReID clusters our own sightings into entities
    # (continuity, no identity claim), so we can honestly say how many DISTINCT
    # vehicles that number represents, and which ones keep coming back.
    vehicles_distinct = None
    recurring_vehicles = []
    pattern_findings_rows = []
    ent: list = []
    vlabels: dict = {}
    try:
        from alibi.cameras.cross_camera import get_cross_camera_tracker
        from alibi.patterns.familiarity import (classify_entity, get_vehicle_labels,
                                                pattern_findings)
        ent = get_cross_camera_tracker().entity_summary("vehicle", hours=hours)
        vlabels = get_vehicle_labels()
        if ent:
            vehicles_distinct = len(ent)
            for i, r in enumerate(ent[:5]):
                # NB: `range` is the shadowing query param here — no range() calls
                busiest = r["hours"].index(max(r["hours"])) if any(r["hours"]) else None
                cls = classify_entity(r["count"], r["first_seen"], r["last_seen"],
                                      r.get("days", 1), r.get("active_hours", 1))
                recurring_vehicles.append({
                    "label": f"Vehicle {chr(65 + i)}",       # anonymous cluster, honest
                    "entity_id": r["entity_id"],
                    "owner_label": (vlabels.get(r["entity_id"]) or {}).get("label"),
                    "familiarity": cls,
                    "count": r["count"],
                    "days": r.get("days", 1),
                    "first_seen": r["first_seen"],
                    "last_seen": r["last_seen"],
                    "cameras": [names.get(c, c) for c in r["cameras"]],
                    "busiest_hour_utc": busiest,
                })

        # Explicit findings: what is here all the time, what is new, what has a
        # rhythm — plus each camera's learned "normal" scene.
        camera_normals = {}
        try:
            from alibi.cameras.scene_baseline import get_scene_baseline
            bl = get_scene_baseline()
            for cid, nm in names.items():
                if bl.is_learned(cid):
                    camera_normals[nm] = bl.normal(cid)
        except Exception:
            pass
        people_hours_utc = None
        if patterns and patterns.get("people_by_hour"):
            # patterns buckets are site-local; rotate back to UTC for findings
            # (no range() here — the query param shadows the builtin)
            local = patterns["people_by_hour"]
            off = 2  # Africa/Johannesburg
            people_hours_utc = [local[(i + off) % 24] for i, _ in enumerate(local)]
        pattern_findings_rows = pattern_findings(
            [dict(r, label=f"Vehicle {chr(65 + i)}") for i, r in enumerate(ent[:5])],
            labels=vlabels, camera_normals=camera_normals,
            people_by_hour=people_hours_utc)
    except Exception as e:
        print(f"[dashboard] vehicle entity summary unavailable: {e}")

    # Click-through: map each card back to the incident it belongs to, so a
    # person/vehicle picture on the Overview opens its incident + full detail.
    # Incidents store event_ids; build event_id -> incident_id once (cheap now
    # that list_incidents is O(file)). Face-people rows carry a frame_url whose
    # frame_id ties to the "frm_<id>" event.
    ev_to_incident: dict = {}
    try:
        for inc in store.list_incidents(limit=2000):
            for eid in [ev.event_id for ev in inc.events]:
                ev_to_incident.setdefault(eid, inc.incident_id)

        def _attach_incident(row):
            eid = row.get("event_id")
            if not eid and row.get("frame_url"):
                fid = str(row["frame_url"]).rsplit("/", 1)[-1].replace(".jpg", "")
                eid = f"frm_{fid}"
            row["incident_id"] = ev_to_incident.get(eid) if eid else None
            return row

        for r in recent_vehicles:
            _attach_incident(r)
        for p in recent_people:
            _attach_incident(p)
    except Exception as e:
        print(f"[dashboard] incident linkage unavailable: {e}")

    # Out-of-the-ordinary vehicles + criteria-based situations. The Situations
    # panel used to be populated ONLY by raised incidents, so a quiet site showed
    # an empty panel even while the cameras were seeing genuinely unusual things.
    # Here we surface, against our own criteria: cars that are NOT the usual scene
    # (new/occasional, unnamed) with how often + when they came down the road; and
    # criteria situations (a new vehicle, presence after hours, someone at the
    # parked vehicles, a lingering person, repeated passes) — each "worth a look",
    # never an accusation, so the top-5 reflects the site's real state.
    out_of_ordinary: list = []
    try:
        from alibi.patterns.situations import (out_of_ordinary_vehicles,
                                               new_vehicle_situations, rank_situations)
        out_of_ordinary = out_of_ordinary_vehicles(ent, labels=vlabels, names=names)

        events_by_id = {e.event_id: e for e in events}

        def _frame_at(camera_id, ts_iso):
            """Best evidence still for a criteria situation: the event whose id we
            were handed, else the newest event at that camera with a snapshot."""
            for e in events:
                if e.camera_id == camera_id and e.snapshot_url:
                    return e.snapshot_url, e.event_id
            return None, None

        criteria_rows: list = []
        # New vehicles get their own card (entity-linked, no incident needed).
        criteria_rows.extend(new_vehicle_situations(out_of_ordinary))

        # Fired posture triggers → situations (after-hours, dwell, repeated passes).
        _TRIGGER_TITLES = {
            "after_hours": "Presence after hours",
            "dwell": "Someone stayed in view",
            "repeated_passes": "Same person, repeated passes",
        }
        for t in (watching_for or {}).get("triggers", []) if watching_for else []:
            if not t.get("fired") or t.get("kind") not in _TRIGGER_TITLES:
                continue
            cam_id = t.get("camera_id")
            eid = t.get("event_id")
            snap, snap_eid = (None, None)
            if eid and eid in events_by_id and events_by_id[eid].snapshot_url:
                snap, snap_eid = events_by_id[eid].snapshot_url, eid
            else:
                snap, snap_eid = _frame_at(cam_id, t.get("ts"))
            criteria_rows.append({
                "kind": t["kind"], "tier": "review", "incident_id": None,
                "entity_id": None, "event_id": snap_eid,
                "title": _TRIGGER_TITLES[t["kind"]],
                "description": t.get("note") or "Worth a look.",
                "camera_name": names.get(cam_id, cam_id), "ts": t.get("ts"),
                "snapshot_url": snap, "count": None, "confirmed": None,
            })

        # Someone at / moving between the parked vehicles (the honest "checking
        # car doors" signal) — a concrete action, evaluated over the same events.
        try:
            from alibi.site_profile import get_site_profile_store
            from alibi.patterns.observed_actions import evaluate_at_vehicles
            _sites = get_site_profile_store().list()
            if _sites:
                av = evaluate_at_vehicles(_sites[0], events)
                if av.get("fired"):
                    snap, snap_eid = _frame_at(av.get("camera_id"), av.get("ts"))
                    criteria_rows.append({
                        "kind": "at_vehicles", "tier": "review", "incident_id": None,
                        "entity_id": None, "event_id": snap_eid,
                        "title": "Someone at the parked vehicles",
                        "description": av.get("note") or "Worth a look.",
                        "camera_name": names.get(av.get("camera_id"), av.get("camera_id")),
                        "ts": av.get("ts"), "snapshot_url": snap,
                        "count": av.get("vehicles_touched"), "confirmed": None,
                    })
        except Exception as e:
            print(f"[dashboard] at-vehicles unavailable: {e}")

        # Resolve each criteria row's incident (most fired events raised one) so
        # the card can still click through to the full evidence + why-flagged.
        for r in criteria_rows:
            if r.get("incident_id") is None and r.get("event_id"):
                r["incident_id"] = ev_to_incident.get(r["event_id"])

        # Top-5 things worth attention = confirmed/review incidents + criteria,
        # ranked by how much they warrant a look; routine "noted" incidents keep
        # their place below (the UI collapses them to a single line).
        noted_rows = [s for s in situations if s.get("kind") == "noted"]
        attention = [s for s in situations if s.get("kind") != "noted"] + criteria_rows
        situations = rank_situations(attention, limit=5) + noted_rows
    except Exception as e:
        print(f"[dashboard] criteria situations unavailable: {e}")
        situations = situations[:8]

    return {
        "range": range,
        "generated_at": datetime.utcnow().isoformat(),
        "kpis": {
            "events": len(events),
            "alerts": sum(1 for e in events if _is_alert(e)),
            "people": people,
            "vehicles": vehicles,
            "vehicles_distinct": vehicles_distinct,
        },
        "by_type": [{"type": t, "count": c} for t, c in by_type.most_common()],
        "over_time": [buckets[k] for k in sorted(buckets)],
        "recent": [_row(e) for e in events[:24]],
        "cameras": cameras,
        "alerts": alerts,
        "recent_people": recent_people,
        "recent_vehicles": recent_vehicles,
        "watching_for": watching_for,
        "patterns": patterns,
        "situations": situations,
        "out_of_ordinary_vehicles": out_of_ordinary,
        "recurring_vehicles": recurring_vehicles,
        "pattern_findings": pattern_findings_rows,
        "security_suggestions": _security_suggestions_payload(names),
        "field_reports": _field_reports_payload(recent_vehicles, cutoff, names),
    }


# Settings endpoints

@app.get("/settings")
async def get_settings_endpoint():
    """Get current system settings"""
    settings = get_settings()
    
    return {
        "incident_grouping": {
            "merge_window_seconds": settings.merge_window_seconds,
            "dedup_window_seconds": settings.dedup_window_seconds,
            "compatible_event_types": settings.get("incident_grouping.compatible_event_types", {}),
        },
        "thresholds": {
            "min_confidence_for_notify": settings.min_confidence_for_notify,
            "high_severity_threshold": settings.high_severity_threshold,
        },
        "api": {
            "port": settings.api_port,
            "host": settings.api_host,
        }
    }


@app.put("/settings")
async def update_settings(
    settings_update: dict,
    current_user: User = Depends(require_role([Role.ADMIN]))  # Admin only
):
    """
    Update system settings.
    
    Saves to alibi_settings.json file.
    """
    from alibi.settings import get_settings
    import json
    from pathlib import Path
    
    settings = get_settings()
    settings_file = Path("alibi/data/alibi_settings.json")
    
    # Load current settings
    if settings_file.exists():
        with open(settings_file, "r") as f:
            current = json.load(f)
    else:
        current = {}
    
    # Merge updates
    def deep_merge(base, updates):
        for key, value in updates.items():
            if isinstance(value, dict) and key in base:
                deep_merge(base[key], value)
            else:
                base[key] = value
    
    deep_merge(current, settings_update)
    
    # Save
    with open(settings_file, "w") as f:
        json.dump(current, f, indent=2)
    
    # Audit log
    store = get_store()
    store.append_audit("settings_updated", settings_update)
    
    return {"status": "updated", "settings": current}


# ── Camera Registry endpoints ────────────────────────────────────────────

from alibi.cameras.camera_store import Camera, CameraStore, get_camera_store
from alibi.cameras.vms_connect import test_connection as vms_test_connection


class CameraCreateRequest(BaseModel):
    """Request to register a new camera"""
    camera_id: str
    name: str
    source: str = ""
    source_type: str = "rtsp"  # rtsp | onvif | milestone | genetec | mobile
    enabled: bool = True
    location: str = ""
    area: str = ""  # Suburb/area — links this camera to place-context (§9)
    site_id: str = ""  # optional — link this camera to a protected site
    vms_config: dict = Field(default_factory=dict)


def _link_camera_to_site(site_id: str, camera_id: str) -> None:
    """Add a camera to a site's camera list (so the site's brief covers it)."""
    if not site_id:
        return
    from alibi.site_profile import get_site_profile_store
    store = get_site_profile_store()
    site = store.get(site_id)
    if site and camera_id not in site.camera_ids:
        store.update(site_id, camera_ids=list(site.camera_ids) + [camera_id])


class CameraUpdateRequest(BaseModel):
    """Partial update for a camera"""
    name: Optional[str] = None
    source: Optional[str] = None
    source_type: Optional[str] = None
    enabled: Optional[bool] = None
    location: Optional[str] = None
    area: Optional[str] = None  # Suburb/area — links this camera to place-context (§9)
    vms_config: Optional[dict] = None


@app.get("/cameras", tags=["Cameras"])
async def list_cameras(
    current_user: User = Depends(get_current_user),
):
    """List all registered cameras with status."""
    store = get_camera_store()
    cameras = store.list_all()
    return {"cameras": [c.to_dict() for c in cameras]}


@app.post("/cameras", tags=["Cameras"])
async def add_camera(
    req: CameraCreateRequest,
    current_user: User = Depends(require_role([Role.ADMIN])),
):
    """Register a new camera (admin only)."""
    store = get_camera_store()
    camera = Camera(
        camera_id=req.camera_id,
        name=req.name,
        source=req.source,
        source_type=req.source_type,
        enabled=req.enabled,
        location=req.location,
        area=req.area,
        vms_config=req.vms_config,
    )
    store.add(camera)
    _link_camera_to_site(req.site_id, camera.camera_id)

    audit_store = get_store()
    audit_store.append_audit("camera_added", {"camera_id": req.camera_id, "user": current_user.username})

    return camera.to_dict()


@app.put("/cameras/{camera_id}", tags=["Cameras"])
async def update_camera(
    camera_id: str,
    req: CameraUpdateRequest,
    current_user: User = Depends(require_role([Role.ADMIN])),
):
    """Update camera configuration (admin only)."""
    store = get_camera_store()
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    camera = store.update(camera_id, updates)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    return camera.to_dict()


@app.delete("/cameras/{camera_id}", tags=["Cameras"])
async def delete_camera(
    camera_id: str,
    current_user: User = Depends(require_role([Role.ADMIN])),
):
    """Remove a camera (admin only)."""
    store = get_camera_store()
    if not store.remove(camera_id):
        raise HTTPException(status_code=404, detail="Camera not found")

    audit_store = get_store()
    audit_store.append_audit("camera_removed", {"camera_id": camera_id, "user": current_user.username})

    return {"status": "removed", "camera_id": camera_id}


@app.post("/cameras/{camera_id}/test", tags=["Cameras"])
async def test_camera_connection(
    camera_id: str,
    current_user: User = Depends(require_role([Role.ADMIN])),
):
    """Test camera connection by reading one frame."""
    store = get_camera_store()
    camera = store.get(camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")

    result = vms_test_connection(camera)

    # Update camera status based on test result
    new_status = "online" if result.get("ok") else "offline"
    store.update_status(camera_id, new_status, datetime.now().isoformat() if result.get("ok") else None)

    return result


# ── Cross-Camera Trail endpoint ──────────────────────────────────────────

from alibi.cameras.cross_camera import get_cross_camera_tracker


@app.get("/trail/{entity_type}/{entity_id}", tags=["Cameras"])
async def get_entity_trail(
    entity_type: str,
    entity_id: str,
    hours: int = 24,
    current_user: User = Depends(get_current_user),
):
    """
    Get camera-by-camera trail for an entity (plate or vehicle description).

    Returns chronological list of sightings across cameras.
    """
    tracker = get_cross_camera_tracker()
    trail = tracker.get_entity_trail(entity_type, entity_id, hours=hours)
    return {"entity_type": entity_type, "entity_id": entity_id, "trail": trail}


# Watchlist endpoints

@app.get("/watchlist")
async def get_watchlist(
    current_user: User = Depends(require_role([Role.SUPERVISOR, Role.ADMIN]))  # Supervisor+ only
):
    """
    Get watchlist entries (without embeddings).
    
    Returns metadata only for security.
    Requires: Supervisor or Admin role
    """
    from alibi.watchlist.watchlist_store import WatchlistStore

    store = WatchlistStore()
    entries = store.get_all_metadata()

    # Join each enrolled person to the camera archive: their face shot (a crop of
    # a REAL evidence frame), when last seen, and how often. Same conservative
    # cosine threshold as live matching; degrades to enrolment metadata (or
    # honest nulls) if the sighting archive is empty.
    try:
        import numpy as _np
        from alibi.watchlist.face_sighting_store import get_face_sighting_store
        embeddings = store.get_all_embeddings()
        sighting_store = get_face_sighting_store()
        for entry in entries:
            entry["times_seen"] = 0
            entry["last_seen"] = None
            md = entry.get("metadata") or {}
            fb = md.get("face_bbox") or {}
            entry["face"] = ({"frame_url": md["frame_url"],
                              "bbox": [fb.get("x", 0), fb.get("y", 0), fb.get("w", 0), fb.get("h", 0)]}
                             if md.get("frame_url") else None)
            emb = embeddings.get(entry["person_id"]) if hasattr(embeddings, "get") else None
            if emb is None or not len(emb):
                continue
            matches = sighting_store.find_similar(_np.asarray(emb, dtype=_np.float32),
                                                  threshold=0.6, limit=500)
            if matches:
                newest = max(matches, key=lambda m: m[0].ts)[0]
                entry["times_seen"] = len(matches)
                entry["last_seen"] = newest.ts
                if newest.image_path:
                    entry["face"] = {"frame_url": newest.image_path, "bbox": list(newest.bbox)}
    except Exception as e:
        print(f"[watchlist] sighting join unavailable: {e}")

    # Audit log
    audit_store = get_store()
    audit_store.append_audit("watchlist_accessed", {
        "user": current_user.username,
        "role": current_user.role.value,
        "entry_count": len(entries)
    })

    return {
        "entries": entries,
        "total": len(entries)
    }


@app.post("/watchlist/enroll-sighting")
async def enroll_face_from_sighting(
    payload: dict,
    current_user: User = Depends(require_role([Role.SUPERVISOR, Role.ADMIN]))
):
    """One-click enrol from an unknown face the cameras already saw.

    The sighting carries the face embedding we generated at detection time, so
    enrolling is just a name and a button — no photo upload. Every enrolment
    makes the next sighting (and, via the read-time match, the current strip)
    say a name instead of "Unknown person".

    Requires: Supervisor or Admin role
    """
    import re
    import uuid as _uuid
    from alibi.watchlist.watchlist_store import WatchlistStore, WatchlistEntry
    from alibi.watchlist.face_sighting_store import get_face_sighting_store

    sighting_id = str(payload.get("sighting_id") or "").strip()
    label = str(payload.get("label") or "").strip()
    if not sighting_id or not label:
        raise HTTPException(status_code=400, detail="sighting_id and label are required")

    sighting = next((s for s in get_face_sighting_store().load_all()
                     if s.sighting_id == sighting_id), None)
    if sighting is None:
        raise HTTPException(status_code=404, detail="Sighting not found")
    if not sighting.embedding:
        raise HTTPException(status_code=400, detail="Sighting has no face embedding")

    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-") or "person"
    person_id = f"{slug}-{_uuid.uuid4().hex[:6]}"

    store = WatchlistStore()
    store.add_entry(WatchlistEntry(
        person_id=person_id,
        label=label,
        embedding=list(sighting.embedding),
        added_ts=datetime.utcnow().isoformat(),
        source_ref=f"sighting:{sighting_id}",
        metadata={
            "enrolled_by": current_user.username,
            "enrolled_from": "camera_sighting",
            "camera_id": sighting.camera_id,
            "sighting_ts": sighting.ts,
            "face_bbox": {"x": int(sighting.bbox[0]), "y": int(sighting.bbox[1]),
                          "w": int(sighting.bbox[2]), "h": int(sighting.bbox[3])},
            "frame_url": sighting.image_path,
        },
    ))

    get_store().append_audit("watchlist_enrolled", {
        "user": current_user.username,
        "person_id": person_id,
        "label": label,
        "source": f"sighting:{sighting_id}",
    })
    return {"status": "enrolled", "person_id": person_id, "label": label}


@app.post("/watchlist/enroll")
async def enroll_watchlist_face(
    person_id: str = Form(...),
    label: str = Form(...),
    source_ref: str = Form(""),
    image: UploadFile = File(...),
    current_user: User = Depends(require_role([Role.SUPERVISOR, Role.ADMIN]))
):
    """
    Enroll a face into the watchlist from an uploaded image.

    Requires: Supervisor or Admin role
    """
    import cv2
    import numpy as np
    from alibi.watchlist.watchlist_store import WatchlistStore, WatchlistEntry
    from alibi.watchlist.face_detect import FaceDetector
    from alibi.watchlist.face_embed import FaceEmbedder

    contents = await image.read()
    nparr = np.frombuffer(contents, np.uint8)
    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    if frame is None:
        raise HTTPException(status_code=400, detail="Invalid image")

    detector = FaceDetector(confidence_threshold=0.5)
    result = detector.detect_and_extract(frame, return_largest=True)

    if result is None:
        raise HTTPException(status_code=400, detail="No face detected in image")

    face_crop, bbox = result
    embedder = FaceEmbedder()
    embedding = embedder.generate_embedding(face_crop)

    entry = WatchlistEntry(
        person_id=person_id,
        label=label,
        embedding=embedding.tolist(),
        added_ts=datetime.utcnow().isoformat(),
        source_ref=source_ref,
        metadata={
            "enrolled_by": current_user.username,
            "face_bbox": {"x": int(bbox[0]), "y": int(bbox[1]), "w": int(bbox[2]), "h": int(bbox[3])},
        }
    )

    store = WatchlistStore()
    store.add_entry(entry)

    # Audit log
    audit_store = get_store()
    audit_store.append_audit("watchlist_enrolled", {
        "user": current_user.username,
        "person_id": person_id,
        "label": label,
    })

    return {"status": "enrolled", "person_id": person_id, "label": label}


@app.delete("/watchlist/{person_id}")
async def remove_watchlist_entry(
    person_id: str,
    current_user: User = Depends(require_role([Role.ADMIN]))
):
    """
    Remove a person from the watchlist by appending a removal record.

    Requires: Admin role
    """
    from alibi.watchlist.watchlist_store import WatchlistStore, WatchlistEntry

    store = WatchlistStore()
    existing = store.get_by_person_id(person_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Person {person_id} not found in watchlist")

    # Append a removal record (empty embedding signals removal)
    removal = WatchlistEntry(
        person_id=person_id,
        label=existing.label,
        embedding=[],
        added_ts=datetime.utcnow().isoformat(),
        source_ref="REMOVED",
        metadata={
            "removed_by": current_user.username,
            "removal_reason": "manual_removal",
        }
    )
    store.add_entry(removal)

    # Audit log
    audit_store = get_store()
    audit_store.append_audit("watchlist_removed", {
        "user": current_user.username,
        "person_id": person_id,
    })

    return {"status": "removed", "person_id": person_id}


@app.post("/watchlist/search")
async def search_watchlist_by_face(
    image: UploadFile = File(...),
    current_user: User = Depends(require_role([Role.SUPERVISOR, Role.ADMIN]))
):
    """
    Upload an image and search the watchlist for matching faces.

    Requires: Supervisor or Admin role
    """
    import cv2
    import numpy as np
    from alibi.watchlist.watchlist_store import WatchlistStore
    from alibi.watchlist.face_detect import FaceDetector
    from alibi.watchlist.face_embed import FaceEmbedder
    from alibi.watchlist.face_match import FaceMatcher

    contents = await image.read()
    nparr = np.frombuffer(contents, np.uint8)
    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    if frame is None:
        raise HTTPException(status_code=400, detail="Invalid image")

    detector = FaceDetector(confidence_threshold=0.5)
    result = detector.detect_and_extract(frame, return_largest=True)

    if result is None:
        raise HTTPException(status_code=400, detail="No face detected in image")

    face_crop, bbox = result
    embedder = FaceEmbedder()
    embedding = embedder.generate_embedding(face_crop)

    store = WatchlistStore()
    watchlist_embeddings = store.get_all_embeddings()
    watchlist_labels = {e.person_id: e.label for e in store.load_all()}

    if not watchlist_embeddings:
        return {"match": False, "candidates": [], "message": "Watchlist is empty"}

    matcher = FaceMatcher(match_threshold=0.6, top_k=5)
    is_match, top_candidates, best_score = matcher.match(
        embedding, watchlist_embeddings, watchlist_labels
    )

    # Audit log
    audit_store = get_store()
    audit_store.append_audit("watchlist_searched", {
        "user": current_user.username,
        "match_found": is_match,
        "best_score": round(best_score, 4),
    })

    return {
        "match": is_match,
        "best_score": round(best_score, 4),
        "candidates": [c.to_dict() for c in top_candidates],
    }


# Hotlist endpoints

class HotlistEntryRequest(BaseModel):
    """Request model for adding hotlist entry"""
    plate: str
    reason: str
    source_ref: str
    metadata: Optional[dict] = None


@app.post("/hotlist/plates")
async def add_hotlist_plate(
    entry_request: HotlistEntryRequest,
    current_user: User = Depends(require_role([Role.SUPERVISOR, Role.ADMIN]))  # Supervisor+ only
):
    """
    Add license plate to hotlist.
    
    Requires: Supervisor or Admin role
    """
    from alibi.plates.hotlist_store import HotlistStore, HotlistEntry
    from alibi.plates.normalize import normalize_plate
    from datetime import datetime
    
    # Normalize plate
    normalized_plate = normalize_plate(entry_request.plate)
    
    if not normalized_plate:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid plate format"
        )
    
    # Create entry
    entry = HotlistEntry(
        plate=normalized_plate,
        reason=entry_request.reason,
        added_ts=datetime.utcnow().isoformat(),
        source_ref=entry_request.source_ref,
        metadata=entry_request.metadata or {}
    )
    
    # Store
    store = HotlistStore()
    store.add_entry(entry)
    
    # Audit log
    audit_store = get_store()
    audit_store.append_audit("hotlist_plate_added", {
        "user": current_user.username,
        "role": current_user.role.value,
        "plate": normalized_plate,
        "reason": entry_request.reason,
        "source_ref": entry_request.source_ref
    })
    
    return {
        "status": "added",
        "plate": normalized_plate,
        "entry": entry.to_dict()
    }


@app.get("/hotlist/plates")
async def get_hotlist_plates(
    current_user: User = Depends(require_role([Role.SUPERVISOR, Role.ADMIN]))  # Supervisor+ only
):
    """
    Get hotlist plates.
    
    Returns active (non-removed) plates only.
    Requires: Supervisor or Admin role
    """
    from alibi.plates.hotlist_store import HotlistStore
    
    store = HotlistStore()
    entries = store.get_active_entries()
    
    # Audit log
    audit_store = get_store()
    audit_store.append_audit("hotlist_accessed", {
        "user": current_user.username,
        "role": current_user.role.value,
        "entry_count": len(entries)
    })
    
    return {
        "entries": [e.to_dict() for e in entries],
        "total": len(entries)
    }


@app.delete("/hotlist/plates/{plate}")
async def remove_hotlist_plate(
    plate: str,
    current_user: User = Depends(require_role([Role.SUPERVISOR, Role.ADMIN]))  # Supervisor+ only
):
    """
    Remove license plate from hotlist.
    
    Requires: Supervisor or Admin role
    """
    from alibi.plates.hotlist_store import HotlistStore
    from alibi.plates.normalize import normalize_plate
    
    # Normalize plate
    normalized_plate = normalize_plate(plate)
    
    if not normalized_plate:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid plate format"
        )
    
    # Remove
    store = HotlistStore()
    removed = store.remove_entry(normalized_plate)
    
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plate not found in hotlist"
        )
    
    # Audit log
    audit_store = get_store()
    audit_store.append_audit("hotlist_plate_removed", {
        "user": current_user.username,
        "role": current_user.role.value,
        "plate": normalized_plate
    })
    
    return {
        "status": "removed",
        "plate": normalized_plate
    }


# Vehicle Search endpoints

@app.get("/search/vehicles")
async def search_vehicles(
    plate: Optional[str] = None,
    make: Optional[str] = None,
    model: Optional[str] = None,
    color: Optional[str] = None,
    camera_id: Optional[str] = None,
    from_ts: Optional[str] = None,
    to_ts: Optional[str] = None,
    limit: int = 100,
    current_user: User = Depends(get_current_user)  # All authenticated users
):
    """
    Search vehicle sightings.

    Query parameters:
    - plate: License plate text (partial match, searches metadata)
    - make: Vehicle make (partial match)
    - model: Vehicle model (partial match)
    - color: Vehicle color (exact match)
    - camera_id: Camera ID (exact match)
    - from_ts: Start timestamp (ISO format)
    - to_ts: End timestamp (ISO format)
    - limit: Max results (default 100)

    Returns matched sightings with evidence URLs.
    """
    from alibi.vehicles.sightings_store import VehicleSightingsStore

    store = VehicleSightingsStore()

    # If plate search, use dedicated method
    if plate:
        sightings = store.search_by_plate(plate_query=plate, limit=limit)
    else:
        sightings = store.search(
            make=make,
            model=model,
            color=color,
            camera_id=camera_id,
            from_ts=from_ts,
            to_ts=to_ts,
            limit=limit
        )

    # Audit log
    audit_store = get_store()
    audit_store.append_audit("vehicle_search", {
        "user": current_user.username,
        "role": current_user.role.value,
        "filters": {
            "plate": plate,
            "make": make,
            "model": model,
            "color": color,
            "camera_id": camera_id,
            "from_ts": from_ts,
            "to_ts": to_ts
        },
        "result_count": len(sightings)
    })

    return {
        "sightings": [s.to_dict() for s in sightings],
        "total": len(sightings),
        "filters": {
            "plate": plate,
            "make": make,
            "model": model,
            "color": color,
            "camera_id": camera_id,
            "from_ts": from_ts,
            "to_ts": to_ts,
            "limit": limit
        }
    }


# Simulator endpoints

class SimulatorStartRequest(BaseModel):
    """Request model for starting simulator"""
    scenario: str
    rate_per_min: float = Field(default=10.0, ge=0.1, le=120.0)
    seed: Optional[int] = None


class SimulatorReplayRequest(BaseModel):
    """Request model for replaying events"""
    jsonl_data: Optional[str] = None
    file_path: Optional[str] = None


@app.post("/sim/start")
async def start_simulator(
    request: SimulatorStartRequest,
    current_user: User = Depends(require_role([Role.ADMIN]))  # Admin only - demo/testing
):
    """
    Start event simulator.
    
    Generates events at specified rate and posts to /webhook/camera-event.
    """
    manager = get_simulator_manager()
    
    # Validate scenario
    try:
        scenario = Scenario(request.scenario)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid scenario. Must be one of: {[s.value for s in Scenario]}"
        )
    
    # Define callback to post events
    async def event_callback(event: dict):
        """Post generated event to webhook endpoint"""
        try:
            # Convert to CameraEvent request format
            event_request = CameraEventRequest(**event)
            
            # Call the webhook endpoint logic directly
            store = get_store()
            settings_obj = get_settings()
            
            # Convert to CameraEvent
            camera_event = CameraEvent(
                event_id=event_request.event_id,
                camera_id=event_request.camera_id,
                ts=datetime.fromisoformat(event_request.ts),
                zone_id=event_request.zone_id,
                event_type=event_request.event_type,
                confidence=event_request.confidence,
                severity=event_request.severity,
                clip_url=event_request.clip_url,
                snapshot_url=event_request.snapshot_url,
                metadata=event_request.metadata,
            )
            
            # Store event
            store.append_event(camera_event)
            
            # Process into incident
            incident = process_camera_event(camera_event, store, settings_obj)
            
            # Build plan, validate, compile alert
            config = VantageConfig(
                min_confidence_for_notify=settings_obj.min_confidence_for_notify,
                high_severity_threshold=settings_obj.high_severity_threshold,
            )
            
            plan = build_incident_plan(incident, config)
            validation = validate_incident_plan(plan, incident, config)
            
            alert = None
            if validation.passed:
                alert = compile_alert(plan, incident, config)
            
            # Store incident with metadata
            metadata = {
                "plan": {
                    "summary": plan.summary_1line,
                    "severity": plan.severity,
                    "confidence": plan.confidence,
                    "uncertainty_notes": plan.uncertainty_notes,
                    "recommended_next_step": plan.recommended_next_step.value,
                    "requires_human_approval": plan.requires_human_approval,
                    "action_risk_flags": plan.action_risk_flags,
                    "evidence_refs": plan.evidence_refs,
                },
                "validation": {
                    "status": validation.status.value,
                    "passed": validation.passed,
                    "violations": validation.violations,
                    "warnings": validation.warnings,
                },
            }
            
            if alert:
                metadata["alert"] = {
                    "title": alert.title,
                    "body": alert.body,
                    "operator_actions": alert.operator_actions,
                    "evidence_refs": alert.evidence_refs,
                    "disclaimer": alert.disclaimer,
                }
            
            store.upsert_incident(incident, metadata)
            
            return {"incident_id": incident.incident_id}
            
        except Exception as e:
            print(f"[Simulator] Failed to process event: {e}")
            return {"error": str(e)}
    
    try:
        await manager.start(
            scenario=scenario,
            rate_per_min=request.rate_per_min,
            seed=request.seed,
            event_callback=event_callback
        )
        
        return {
            "status": "started",
            "scenario": request.scenario,
            "rate_per_min": request.rate_per_min,
            "seed": request.seed,
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@app.post("/sim/stop")
async def stop_simulator(current_user: User = Depends(require_role([Role.ADMIN]))):
    """Stop event simulator"""
    manager = get_simulator_manager()
    
    await manager.stop()
    
    return {"status": "stopped"}


@app.get("/sim/status")
async def get_simulator_status(current_user: User = Depends(get_current_user)):
    """Get simulator status and statistics"""
    manager = get_simulator_manager()
    
    return manager.get_status()


@app.post("/sim/replay")
async def replay_events(
    request: SimulatorReplayRequest,
    current_user: User = Depends(require_role([Role.ADMIN]))  # Admin only
):
    """
    Replay events from JSONL data or file.
    
    Posts each event to /webhook/camera-event endpoint.
    """
    # Get JSONL data
    if request.jsonl_data:
        lines = request.jsonl_data.strip().split('\n')
    elif request.file_path:
        try:
            with open(request.file_path, 'r') as f:
                lines = f.readlines()
        except FileNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"File not found: {request.file_path}"
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to read file: {str(e)}"
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must provide either jsonl_data or file_path"
        )
    
    # Parse and replay events
    events_replayed = 0
    incidents_created = []
    errors = []
    
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        
        try:
            event_data = json.loads(line)
            
            # Validate event
            event_request = CameraEventRequest(**event_data)
            
            # Post to webhook (reuse logic)
            store = get_store()
            settings_obj = get_settings()
            
            camera_event = CameraEvent(
                event_id=event_request.event_id,
                camera_id=event_request.camera_id,
                ts=datetime.fromisoformat(event_request.ts),
                zone_id=event_request.zone_id,
                event_type=event_request.event_type,
                confidence=event_request.confidence,
                severity=event_request.severity,
                clip_url=event_request.clip_url,
                snapshot_url=event_request.snapshot_url,
                metadata=event_request.metadata,
            )
            
            store.append_event(camera_event)
            incident = process_camera_event(camera_event, store, settings_obj)
            
            config = VantageConfig(
                min_confidence_for_notify=settings_obj.min_confidence_for_notify,
                high_severity_threshold=settings_obj.high_severity_threshold,
            )
            
            plan = build_incident_plan(incident, config)
            validation = validate_incident_plan(plan, incident, config)
            
            alert = None
            if validation.passed:
                alert = compile_alert(plan, incident, config)
            
            metadata = {
                "plan": {
                    "summary": plan.summary_1line,
                    "severity": plan.severity,
                    "confidence": plan.confidence,
                    "recommended_next_step": plan.recommended_next_step.value,
                    "requires_human_approval": plan.requires_human_approval,
                },
                "validation": {
                    "status": validation.status.value,
                    "passed": validation.passed,
                },
            }
            
            if alert:
                metadata["alert"] = {
                    "title": alert.title,
                    "body": alert.body,
                }
            
            store.upsert_incident(incident, metadata)
            
            events_replayed += 1
            if incident.incident_id not in incidents_created:
                incidents_created.append(incident.incident_id)
            
        except json.JSONDecodeError as e:
            errors.append(f"Line {i+1}: Invalid JSON - {str(e)}")
        except Exception as e:
            errors.append(f"Line {i+1}: {str(e)}")
    
    return {
        "status": "completed",
        "events_replayed": events_replayed,
        "incidents_created": len(incidents_created),
        "errors": errors,
    }


# ── Training Stats ──────────────────────────────────────────────

# ── Camera Discovery ────────────────────────────────────────────

@app.post("/cameras/scan")
async def scan_for_cameras(
    verify: bool = False,
    current_user: User = Depends(get_current_user),
):
    """Scan the local network for IP cameras (ONVIF, RTSP, mDNS)."""
    from alibi.cameras.network_scanner import get_network_scanner

    scanner = get_network_scanner()
    if scanner.is_scanning:
        return {"status": "already_scanning", "progress": scanner.progress}

    cameras = scanner.scan_all(timeout=15.0, verify=verify)
    return {
        "status": "complete",
        "cameras": [c.to_dict() for c in cameras],
        "count": len(cameras),
        "new_cameras": len([c for c in cameras if not c.already_registered]),
    }


@app.get("/cameras/scan/status")
async def scan_status(current_user: User = Depends(get_current_user)):
    """Get current network scan progress."""
    from alibi.cameras.network_scanner import get_network_scanner

    scanner = get_network_scanner()
    return scanner.progress


class AddDiscoveredRequest(BaseModel):
    ip: str
    port: int = 554
    rtsp_url: str = ""
    name: str = ""
    source_type: str = "rtsp"
    location: str = ""
    username: str = ""
    password: str = ""
    vendor: str = ""       # brand hint from discovery, for URL resolution
    manufacturer: str = ""
    site_id: str = ""      # optional — link this camera to a protected site


@app.post("/cameras/add-discovered")
async def add_discovered_camera(
    req: AddDiscoveredRequest,
    current_user: User = Depends(get_current_user),
):
    """One-click add a discovered camera to the registry.

    Resolves the correct brand-specific RTSP URL from credentials where possible
    (a default like /stream1 fails on most real cameras — Dahua/Hikvision/etc.
    each use their own path)."""
    from alibi.cameras.camera_store import get_camera_store, Camera, slugify
    from alibi.cameras.rtsp_resolver import resolve_for_discovered

    store = get_camera_store()
    # Always fold the IP into the id — discovered cameras often share a name
    # ("Dahua"), which would otherwise collide and overwrite each other.
    ip_suffix = req.ip.replace('.', '-')
    base = slugify(req.name) if req.name else "camera"
    camera_id = f"{base}-{ip_suffix}"

    from urllib.parse import quote
    rtsp_url = req.rtsp_url

    # Prefer a resolved brand-specific URL when we have credentials + a brand.
    resolved = resolve_for_discovered(
        {"ip": req.ip, "port": req.port, "vendor": req.vendor,
         "manufacturer": req.manufacturer, "name": req.name},
        username=req.username, password=req.password, stream="main",
    ) if req.username else None

    if resolved:
        rtsp_url = resolved
    elif req.username and rtsp_url and "://" in rtsp_url:
        # Fallback: inject credentials into the discovered URL as-is.
        cred = f"{quote(req.username)}:{quote(req.password)}@"
        rtsp_url = rtsp_url.replace("rtsp://", f"rtsp://{cred}", 1)

    camera = Camera(
        camera_id=camera_id,
        name=req.name or f"Camera {req.ip}",
        source=rtsp_url or f"rtsp://{req.ip}:{req.port}/stream1",
        source_type=req.source_type,
        enabled=True,
        location=req.location,
        status="unknown",
        vms_config={
            "host": req.ip,
            "port": req.port,
            "username": req.username,
            "password": req.password,
        } if req.username else {},
    )

    store.add(camera)
    _link_camera_to_site(getattr(req, "site_id", ""), camera.camera_id)
    return {"status": "ok", "camera": camera.to_dict()}


# ── Camera Bridge (scan a user's own WiFi via a local agent) ─────
#
# A cloud-hosted Vantage cannot scan the user's LAN. A small "bridge" agent runs
# on that network, connects OUTBOUND, and does the scan locally. Admin mints a
# pairing code; the agent redeems it; the console enqueues scan jobs the agent
# polls and answers. See alibi/cameras/bridge.py.

def _require_bridge(
    x_bridge_id: str = Header(None),
    x_bridge_token: str = Header(None),
):
    """Authenticate an agent request via its bridge id + token headers."""
    from alibi.cameras.bridge import get_bridge_registry
    if not (x_bridge_id and x_bridge_token) or not get_bridge_registry().authenticate(
        x_bridge_id, x_bridge_token
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bridge credentials")
    return x_bridge_id


class BridgeRegisterRequest(BaseModel):
    code: str
    name: str = "Vantage Bridge"
    site_hint: str = ""


class BridgeScanRequest(BaseModel):
    cidr: Optional[str] = None
    # Optional camera login. With it, the recorder asks ONVIF cameras for their
    # real stream URLs instead of guessing vendor RTSP paths, so cameras arrive
    # already configured. Passed to the recorder for that one lookup and not
    # stored on the job.
    username: Optional[str] = None
    password: Optional[str] = None


class BridgeResultsRequest(BaseModel):
    cameras: List[dict] = Field(default_factory=list)
    error: str = ""


# --- Admin (console) side ---------------------------------------- #

@app.post("/cameras/bridge/pair", tags=["Camera Bridge"])
async def bridge_pair(current_user: User = Depends(require_role([Role.ADMIN]))):
    """Mint a single-use pairing code + the one-line setup command for the agent."""
    from alibi.cameras.bridge import get_bridge_registry, PAIRING_TTL_MINUTES
    pc = get_bridge_registry().create_pairing_code(created_by=current_user.username)
    return {
        "code": pc.code,
        "expires_at": pc.expires_at,
        "expires_in_minutes": PAIRING_TTL_MINUTES,
        # The agent binary/script is a later slice; this is the intended shape.
        "setup_hint": f"Run the Vantage Bridge on the network you want to scan and pair it with code {pc.code}.",
    }


@app.get("/cameras/bridge", tags=["Camera Bridge"])
async def bridge_list(current_user: User = Depends(get_current_user)):
    """List paired bridges + their online status."""
    from alibi.cameras.bridge import get_bridge_registry
    return {"bridges": get_bridge_registry().list_bridges()}


class BridgeRenameRequest(BaseModel):
    name: str


@app.patch("/cameras/bridge/{bridge_id}", tags=["Camera Bridge"])
async def bridge_rename(
    bridge_id: str,
    req: BridgeRenameRequest,
    current_user: User = Depends(require_role([Role.ADMIN])),
):
    """Relabel a recording PC (admin only)."""
    from alibi.cameras.bridge import get_bridge_registry
    b = get_bridge_registry().rename_bridge(bridge_id, req.name)
    if b is None:
        raise HTTPException(status_code=404, detail="PC not found")
    return b.public_dict()


@app.delete("/cameras/bridge/{bridge_id}", tags=["Camera Bridge"])
async def bridge_remove(
    bridge_id: str,
    current_user: User = Depends(require_role([Role.ADMIN])),
):
    """Unpair a recording PC (admin only). Its token stops working immediately;
    to record from it again you re-download and run the recorder. Makes swapping
    the recording PC (e.g. a temporary Mac → the always-on box) a one-click job."""
    from alibi.cameras.bridge import get_bridge_registry
    if not get_bridge_registry().remove_bridge(bridge_id):
        raise HTTPException(status_code=404, detail="PC not found")
    get_store().append_audit("bridge_removed",
                             {"bridge_id": bridge_id, "user": current_user.username})
    return {"status": "removed", "bridge_id": bridge_id}


@app.get("/cameras/bridge/download", tags=["Camera Bridge"])
async def bridge_download(
    request: Request,
    current_user: User = Depends(require_role([Role.ADMIN])),
):
    """Serve the Vantage Bridge agent, personalized with this Vantage's URL and a
    fresh single-use pairing code baked in — so the user just downloads and runs
    it (no code to type). The agent auto-pairs on first launch."""
    import os as _os
    from fastapi.responses import Response
    from alibi.cameras import bridge_agent
    from alibi.cameras.bridge import get_bridge_registry

    pc = get_bridge_registry().create_pairing_code(created_by=current_user.username)
    base_url = str(request.base_url).rstrip("/")

    with open(bridge_agent.__file__, "r") as f:
        src = f.read()

    # Bake in the defaults; the env-var override still works.
    src = src.replace(
        'VANTAGE_URL = os.environ.get("VANTAGE_URL", "https://vantage.developai.co.za")',
        f'VANTAGE_URL = os.environ.get("VANTAGE_URL", "{base_url}")',
    ).replace(
        'PAIRING_CODE = os.environ.get("VANTAGE_PAIRING_CODE", "")',
        f'PAIRING_CODE = os.environ.get("VANTAGE_PAIRING_CODE", "{pc.code}")',
    )

    return Response(
        content=src,
        media_type="text/x-python",
        headers={"Content-Disposition": 'attachment; filename="vantage_bridge.py"'},
    )


def _bake_agent_config(src: str, base_url: str, code: str) -> str:
    """Bake this Vantage's URL + a fresh pairing code into the bridge agent
    source (env-var overrides still work)."""
    return src.replace(
        'VANTAGE_URL = os.environ.get("VANTAGE_URL", "https://vantage.developai.co.za")',
        f'VANTAGE_URL = os.environ.get("VANTAGE_URL", "{base_url}")',
    ).replace(
        'PAIRING_CODE = os.environ.get("VANTAGE_PAIRING_CODE", "")',
        f'PAIRING_CODE = os.environ.get("VANTAGE_PAIRING_CODE", "{code}")',
    )


def _build_recorder_zipapp(base_url: str, code: str) -> bytes:
    """Build the personalized recorder zipapp (recorder + bridge + agent +
    __main__), URL & pairing code baked in. Returns the .pyz bytes."""
    import io
    import zipfile
    from alibi.cameras import recorder, bridge_agent, record_agent, onvif, local_vision
    with open(recorder.__file__) as f:
        recorder_src = f.read()
    with open(onvif.__file__) as f:
        onvif_src = f.read()
    with open(local_vision.__file__) as f:
        local_vision_src = f.read()
    with open(record_agent.__file__) as f:
        record_agent_src = f.read()
    with open(bridge_agent.__file__) as f:
        bridge_agent_src = _bake_agent_config(f.read(), base_url, code)
    main_src = "import sys\nimport record_agent\nsys.exit(record_agent.main())\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("recorder.py", recorder_src)
        z.writestr("onvif.py", onvif_src)          # ONVIF stream-URL lookup
        z.writestr("local_vision.py", local_vision_src)   # free offline scene description
        z.writestr("bridge_agent.py", bridge_agent_src)
        z.writestr("record_agent.py", record_agent_src)
        z.writestr("__main__.py", main_src)
    return buf.getvalue()


_LAUNCHER_MARKER = "#___VANTAGE_PAYLOAD___"


def _mac_launcher(zip_b64: str) -> str:
    """A double-clickable macOS .command that extracts the embedded recorder and
    runs it — no typing. The base64 zipapp is appended after the marker."""
    return (
        "#!/bin/bash\n"
        "# Vantage Recorder — double-click to run. Records this network's cameras.\n"
        "set -e\n"
        'DIR="$HOME/VantageRecorder"\n'
        'mkdir -p "$DIR/rec"\n'
        'echo "Setting up the Vantage recorder…"\n'
        # everything after the marker line is the base64 payload
        f"awk 'f{{print}} /^{_LAUNCHER_MARKER}$/{{f=1}}' \"$0\" | base64 --decode > \"$DIR/vantage_recorder.pyz\"\n"
        'if ! command -v python3 >/dev/null 2>&1; then\n'
        '  echo "" ; echo "Python 3 is needed. Install it from https://www.python.org/downloads/ then double-click this file again."\n'
        '  read -n 1 -s -r -p "Press any key to close." ; exit 1\n'
        'fi\n'
        'if ! command -v ffmpeg >/dev/null 2>&1; then\n'
        '  echo "" ; echo "ffmpeg is needed. Install Homebrew (https://brew.sh) then run:  brew install ffmpeg"\n'
        '  read -n 1 -s -r -p "Press any key to close." ; exit 1\n'
        'fi\n'
        'echo "Recorder running — recording to $DIR/rec. Leave this window open."\n'
        'exec python3 "$DIR/vantage_recorder.pyz" --dir "$DIR/rec" --max-gb 200 --max-days 30\n'
        f"{_LAUNCHER_MARKER}\n"
        f"{zip_b64}\n"
    )


def _windows_launcher(zip_b64: str) -> str:
    """A double-clickable Windows .bat that extracts the embedded recorder (via
    PowerShell) and runs it."""
    ps = (
        "$ErrorActionPreference='Stop';"
        "$d=Join-Path $env:USERPROFILE 'VantageRecorder';"
        "New-Item -ItemType Directory -Force -Path (Join-Path $d 'rec')|Out-Null;"
        "$b='" + zip_b64 + "';"
        "[IO.File]::WriteAllBytes((Join-Path $d 'vantage_recorder.pyz'),[Convert]::FromBase64String($b));"
        "python (Join-Path $d 'vantage_recorder.pyz') '--dir' (Join-Path $d 'rec') '--max-gb' '200' '--max-days' '30'"
    )
    return (
        "@echo off\r\n"
        "REM Vantage Recorder - double-click to run.\r\n"
        "echo Setting up the Vantage recorder...\r\n"
        f"powershell -NoProfile -ExecutionPolicy Bypass -Command \"{ps}\"\r\n"
        "pause\r\n"
    )


@app.get("/cameras/bridge/download-launcher", tags=["Camera Bridge"])
async def bridge_download_launcher(
    request: Request,
    platform: str = "mac",
    current_user: User = Depends(require_role([Role.ADMIN])),
):
    """A double-clickable launcher for THIS computer — the recorder embedded, so
    the owner downloads one file and double-clicks it (no terminal). macOS gets a
    .command, Windows a .bat."""
    import base64
    from fastapi.responses import Response
    from alibi.cameras.bridge import get_bridge_registry

    pc = get_bridge_registry().create_pairing_code(created_by=current_user.username)
    base_url = str(request.base_url).rstrip("/")
    zip_b64 = base64.b64encode(_build_recorder_zipapp(base_url, pc.code)).decode()

    if platform == "windows":
        body, filename = _windows_launcher(zip_b64), "Vantage Recorder.bat"
    else:
        body, filename = _mac_launcher(zip_b64), "Vantage Recorder.command"
    return Response(
        content=body, media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/cameras/bridge/download-recorder", tags=["Camera Bridge"])
async def bridge_download_recorder(
    request: Request,
    current_user: User = Depends(require_role([Role.ADMIN])),
):
    """Serve the Vantage recording agent as a single self-contained zipapp,
    personalized with this Vantage's URL + a fresh pairing code. The PC owner
    runs ONE file — `python vantage_recorder.pyz` — and every camera records to
    that PC, auto-pairing on first launch. Bundles the recorder engine, the
    bridge connection helpers, and the record-agent orchestration."""
    from fastapi.responses import Response
    from alibi.cameras.bridge import get_bridge_registry

    pc = get_bridge_registry().create_pairing_code(created_by=current_user.username)
    base_url = str(request.base_url).rstrip("/")

    # Single source of truth for the zipapp contents — the helper bundles the
    # recorder engine (incl. onvif.py) + bridge + agent, config baked in. The
    # endpoint used to inline a stale copy that referenced an unread `onvif_src`
    # and 500'd; delegating fixes that and keeps one builder.
    payload = _build_recorder_zipapp(base_url, pc.code)

    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="vantage_recorder.pyz"'},
    )


@app.post("/cameras/bridge/{bridge_id}/scan", tags=["Camera Bridge"])
async def bridge_scan(
    bridge_id: str,
    req: BridgeScanRequest,
    current_user: User = Depends(require_role([Role.ADMIN])),
):
    """Enqueue a scan on a bridge. The agent picks it up and reports back."""
    from alibi.cameras.bridge import get_bridge_registry
    reg = get_bridge_registry()
    bridge = reg.get_bridge(bridge_id)
    if not bridge:
        raise HTTPException(status_code=404, detail="Bridge not found")
    if not bridge.is_online():
        raise HTTPException(status_code=409, detail="Bridge is offline — start the Vantage Bridge on that network")
    params = {}
    if req.cidr:
        params["cidr"] = req.cidr
    if req.username:
        # Lets the agent run ONVIF GetStreamUri; the camera names its own URL.
        params["username"] = req.username
        params["password"] = req.password or ""
    job = reg.enqueue_scan(bridge_id, params=params)
    return {"job_id": job.job_id, "status": job.status,
            "onvif_lookup": bool(req.username)}


@app.get("/cameras/bridge/scan/{job_id}", tags=["Camera Bridge"])
async def bridge_scan_status(
    job_id: str,
    current_user: User = Depends(get_current_user),
):
    """Poll a scan job for status + discovered cameras."""
    from alibi.cameras.bridge import get_bridge_registry
    job = get_bridge_registry().get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.public_dict()


@app.get("/cameras/bridge/{bridge_id}/latest-scan", tags=["Camera Bridge"])
async def bridge_latest_scan(
    bridge_id: str,
    current_user: User = Depends(get_current_user),
):
    """The most recent completed scan for a bridge (results), or null. Lets the
    console show the last discovered cameras on page load — resilient to a
    browser tab that froze mid-poll."""
    from alibi.cameras.bridge import get_bridge_registry
    job = get_bridge_registry().latest_completed_scan(bridge_id)
    return {"job": job.public_dict() if job else None}


# --- Agent (bridge) side ----------------------------------------- #

@app.post("/cameras/bridge/register", tags=["Camera Bridge"])
async def bridge_register(req: BridgeRegisterRequest):
    """Agent redeems a pairing code -> receives its bridge id + token (once)."""
    from alibi.cameras.bridge import get_bridge_registry
    creds = get_bridge_registry().redeem_pairing_code(
        req.code, name=req.name, site_hint=req.site_hint
    )
    if not creds:
        raise HTTPException(status_code=400, detail="Invalid or expired pairing code")
    return creds  # {bridge_id, token} — token shown only here


@app.post("/cameras/bridge/heartbeat", tags=["Camera Bridge"])
async def bridge_heartbeat(
    payload: dict = Body(default={}),
    bridge_id: str = Depends(_require_bridge),
):
    """Agent keep-alive."""
    from alibi.cameras.bridge import get_bridge_registry
    get_bridge_registry().heartbeat(bridge_id, site_hint=payload.get("site_hint"))
    return {"status": "ok"}


@app.get("/cameras/bridge/jobs", tags=["Camera Bridge"])
async def bridge_next_job(bridge_id: str = Depends(_require_bridge)):
    """Agent polls for the next pending scan job (also refreshes heartbeat)."""
    from alibi.cameras.bridge import get_bridge_registry
    reg = get_bridge_registry()
    reg.heartbeat(bridge_id)
    job = reg.claim_next_job(bridge_id)
    return {"job": job.public_dict() if job else None}


@app.post("/cameras/bridge/jobs/{job_id}/results", tags=["Camera Bridge"])
async def bridge_submit_results(
    job_id: str,
    req: BridgeResultsRequest,
    bridge_id: str = Depends(_require_bridge),
):
    """Agent posts scan results (discovered cameras) for a job."""
    from alibi.cameras.bridge import get_bridge_registry
    ok = get_bridge_registry().submit_results(bridge_id, job_id, req.cameras, error=req.error)
    if not ok:
        raise HTTPException(status_code=404, detail="Job not found for this bridge")
    return {"status": "ok"}


def _build_record_targets() -> list:
    """The cameras a recording PC should capture: enabled RTSP cameras, each with
    its resolved MAIN (record) URL and a derived SUB (motion) URL. The main URL
    already carries encoded credentials (set when the camera was added)."""
    from alibi.cameras.camera_store import get_camera_store
    from alibi.cameras.rtsp_resolver import derive_substream_url

    targets = []
    for cam in get_camera_store().list_all():
        if not cam.enabled:
            continue
        source = (cam.source or "").strip()
        if not source.lower().startswith("rtsp://"):
            continue    # skip mobile/VMS/other sources — the recorder speaks RTSP
        targets.append({
            "camera_id": cam.camera_id,
            "name": cam.name,
            "record_url": source,
            "motion_url": derive_substream_url(source) or source,
        })
    return targets


class BridgeStorageRequest(BaseModel):
    storage: dict


@app.post("/cameras/bridge/storage", tags=["Camera Bridge"])
async def bridge_report_storage(req: BridgeStorageRequest,
                                bridge_id: str = Depends(_require_bridge)):
    """The agent reports what it's storing on the PC (folder, size, per-camera)."""
    from alibi.cameras.bridge import get_bridge_registry
    get_bridge_registry().set_storage(bridge_id, req.storage)
    return {"status": "ok"}


@app.get("/cameras/bridge/record-targets", tags=["Camera Bridge"])
async def bridge_record_targets(bridge_id: str = Depends(_require_bridge)):
    """The recording agent pulls the cameras it should record, each with a
    resolved record + motion RTSP URL. Agent-authenticated (bridge token)."""
    return {"targets": _build_record_targets()}


# ── Live view (on-demand HLS) ───────────────────────────────────
#
# The recording PC streams a camera to the cloud ONLY while a viewer is watching
# it. The console pings /watch to keep it alive; the agent polls the active
# watches, runs ffmpeg (RTSP -> H.264 HLS) for each, and PUTs the playlist +
# segments; the browser plays them. Nothing runs when nobody is watching.
# See alibi/cameras/hls_relay.py.

def _record_url_for(camera_id: str) -> Optional[str]:
    from alibi.cameras.camera_store import get_camera_store
    cam = get_camera_store().get(camera_id)
    if cam and (cam.source or "").lower().startswith("rtsp://"):
        return cam.source
    return None


@app.post("/cameras/{camera_id}/watch", tags=["Cameras"])
async def watch_camera(camera_id: str, current_user: User = Depends(get_current_user)):
    """Register interest in a camera's live view (call repeatedly as a heartbeat
    while the player is open). The agent starts streaming it within ~2s."""
    from alibi.cameras.hls_relay import get_hls_relay
    if _record_url_for(camera_id) is None:
        raise HTTPException(status_code=404, detail="Camera not found or not an RTSP camera")
    expiry = get_hls_relay().request_watch(camera_id)
    return {"status": "watching", "camera_id": camera_id, "expires_at": expiry}


@app.get("/cameras/{camera_id}/hls/{filename}", tags=["Cameras"])
async def get_hls_file(camera_id: str, filename: str,
                       current_user: User = Depends(get_current_user)):
    """Serve an HLS playlist or segment for the browser player."""
    from fastapi.responses import Response
    from alibi.cameras.hls_relay import get_hls_relay, is_safe_hls_name
    if not is_safe_hls_name(filename):
        raise HTTPException(status_code=400, detail="Bad filename")
    data = get_hls_relay().get_file(camera_id, filename)
    if data is None:
        # 404 while the agent is still spinning ffmpeg up — the player retries.
        raise HTTPException(status_code=404, detail="Not ready")
    media = "application/vnd.apple.mpegurl" if filename.endswith(".m3u8") else "video/mp2t"
    return Response(content=data, media_type=media,
                    headers={"Cache-Control": "no-store"})


@app.get("/cameras/bridge/watch-requests", tags=["Camera Bridge"])
async def bridge_watch_requests(bridge_id: str = Depends(_require_bridge)):
    """The agent polls which cameras are being watched right now, each with the
    RTSP URL to stream. We hand it the low-res SUB stream where we can derive it
    (cheap to decode + send); otherwise the main stream."""
    from alibi.cameras.hls_relay import get_hls_relay
    from alibi.cameras.rtsp_resolver import derive_substream_url
    watched = get_hls_relay().active_watches()
    cams = []
    for cid in watched:
        main = _record_url_for(cid)
        if not main:
            continue
        cams.append({"camera_id": cid, "url": derive_substream_url(main) or main})
    return {"cameras": cams}


@app.put("/cameras/bridge/hls/{camera_id}/{filename}", tags=["Camera Bridge"])
async def bridge_put_hls(camera_id: str, filename: str, request: Request,
                         bridge_id: str = Depends(_require_bridge)):
    """The agent uploads an HLS playlist/segment for a watched camera."""
    from alibi.cameras.hls_relay import get_hls_relay
    body = await request.body()
    if not get_hls_relay().put_file(camera_id, filename, body):
        raise HTTPException(status_code=400, detail="Bad filename")
    return {"status": "ok", "bytes": len(body)}


# ── Frame AI (phase 4): motion still -> vision -> incident ───────
#
# The agent uploads motion-triggered stills (a few seconds apart, only when
# something moves). The cloud runs vision on each and, when it sees a person /
# vehicle / safety concern, creates an incident that the explainer + area
# context + security brief already narrate. Motion-gated on the edge and
# throttled here, so idle scenes cost nothing. See cameras/frame_analyzer.py.

@app.post("/cameras/bridge/frame", tags=["Camera Bridge"])
async def bridge_ingest_frame(camera_id: str, request: Request,
                              bridge_id: str = Depends(_require_bridge)):
    """The agent posts a motion still; the cloud analyses it and may raise an
    incident. Throttled per camera so a motion burst can't spam the models.

    Two layers run on the one (already motion-gated, throttled) frame:
      * the VLM scene description (narration), and
      * the structured CV stack — the same detection/plate/face/vehicle-ReID
        pipeline the phone endpoint uses — which WRITES the sighting stores the
        pattern/history engine reads, and surfaces hotlist/watchlist hits.
    """
    import time as _time
    from fastapi.concurrency import run_in_threadpool
    from alibi.cameras import frame_analyzer as fa
    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="Empty frame")
    if not fa.should_analyze(camera_id, _time.time()):
        return {"analyzed": False, "reason": "throttled"}

    # The recorder may describe the frame LOCALLY (free Ollama on the PC) and
    # send the description with it — use that instead of a paid Claude call.
    agent_scene = request.headers.get("X-Vantage-Scene") or None
    if agent_scene:
        agent_scene = agent_scene.strip()[:1500] or None

    now = datetime.utcnow()
    # Store the evidence frame FIRST so sightings can reference it — a face
    # sighting is far more useful to a reviewer when it points at the still it
    # came from. Every analysed frame is stored regardless.
    frame_id = fa.store_frame(data)

    # The decode + structured CV (detection/plates/faces/ReID) + VLM are all
    # synchronous and heavy — run them in a worker thread so they never block the
    # event loop (which is also serving live-view HLS). Structured intel writes the
    # sighting stores; both layers degrade to empty/None on failure.
    def _analyze():
        frame = fa.decode(data)
        if frame is None:
            return None, None, None
        intel_ = None
        try:
            from alibi.vision import frame_intelligence as fi
            intel_ = fi.analyze_and_record(frame, camera_id, now, frame_id=frame_id)
        except Exception as e:
            print(f"[frame-ai] structured intelligence failed: {e}")
        # COST GATE: the local detector is free, the vision model is not. Only
        # spend a paid VLM call on a frame where the detector actually found a
        # person/vehicle (or a hotlist/watchlist hit). Wind, rain, and shifting
        # shadows trip the motion trigger constantly and are worth $0 to narrate.
        # If the structured layer is unavailable we fall back to always calling,
        # so a CV failure degrades to the old behaviour rather than going blind.
        #
        # Judge newsworthiness BEFORE the paid call: the scene baseline already
        # knows the parked SUV is furniture, and narrating furniture was the
        # single biggest credit burner (~$0.01 per motion frame, all day). The
        # judgment is passed into decide_event so the baseline isn't taught the
        # same frame twice.
        news = fa.judge_newsworthiness(camera_id, intel_) if intel_ else None
        wants_attrs = bool(intel_ and int(intel_.get("vehicle_count") or 0) > 0)
        worth_paying = _worth_narrating(intel_) and (news is None or news[0])
        # Owner's spend controls (Costs page): vehicle-only frames may be set to
        # never earn narration, and paid calls are rate-capped per camera.
        # People and hotlist/watchlist hits always qualify.
        if worth_paying and intel_ is not None:
            try:
                from alibi.ai_config import get_ai_config, narration_allowed
                from alibi.cost_tracker import todays_spend
                cfg = get_ai_config()
                flagged_ = bool(intel_.get("hotlist_hit") or intel_.get("watchlist_hit"))
                has_person_ = int(intel_.get("person_count") or 0) > 0
                has_vehicle_ = int(intel_.get("vehicle_count") or 0) > 0
                normal_hours = None
                try:
                    from alibi.site_profile import get_site_profile_store
                    _sites = get_site_profile_store().list()
                    normal_hours = _sites[0].normal_hours if _sites else None
                except Exception:
                    pass
                local_minutes = ((now.hour * 60 + now.minute) + 120) % 1440  # SAST
                from alibi.ai_config import is_local_vision
                free_vision = is_local_vision(cfg.get("vision_model", ""))
                if not narration_allowed(cfg, has_person_, has_vehicle_, flagged_,
                                         local_minutes, todays_spend("vision"),
                                         normal_hours=normal_hours):
                    worth_paying = False
                # The per-camera gap throttle exists to bound PAID spend; a free
                # local model isn't rate-capped, so it describes every frame.
                if worth_paying and not free_vision and not fa.should_pay(
                        camera_id, _time.time(), cfg["paid_min_gap_seconds"], flagged=flagged_):
                    worth_paying = False
            except Exception as e:
                print(f"[frame-ai] ai_config unavailable: {e}")
        if worth_paying and agent_scene:
            # The recorder already described it locally (free) — use that; no
            # paid call. Derive the same lightweight fields the cloud path adds.
            objs = [o for o in ("person", "car", "truck", "motorcycle", "bike", "dog", "cat")
                    if o in agent_scene.lower()]
            analysis_ = {"description": agent_scene, "detected_objects": objs,
                         "safety_concern": any(w in agent_scene.lower() for w in
                                               ("fight", "weapon", "attack", "suspicious",
                                                "intruder", "danger", "emergency")),
                         "method": "agent_local_ollama"}
        else:
            analysis_ = (fa.analyze_frame(frame, want_vehicle_attrs=wants_attrs) or {}
                         if worth_paying else {})
        # Validate VLM-claimed badges against the reference catalog — an
        # unknown make is downgraded so the UI never shows a doubtful badge.
        if analysis_.get("vehicles"):
            try:
                from alibi.dataengine.vehicle_reference import validate_vehicle_attrs
                analysis_["vehicles"] = validate_vehicle_attrs(analysis_["vehicles"])
            except Exception:
                pass
        # Persist a vehicle sighting per detected vehicle (evidence frame + bbox
        # + VLM attributes when unambiguous) — feeds the Overview vehicles strip
        # and vehicle search.
        if wants_attrs and worth_paying:
            try:
                fa.record_vehicle_sightings(intel_, analysis_.get("vehicles"),
                                            camera_id, now, frame_id)
            except Exception as e:
                print(f"[frame-ai] vehicle sighting persist failed: {e}")
            # Local-data loop: log the crop + VLM guess for human review, so
            # confirmed rows become a locally-labelled training corpus.
            try:
                from alibi.vehicles.review_queue import enqueue_vehicle_guess
                enqueue_vehicle_guess(intel_, analysis_.get("vehicles"),
                                      camera_id, frame_id, now=now)
            except Exception as e:
                print(f"[frame-ai] review-queue enqueue failed: {e}")
        return intel_, analysis_, news

    intel, analysis, news = await run_in_threadpool(_analyze)
    if analysis is None:
        return {"analyzed": False, "reason": "decode_failed"}
    event = fa.decide_event(analysis, camera_id, now, frame_id, intel=intel,
                            newsworthiness=news)
    if event is None:
        return {"analyzed": True, "incident": None,
                "description": analysis.get("description", ""),
                "intel": _intel_summary(intel)}

    store = get_store()
    settings = get_settings()
    store.append_event(event)
    incident = process_camera_event(event, store, settings)

    # PERSIST the incident. process_camera_event only groups in memory and hands
    # back the object — every other ingest path follows it with upsert_incident,
    # and this one never did. The result: frames produced events and an incident
    # id, but nothing was ever written to incidents.jsonl, so the Incidents page,
    # the security brief and every incident-backed surface stayed empty forever
    # while the endpoint reported success.
    try:
        store.upsert_incident(incident, {
            "source": "frame_ai",
            "camera_id": event.camera_id,
            "event_type": event.event_type,
            "severity": event.severity,
            "description": (analysis or {}).get("description", ""),
            "intel": _intel_summary(intel),
        })
        store.append_audit("incident_processed", {
            "incident_id": incident.incident_id,
            "camera_id": event.camera_id,
            "source": "frame_ai",
        })
    except Exception as e:
        print(f"[frame-ai] could not persist incident: {e}")

    return {"analyzed": True, "incident": incident.incident_id,
            "event_type": event.event_type, "severity": event.severity,
            "intel": _intel_summary(intel)}


def _worth_narrating(intel) -> bool:
    """True if a frame earns a PAID vision call: the free local detector found a
    person/vehicle, or a hotlist/watchlist hit. `None` (structured CV
    unavailable) falls back to True so we never go blind."""
    if intel is None:
        return True
    return bool(intel.get("person_count") or intel.get("vehicle_count")
                or intel.get("hotlist_hit") or intel.get("watchlist_hit"))


def _intel_summary(intel):
    """Compact structured-CV summary for the agent's log / debugging."""
    if not intel:
        return None
    return {
        "person_count": intel.get("person_count", 0),
        "vehicle_count": intel.get("vehicle_count", 0),
        "plates": [p.get("display") or p.get("text") for p in (intel.get("plates") or [])],
        "hotlist_hit": intel.get("hotlist_hit", False),
        "watchlist_hit": intel.get("watchlist_hit", False),
        "cross_camera_alerts": len(intel.get("cross_camera_alerts") or []),
    }


@app.get("/cameras/frames/{frame_id}", tags=["Cameras"])
async def get_camera_frame(frame_id: str, current_user: User = Depends(get_current_user)):
    """Serve a stored evidence frame (the still behind an incident)."""
    from fastapi.responses import Response
    from alibi.cameras.frame_analyzer import get_frame
    data = get_frame(frame_id.replace(".jpg", ""))
    if data is None:
        raise HTTPException(status_code=404, detail="Frame not found")
    return Response(content=data, media_type="image/jpeg",
                    headers={"Cache-Control": "private, max-age=3600"})


# ── Sites (what Vantage is protecting) ──────────────────────────
#
# A "site" is the subject a deployment protects — a home, an office, or a
# neighbourhood. The subject type carries a built-in intelligence *posture*
# that tailors the whole intelligence layer (explainer, area context, patterns,
# and the security brief). See alibi/site_profile.py.

class SiteCreateRequest(BaseModel):
    name: str
    subject_type: str = "home"                 # home | office | neighbourhood
    area: str = ""                             # suburb/area — links to place-context (§9)
    address: str = ""
    timezone: str = "Africa/Johannesburg"
    normal_hours: dict = Field(default_factory=dict)
    camera_ids: list = Field(default_factory=list)
    notes: str = ""
    context: str = ""      # free-text intelligence context for the AI


class SiteUpdateRequest(BaseModel):
    name: Optional[str] = None
    subject_type: Optional[str] = None
    area: Optional[str] = None
    address: Optional[str] = None
    timezone: Optional[str] = None
    normal_hours: Optional[dict] = None
    camera_ids: Optional[list] = None
    notes: Optional[str] = None
    context: Optional[str] = None


def _site_payload(site) -> dict:
    """Serialize a SiteProfile plus its built-in posture (so the console can
    show what the intelligence layer will focus on for this site)."""
    from dataclasses import asdict
    data = asdict(site)
    data["posture"] = asdict(site.posture())
    return data


@app.get("/sites/postures", tags=["Sites"])
async def list_site_postures(current_user: User = Depends(get_current_user)):
    """The built-in intelligence postures per subject type — lets the console
    show 'what this protects, and what the AI will focus on' before a site is
    created."""
    from dataclasses import asdict
    from alibi.site_profile import POSTURES
    return {"postures": {k: asdict(v) for k, v in POSTURES.items()}}


@app.get("/sites", tags=["Sites"])
async def list_sites(current_user: User = Depends(get_current_user)):
    """List all protected sites with their postures."""
    from alibi.site_profile import get_site_profile_store
    sites = get_site_profile_store().list()
    return {"sites": [_site_payload(s) for s in sites]}


@app.post("/sites", tags=["Sites"])
async def create_site(
    req: SiteCreateRequest,
    current_user: User = Depends(require_role([Role.ADMIN])),
):
    """Create a protected site (admin only)."""
    from alibi.site_profile import get_site_profile_store
    site = get_site_profile_store().create(
        name=req.name,
        subject_type=req.subject_type,
        area=req.area,
        address=req.address,
        timezone=req.timezone,
        normal_hours=req.normal_hours,
        camera_ids=req.camera_ids,
        notes=req.notes,
        context=req.context,
    )
    get_store().append_audit("site_created",
                             {"site_id": site.site_id, "subject_type": site.subject_type,
                              "user": current_user.username})
    return _site_payload(site)


@app.get("/sites/{site_id}", tags=["Sites"])
async def get_site(site_id: str, current_user: User = Depends(get_current_user)):
    """Get one protected site."""
    from alibi.site_profile import get_site_profile_store
    site = get_site_profile_store().get(site_id)
    if site is None:
        raise HTTPException(status_code=404, detail="Site not found")
    return _site_payload(site)


# ── Security Advisor (Phase 4) ──────────────────────────────────
#
# "How do I improve my security?" — observed state in, prioritised plain-English
# recommendations out. Every one cites the fact that triggered it; a healthy
# deployment returns none. It advises on the SYSTEM, never on people.

@app.get("/advisor", tags=["Advisor"])
async def security_advisor(site_id: Optional[str] = None,
                           window_hours: int = 24,
                           current_user: User = Depends(get_current_user)):
    """Recommendations derived from the deployment's real state."""
    from alibi.advisor import build_recommendations, summarise

    state: Dict[str, Any] = {"window_hours": window_hours}

    # Recorders
    try:
        from alibi.cameras.bridge import get_bridge_registry
        # list_bridges() returns public dicts with a computed "online" key
        # (freshness of the last heartbeat) — not objects with an attribute.
        bridges = get_bridge_registry().list_bridges()
        state["recorders_total"] = len(bridges)
        state["recorders_online"] = sum(1 for b in bridges if b.get("online"))
    except Exception:
        pass

    # Cameras + which are on no site
    site_cam_ids: set = set()
    sites_state = []
    try:
        from alibi.site_profile import get_site_profile_store
        for s in get_site_profile_store().list():
            site_cam_ids.update(s.camera_ids or [])
            sites_state.append({
                "name": s.name,
                "camera_ids": list(s.camera_ids or []),
                "has_context": bool((s.context or "").strip()),
                "has_hours": bool((s.normal_hours or {}).get("open") or (s.normal_hours or {}).get("close")),
                "area": (s.area or "").strip(),
            })
        state["sites"] = sites_state
    except Exception:
        pass
    try:
        from alibi.cameras.camera_store import get_camera_store
        cams = get_camera_store().list_all()
        state["cameras_total"] = len(cams)
        state["cameras_unassigned"] = [c.camera_id for c in cams if c.camera_id not in site_cam_ids]
    except Exception:
        pass

    # Lists that only pay off once switched on
    try:
        from alibi.plates.hotlist_store import HotlistStore
        state["hotlist_count"] = HotlistStore().count()
    except Exception:
        pass
    try:
        from alibi.watchlist.watchlist_store import WatchlistStore
        state["watchlist_count"] = len(WatchlistStore().load_all())
    except Exception:
        pass
    try:
        from alibi.dataengine.user_sources import get_user_source_store
        state["intel_sources"] = len(get_user_source_store().list())
    except Exception:
        pass

    # Is the vision layer real, or the fallback?
    try:
        import os as _os
        state["vision_backend"] = "claude" if _os.getenv("ANTHROPIC_API_KEY") else (
            "openai" if _os.getenv("OPENAI_API_KEY") else "basic_cv")
    except Exception:
        pass

    # Blind spots for a specific site come from its brief's coverage
    if site_id:
        try:
            brief = await get_site_brief(site_id, window_hours=window_hours,
                                         current_user=current_user)
            state["quiet_cameras"] = (brief.get("coverage") or {}).get("quiet_cameras") or []
            state["incident_count"] = brief.get("incident_count", 0)
        except Exception:
            pass

    recs = build_recommendations(state)
    return {
        "summary": summarise(recs),
        "recommendations": [r.to_dict() for r in recs],
        "generated_ts": datetime.utcnow().isoformat(),
        "observed": {k: v for k, v in state.items() if k != "sites"},
        "note": ("Every recommendation is derived from your system's actual state and cites the "
                 "fact behind it. Advice is about coverage and configuration — never about people."),
    }


@app.get("/sites/{site_id}/brief", tags=["Sites"])
async def get_site_brief(
    site_id: str,
    window_hours: int = 24,
    current_user: User = Depends(get_current_user),
):
    """The site-tailored security brief — what has been happening in the window
    and what may be worth a human look, grounded in this site's real incidents
    and tuned to its posture. Honest empty state when the window is quiet."""
    from alibi.security_brief import generate_brief_for_site
    from alibi.ttl_cache import cached
    window_hours = max(1, min(int(window_hours or 24), 24 * 30))   # clamp 1h..30d
    # Cache 10 min: the brief makes a PAID Claude call to phrase the narrative,
    # so recomputing on every Advisor page view was both ~20s slow AND a repeat
    # spend. Incidents change slowly; 10 min is plenty fresh.
    result = cached(f"brief:{site_id}:{window_hours}", 600.0,
                    lambda: generate_brief_for_site(site_id, window_hours=window_hours))
    if result is None:
        raise HTTPException(status_code=404, detail="Site not found")
    return result.to_dict()


@app.put("/sites/{site_id}", tags=["Sites"])
async def update_site(
    site_id: str,
    req: SiteUpdateRequest,
    current_user: User = Depends(require_role([Role.ADMIN])),
):
    """Update a protected site (admin only)."""
    from alibi.site_profile import get_site_profile_store
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    site = get_site_profile_store().update(site_id, **updates)
    if site is None:
        raise HTTPException(status_code=404, detail="Site not found")
    return _site_payload(site)


@app.delete("/sites/{site_id}", tags=["Sites"])
async def delete_site(
    site_id: str,
    current_user: User = Depends(require_role([Role.ADMIN])),
):
    """Delete a protected site (admin only)."""
    from alibi.site_profile import get_site_profile_store
    if not get_site_profile_store().delete(site_id):
        raise HTTPException(status_code=404, detail="Site not found")
    get_store().append_audit("site_deleted",
                             {"site_id": site_id, "user": current_user.username})
    return {"status": "deleted", "site_id": site_id}


# ── System Storage ──────────────────────────────────────────────

@app.get("/system/storage")
async def get_storage_info(current_user: User = Depends(get_current_user)):
    """Get disk usage breakdown for all data stores."""
    from alibi.data_manager import get_data_manager

    manager = get_data_manager()
    usage = manager.get_disk_usage()
    return usage.to_dict()


@app.post("/system/cleanup")
async def run_cleanup(current_user: User = Depends(get_current_user)):
    """Run data rotation and cleanup."""
    from alibi.data_manager import get_data_manager

    manager = get_data_manager()
    results = manager.auto_rotate()
    return results


# ── Semantic Search ────────────────────────────────────────────

class SemanticSearchRequest(BaseModel):
    query: str
    limit: int = 20
    min_score: float = 0.15
    source: Optional[str] = None      # "camera_analysis", "red_flag", "intelligence"
    camera_id: Optional[str] = None
    hours: Optional[int] = None
    threat_level: Optional[str] = None  # "caution", "warning", "critical"


@app.post("/search/semantic")
async def semantic_search(
    req: SemanticSearchRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Natural language search across all stored security data.

    Examples:
    - "person in red jacket near entrance"
    - "suspicious vehicle at night"
    - "group of people running"
    """
    from alibi.semantic_search import get_semantic_search

    engine = get_semantic_search()
    results = engine.search(
        query=req.query,
        limit=req.limit,
        min_score=req.min_score,
        source_filter=req.source,
        camera_filter=req.camera_id,
        hours=req.hours,
        threat_filter=req.threat_level,
    )

    return {
        "query": req.query,
        "results": [r.to_dict() for r in results],
        "total": len(results),
    }


@app.get("/search/stats")
async def search_stats(current_user: User = Depends(get_current_user)):
    """Get semantic search index statistics."""
    from alibi.semantic_search import get_semantic_search
    return get_semantic_search().get_stats()


@app.post("/search/rebuild-index")
async def rebuild_search_index(current_user: User = Depends(get_current_user)):
    """Force rebuild the semantic search index."""
    from alibi.semantic_search import get_semantic_search
    return get_semantic_search().rebuild_index()


# ── Intelligence Search ───────────────────────────────────────

@app.get("/costs/summary", tags=["Costs"])
async def costs_summary(window_days: int = 30, current_user: User = Depends(get_current_user)):
    """Estimated service spend from recorded Claude token usage."""
    from alibi.cost_tracker import summary
    window_days = max(1, min(int(window_days or 30), 365))
    return summary(window_days=window_days)


class AiConfigUpdate(BaseModel):
    vision_model: Optional[str] = None
    paid_min_gap_seconds: Optional[int] = None
    narrate_vehicles: Optional[bool] = None
    narrate_people: Optional[bool] = None
    schedule: Optional[str] = None
    daily_budget_usd: Optional[float] = None


@app.get("/costs/ai-config", tags=["Costs"])
async def get_ai_config_endpoint(current_user: User = Depends(get_current_user)):
    """The owner's AI spend controls + the model menu with prices."""
    from alibi.ai_config import get_ai_config, VISION_MODELS
    return {"config": get_ai_config(), "vision_models": VISION_MODELS}


@app.put("/costs/ai-config", tags=["Costs"])
async def update_ai_config_endpoint(
    payload: AiConfigUpdate,
    current_user: User = Depends(require_role([Role.ADMIN])),
):
    """Change the vision model / paid-call cap / vehicle narration. Admin only,
    audited — these are direct spend dials."""
    from alibi.ai_config import set_ai_config, VISION_MODELS
    try:
        cfg = set_ai_config(payload.vision_model, payload.paid_min_gap_seconds,
                            payload.narrate_vehicles, payload.narrate_people,
                            payload.schedule, payload.daily_budget_usd)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    get_store().append_audit("ai_config_set", {"user": current_user.username, **cfg})
    return {"config": cfg, "vision_models": VISION_MODELS}


class VehicleLabelUpdate(BaseModel):
    entity_id: str
    label: str


@app.put("/vehicles/entity-label", tags=["Vehicles"])
async def set_vehicle_entity_label(
    payload: VehicleLabelUpdate,
    current_user: User = Depends(require_role([Role.SUPERVISOR, Role.ADMIN])),
):
    """Name a recurring vehicle ("Paul's Fortuner") — the owner saying "that
    one is mine". Identity only ever comes from the owner; empty label removes
    the name. Audited."""
    from alibi.patterns.familiarity import set_vehicle_label
    result = set_vehicle_label(payload.entity_id, payload.label,
                               set_by=current_user.username)
    get_store().append_audit("vehicle_labelled", {
        "user": current_user.username, "entity_id": payload.entity_id,
        "label": payload.label.strip() or None,
    })
    return {"entity_id": payload.entity_id, **(result or {"label": None})}


class CreditsUpdate(BaseModel):
    balance_usd: float


@app.put("/costs/credits", tags=["Costs"])
async def update_credits(
    payload: CreditsUpdate,
    current_user: User = Depends(require_role([Role.ADMIN])),
):
    """Record the API account's credit balance, as read by the owner from
    console.anthropic.com. The Anthropic API has no balance endpoint, so this
    entered figure — burned down against our tracked spend — is the honest
    source for "how much is left and when does it run out".

    Requires: Admin role
    """
    from alibi.cost_tracker import set_credits, credit_status
    if payload.balance_usd < 0:
        raise HTTPException(status_code=400, detail="balance_usd must be >= 0")
    set_credits(payload.balance_usd, set_by=current_user.username)
    get_store().append_audit("api_credits_set", {
        "user": current_user.username,
        "balance_usd": round(float(payload.balance_usd), 2),
    })
    return credit_status()


# ── Intel: owner-declared data sources ──────────────────────────
#
# "Feed the brain as you go." The owner declares a source from the console; the
# same boundary the code-declared registry enforces applies here — an allowed
# (non-personal) domain, a stated lawful basis, and a positive retention. The
# catalogue alongside it is the honest roadmap of routes we have researched but do
# NOT have yet, each with what it would actually take.

class UserSourceCreate(BaseModel):
    name: str
    domain: str
    lawful_basis: str
    retention_days: int
    description: str = ""
    endpoint: str = ""
    notes: str = ""


class UserSourceRecords(BaseModel):
    records: List[dict]


@app.get("/intelligence/ml-status", tags=["Intelligence"])
async def ml_status(current_user: User = Depends(get_current_user)):
    """The honest inventory: every module in the vision stack with its REAL
    availability, and every data-engine feed with its real record count and
    what (if anything) is blocking it. No aspirational entries marked live."""
    import importlib.util as _ilu
    from pathlib import Path as _P

    def _has(mod: str) -> bool:
        try:
            return _ilu.find_spec(mod) is not None
        except (ImportError, ValueError):
            return False

    from alibi.ai_config import get_ai_config
    cfg = get_ai_config()

    vision = [
        {"name": "D-FINE object detection", "purpose": "people / vehicles / objects per frame",
         "status": "active" if _has("onnxruntime") else "unavailable",
         "detail": "Apache-2.0, ONNX", "kind": "open_source"},
        {"name": "SCRFD face detection", "purpose": "find faces (gated on a detected person)",
         "status": "active" if _has("insightface") else "unavailable",
         "detail": "InsightFace, ONNX", "kind": "open_source"},
        {"name": "ArcFace embeddings", "purpose": "512-d face vectors for Faces + person history",
         "status": "active" if _has("insightface") else "unavailable",
         "detail": "InsightFace buffalo_l", "kind": "open_source"},
        {"name": "OSNet appearance ReID", "purpose": "link the SAME vehicle/person across sightings",
         "status": "active" if _has("torchreid") else "unavailable",
         "detail": "powers distinct-vehicle counts + familiar/new", "kind": "open_source"},
        {"name": "FastALPR plates", "purpose": "plate detect + OCR",
         "status": "active" if _has("fast_alpr") or _has("fast_plate_ocr") else "unavailable",
         "detail": "ONNX; reads validated against reference.plate_formats", "kind": "open_source"},
        {"name": f"Claude vision ({cfg['vision_model']})", "purpose": "scene narration + vehicle attributes",
         "status": "active",
         "detail": (f"paid; capped at 1 call/camera/{cfg['paid_min_gap_seconds']}s, "
                    f"vehicles {'narrated' if cfg['narrate_vehicles'] else 'not narrated'}"),
         "kind": "paid_api"},
        {"name": "Scene baseline", "purpose": "learn each camera's normal so furniture stays quiet",
         "status": "active", "detail": "own algorithm, per-camera medians", "kind": "built_in"},
        {"name": "ByteTrack tracking", "purpose": "dwell / loitering durations (arms the dwell trigger)",
         "status": "planned", "detail": "standalone port planned — clears the last AGPL dependency",
         "kind": "open_source"},
        {"name": "Make/model classifier", "purpose": "vehicle badge from the image, no VLM spend",
         "status": "planned", "detail": "open model needed; VLM attributes cover this today",
         "kind": "open_source"},
    ]

    feeds = []
    try:
        from alibi.dataengine.sources import SOURCES
        from alibi.dataengine.store import DataEngineStore
        stats = DataEngineStore().stats()
        per_source = stats.get("by_source") or {}
        areas = []
        try:
            from alibi.dataengine.refresh import areas_from_cameras
            areas = areas_from_cameras()
        except Exception:
            pass
        import os as _os
        token = bool(_os.environ.get("APIFY_TOKEN"))
        for sid, spec in SOURCES.items():
            entry = per_source.get(sid)
            records = entry.get("records", entry) if isinstance(entry, dict) else (entry or 0)
            blocked = None
            if spec.apify_actor and not token:
                blocked = "APIFY_TOKEN not set"
            elif sid.startswith("places.") and not areas:
                blocked = "no camera/site has an area set — nothing to harvest for"
            elif sid == "places.area_crime_stats" and not records:
                blocked = ("harvester agent live (weekly timer) — candidate "
                           "pages not parseable yet, stored nothing")
            elif not spec.apify_actor and not records:
                blocked = "no feed wired yet (actor or curated seed)"
            feeds.append({
                "source_id": sid,
                "description": spec.description,
                "records": records,
                "actor": spec.apify_actor,
                "lawful_basis": getattr(spec.lawful_basis, "value", str(spec.lawful_basis)),
                "retention_days": spec.retention_days,
                "blocked": blocked,
            })
    except Exception as e:
        print(f"[intel] dataengine status unavailable: {e}")

    return {"vision_stack": vision, "data_feeds": feeds,
            "generated_at": datetime.utcnow().isoformat()}


@app.get("/vehicles/review", tags=["Vehicles"])
async def list_vehicle_review(limit: int = 40,
                              current_user: User = Depends(get_current_user)):
    """Pending vehicle crops awaiting make/model confirmation, plus counts and
    how many confirmed labels the local-training corpus holds."""
    from alibi.vehicles.review_queue import get_review_queue_store
    store = get_review_queue_store()
    return {
        "pending": [i.to_dict() for i in store.list_pending(limit=limit)],
        "counts": store.counts(),
        "corpus_size": len(store.confirmed_labels()),
    }


class VehicleReviewDecision(BaseModel):
    decision: str                      # confirm | reject
    make: Optional[str] = None
    model: Optional[str] = None
    colour: Optional[str] = None
    body: Optional[str] = None


@app.post("/vehicles/review/{item_id}", tags=["Vehicles"])
async def decide_vehicle_review(
    item_id: str,
    payload: VehicleReviewDecision,
    current_user: User = Depends(require_role([Role.SUPERVISOR, Role.ADMIN])),
):
    """Confirm (accept the VLM guess, or a correction) or reject a review item.
    Confirmed rows become gold labels for the local classifier."""
    from alibi.vehicles.review_queue import get_review_queue_store, apply_review
    store = get_review_queue_store()
    item = store.get(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Review item not found")
    label = None
    if payload.decision == "confirm" and any([payload.make, payload.model, payload.colour, payload.body]):
        label = {"make": payload.make, "model": payload.model,
                 "colour": payload.colour, "body": payload.body}
    try:
        apply_review(item, payload.decision, current_user.username, label=label)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    store.update(item)
    get_store().append_audit("vehicle_review", {
        "user": current_user.username, "item_id": item_id, "decision": payload.decision,
    })
    return item.to_dict()


@app.get("/vehicles/dataset", tags=["Vehicles"])
async def vehicle_local_dataset(current_user: User = Depends(require_role([Role.ADMIN]))):
    """The locally-labelled training corpus so far: confirmed crops + gold
    labels (rendered from frames we already store; no second copy at rest)."""
    from alibi.vehicles.review_queue import get_review_queue_store
    rows = get_review_queue_store().confirmed_labels()
    from collections import Counter
    by_make = Counter((r["label"] or {}).get("make") or "unknown" for r in rows)
    return {"count": len(rows), "by_make": dict(by_make.most_common()), "manifest": rows}


class FieldReportCreate(BaseModel):
    subject: str                       # person | vehicle | other
    note: str
    observer: Optional[str] = None     # defaults to the logged-in user
    camera_id: Optional[str] = None
    location: str = ""
    ts: Optional[str] = None           # when observed (defaults to now)
    tags: Optional[Dict[str, Any]] = None


@app.post("/reports/field", tags=["Reports"])
async def submit_field_report(
    payload: FieldReportCreate,
    current_user: User = Depends(require_role([Role.OPERATOR, Role.SUPERVISOR, Role.ADMIN])),
):
    """Log a human observation from the ground (a guard, an operator) as a
    first-class data source beside the cameras. Evidence, never a verdict."""
    from alibi.reports.field_reports import build_report, get_field_report_store
    try:
        report = build_report(
            observer=(payload.observer or current_user.username),
            subject=payload.subject, note=payload.note, camera_id=payload.camera_id,
            location=payload.location, tags=payload.tags, ts=payload.ts, source="console",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    get_field_report_store().add(report)
    get_store().append_audit("field_report_logged", {
        "user": current_user.username, "subject": report.subject,
        "camera_id": report.camera_id,
    })
    return report.to_dict()


@app.get("/reports/field", tags=["Reports"])
async def list_field_reports(limit: int = 30, hours: int = 168,
                             current_user: User = Depends(get_current_user)):
    """Recent field reports, newest first."""
    from datetime import timedelta as _td
    from alibi.reports.field_reports import get_field_report_store
    cutoff = (datetime.utcnow() - _td(hours=max(1, hours))).isoformat()
    reports = get_field_report_store().list_recent(limit=limit, since_iso=cutoff)
    return {"reports": [r.to_dict() for r in reports], "count": len(reports)}


@app.get("/intelligence/sources", tags=["Intelligence"])
async def list_user_sources(current_user: User = Depends(get_current_user)):
    """Sources the owner has declared, plus the vocabulary the console needs."""
    from alibi.dataengine.user_sources import get_user_source_store, CATALOGUE
    from alibi.dataengine.schemas import DataDomain, LawfulBasis
    return {
        "sources": [s.to_dict() for s in get_user_source_store().list()],
        "catalogue": CATALOGUE,
        "domains": [{"value": d.value, "label": d.value.replace("_", " ")} for d in DataDomain],
        "lawful_bases": [{"value": b.value, "label": b.value.replace("_", " ")} for b in LawfulBasis],
        "boundary": ("Non-personal data only. Vantage has no data domain for personal "
                     "dossiers — a source for them cannot be declared, by design."),
    }


@app.post("/intelligence/sources", tags=["Intelligence"])
async def create_user_source(req: UserSourceCreate,
                             current_user: User = Depends(require_role([Role.ADMIN]))):
    """Declare a new source. Rejected unless it names an allowed domain, a lawful
    basis, and a retention period."""
    from alibi.dataengine.user_sources import get_user_source_store
    try:
        src = get_user_source_store().add(
            name=req.name, domain=req.domain, lawful_basis=req.lawful_basis,
            retention_days=req.retention_days, description=req.description,
            endpoint=req.endpoint, notes=req.notes,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return src.to_dict()


@app.post("/intelligence/sources/{source_id}/records", tags=["Intelligence"])
async def feed_user_source(source_id: str, req: UserSourceRecords,
                           current_user: User = Depends(require_role([Role.ADMIN]))):
    """Feed records into a declared source. They are stored under that source's
    declared domain, lawful basis and retention — never outside it."""
    from alibi.dataengine.user_sources import get_user_source_store
    store_u = get_user_source_store()
    src = store_u.get(source_id)
    if not src:
        raise HTTPException(status_code=404, detail="Source not found")
    if not req.records:
        raise HTTPException(status_code=400, detail="No records supplied")

    import uuid as _uuid
    from alibi.dataengine.store import DataEngineStore
    from alibi.dataengine.schemas import DataDomain, LawfulBasis, SourceSpec, build_record
    from alibi.dataengine.guard import assert_non_personal, PersonalDataRejected

    # Reconstruct the declaration as a SourceSpec so retention is derived from it,
    # exactly like a code-declared source.
    spec = SourceSpec(
        source_id=src.source_id, domain=DataDomain(src.domain),
        lawful_basis=LawfulBasis(src.lawful_basis),
        retention_days=src.retention_days, description=src.description or src.name,
    )
    ds = DataEngineStore()
    written, rejected = 0, []
    for rec in req.records:
        if not isinstance(rec, dict):
            rejected.append("a record was not an object")
            continue
        try:
            # Fail-closed: the same guard every ingested record passes. If the
            # owner pastes anything person-identifying, it is refused here.
            assert_non_personal(rec)
        except PersonalDataRejected as e:
            rejected.append(str(e))
            continue
        try:
            ds.append(build_record(
                record_id="rec_" + _uuid.uuid4().hex[:12], spec=spec, payload=rec,
                provenance={"declared_by": current_user.username if current_user else "admin",
                            "source_name": src.name, "endpoint": src.endpoint or None,
                            "entered": "console"},
            ))
            written += 1
        except Exception as e:
            rejected.append(str(e))

    store_u.bump_records(source_id, written)
    if written == 0 and rejected:
        raise HTTPException(status_code=400, detail="; ".join(rejected[:3]))
    return {"status": "ok", "written": written, "rejected": rejected, "source_id": source_id}


@app.delete("/intelligence/sources/{source_id}", tags=["Intelligence"])
async def delete_user_source(source_id: str,
                             current_user: User = Depends(require_role([Role.ADMIN]))):
    from alibi.dataengine.user_sources import get_user_source_store
    if not get_user_source_store().delete(source_id):
        raise HTTPException(status_code=404, detail="Source not found")
    return {"status": "deleted"}


@app.get("/intelligence/data", tags=["Intelligence"])
async def intelligence_data(current_user: User = Depends(get_current_user)):
    """External, non-personal reference data the Data Engine harvests (crime/area
    context, POI, detection reference) — what we collect, and what's live now.
    Boundary: official/reference/aggregate data only, never personal dossiers."""
    from alibi.dataengine.store import DataEngineStore
    from alibi.dataengine import sources as src
    store = DataEngineStore()
    records = store.query()
    return {
        "boundary": ("Non-personal, official / reference / aggregate data only "
                     "(POPIA & GDPR). No dossiers on individuals."),
        "sources": [
            {"source_id": s.source_id, "domain": s.domain.value,
             "description": s.description, "apify_actor": s.apify_actor,
             "retention_days": s.retention_days}
            for s in src.list_sources()
        ],
        "stats": store.stats(),
        "records": [
            {"source_id": r.source_id, "domain": r.domain.value,
             "lawful_basis": r.lawful_basis.value,
             "ingested_at": r.ingested_at.isoformat(),
             "retention_until": r.retention_until.isoformat(),
             "payload": r.payload}
            for r in records[:100]
        ],
    }


@app.get("/intelligence/search")
async def search_intelligence(
    q: str,
    current_user: User = Depends(get_current_user),
):
    """Search across red flags, people tags, place tags, and intelligence notes."""
    from alibi.intelligence_store import get_intelligence_store

    store = get_intelligence_store()
    results = store.search(q)

    # Convert dataclass results to dicts
    def to_dict_safe(obj):
        if hasattr(obj, '__dataclass_fields__'):
            from dataclasses import asdict as _asdict
            return _asdict(obj)
        return obj

    return {
        "query": q,
        "red_flags": [to_dict_safe(f) for f in results.get("red_flags", [])],
        "people": [to_dict_safe(p) for p in results.get("people", [])],
        "places": [to_dict_safe(p) for p in results.get("places", [])],
        "notes": [to_dict_safe(n) for n in results.get("notes", [])],
        "total": sum(len(v) for v in results.values()),
    }


# ── Training Stats ──────────────────────────────────────────────

@app.get("/training/stats")
async def get_training_stats(current_user: User = Depends(get_current_user)):
    """Get statistics about collected training examples and the training selector index."""
    from alibi.training_agent import get_training_agent
    from alibi.training_selector import get_training_selector

    agent_stats = get_training_agent().get_collection_stats()
    selector_stats = get_training_selector().get_stats()

    return {
        **agent_stats,
        "index_type": selector_stats.get("index_type", "none"),
        "index_loaded": selector_stats.get("total_examples", 0) > 0,
    }


# ── Activity Baselines ─────────────────────────────────────────

@app.get("/baselines/anomalies")
async def get_recent_anomalies(
    hours: int = 24,
    current_user: User = Depends(get_current_user),
):
    """Get recent anomaly scores above threshold."""
    from alibi.activity_baseline import get_baseline_engine

    engine = get_baseline_engine()
    anomalies = engine.get_recent_anomalies(hours=hours)
    return {"anomalies": [a.to_dict() for a in anomalies], "hours": hours}


@app.post("/baselines/rebuild")
async def rebuild_baselines(
    camera_id: Optional[str] = None,
    days: int = 7,
    current_user: User = Depends(get_current_user),
):
    """Rebuild activity baselines from camera analysis history."""
    from alibi.activity_baseline import get_baseline_engine

    engine = get_baseline_engine()
    count = engine.build_baselines(camera_id=camera_id, days=days)
    return {"status": "ok", "baselines_built": count, "camera_id": camera_id or "all", "days": days}


@app.get("/baselines/{camera_id}")
async def get_baselines(camera_id: str, current_user: User = Depends(get_current_user)):
    """Get activity baselines for a camera (24h x 7d matrix)."""
    from alibi.activity_baseline import get_baseline_engine

    engine = get_baseline_engine()
    baselines = engine.get_all_baselines(camera_id=camera_id)
    return {"camera_id": camera_id, "baselines": [b.to_dict() for b in baselines]}


# ── Face Sighting Index ────────────────────────────────────────

# ── People ──────────────────────────────────────────────────────
#
# "Who has been here, and where have they been before?" — answered ONLY from this
# deployment's own cameras. Each row is a real face sighting with the evidence
# still it came from; the history behind it is a cosine search over our own
# sighting archive (patterns/person_history). Unknown people stay unknown: we
# surface continuity ("seen 4 times since Tuesday"), never an identity we guessed.

@app.get("/people/recent", tags=["People"])
async def people_recent(limit: int = 60, hours: int = 168,
                        current_user: User = Depends(get_current_user)):
    """Recent face sightings from our own cameras, newest first."""
    from datetime import timedelta
    from alibi.watchlist.face_sighting_store import get_face_sighting_store
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()

    try:
        sightings = get_face_sighting_store().get_recent(limit=limit)
    except Exception:
        sightings = []

    names = _display_names()
    labels = {}
    try:
        from alibi.watchlist.watchlist_store import WatchlistStore
        labels = {e.person_id: e.label for e in WatchlistStore().load_all()}
    except Exception:
        pass

    rows = []
    for s in sightings:
        if s.ts < cutoff:
            continue
        rows.append({
            "sighting_id": s.sighting_id,
            "source": "face",
            "camera_id": s.camera_id,
            "camera_name": names.get(s.camera_id, s.camera_id),
            "ts": s.ts,
            "bbox": list(s.bbox) if s.bbox else None,
            "image_url": s.image_path,              # the real evidence still
            "matched_person_id": s.matched_person_id,
            "matched_label": labels.get(s.matched_person_id) if s.matched_person_id else None,
            "match_score": s.match_score,
        })
    rows.sort(key=lambda r: r["ts"], reverse=True)

    # No (or few) captured faces yet — at pavement distance the detector finds
    # the PERSON but not a readable face. Fall back to real person-detection
    # crops from events so the page isn't dormant while the archive builds.
    # These rows carry no embedding: no history lookup, no identity, honest.
    if len(rows) < limit:
        try:
            def _piou(a, b) -> float:
                ax, ay, aw, ah = a
                bx, by, bw, bh = b
                ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
                iy = max(0, min(ay + ah, by + bh) - max(ay, by))
                inter = ix * iy
                union = aw * ah + bw * bh - inter
                return inter / union if union > 0 else 0.0

            cutoff_dt = datetime.fromisoformat(cutoff)
            events = [e for e in get_store().list_events(limit=5000)
                      if getattr(e, "ts", None) and e.ts >= cutoff_dt]
            events.sort(key=lambda e: e.ts, reverse=True)
            seen_boxes: list = []
            for e in events:
                if len(rows) >= limit:
                    break
                if not e.snapshot_url:
                    continue
                intel_ = ((getattr(e, "metadata", None) or {}).get("intel") or {})
                for d in (intel_.get("detections") or []):
                    if d.get("class") != "person" or len(rows) >= limit:
                        continue
                    bbox = d.get("bbox") or []
                    if len(bbox) != 4:
                        continue
                    if any(cam == e.camera_id and _piou(bbox, prev) > 0.5
                           for cam, prev in seen_boxes):
                        continue
                    seen_boxes.append((e.camera_id, bbox))
                    rows.append({
                        "sighting_id": None,
                        "source": "detection",
                        "camera_id": e.camera_id,
                        "camera_name": names.get(e.camera_id, e.camera_id),
                        "ts": e.ts.isoformat(),
                        "bbox": bbox,
                        "image_url": e.snapshot_url,
                        "matched_person_id": None,
                        "matched_label": None,
                        "match_score": None,
                    })
        except Exception as e:
            print(f"[people] detection fallback unavailable: {e}")

    return {"people": rows, "count": len(rows), "window_hours": hours}


@app.get("/faces/recent")
async def get_recent_faces(
    camera_id: Optional[str] = None,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
):
    """Get recent face sightings (without embeddings for bandwidth)."""
    from alibi.watchlist.face_sighting_store import get_face_sighting_store

    store = get_face_sighting_store()
    if camera_id:
        sightings = store.get_by_camera(camera_id, limit=limit)
    else:
        sightings = store.get_recent(limit=limit)

    # Strip embeddings from response
    results = []
    for s in sightings:
        d = s.to_dict()
        d.pop("embedding", None)
        results.append(d)

    return {"sightings": results, "count": len(results)}


@app.post("/faces/search")
async def search_faces(
    file: UploadFile = File(...),
    threshold: float = 0.6,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
):
    """Upload an image, detect the face, and find matching sightings."""
    import numpy as np
    import cv2
    from alibi.watchlist.face_detect import FaceDetector
    from alibi.watchlist.face_embed import FaceEmbedder
    from alibi.watchlist.face_sighting_store import get_face_sighting_store

    contents = await file.read()
    nparr = np.frombuffer(contents, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(status_code=400, detail="Could not decode image")

    detector = FaceDetector()
    embedder = FaceEmbedder()

    faces = detector.detect(img)
    if not faces:
        return {"matches": [], "message": "No face detected in uploaded image"}

    # Use the first (largest) face
    bbox = faces[0]
    face_crop = detector.extract_face(img, bbox)
    embedding = embedder.generate_embedding(face_crop)
    if embedding is None:
        raise HTTPException(status_code=400, detail="Could not generate face embedding")

    store = get_face_sighting_store()
    matches = store.find_similar(embedding, threshold=threshold, limit=limit)

    results = []
    for sighting, score in matches:
        d = sighting.to_dict()
        d.pop("embedding", None)
        d["search_score"] = round(score, 4)
        results.append(d)

    return {"matches": results, "count": len(results)}


@app.get("/faces/stats")
async def get_face_stats(current_user: User = Depends(get_current_user)):
    """Get face sighting statistics."""
    from alibi.watchlist.face_sighting_store import get_face_sighting_store

    store = get_face_sighting_store()
    all_sightings = store.load_all()

    total = len(all_sightings)
    matched = sum(1 for s in all_sightings if s.matched_person_id)
    cameras = {}
    for s in all_sightings:
        cameras[s.camera_id] = cameras.get(s.camera_id, 0) + 1

    return {
        "total_sightings": total,
        "watchlist_matches": matched,
        "match_percentage": round(matched / total * 100, 1) if total else 0,
        "by_camera": cameras,
    }


# Main entry point for CLI

def main():
    """Run API server"""
    import uvicorn
    
    settings = get_settings()
    
    print(f"🔒 Starting Vantage API server...")
    print(f"   Host: {settings.api_host}")
    print(f"   Port: {settings.api_port}")
    print(f"   Docs: http://localhost:{settings.api_port}/docs")
    
    uvicorn.run(
        "alibi.alibi_api:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
