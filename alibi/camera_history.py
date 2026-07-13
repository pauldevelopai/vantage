"""
Camera History Page - Browse analyzed snapshots with AI descriptions
"""

CAMERA_HISTORY_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Camera History</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 20px;
        }
        
        .back-btn {
            background: rgba(255,255,255,0.2);
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 10px;
            text-decoration: none;
            font-size: 16px;
        }
        
        h1 {
            color: white;
            font-size: 28px;
        }
        
        .filter-bar {
            background: rgba(255,255,255,0.15);
            backdrop-filter: blur(10px);
            border-radius: 15px;
            padding: 15px;
            margin-bottom: 20px;
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }
        
        .filter-bar button {
            background: rgba(255,255,255,0.2);
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 8px;
            font-size: 14px;
            cursor: pointer;
        }
        
        .filter-bar button.active {
            background: white;
            color: #667eea;
        }
        
        .stats {
            background: rgba(255,255,255,0.15);
            backdrop-filter: blur(10px);
            border-radius: 15px;
            padding: 15px;
            margin-bottom: 20px;
            color: white;
            display: flex;
            gap: 20px;
            flex-wrap: wrap;
        }
        
        .stat {
            flex: 1;
            min-width: 120px;
        }
        
        .stat-value {
            font-size: 24px;
            font-weight: 600;
        }
        
        .stat-label {
            font-size: 12px;
            opacity: 0.8;
        }
        
        .gallery {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 15px;
        }
        
        .snapshot-card {
            background: white;
            border-radius: 15px;
            overflow: hidden;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            cursor: pointer;
            transition: transform 0.2s;
        }
        
        .snapshot-card:active {
            transform: scale(0.98);
        }
        
        .snapshot-card.safety-concern {
            border: 3px solid #ef4444;
        }
        
        .snapshot-img {
            width: 100%;
            height: 200px;
            object-fit: cover;
            background: #f0f0f0;
        }
        
        .snapshot-content {
            padding: 15px;
        }
        
        .snapshot-time {
            font-size: 12px;
            color: #666;
            margin-bottom: 8px;
        }
        
        .snapshot-description {
            font-size: 14px;
            color: #333;
            margin-bottom: 10px;
            font-weight: 500;
        }
        
        .snapshot-meta {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
            margin-bottom: 8px;
        }
        
        .tag {
            background: #e0e0e0;
            padding: 4px 8px;
            border-radius: 6px;
            font-size: 11px;
            color: #555;
        }
        
        .tag.safety {
            background: #fee;
            color: #c33;
            font-weight: 600;
        }
        
        .snapshot-user {
            font-size: 11px;
            color: #999;
        }
        
        .loading {
            text-align: center;
            color: white;
            padding: 40px;
            font-size: 18px;
        }
        
        .empty {
            text-align: center;
            color: white;
            padding: 60px 20px;
        }
        
        .empty-icon {
            font-size: 64px;
            margin-bottom: 20px;
        }
        
        .cleanup-btn {
            background: #ef4444;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 10px;
            font-size: 14px;
            cursor: pointer;
        }
        
        /* Modal for full view */
        .modal {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0,0,0,0.9);
            z-index: 1000;
            padding: 20px;
            overflow-y: auto;
        }
        
        .modal.active {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
        }
        
        .modal-content {
            background: white;
            border-radius: 20px;
            padding: 20px;
            max-width: 800px;
            width: 100%;
        }
        
        .modal-img {
            width: 100%;
            border-radius: 10px;
            margin-bottom: 20px;
        }
        
        .modal-close {
            position: fixed;
            top: 20px;
            right: 20px;
            background: white;
            border: none;
            width: 40px;
            height: 40px;
            border-radius: 50%;
            font-size: 24px;
            cursor: pointer;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>Camera History</h1>
        <button class="cleanup-btn" onclick="cleanupOld()">Cleanup</button>
    </div>
    
    <div class="stats" id="stats">
        <div class="stat">
            <div class="stat-value" id="totalCount">-</div>
            <div class="stat-label">Total Snapshots</div>
        </div>
        <div class="stat">
            <div class="stat-value" id="safetyCount">-</div>
            <div class="stat-label">Safety Concerns</div>
        </div>
        <div class="stat">
            <div class="stat-value" id="todayCount">-</div>
            <div class="stat-label">Today</div>
        </div>
    </div>
    
    <div class="filter-bar">
        <button class="active" onclick="filterBy('all')">All</button>
        <button onclick="filterBy('today')">Today</button>
        <button onclick="filterBy('safety')">Safety Concerns</button>
        <button onclick="filterBy('week')">This Week</button>
    </div>
    
    <div class="gallery" id="gallery">
        <div class="loading">Loading snapshots...</div>
    </div>
    
    <div class="modal" id="modal">
        <button class="modal-close" onclick="closeModal()">×</button>
        <div class="modal-content" id="modalContent"></div>
    </div>
    
    <div class="modal" id="feedbackModal">
        <button class="modal-close" onclick="closeFeedbackModal()">×</button>
        <div class="modal-content">
            <h2>🇿🇦 Improve Vantage Vision for South Africa</h2>
            <p style="color: #666; margin-bottom: 20px;">Your corrections help Vantage understand South African context better!</p>
            
            <form id="feedbackForm">
                <input type="hidden" id="feedbackAnalysisId">
                
                <div style="margin-bottom: 15px;">
                    <label style="display: block; margin-bottom: 5px; font-weight: 600;">Original Description:</label>
                    <div id="originalDescription" style="background: #f5f5f5; padding: 10px; border-radius: 5px;"></div>
                </div>
                
                <div style="margin-bottom: 15px;">
                    <label for="correctedDescription" style="display: block; margin-bottom: 5px; font-weight: 600;">
                        Corrected Description (what AI should have said):
                    </label>
                    <textarea id="correctedDescription" rows="3" style="width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 5px;" placeholder="e.g., Minibus taxi loading passengers at taxi rank"></textarea>
                </div>
                
                <div style="margin-bottom: 15px;">
                    <label for="saContext" style="display: block; margin-bottom: 5px; font-weight: 600;">
                        South African Context Notes:
                    </label>
                    <textarea id="saContext" rows="2" style="width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 5px;" placeholder="e.g., This is a typical township scene with RDP houses, or This shows a bakkie (pickup truck), not just a 'truck'"></textarea>
                </div>
                
                <div style="margin-bottom: 15px;">
                    <label for="missingContext" style="display: block; margin-bottom: 5px; font-weight: 600;">
                        What did AI miss?
                    </label>
                    <textarea id="missingContext" rows="2" style="width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 5px;" placeholder="e.g., Missed the spaza shop in background, Didn't recognize informal settlement"></textarea>
                </div>
                
                <div style="margin-bottom: 15px;">
                    <label style="display: block; margin-bottom: 5px; font-weight: 600;">Rate AI Accuracy:</label>
                    <div style="display: flex; gap: 10px;">
                        <button type="button" class="rating-btn" data-rating="1">1⭐</button>
                        <button type="button" class="rating-btn" data-rating="2">2⭐</button>
                        <button type="button" class="rating-btn" data-rating="3">3⭐</button>
                        <button type="button" class="rating-btn" data-rating="4">4⭐</button>
                        <button type="button" class="rating-btn" data-rating="5">5⭐</button>
                    </div>
                    <input type="hidden" id="accuracyRating">
                </div>
                
                <div style="background: #fff3cd; padding: 10px; border-radius: 5px; margin-bottom: 15px; font-size: 13px;">
                    <strong>💡 Tips:</strong>
                    <ul style="margin: 5px 0 0 20px;">
                        <li>Use SA terms: "minibus taxi", "bakkie", "township", "braai"</li>
                        <li>Be specific about regional context</li>
                        <li>Your feedback trains the AI!</li>
                    </ul>
                </div>
                
                <button type="submit" style="width: 100%; padding: 14px; background: #10b981; color: white; border: none; border-radius: 10px; font-size: 16px; font-weight: 600; cursor: pointer;">
                    ✅ Submit Feedback
                </button>
            </form>
        </div>
    </div>
    
    <style>
        .rating-btn {
            flex: 1;
            padding: 8px;
            background: #f0f0f0;
            border: 2px solid #ddd;
            border-radius: 5px;
            cursor: pointer;
        }
        .rating-btn.selected {
            background: #fbbf24;
            border-color: #f59e0b;
        }
    </style>
    
    <script>
        const token = localStorage.getItem('alibi_token');
        let allSnapshots = [];
        let currentFilter = 'all';
        
        if (!token) {
            window.location.href = '/camera/login';
        }
        
        async function loadSnapshots() {
            try {
                const response = await fetch('/camera/analysis/recent?hours=168&limit=500', {
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                
                if (!response.ok) {
                    throw new Error('Failed to load');
                }
                
                const data = await response.json();
                allSnapshots = data.analyses || [];
                
                updateStats();
                displaySnapshots(allSnapshots);
            } catch (error) {
                console.error('Error:', error);
                document.getElementById('gallery').innerHTML = '<div class="empty"><div class="empty-icon">❌</div><div>Failed to load snapshots</div></div>';
            }
        }
        
        function updateStats() {
            const now = new Date();
            const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
            
            const todaySnapshots = allSnapshots.filter(s => 
                new Date(s.timestamp) >= todayStart
            );
            
            const safetySnapshots = allSnapshots.filter(s => s.safety_concern);
            
            document.getElementById('totalCount').textContent = allSnapshots.length;
            document.getElementById('safetyCount').textContent = safetySnapshots.length;
            document.getElementById('todayCount').textContent = todaySnapshots.length;
        }
        
        function filterBy(type) {
            currentFilter = type;
            
            // Update button states
            document.querySelectorAll('.filter-bar button').forEach(btn => {
                btn.classList.remove('active');
            });
            event.target.classList.add('active');
            
            // Filter snapshots
            let filtered = allSnapshots;
            const now = new Date();
            
            if (type === 'today') {
                const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
                filtered = allSnapshots.filter(s => new Date(s.timestamp) >= todayStart);
            } else if (type === 'safety') {
                filtered = allSnapshots.filter(s => s.safety_concern);
            } else if (type === 'week') {
                const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
                filtered = allSnapshots.filter(s => new Date(s.timestamp) >= weekAgo);
            }
            
            displaySnapshots(filtered);
        }
        
        function displaySnapshots(snapshots) {
            const gallery = document.getElementById('gallery');
            
            if (snapshots.length === 0) {
                gallery.innerHTML = '<div class="empty"><div class="empty-icon">📸</div><div>No snapshots found</div></div>';
                return;
            }
            
            gallery.innerHTML = snapshots.map(snapshot => {
                const time = new Date(snapshot.timestamp).toLocaleString();
                const safetyClass = snapshot.safety_concern ? 'safety-concern' : '';
                
                return `
                    <div class="snapshot-card ${safetyClass}" onclick='showSnapshot(${JSON.stringify(snapshot).replace(/'/g, "&apos;")})'>
                        <img src="${snapshot.thumbnail_path || snapshot.snapshot_path}" class="snapshot-img" alt="Snapshot">
                        <div class="snapshot-content">
                            <div class="snapshot-time">${time}</div>
                            <div class="snapshot-description">${snapshot.description}</div>
                            <div class="snapshot-meta">
                                ${snapshot.safety_concern ? '<span class="tag safety">⚠️ Safety Concern</span>' : ''}
                                ${snapshot.detected_objects.slice(0, 3).map(obj => 
                                    `<span class="tag">${obj}</span>`
                                ).join('')}
                            </div>
                            <div class="snapshot-user">by ${snapshot.user} • ${snapshot.method}</div>
                        </div>
                    </div>
                `;
            }).join('');
        }
        
        function showSnapshot(snapshot) {
            const modal = document.getElementById('modal');
            const modalContent = document.getElementById('modalContent');
            
            const time = new Date(snapshot.timestamp).toLocaleString();
            
            modalContent.innerHTML = `
                <img src="${snapshot.snapshot_path}" class="modal-img" alt="Full snapshot">
                <h2>${snapshot.description}</h2>
                <p><strong>Time:</strong> ${time}</p>
                <p><strong>User:</strong> ${snapshot.user}</p>
                <p><strong>Confidence:</strong> ${(snapshot.confidence * 100).toFixed(0)}%</p>
                ${snapshot.safety_concern ? '<p style="color: #ef4444; font-weight: 600;">⚠️ SAFETY CONCERN DETECTED</p>' : ''}
                <p><strong>Detected Objects:</strong> ${snapshot.detected_objects.join(', ') || 'None'}</p>
                <p><strong>Detected Activities:</strong> ${snapshot.detected_activities.join(', ') || 'None'}</p>
                <p><strong>Method:</strong> ${snapshot.method}</p>
                <hr style="margin: 20px 0;">
                <div style="background: #f0f7ff; padding: 15px; border-radius: 10px; margin-bottom: 10px;">
                    <strong>💡 Help Improve Vantage Vision for South Africa!</strong>
                    <p style="font-size: 13px; margin-top: 5px;">
                        Your feedback helps us understand SA context better (townships, minibus taxis, local objects, etc.)
                    </p>
                </div>
                <button onclick="provideFeedback('${snapshot.analysis_id}')" style="width: 100%; padding: 12px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border: none; border-radius: 10px; font-size: 16px; cursor: pointer; margin-bottom: 10px;">
                    ✏️ Provide Feedback on This Analysis
                </button>
                <button onclick="createRedFlag('${snapshot.analysis_id}', '${snapshot.snapshot_path}')" style="width: 100%; padding: 12px; background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%); color: white; border: none; border-radius: 10px; font-size: 16px; cursor: pointer; font-weight: 600;">
                    🚩 RED FLAG - Mark as Important
                </button>
            `;
            
            modal.classList.add('active');
        }
        
        function closeModal() {
            document.getElementById('modal').classList.remove('active');
        }
        
        async function cleanupOld() {
            if (!confirm('Delete snapshots older than 7 days?')) return;
            
            try {
                const response = await fetch('/camera/cleanup', {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                
                const data = await response.json();
                alert(`Cleaned up ${data.deleted} old files`);
                loadSnapshots();
            } catch (error) {
                alert('Cleanup failed: ' + error.message);
            }
        }
        
        function provideFeedback(analysisId) {
            const snapshot = allSnapshots.find(s => s.analysis_id === analysisId);
            if (!snapshot) return;
            
            document.getElementById('feedbackAnalysisId').value = analysisId;
            document.getElementById('originalDescription').textContent = snapshot.description;
            document.getElementById('feedbackModal').classList.add('active');
            closeModal();
        }
        
        function closeFeedbackModal() {
            document.getElementById('feedbackModal').classList.remove('active');
            document.getElementById('feedbackForm').reset();
            document.querySelectorAll('.rating-btn').forEach(btn => btn.classList.remove('selected'));
        }
        
        // Rating button handling
        document.querySelectorAll('.rating-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                document.querySelectorAll('.rating-btn').forEach(b => b.classList.remove('selected'));
                this.classList.add('selected');
                document.getElementById('accuracyRating').value = this.dataset.rating;
            });
        });
        
        // Feedback form submission
        document.getElementById('feedbackForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            
            const analysisId = document.getElementById('feedbackAnalysisId').value;
            const correctedDescription = document.getElementById('correctedDescription').value;
            const saContext = document.getElementById('saContext').value;
            const missingContext = document.getElementById('missingContext').value;
            const rating = document.getElementById('accuracyRating').value;
            
            if (!correctedDescription && !saContext && !missingContext && !rating) {
                alert('Please provide at least one piece of feedback');
                return;
            }
            
            try {
                const response = await fetch('/camera/feedback', {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${token}`,
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        analysis_id: analysisId,
                        corrected_description: correctedDescription || null,
                        south_african_context: saContext || null,
                        missing_context: missingContext || null,
                        accuracy_rating: rating ? parseInt(rating) : null,
                        feedback_type: 'correction'
                    })
                });
                
                if (response.ok) {
                    alert('✅ Thank you! Your feedback helps improve Vantage Vision for South Africa!');
                    closeFeedbackModal();
                } else {
                    const error = await response.json();
                    alert('Error: ' + (error.detail || 'Failed to submit feedback'));
                }
            } catch (error) {
                alert('Error submitting feedback: ' + error.message);
            }
        });
        
        // RED FLAG FUNCTIONALITY
        async function createRedFlag(analysisId, snapshotUrl) {
            const snapshot = allSnapshots.find(s => s.analysis_id === analysisId);
            if (!snapshot) return;
            
            const severity = prompt('Red Flag Severity:\\n1 = Low\\n2 = Medium\\n3 = High\\n4 = Critical\\n\\nEnter 1-4:', '3');
            if (!severity || !['1', '2', '3', '4'].includes(severity)) return;
            
            const severityMap = {'1': 'low', '2': 'medium', '3': 'high', '4': 'critical'};
            const severityName = severityMap[severity];
            
            const category = prompt('Category:\\n1 = Suspicious Person\\n2 = Suspicious Vehicle\\n3 = Suspicious Activity\\n4 = Location\\n5 = Pattern\\n6 = Other\\n\\nEnter 1-6:', '3');
            if (!category || !['1', '2', '3', '4', '5', '6'].includes(category)) return;
            
            const categoryMap = {
                '1': 'suspicious_person',
                '2': 'suspicious_vehicle', 
                '3': 'suspicious_activity',
                '4': 'location',
                '5': 'pattern',
                '6': 'other'
            };
            const categoryName = categoryMap[category];
            
            const description = prompt('Describe why this is flagged (required):', snapshot.description);
            if (!description) return;
            
            const location = prompt('Location (optional):', '');
            const tags = prompt('Tags (comma-separated, optional):', '');
            
            try {
                const response = await fetch('/camera/red-flag', {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${token}`,
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        analysis_id: analysisId,
                        severity: severityName,
                        category: categoryName,
                        description: description,
                        location: location || null,
                        tags: tags ? tags.split(',').map(t => t.trim()) : [],
                        snapshot_url: snapshotUrl
                    })
                });
                
                if (response.ok) {
                    const result = await response.json();
                    alert(`🚩 RED FLAG CREATED!\\n\\nFlag ID: ${result.flag_id}\\n\\nThis incident is now tracked in Insights & Reports.`);
                    closeModal();
                } else {
                    const error = await response.json();
                    alert('Error: ' + (error.detail || 'Failed to create red flag'));
                }
            } catch (error) {
                alert('Error creating red flag: ' + error.message);
            }
        }
        
        // Load on page load
        loadSnapshots();
        
        // Refresh every 30 seconds
        setInterval(loadSnapshots, 30000);
    </script>
</body>
</html>
"""
