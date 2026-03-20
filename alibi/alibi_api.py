"""
Alibi FastAPI Server

RESTful API for incident management.
"""

from datetime import datetime
from typing import List, Optional
import asyncio
import json
from pathlib import Path
from pydantic import BaseModel, Field

from fastapi import FastAPI, HTTPException, status, Depends, UploadFile, File, Body, Form
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from alibi.schemas import (
    CameraEvent,
    Incident,
    IncidentStatus,
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
from alibi.config import AlibiConfig
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
    title="Alibi API",
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
    Mobile-friendly home page with access to all Alibi features.
    
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
        "service": "Alibi API",
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
    config = AlibiConfig(
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
        metadata={
            "dismiss_reason": decision_request.dismiss_reason
        } if decision_request.dismiss_reason else {},
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

@app.get("/api/metrics/summary")
async def get_metrics_summary(range: str = "24h", current_user: User = Depends(get_current_user)):
    """Get aggregated KPI metrics for the dashboard."""
    from alibi.metrics import get_metrics_aggregator
    aggregator = get_metrics_aggregator()
    return aggregator.compute_summary(range)


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
    vms_config: dict = Field(default_factory=dict)


class CameraUpdateRequest(BaseModel):
    """Partial update for a camera"""
    name: Optional[str] = None
    source: Optional[str] = None
    source_type: Optional[str] = None
    enabled: Optional[bool] = None
    location: Optional[str] = None
    vms_config: Optional[dict] = None


@app.get("/api/cameras", tags=["Cameras"])
async def list_cameras(
    current_user: User = Depends(get_current_user),
):
    """List all registered cameras with status."""
    store = get_camera_store()
    cameras = store.list_all()
    return {"cameras": [c.to_dict() for c in cameras]}


@app.post("/api/cameras", tags=["Cameras"])
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
        vms_config=req.vms_config,
    )
    store.add(camera)

    audit_store = get_store()
    audit_store.append_audit("camera_added", {"camera_id": req.camera_id, "user": current_user.username})

    return camera.to_dict()


@app.put("/api/cameras/{camera_id}", tags=["Cameras"])
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


@app.delete("/api/cameras/{camera_id}", tags=["Cameras"])
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


@app.post("/api/cameras/{camera_id}/test", tags=["Cameras"])
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


@app.get("/api/trail/{entity_type}/{entity_id}", tags=["Cameras"])
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
            config = AlibiConfig(
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
            
            config = AlibiConfig(
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

@app.post("/api/cameras/scan")
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


@app.get("/api/cameras/scan/status")
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


@app.post("/api/cameras/add-discovered")
async def add_discovered_camera(
    req: AddDiscoveredRequest,
    current_user: User = Depends(get_current_user),
):
    """One-click add a discovered camera to the registry."""
    from alibi.cameras.camera_store import get_camera_store, Camera, slugify

    store = get_camera_store()
    camera_id = slugify(req.name or f"camera-{req.ip.replace('.', '-')}")

    # Build RTSP URL with credentials if provided
    rtsp_url = req.rtsp_url
    if req.username and rtsp_url and "://" in rtsp_url:
        # Insert credentials into URL
        from urllib.parse import quote
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
    return {"status": "ok", "camera": camera.to_dict()}


# ── System Storage ──────────────────────────────────────────────

@app.get("/api/system/storage")
async def get_storage_info(current_user: User = Depends(get_current_user)):
    """Get disk usage breakdown for all data stores."""
    from alibi.data_manager import get_data_manager

    manager = get_data_manager()
    usage = manager.get_disk_usage()
    return usage.to_dict()


@app.post("/api/system/cleanup")
async def run_cleanup(current_user: User = Depends(get_current_user)):
    """Run data rotation and cleanup."""
    from alibi.data_manager import get_data_manager

    manager = get_data_manager()
    results = manager.auto_rotate()
    return results


# ── Training Stats ──────────────────────────────────────────────

@app.get("/api/training/stats")
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

@app.get("/api/baselines/anomalies")
async def get_recent_anomalies(
    hours: int = 24,
    current_user: User = Depends(get_current_user),
):
    """Get recent anomaly scores above threshold."""
    from alibi.activity_baseline import get_baseline_engine

    engine = get_baseline_engine()
    anomalies = engine.get_recent_anomalies(hours=hours)
    return {"anomalies": [a.to_dict() for a in anomalies], "hours": hours}


@app.post("/api/baselines/rebuild")
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


@app.get("/api/baselines/{camera_id}")
async def get_baselines(camera_id: str, current_user: User = Depends(get_current_user)):
    """Get activity baselines for a camera (24h x 7d matrix)."""
    from alibi.activity_baseline import get_baseline_engine

    engine = get_baseline_engine()
    baselines = engine.get_all_baselines(camera_id=camera_id)
    return {"camera_id": camera_id, "baselines": [b.to_dict() for b in baselines]}


# ── Face Sighting Index ────────────────────────────────────────

@app.get("/api/faces/recent")
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


@app.post("/api/faces/search")
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


@app.get("/api/faces/stats")
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
    
    print(f"🔒 Starting Alibi API server...")
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
