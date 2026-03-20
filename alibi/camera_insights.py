"""
Camera Insights & Reports
AI-powered analysis of camera history data
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import json
from pathlib import Path
from collections import Counter, defaultdict
from dataclasses import asdict
from alibi.auth import get_current_user, User
from alibi.camera_analysis_store import CameraAnalysisStore
from alibi.intelligence_store import (
    get_intelligence_store,
    RedFlag,
    PersonTag,
    PlaceTag,
    IntelligenceNote
)
import uuid

router = APIRouter(prefix="/camera", tags=["insights"])

store = CameraAnalysisStore()
intel_store = get_intelligence_store()

@router.get("/insights", response_class=HTMLResponse)
async def insights_page():
    """Insights & Reports page - AI analysis of camera history"""
    from alibi.alibi_nav import build_nav
    nav_css, nav_html, nav_js = build_nav(active_page="insights")
    html = INSIGHTS_HTML
    html = html.replace("</style>", nav_css + "\n    </style>", 1)
    html = html.replace("<body>", "<body>\n" + nav_html, 1)
    html = html.replace("</body>", nav_js + "\n</body>", 1)
    return HTMLResponse(content=html)


@router.get("/insights/summary")
async def get_insights_summary(
    hours: int = 24,
    current_user: User = Depends(get_current_user)
):
    """Get AI-powered insights summary from camera history"""
    
    # Get recent analyses from camera history
    analyses = store.get_recent(hours=hours, limit=1000)
    
    if not analyses:
        return {
            "period": f"Last {hours} hours",
            "total_snapshots": 0,
            "insights": [],
            "patterns": [],
            "safety_summary": {"total": 0, "concerns": []},
            "activity_breakdown": {},
            "objects_detected": {}
        }
    
    # Analyze patterns
    all_objects = []
    all_activities = []
    all_safety_concerns = []
    hourly_activity = defaultdict(int)
    
    for analysis in analyses:
        # Extract timestamp hour
        hour = datetime.fromisoformat(analysis.timestamp.replace('Z', '+00:00')).hour
        hourly_activity[hour] += 1
        
        # Collect objects
        if analysis.detected_objects:
            all_objects.extend(analysis.detected_objects)
        
        # Collect activities
        if analysis.detected_activities:
            all_activities.extend(analysis.detected_activities)
        
        # Collect safety concerns
        if analysis.safety_concern:
            all_safety_concerns.append("Safety concern detected")
    
    # Count frequencies
    object_counts = Counter(all_objects)
    activity_counts = Counter(all_activities)
    safety_counts = Counter(all_safety_concerns)
    
    # Generate insights
    insights = []
    
    # Most common objects
    if object_counts:
        top_obj = object_counts.most_common(1)[0]
        insights.append({
            "type": "objects",
            "title": f"Most Detected: {top_obj[0]}",
            "description": f"Seen {top_obj[1]} times in the last {hours} hours",
            "severity": "info"
        })
    
    # Activity patterns
    if activity_counts:
        top_activity = activity_counts.most_common(1)[0]
        insights.append({
            "type": "activity",
            "title": f"Common Activity: {top_activity[0]}",
            "description": f"Observed {top_activity[1]} times",
            "severity": "info"
        })
    
    # Safety concerns
    if safety_counts:
        for concern, count in safety_counts.most_common(3):
            insights.append({
                "type": "safety",
                "title": f"Safety Alert: {concern}",
                "description": f"Detected {count} times - review recommended",
                "severity": "warning" if count > 2 else "info"
            })
    
    # Peak activity hours
    if hourly_activity:
        peak_hour = max(hourly_activity.items(), key=lambda x: x[1])
        insights.append({
            "type": "pattern",
            "title": f"Peak Activity: {peak_hour[0]:02d}:00",
            "description": f"{peak_hour[1]} events recorded during this hour",
            "severity": "info"
        })
    
    # Unusual patterns
    if len(all_safety_concerns) > len(analyses) * 0.3:
        insights.append({
            "type": "alert",
            "title": "High Safety Alert Rate",
            "description": f"{len(all_safety_concerns)} safety concerns in {len(analyses)} snapshots (>{30}%)",
            "severity": "warning"
        })
    
    return {
        "period": f"Last {hours} hours",
        "total_snapshots": len(analyses),
        "insights": insights,
        "patterns": [
            {
                "name": "Hourly Activity",
                "data": dict(sorted(hourly_activity.items()))
            }
        ],
        "safety_summary": {
            "total": len(all_safety_concerns),
            "concerns": [{"concern": k, "count": v} for k, v in safety_counts.most_common(10)]
        },
        "activity_breakdown": dict(activity_counts.most_common(10)),
        "objects_detected": dict(object_counts.most_common(10)),
        "generated_at": datetime.utcnow().isoformat()
    }


@router.get("/insights/incident-report")
async def generate_incident_report(
    hours: int = 8,
    current_user: User = Depends(get_current_user)
):
    """Generate a detailed incident report from camera history"""
    
    # Get recent analyses with safety concerns from camera history
    all_analyses = store.get_recent(hours=hours, limit=1000)
    
    # Filter for safety concerns
    incidents = [a for a in all_analyses if a.safety_concern]
    
    if not incidents:
        return {
            "period": f"Last {hours} hours",
            "incident_count": 0,
            "report": "No safety concerns detected during this period.",
            "incidents": []
        }
    
    # Build report
    since = datetime.utcnow() - timedelta(hours=hours)
    report_lines = [
        f"# Camera Incident Report",
        f"",
        f"**Period:** {since.strftime('%Y-%m-%d %H:%M')} to {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}",
        f"**Generated:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Total Incidents:** {len(incidents)}",
        f"",
        f"## Summary",
        f"",
        f"During the {hours}-hour monitoring period, the AI vision system detected {len(incidents)} incidents requiring attention.",
        f"",
        f"## Incidents",
        f""
    ]
    
    incident_list = []
    for i, incident in enumerate(incidents, 1):
        ts = incident.timestamp
        desc = incident.description
        safety = "Safety concern flagged"
        
        report_lines.append(f"### Incident {i}")
        report_lines.append(f"- **Time:** {ts}")
        report_lines.append(f"- **Safety Concerns:** {safety}")
        report_lines.append(f"- **Description:** {desc}")
        report_lines.append(f"")
        
        incident_list.append({
            "number": i,
            "timestamp": ts,
            "safety_concerns": ["Safety concern detected"],
            "description": desc,
            "snapshot_url": incident.snapshot_path,
            "thumbnail_url": incident.thumbnail_path
        })
    
    report_lines.append(f"## Recommendations")
    report_lines.append(f"")
    report_lines.append(f"1. Review all incidents marked with safety concerns")
    report_lines.append(f"2. Investigate patterns in detected concerns")
    report_lines.append(f"3. Provide feedback on AI accuracy")
    report_lines.append(f"4. Update training data for improved detection")
    
    return {
        "period": f"Last {hours} hours",
        "incident_count": len(incidents),
        "report": "\n".join(report_lines),
        "incidents": incident_list,
        "generated_at": datetime.utcnow().isoformat()
    }


# RED FLAG ENDPOINTS

@router.post("/red-flag")
async def create_red_flag(
    analysis_id: Optional[str] = None,
    severity: str = "medium",
    category: str = "other",
    description: str = "",
    location: Optional[str] = None,
    tags: List[str] = [],
    snapshot_url: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    """Create a red flag for an observation"""
    
    flag = RedFlag(
        flag_id=f"rf-{str(uuid.uuid4())[:8]}",
        timestamp=datetime.utcnow().isoformat(),
        created_by=current_user.username,
        severity=severity,
        category=category,
        description=description,
        snapshot_url=snapshot_url,
        analysis_id=analysis_id,
        location=location,
        tags=tags,
        metadata={
            "created_by_role": current_user.role.value,
            "created_from": "camera_analysis"
        },
        resolved=False,
        resolved_by=None,
        resolved_at=None,
        resolution_notes=None
    )
    
    intel_store.add_red_flag(flag)
    
    return {
        "success": True,
        "flag_id": flag.flag_id,
        "message": "Red flag created successfully"
    }


@router.get("/red-flags")
async def get_red_flags(
    resolved: Optional[bool] = None,
    severity: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 100,
    current_user: User = Depends(get_current_user)
):
    """Get red flags"""
    flags = intel_store.get_red_flags(resolved=resolved, severity=severity, category=category, limit=limit)
    return {
        "flags": [asdict(f) for f in flags],
        "count": len(flags)
    }


@router.post("/red-flags/{flag_id}/resolve")
async def resolve_red_flag(
    flag_id: str,
    notes: str,
    current_user: User = Depends(get_current_user)
):
    """Resolve a red flag"""
    intel_store.resolve_red_flag(flag_id, current_user.username, notes)
    return {
        "success": True,
        "message": "Red flag resolved"
    }


# PEOPLE TAGGING

@router.post("/tag-person")
async def tag_person(
    label: str,
    description: str,
    snapshot_url: Optional[str] = None,
    analysis_id: Optional[str] = None,
    location: Optional[str] = None,
    notes: str = "",
    current_user: User = Depends(get_current_user)
):
    """Tag a person of interest"""
    
    person = PersonTag(
        person_tag_id=f"person-{str(uuid.uuid4())[:8]}",
        timestamp=datetime.utcnow().isoformat(),
        created_by=current_user.username,
        label=label,
        description=description,
        first_seen=datetime.utcnow().isoformat(),
        last_seen=datetime.utcnow().isoformat(),
        sightings=[{
            "timestamp": datetime.utcnow().isoformat(),
            "snapshot_url": snapshot_url,
            "location": location,
            "analysis_id": analysis_id
        }] if snapshot_url else [],
        associated_flags=[],
        notes=notes,
        metadata={}
    )
    
    intel_store.add_person_tag(person)
    
    return {
        "success": True,
        "person_tag_id": person.person_tag_id,
        "message": "Person tagged successfully"
    }


@router.get("/people-tags")
async def get_people_tags(
    limit: int = 100,
    current_user: User = Depends(get_current_user)
):
    """Get tagged people"""
    people = intel_store.get_person_tags(limit=limit)
    return {
        "people": [asdict(p) for p in people],
        "count": len(people)
    }


# PLACE TAGGING

@router.post("/tag-place")
async def tag_place(
    name: str,
    description: str,
    location_type: str = "other",
    risk_level: str = "low",
    notable_features: List[str] = [],
    notes: str = "",
    current_user: User = Depends(get_current_user)
):
    """Tag a location or place"""
    
    place = PlaceTag(
        place_tag_id=f"place-{str(uuid.uuid4())[:8]}",
        timestamp=datetime.utcnow().isoformat(),
        created_by=current_user.username,
        name=name,
        description=description,
        location_type=location_type,
        coordinates=None,
        notable_features=notable_features,
        incidents=[],
        risk_level=risk_level,
        notes=notes,
        metadata={}
    )
    
    intel_store.add_place_tag(place)
    
    return {
        "success": True,
        "place_tag_id": place.place_tag_id,
        "message": "Place tagged successfully"
    }


@router.get("/place-tags")
async def get_place_tags(
    risk_level: Optional[str] = None,
    limit: int = 100,
    current_user: User = Depends(get_current_user)
):
    """Get tagged places"""
    places = intel_store.get_place_tags(risk_level=risk_level, limit=limit)
    return {
        "places": [asdict(p) for p in places],
        "count": len(places)
    }


# INTELLIGENCE NOTES

@router.post("/intelligence-note")
async def create_intelligence_note(
    title: str,
    content: str,
    category: str = "other",
    confidence: str = "medium",
    actionable: bool = False,
    tags: List[str] = [],
    related_flags: List[str] = [],
    related_people: List[str] = [],
    related_places: List[str] = [],
    current_user: User = Depends(get_current_user)
):
    """Create an intelligence note"""
    
    note = IntelligenceNote(
        note_id=f"note-{str(uuid.uuid4())[:8]}",
        timestamp=datetime.utcnow().isoformat(),
        created_by=current_user.username,
        category=category,
        title=title,
        content=content,
        related_flags=related_flags,
        related_people=related_people,
        related_places=related_places,
        confidence=confidence,
        actionable=actionable,
        tags=tags,
        metadata={}
    )
    
    intel_store.add_intelligence_note(note)
    
    return {
        "success": True,
        "note_id": note.note_id,
        "message": "Intelligence note created"
    }


@router.get("/intelligence-notes")
async def get_intelligence_notes(
    category: Optional[str] = None,
    actionable: Optional[bool] = None,
    limit: int = 100,
    current_user: User = Depends(get_current_user)
):
    """Get intelligence notes"""
    notes = intel_store.get_intelligence_notes(category=category, actionable=actionable, limit=limit)
    return {
        "notes": [asdict(n) for n in notes],
        "count": len(notes)
    }


# SEARCH

@router.get("/intelligence/search")
async def search_intelligence(
    q: str,
    current_user: User = Depends(get_current_user)
):
    """Search across all intelligence data"""
    results = intel_store.search(q)
    
    return {
        "query": q,
        "results": {
            "red_flags": [asdict(f) for f in results["red_flags"][:20]],
            "people": [asdict(p) for p in results["people"][:20]],
            "places": [asdict(p) for p in results["places"][:20]],
            "notes": [asdict(n) for n in results["notes"][:20]]
        },
        "counts": {
            "red_flags": len(results["red_flags"]),
            "people": len(results["people"]),
            "places": len(results["places"]),
            "notes": len(results["notes"])
        }
    }


@router.get("/intelligence/stats")
async def get_intelligence_stats(
    current_user: User = Depends(get_current_user)
):
    """Get intelligence statistics"""
    stats = intel_store.get_stats()
    return stats


# Import asdict for serialization
from dataclasses import asdict


INSIGHTS_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Insights & Reports - Alibi</title>
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
            max-width: 800px;
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
        
        .tabs {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
        }
        
        .tab {
            flex: 1;
            background: rgba(255,255,255,0.9);
            border: none;
            padding: 15px;
            border-radius: 12px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            color: #666;
            transition: all 0.3s;
        }
        
        .tab.active {
            background: white;
            color: #667eea;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
        }
        
        .content {
            background: white;
            border-radius: 15px;
            padding: 20px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            min-height: 400px;
        }
        
        .section {
            display: none;
        }
        
        .section.active {
            display: block;
        }
        
        .insight-card {
            background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
            border-radius: 12px;
            padding: 15px;
            margin-bottom: 15px;
            border-left: 4px solid #667eea;
        }
        
        .insight-card.warning {
            border-left-color: #f59e0b;
            background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
        }
        
        .insight-card h3 {
            color: #333;
            font-size: 16px;
            margin-bottom: 5px;
        }
        
        .insight-card p {
            color: #666;
            font-size: 14px;
        }
        
        .stat-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }
        
        .stat-card {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border-radius: 12px;
            padding: 20px;
            text-align: center;
        }
        
        .stat-value {
            font-size: 32px;
            font-weight: bold;
            margin-bottom: 5px;
        }
        
        .stat-label {
            font-size: 12px;
            opacity: 0.9;
        }
        
        .list-item {
            padding: 10px;
            border-bottom: 1px solid #eee;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .list-item:last-child {
            border-bottom: none;
        }
        
        .badge {
            background: #667eea;
            color: white;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
        }
        
        .loading {
            text-align: center;
            padding: 40px;
            color: #666;
        }
        
        .report-content {
            background: #f9fafb;
            padding: 20px;
            border-radius: 8px;
            margin-top: 20px;
            white-space: pre-wrap;
            font-family: monospace;
            font-size: 12px;
            max-height: 500px;
            overflow-y: auto;
        }
        
        .controls {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
        }
        
        .btn {
            padding: 10px 20px;
            border: none;
            border-radius: 8px;
            background: #667eea;
            color: white;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
        }
        
        .btn:active {
            opacity: 0.8;
        }
        
        select {
            padding: 10px;
            border-radius: 8px;
            border: 1px solid #ddd;
            font-size: 14px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🧠 Insights & Reports</h1>
            <p class="subtitle">AI-powered analysis of camera footage</p>
        </div>
        
        <div class="tabs">
            <button class="tab active" onclick="showTab('insights')">📊 Insights</button>
            <button class="tab" onclick="showTab('report')">📋 Incident Report</button>
            <button class="tab" onclick="showTab('redflags')">🚩 Red Flags</button>
            <button class="tab" onclick="showTab('intelligence')">🕵️ Intelligence</button>
        </div>
        
        <div class="content">
            <!-- Insights Tab -->
            <div id="insights" class="section active">
                <div class="controls">
                    <select id="insightsPeriod" onchange="loadInsights()">
                        <option value="24">Last 24 Hours</option>
                        <option value="8">Last 8 Hours</option>
                        <option value="48">Last 48 Hours</option>
                        <option value="168">Last Week</option>
                    </select>
                    <button class="btn" onclick="loadInsights()">🔄 Refresh</button>
                </div>
                
                <div id="insightsContent">
                    <div class="loading">Loading insights...</div>
                </div>
            </div>
            
            <!-- Report Tab -->
            <div id="report" class="section">
                <div class="controls">
                    <select id="reportPeriod">
                        <option value="8">Last 8 Hours</option>
                        <option value="24">Last 24 Hours</option>
                        <option value="48">Last 48 Hours</option>
                    </select>
                    <button class="btn" onclick="generateReport()">📋 Generate Report</button>
                </div>
                
                <div id="reportContent">
                    <div class="loading">Select a period and click Generate Report</div>
                </div>
            </div>
            
            <!-- Red Flags Tab -->
            <div id="redflags" class="section">
                <div class="controls">
                    <select id="flagFilter">
                        <option value="all">All Flags</option>
                        <option value="unresolved">Unresolved Only</option>
                        <option value="critical">Critical Severity</option>
                    </select>
                    <button class="btn" onclick="loadRedFlags()">🔄 Refresh</button>
                </div>
                
                <div id="redFlagsContent">
                    <div class="loading">Loading red flags...</div>
                </div>
            </div>
            
            <!-- Intelligence Tab -->
            <div id="intelligence" class="section">
                <div class="controls">
                    <input type="text" id="searchQuery" placeholder="Search intelligence..." style="flex: 1; padding: 10px; border-radius: 8px; border: 1px solid #ddd;">
                    <button class="btn" onclick="searchIntelligence()">🔍 Search</button>
                    <button class="btn" onclick="showIntelStats()">📊 Stats</button>
                </div>
                
                <div style="display: flex; gap: 10px; margin-bottom: 20px;">
                    <button class="btn" onclick="addPersonTag()" style="flex: 1; background: #3b82f6;">👤 Tag Person</button>
                    <button class="btn" onclick="addPlaceTag()" style="flex: 1; background: #10b981;">📍 Tag Place</button>
                    <button class="btn" onclick="addIntelNote()" style="flex: 1; background: #f59e0b;">📝 Add Note</button>
                </div>
                
                <div id="intelligenceContent">
                    <div class="loading">Intelligence database ready</div>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        const token = localStorage.getItem('alibi_token');
        
        if (!token) {
            window.location.href = '/camera/login';
        }
        
        function showTab(tabName) {
            // Update tab buttons
            document.querySelectorAll('.tab').forEach(tab => {
                tab.classList.remove('active');
            });
            event.target.classList.add('active');
            
            // Update sections
            document.querySelectorAll('.section').forEach(section => {
                section.classList.remove('active');
            });
            document.getElementById(tabName).classList.add('active');
            
            // Load data if needed
            if (tabName === 'insights') {
                loadInsights();
            }
        }
        
        async function loadInsights() {
            const hours = document.getElementById('insightsPeriod').value;
            const content = document.getElementById('insightsContent');
            content.innerHTML = '<div class="loading">Loading insights...</div>';
            
            try {
                const response = await fetch(`/camera/insights/summary?hours=${hours}`, {
                    headers: {
                        'Authorization': `Bearer ${token}`
                    }
                });
                
                if (!response.ok) throw new Error('Failed to load insights');
                
                const data = await response.json();
                displayInsights(data);
            } catch (error) {
                content.innerHTML = `<div class="loading">Error: ${error.message}</div>`;
            }
        }
        
        function displayInsights(data) {
            const content = document.getElementById('insightsContent');
            
            let html = `
                <div class="stat-grid">
                    <div class="stat-card">
                        <div class="stat-value">${data.total_snapshots}</div>
                        <div class="stat-label">Total Snapshots</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value">${data.safety_summary.total}</div>
                        <div class="stat-label">Safety Alerts</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value">${Object.keys(data.objects_detected).length}</div>
                        <div class="stat-label">Object Types</div>
                    </div>
                </div>
                
                <h3 style="margin-bottom: 15px;">🔍 Key Insights</h3>
            `;
            
            if (data.insights.length === 0) {
                html += '<p style="color: #666;">No significant insights for this period.</p>';
            } else {
                data.insights.forEach(insight => {
                    html += `
                        <div class="insight-card ${insight.severity === 'warning' ? 'warning' : ''}">
                            <h3>${insight.title}</h3>
                            <p>${insight.description}</p>
                        </div>
                    `;
                });
            }
            
            // Top objects
            if (Object.keys(data.objects_detected).length > 0) {
                html += '<h3 style="margin: 20px 0 15px 0;">🔎 Most Detected Objects</h3>';
                Object.entries(data.objects_detected).slice(0, 5).forEach(([obj, count]) => {
                    html += `
                        <div class="list-item">
                            <span>${obj}</span>
                            <span class="badge">${count}</span>
                        </div>
                    `;
                });
            }
            
            // Top activities
            if (Object.keys(data.activity_breakdown).length > 0) {
                html += '<h3 style="margin: 20px 0 15px 0;">🏃 Common Activities</h3>';
                Object.entries(data.activity_breakdown).slice(0, 5).forEach(([activity, count]) => {
                    html += `
                        <div class="list-item">
                            <span>${activity}</span>
                            <span class="badge">${count}</span>
                        </div>
                    `;
                });
            }
            
            content.innerHTML = html;
        }
        
        async function generateReport() {
            const hours = document.getElementById('reportPeriod').value;
            const content = document.getElementById('reportContent');
            content.innerHTML = '<div class="loading">Generating report...</div>';
            
            try {
                const response = await fetch(`/camera/insights/incident-report?hours=${hours}`, {
                    headers: {
                        'Authorization': `Bearer ${token}`
                    }
                });
                
                if (!response.ok) throw new Error('Failed to generate report');
                
                const data = await response.json();
                displayReport(data);
            } catch (error) {
                content.innerHTML = `<div class="loading">Error: ${error.message}</div>`;
            }
        }
        
        function displayReport(data) {
            const content = document.getElementById('reportContent');
            
            let html = `
                <div class="stat-grid">
                    <div class="stat-card">
                        <div class="stat-value">${data.incident_count}</div>
                        <div class="stat-label">Incidents Detected</div>
                    </div>
                </div>
                
                <div class="report-content">${data.report}</div>
            `;
            
            content.innerHTML = html;
        }
        
        // RED FLAGS FUNCTIONS
        async function loadRedFlags() {
            const filter = document.getElementById('flagFilter').value;
            const content = document.getElementById('redFlagsContent');
            content.innerHTML = '<div class="loading">Loading red flags...</div>';
            
            let url = '/camera/red-flags?limit=100';
            if (filter === 'unresolved') url += '&resolved=false';
            if (filter === 'critical') url += '&severity=critical';
            
            try {
                const response = await fetch(url, {
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                
                if (!response.ok) throw new Error('Failed to load');
                
                const data = await response.json();
                displayRedFlags(data.flags);
            } catch (error) {
                content.innerHTML = `<div class="loading">Error: ${error.message}</div>`;
            }
        }
        
        function displayRedFlags(flags) {
            const content = document.getElementById('redFlagsContent');
            
            if (flags.length === 0) {
                content.innerHTML = '<p style="text-align: center; color: #666;">No red flags found</p>';
                return;
            }
            
            let html = '';
            flags.forEach(flag => {
                const severityColors = {
                    low: '#10b981',
                    medium: '#f59e0b',
                    high: '#ef4444',
                    critical: '#dc2626'
                };
                
                html += `
                    <div class="insight-card" style="border-left-color: ${severityColors[flag.severity]};">
                        <div style="display: flex; justify-content: space-between; align-items: start;">
                            <div style="flex: 1;">
                                <h3>🚩 ${flag.category.replace(/_/g, ' ').toUpperCase()} - ${flag.severity.toUpperCase()}</h3>
                                <p>${flag.description}</p>
                                <p style="font-size: 12px; color: #666; margin-top: 8px;">
                                    Created by ${flag.created_by} • ${new Date(flag.timestamp).toLocaleString()}
                                    ${flag.location ? `• Location: ${flag.location}` : ''}
                                </p>
                                ${flag.tags.length > 0 ? `<p style="font-size: 12px;">Tags: ${flag.tags.join(', ')}</p>` : ''}
                            </div>
                            ${!flag.resolved ? `
                                <button class="btn" style="padding: 8px 16px; font-size: 12px; background: #10b981;" 
                                        onclick="resolveFlag('${flag.flag_id}')">
                                    ✓ Resolve
                                </button>
                            ` : `
                                <span style="color: #10b981; font-weight: 600;">✓ RESOLVED</span>
                            `}
                        </div>
                        ${flag.resolved ? `
                            <p style="font-size: 12px; color: #666; margin-top: 8px; padding-top: 8px; border-top: 1px solid #eee;">
                                Resolved by ${flag.resolved_by} • ${flag.resolution_notes}
                            </p>
                        ` : ''}
                    </div>
                `;
            });
            
            content.innerHTML = html;
        }
        
        async function resolveFlag(flagId) {
            const notes = prompt('Resolution notes:');
            if (!notes) return;
            
            try {
                const response = await fetch(`/camera/red-flags/${flagId}/resolve`, {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${token}`,
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ notes })
                });
                
                if (response.ok) {
                    alert('✓ Red flag resolved');
                    loadRedFlags();
                } else {
                    alert('Error resolving flag');
                }
            } catch (error) {
                alert('Error: ' + error.message);
            }
        }
        
        // INTELLIGENCE FUNCTIONS
        async function searchIntelligence() {
            const query = document.getElementById('searchQuery').value;
            if (!query) {
                alert('Enter a search query');
                return;
            }
            
            const content = document.getElementById('intelligenceContent');
            content.innerHTML = '<div class="loading">Searching...</div>';
            
            try {
                const response = await fetch(`/camera/intelligence/search?q=${encodeURIComponent(query)}`, {
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                
                const data = await response.json();
                displaySearchResults(data);
            } catch (error) {
                content.innerHTML = `<div class="loading">Error: ${error.message}</div>`;
            }
        }
        
        function displaySearchResults(data) {
            const content = document.getElementById('intelligenceContent');
            
            let html = '<h3>Search Results</h3>';
            html += `<p style="color: #666; margin-bottom: 20px;">
                Found: ${data.counts.red_flags} flags, ${data.counts.people} people, 
                ${data.counts.places} places, ${data.counts.notes} notes
            </p>`;
            
            if (data.results.red_flags.length > 0) {
                html += '<h4>Red Flags:</h4>';
                data.results.red_flags.forEach(flag => {
                    html += `<div class="list-item"><span>${flag.description}</span><span class="badge">${flag.severity}</span></div>`;
                });
            }
            
            if (data.results.people.length > 0) {
                html += '<h4 style="margin-top: 20px;">People:</h4>';
                data.results.people.forEach(person => {
                    html += `<div class="list-item"><span>${person.label}: ${person.description}</span></div>`;
                });
            }
            
            if (data.results.places.length > 0) {
                html += '<h4 style="margin-top: 20px;">Places:</h4>';
                data.results.places.forEach(place => {
                    html += `<div class="list-item"><span>${place.name}</span><span class="badge">${place.risk_level}</span></div>`;
                });
            }
            
            content.innerHTML = html;
        }
        
        async function showIntelStats() {
            try {
                const response = await fetch('/camera/intelligence/stats', {
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                
                const stats = await response.json();
                
                const html = `
                    <div class="stat-grid">
                        <div class="stat-card"><div class="stat-value">${stats.total_red_flags}</div><div class="stat-label">Red Flags</div></div>
                        <div class="stat-card"><div class="stat-value">${stats.unresolved_flags}</div><div class="stat-label">Unresolved</div></div>
                        <div class="stat-card"><div class="stat-value">${stats.total_people_tagged}</div><div class="stat-label">People Tagged</div></div>
                        <div class="stat-card"><div class="stat-value">${stats.total_places_tagged}</div><div class="stat-label">Places Tagged</div></div>
                        <div class="stat-card"><div class="stat-value">${stats.high_risk_places}</div><div class="stat-label">High Risk Places</div></div>
                        <div class="stat-card"><div class="stat-value">${stats.actionable_notes}</div><div class="stat-label">Actionable Intel</div></div>
                    </div>
                `;
                
                document.getElementById('intelligenceContent').innerHTML = html;
            } catch (error) {
                alert('Error loading stats: ' + error.message);
            }
        }
        
        async function addPersonTag() {
            const label = prompt('Person label (e.g., "Person in red shirt", "Suspect 1"):');
            if (!label) return;
            
            const description = prompt('Detailed description:');
            if (!description) return;
            
            const location = prompt('Location (optional):');
            const notes = prompt('Additional notes (optional):');
            
            try {
                const response = await fetch('/camera/tag-person', {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${token}`,
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        label,
                        description,
                        location: location || null,
                        notes: notes || ''
                    })
                });
                
                if (response.ok) {
                    alert('✓ Person tagged successfully');
                } else {
                    alert('Error tagging person');
                }
            } catch (error) {
                alert('Error: ' + error.message);
            }
        }
        
        async function addPlaceTag() {
            const name = prompt('Place name (e.g., "North entrance", "Parking area"):');
            if (!name) return;
            
            const description = prompt('Description:');
            if (!description) return;
            
            const riskLevel = prompt('Risk level (low/medium/high):', 'low');
            const notes = prompt('Additional notes (optional):');
            
            try {
                const response = await fetch('/camera/tag-place', {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${token}`,
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        name,
                        description,
                        risk_level: riskLevel || 'low',
                        notes: notes || ''
                    })
                });
                
                if (response.ok) {
                    alert('✓ Place tagged successfully');
                } else {
                    alert('Error tagging place');
                }
            } catch (error) {
                alert('Error: ' + error.message);
            }
        }
        
        async function addIntelNote() {
            const title = prompt('Intelligence note title:');
            if (!title) return;
            
            const content = prompt('Note content (detailed information):');
            if (!content) return;
            
            const category = prompt('Category (pattern/correlation/suspect_behavior/location_info/other):', 'other');
            const actionable = confirm('Is this actionable intelligence?');
            
            try {
                const response = await fetch('/camera/intelligence-note', {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${token}`,
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        title,
                        content,
                        category: category || 'other',
                        actionable
                    })
                });
                
                if (response.ok) {
                    alert('✓ Intelligence note created');
                } else {
                    alert('Error creating note');
                }
            } catch (error) {
                alert('Error: ' + error.message);
            }
        }
        
        // Load insights on page load
        loadInsights();
    </script>
</body>
</html>
"""
