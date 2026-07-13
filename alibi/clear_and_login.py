"""
Auto-fix page that clears localStorage and forces fresh login
"""

AUTO_FIX_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Fixing Vantage...</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0;
            color: white;
        }
        .container {
            background: rgba(255,255,255,0.1);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            padding: 40px;
            text-align: center;
            max-width: 500px;
        }
        h1 { font-size: 32px; margin-bottom: 20px; }
        p { font-size: 16px; margin: 10px 0; line-height: 1.6; }
        .status { font-size: 48px; margin: 20px 0; }
        .progress { margin: 20px 0; font-size: 14px; opacity: 0.9; }
    </style>
</head>
<body>
    <div class="container">
        <div class="status" id="icon">🔧</div>
        <h1 id="title">Fixing Vantage...</h1>
        <p id="message">Clearing corrupted data...</p>
        <div class="progress" id="progress"></div>
    </div>
    
    <script>
        const steps = [
            { icon: '🔧', title: 'Clearing Data...', message: 'Removing corrupted localStorage', delay: 500 },
            { icon: '✅', title: 'Fixed!', message: 'Redirecting to login...', delay: 1500 }
        ];
        
        let currentStep = 0;
        
        function updateUI(step) {
            document.getElementById('icon').textContent = step.icon;
            document.getElementById('title').textContent = step.title;
            document.getElementById('message').textContent = step.message;
            document.getElementById('progress').textContent = `Step ${currentStep + 1} of ${steps.length}`;
        }
        
        function nextStep() {
            if (currentStep < steps.length) {
                updateUI(steps[currentStep]);
                
                if (currentStep === 0) {
                    // Clear everything
                    localStorage.clear();
                    sessionStorage.clear();
                }
                
                currentStep++;
                setTimeout(nextStep, steps[currentStep - 1].delay);
            } else {
                // Redirect to login
                window.location.href = '/camera/login';
            }
        }
        
        // Start the process
        setTimeout(nextStep, 100);
    </script>
</body>
</html>
"""
