"""
Mobile Camera API Endpoints

Allows ANY camera (iPhone, Android, webcam) to stream to Vantage
and get real-time feedback on what's being filmed.
"""

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from fastapi.responses import HTMLResponse, StreamingResponse
from typing import Optional, List
import cv2
import numpy as np
import base64
from datetime import datetime
import asyncio
from collections import deque
import uuid

from alibi.auth import User, get_current_user, require_role, Role
from alibi.vision.scene_analyzer import SceneAnalyzer
from alibi.camera_analysis_store import CameraAnalysis, get_camera_analysis_store
from alibi.training_agent import get_training_agent

router = APIRouter(prefix="/camera", tags=["Mobile Camera"])

# Global scene analyzer
_scene_analyzer: Optional[SceneAnalyzer] = None

def get_scene_analyzer() -> SceneAnalyzer:
    """Get or create scene analyzer"""
    global _scene_analyzer
    if _scene_analyzer is None:
        _scene_analyzer = SceneAnalyzer(mode="auto")
    return _scene_analyzer


# Store recent analyses for feedback stream
recent_analyses = deque(maxlen=100)


# Mobile-friendly login page HTML
MOBILE_LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Vantage Login</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f1117;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .login-container {
            background: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 16px;
            padding: 40px 30px;
            width: 100%;
            max-width: 380px;
        }
        h1 {
            text-align: center;
            color: #fff;
            margin-bottom: 6px;
            font-size: 24px;
            font-weight: 700;
            letter-spacing: -0.3px;
        }
        .subtitle {
            text-align: center;
            color: rgba(255,255,255,0.4);
            margin-bottom: 28px;
            font-size: 13px;
        }
        .form-group { margin-bottom: 18px; }
        label {
            display: block;
            color: rgba(255,255,255,0.5);
            margin-bottom: 6px;
            font-weight: 500;
            font-size: 13px;
        }
        input {
            width: 100%;
            padding: 12px 14px;
            background: rgba(255,255,255,0.06);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 8px;
            font-size: 15px;
            color: #fff;
            transition: border-color 0.15s;
        }
        input:focus {
            outline: none;
            border-color: rgba(99, 102, 241, 0.5);
        }
        input::placeholder { color: rgba(255,255,255,0.2); }
        .login-btn {
            width: 100%;
            padding: 12px;
            background: rgba(99, 102, 241, 0.8);
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 15px;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.15s;
            margin-top: 4px;
        }
        .login-btn:hover { background: rgba(99, 102, 241, 1); }
        .login-btn:active { transform: scale(0.98); }
        .login-btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .error {
            background: rgba(239, 68, 68, 0.1);
            border: 1px solid rgba(239, 68, 68, 0.2);
            color: #f87171;
            padding: 10px 14px;
            border-radius: 8px;
            margin-bottom: 16px;
            font-size: 13px;
        }
        .loading {
            text-align: center;
            color: rgba(99, 102, 241, 0.7);
            margin-top: 10px;
            font-size: 13px;
        }
    </style>
</head>
<body>
    <div class="login-container">
        <h1>Vantage</h1>
        <p class="subtitle">Sign in to continue</p>

        <div id="error" class="error" style="display: none;"></div>

        <form id="loginForm">
            <div class="form-group">
                <label for="username">Username</label>
                <input type="text" id="username" name="username" placeholder="Enter username" required autofocus>
            </div>
            <div class="form-group">
                <label for="password">Password</label>
                <input type="password" id="password" name="password" placeholder="Enter password" required>
            </div>
            <button type="submit" id="loginBtn" class="login-btn">Sign In</button>
            <div id="loading" class="loading" style="display: none;">Signing in...</div>
        </form>
    </div>

    <script>
        const form = document.getElementById('loginForm');
        const errorDiv = document.getElementById('error');
        const loginBtn = document.getElementById('loginBtn');
        const loading = document.getElementById('loading');

        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const username = document.getElementById('username').value;
            const password = document.getElementById('password').value;

            errorDiv.style.display = 'none';
            loginBtn.disabled = true;
            loading.style.display = 'block';

            try {
                const response = await fetch('/auth/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username, password })
                });

                if (response.ok) {
                    const data = await response.json();
                    localStorage.setItem('alibi_token', data.access_token);
                    // Store user info (API returns flat: username, role, full_name)
                    localStorage.setItem('alibi_user', JSON.stringify({
                        username: data.username,
                        role: data.role,
                        full_name: data.full_name
                    }));
                    // Redirect to home dashboard
                    window.location.href = '/';
                } else {
                    const error = await response.json();
                    errorDiv.textContent = error.detail || 'Login failed';
                    errorDiv.style.display = 'block';
                    loginBtn.disabled = false;
                    loading.style.display = 'none';
                }
            } catch (err) {
                errorDiv.textContent = 'Connection error. Is the server running?';
                errorDiv.style.display = 'block';
                loginBtn.disabled = false;
                loading.style.display = 'none';
            }
        });
    </script>
</body>
</html>
"""


@router.post("/analyze-frame")
async def analyze_camera_frame(
    file: UploadFile = File(...),
    prompt: str = "describe_scene",
    current_user: User = Depends(get_current_user)
):
    """
    Analyze a single camera frame and return natural language description.
    
    Upload an image from ANY camera (phone, webcam, etc.) and get immediate
    feedback on what's in the frame.
    
    Returns:
        {
            "description": "Two men fighting near a parked car",
            "confidence": 0.85,
            "detected_objects": ["person", "person", "car"],
            "safety_concern": true,
            "timestamp": "2026-01-19T..."
        }
    """
    try:
        # Read uploaded image
        contents = await file.read()
        nparr = np.frombuffer(contents, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if frame is None:
            raise HTTPException(status_code=400, detail="Invalid image file")
        
        # Analyze frame
        analyzer = get_scene_analyzer()
        result = analyzer.analyze_frame(frame, prompt=prompt)
        
        # Store analysis for historical tracking
        analysis_id = str(uuid.uuid4())
        
        # Save snapshot and thumbnail
        store = get_camera_analysis_store()
        snapshot_path, thumbnail_path = store.save_snapshot(frame, analysis_id)
        
        camera_analysis = CameraAnalysis(
            analysis_id=analysis_id,
            timestamp=result.get('timestamp', datetime.utcnow().isoformat()),
            user=current_user.username,
            camera_source="webcam_upload",  # Could be enhanced to track source
            description=result['description'],
            confidence=result['confidence'],
            detected_objects=result.get('detected_objects', []),
            detected_activities=result.get('detected_activities', []),
            safety_concern=result.get('safety_concern', False),
            method=result.get('method', 'unknown'),
            metadata={
                "prompt": prompt,
                "user_role": current_user.role.value,
                "source": "mobile_camera_api"
            },
            snapshot_path=snapshot_path,
            thumbnail_path=thumbnail_path
        )
        
        store.add_analysis(camera_analysis)
        
        # Add to recent analyses for SSE
        result["user"] = current_user.username
        result["uploaded_at"] = datetime.utcnow().isoformat()
        result["analysis_id"] = analysis_id
        recent_analyses.append(result)
        
        return result
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@router.get("/stream-feedback")
async def stream_camera_feedback(
    current_user: User = Depends(get_current_user)
):
    """
    Server-Sent Events stream of recent camera analyses.
    
    Connect to this endpoint to get real-time feedback as frames are analyzed.
    """
    async def event_generator():
        last_index = 0
        
        while True:
            # Send new analyses
            if len(recent_analyses) > last_index:
                for i in range(last_index, len(recent_analyses)):
                    analysis = recent_analyses[i]
                    yield f"data: {json.dumps(analysis)}\n\n"
                last_index = len(recent_analyses)
            
            await asyncio.sleep(0.5)
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/login", response_class=HTMLResponse)
async def mobile_login_page():
    """
    Mobile-friendly login page for camera streaming.
    
    Login here first, then go to /camera/mobile-stream
    """
    return HTMLResponse(content=MOBILE_LOGIN_HTML)


@router.get("/mobile-stream")
async def mobile_camera_stream_page():
    """Superseded — hands over to /phone.

    This page posted to /camera/analyze-frame, which only produced a VLM
    description into camera_analysis.jsonl. It never ran detection, plates,
    faces or vehicle ReID and never raised an event, so nothing it captured
    reached Overview, People or Vehicles — while the console told the owner
    it ran "the same detection, faces, plates and scene analysis as your
    fixed cameras". On the live box that store was 0 bytes.

    /phone speaks the bridge protocol and goes through the real pipeline.
    Redirecting rather than deleting keeps any bookmarked link working.
    """
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/api/phone", status_code=307)


async def _retired_mobile_camera_stream_page():
    """The old markup, unreachable; kept so the change stays reviewable."""
    html_content = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Vantage Mobile Camera</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #000;
            color: #fff;
            overflow: hidden;
        }
        
        #video-container {
            position: relative;
            width: 100vw;
            height: 100vh;
            display: flex;
            flex-direction: column;
        }
        
        #video {
            width: 100%;
            flex: 1;
            object-fit: cover;
            background: #000;
        }
        
        #feedback {
            position: absolute;
            bottom: 0;
            left: 0;
            right: 0;
            background: linear-gradient(to top, rgba(0,0,0,0.9), transparent);
            padding: 20px;
            min-height: 150px;
            display: flex;
            flex-direction: column;
            justify-content: flex-end;
        }
        
        #status {
            color: #10b981;
            font-size: 12px;
            margin-bottom: 5px;
            display: flex;
            align-items: center;
            gap: 5px;
        }
        
        .pulse {
            width: 8px;
            height: 8px;
            background: #10b981;
            border-radius: 50%;
            animation: pulse 2s infinite;
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.3; }
        }
        
        #description {
            font-size: 18px;
            font-weight: 600;
            margin-bottom: 10px;
            line-height: 1.4;
        }
        
        #details {
            font-size: 14px;
            color: #9ca3af;
        }
        
        .safety-warning {
            background: #dc2626;
            color: white;
            padding: 10px 15px;
            border-radius: 8px;
            margin-top: 10px;
            font-weight: 600;
        }
        
        #controls {
            position: absolute;
            top: 20px;
            right: 20px;
            display: flex;
            gap: 10px;
        }
        
        button {
            background: rgba(255,255,255,0.2);
            border: none;
            color: white;
            padding: 10px 20px;
            border-radius: 20px;
            font-size: 14px;
            cursor: pointer;
            backdrop-filter: blur(10px);
        }
        
        button:active {
            background: rgba(255,255,255,0.3);
        }
        
        .error {
            color: #dc2626;
            padding: 20px;
            text-align: center;
        }
    </style>
</head>
<body>
    <div id="video-container">
        <video id="video" autoplay playsinline></video>
        
        <div id="controls">
            <button id="camera-switch">🔄 Flip</button>
            <button id="pause-btn">⏸ Pause</button>
        </div>
        
        <div id="feedback">
            <div id="status">
                <div class="pulse"></div>
                <span>Analyzing camera feed...</span>
            </div>
            <div id="description">Point camera at something to start</div>
            <div id="details"></div>
        </div>
    </div>

    <script>
        let video = document.getElementById('video');
        let description = document.getElementById('description');
        let details = document.getElementById('details');
        let status = document.getElementById('status');
        let feedback = document.getElementById('feedback');
        let stream = null;
        let analyzing = false;
        let isPaused = false;
        let currentFacingMode = 'environment'; // Back camera by default
        
        // Get JWT token from localStorage (set by login page)
        const token = localStorage.getItem('alibi_token');
        
        if (!token) {
            description.innerHTML = '<div class="error">Please login first at /login</div>';
            throw new Error('No auth token');
        }
        
        // Start camera
        async function startCamera() {
            try {
                stream = await navigator.mediaDevices.getUserMedia({
                    video: {
                        facingMode: currentFacingMode,
                        width: { ideal: 1280 },
                        height: { ideal: 720 }
                    }
                });
                
                video.srcObject = stream;
                
                // Start analyzing frames
                setInterval(analyzeFrame, 2000); // Every 2 seconds
            } catch (error) {
                description.innerHTML = `<div class="error">Camera access denied. Please allow camera access.</div>`;
                console.error('Camera error:', error);
            }
        }
        
        // Analyze current frame
        async function analyzeFrame() {
            if (analyzing || isPaused) return;
            analyzing = true;
            
            try {
                // Capture frame from video
                const canvas = document.createElement('canvas');
                canvas.width = video.videoWidth;
                canvas.height = video.videoHeight;
                const ctx = canvas.getContext('2d');
                ctx.drawImage(video, 0, 0);
                
                // Convert to blob
                const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.8));
                
                // Send to API
                const formData = new FormData();
                formData.append('file', blob, 'frame.jpg');
                
                const response = await fetch('/camera/analyze-frame', {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${token}`
                    },
                    body: formData
                });
                
                if (response.ok) {
                    const result = await response.json();
                    updateFeedback(result);
                } else {
                    console.error('Analysis failed:', response.status);
                }
            } catch (error) {
                console.error('Analysis error:', error);
            } finally {
                analyzing = false;
            }
        }
        
        // Update feedback display
        function updateFeedback(result) {
            description.textContent = result.description;
            
            // Show details
            let detailsText = '';
            if (result.detected_objects && result.detected_objects.length > 0) {
                detailsText += `Objects: ${result.detected_objects.join(', ')} • `;
            }
            detailsText += `Confidence: ${(result.confidence * 100).toFixed(0)}% • `;
            detailsText += `Method: ${result.method}`;
            
            details.textContent = detailsText;
            
            // Safety warning
            const existingWarning = feedback.querySelector('.safety-warning');
            if (existingWarning) existingWarning.remove();
            
            if (result.safety_concern) {
                const warning = document.createElement('div');
                warning.className = 'safety-warning';
                warning.textContent = '⚠️ SAFETY CONCERN DETECTED';
                feedback.appendChild(warning);
            }
        }
        
        // Camera switch button
        document.getElementById('camera-switch').addEventListener('click', async () => {
            currentFacingMode = currentFacingMode === 'environment' ? 'user' : 'environment';
            
            // Stop current stream
            if (stream) {
                stream.getTracks().forEach(track => track.stop());
            }
            
            // Start new stream
            await startCamera();
        });
        
        // Pause button
        document.getElementById('pause-btn').addEventListener('click', () => {
            isPaused = !isPaused;
            const btn = document.getElementById('pause-btn');
            btn.textContent = isPaused ? '▶️ Resume' : '⏸ Pause';
            status.querySelector('span').textContent = isPaused ? 'Analysis paused' : 'Analyzing camera feed...';
        });
        
        // Start
        startCamera();
    </script>
</body>
</html>
    """
    from alibi.alibi_nav import build_nav
    nav_css, nav_html, nav_js = build_nav(active_page="camera")
    html_content = html_content.replace("</style>", nav_css + "\n    </style>", 1)
    html_content = html_content.replace("<body>", "<body>\n" + nav_html, 1)
    html_content = html_content.replace("</body>", nav_js + "\n</body>", 1)
    return HTMLResponse(content=html_content)


# Add JSON import
import json


@router.get("/analysis/recent")
async def get_recent_analyses(
    limit: int = 100,
    hours: int = 24,
    current_user: User = Depends(get_current_user)
):
    """
    Get recent camera analyses.
    
    Returns historical camera analysis data for review and insights.
    """
    store = get_camera_analysis_store()
    analyses = store.get_recent(limit=limit, hours=hours)
    return {"analyses": [asdict(a) for a in analyses], "count": len(analyses)}


@router.get("/analysis/statistics")
async def get_analysis_statistics(
    hours: int = 24,
    current_user: User = Depends(get_current_user)
):
    """
    Get camera analysis statistics.
    
    Returns aggregated insights:
    - Total analyses
    - Safety concerns count
    - Most common objects detected
    - Most common activities
    - Analysis methods used
    """
    store = get_camera_analysis_store()
    stats = store.get_statistics(hours=hours)
    return stats


@router.get("/analysis/safety-concerns")
async def get_safety_concerns(
    hours: int = 24,
    current_user: User = Depends(get_current_user)
):
    """
    Get all safety concerns detected by camera analysis.
    
    Returns only analyses where safety_concern=True
    """
    store = get_camera_analysis_store()
    concerns = store.get_safety_concerns(hours=hours)
    return {"concerns": [asdict(c) for c in concerns], "count": len(concerns)}


# Import asdict for serialization
from dataclasses import asdict

# Import vision data collection
from alibi.vision.data_collection import (
    FeedbackRecord,
    get_vision_data_collector
)
from alibi.vision.south_african_context import get_context_hints


@router.post("/feedback")
async def submit_vision_feedback(
    analysis_id: str,
    corrected_description: Optional[str] = None,
    corrected_objects: Optional[List[str]] = None,
    corrected_activities: Optional[List[str]] = None,
    corrected_safety_concern: Optional[bool] = None,
    accuracy_rating: Optional[int] = None,
    missing_context: Optional[str] = None,
    south_african_context: Optional[str] = None,
    feedback_type: str = "correction",
    current_user: User = Depends(get_current_user)
):
    """
    Submit feedback on AI vision analysis.
    
    This is KEY for improving Vantage Vision for South African context!
    
    Users can:
    - Correct AI descriptions
    - Add missing context
    - Rate accuracy
    - Provide SA-specific notes
    
    All feedback is used to fine-tune the model.
    """
    # Get original analysis
    from alibi.camera_analysis_store import get_camera_analysis_store
    store = get_camera_analysis_store()
    recent = store.get_recent(limit=1000, hours=720)  # Last 30 days
    
    original = None
    for analysis in recent:
        if analysis.analysis_id == analysis_id:
            original = analysis
            break
    
    if not original:
        raise HTTPException(status_code=404, detail="Analysis not found")
    
    # Create feedback record
    feedback = FeedbackRecord(
        feedback_id=str(uuid.uuid4()),
        analysis_id=analysis_id,
        timestamp=datetime.utcnow().isoformat(),
        user=current_user.username,
        user_role=current_user.role.value,
        original_description=original.description,
        original_confidence=original.confidence,
        original_objects=original.detected_objects,
        original_activities=original.detected_activities,
        original_safety_concern=original.safety_concern,
        corrected_description=corrected_description,
        corrected_objects=corrected_objects,
        corrected_activities=corrected_activities,
        corrected_safety_concern=corrected_safety_concern,
        feedback_type=feedback_type,
        accuracy_rating=accuracy_rating,
        missing_context=missing_context,
        south_african_context=south_african_context,
        metadata={
            "user_full_name": current_user.full_name,
            "timestamp": datetime.utcnow().isoformat()
        }
    )
    
    # Collect feedback
    collector = get_vision_data_collector()
    collector.collect_feedback(feedback)
    
    return {
        "status": "success",
        "message": "Feedback collected! Thank you for improving Vantage Vision.",
        "feedback_id": feedback.feedback_id
    }


@router.get("/improvement-stats")
async def get_improvement_stats(
    current_user: User = Depends(require_role([Role.SUPERVISOR, Role.ADMIN]))
):
    """
    Get statistics on AI improvement data collection.
    
    Shows:
    - How much feedback collected
    - Improvement rate
    - South African context coverage
    - Fine-tuning readiness
    
    Admin/Supervisor only.
    """
    collector = get_vision_data_collector()
    stats = collector.get_feedback_stats()
    vocab = collector.extract_south_african_vocabulary()
    
    return {
        "stats": stats,
        "vocabulary": vocab,
        "fine_tuning_readiness": stats['total_feedback'] >= 100,
        "recommended_examples": max(0, 100 - stats['total_feedback'])
    }


@router.get("/improvement-report")
async def get_improvement_report(
    current_user: User = Depends(require_role([Role.ADMIN]))
):
    """
    Generate full improvement report (Admin only).
    
    Returns markdown report on:
    - Data collection progress
    - Regional vocabulary discovered
    - Recommendations for fine-tuning
    """
    collector = get_vision_data_collector()
    report = collector.export_improvement_report()
    
    return {
        "report": report,
        "format": "markdown"
    }


@router.post("/prepare-fine-tuning")
async def prepare_fine_tuning_dataset(
    current_user: User = Depends(require_role([Role.ADMIN]))
):
    """
    Prepare dataset for OpenAI fine-tuning (Admin only).
    
    Creates JSONL file ready for upload to OpenAI.
    Returns info on dataset readiness.
    """
    collector = get_vision_data_collector()
    result = collector.prepare_fine_tuning_dataset()
    
    return result


from typing import Optional, List
