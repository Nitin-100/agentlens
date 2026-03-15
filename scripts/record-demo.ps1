# Recording the AgentLens Demo GIF
# ==================================
#
# This script starts the backend + loads demo data so you can record a GIF.
# Use OBS Studio (free) or ShareX to record, then convert to GIF.
#
# Steps:
#   1. Run this script to start the server and load demo data
#   2. Open http://localhost:5173 in your browser (or http://localhost:8340/dashboard)
#   3. Start screen recording (OBS / ShareX / Kap on macOS)
#   4. Walk through the demo flow below (~60 seconds)
#   5. Stop recording
#   6. Convert to GIF with ffmpeg (command below)
#   7. Save as docs/demo.gif and push to GitHub
#
# Demo flow to record (60 seconds):
#   0:00 - Show the Overview page (cost, tokens, sessions, agents)
#   0:10 - Click "Sessions" — show the sessions list with agent names, cost, errors
#   0:18 - Click a session — show the trace tree (nested events)
#   0:28 - Switch to "Graph" tab — show the agent DAG visualization
#   0:35 - Switch to "Timeline" tab — show the waterfall
#   0:40 - Go to "Anomalies" page — show detected cost anomalies
#   0:50 - Go to "Live" page — show real-time event stream
#   0:55 - Back to Overview — done
#
# Convert MP4 to GIF (adjust width as needed):
#   ffmpeg -i demo.mp4 -vf "fps=10,scale=800:-1:flags=lanczos" -loop 0 docs/demo.gif
#
# Or for higher quality with a palette:
#   ffmpeg -i demo.mp4 -vf "fps=10,scale=800:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse" -loop 0 docs/demo.gif

Write-Host ""
Write-Host "=== AgentLens Demo Recording Setup ===" -ForegroundColor Cyan
Write-Host ""

# Start backend
Write-Host "[1/3] Starting backend server..." -ForegroundColor Yellow
$backend = Start-Process -NoNewWindow -PassThru -FilePath "python" -ArgumentList "-c", "import uvicorn; uvicorn.run('main:app', host='0.0.0.0', port=8340)" -WorkingDirectory "$PSScriptRoot\..\backend"
Start-Sleep -Seconds 3

# Load demo data
Write-Host "[2/3] Loading demo data..." -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "http://localhost:8340/api/v1/demo/load" -Method POST -ContentType "application/json" -Body "{}"
    Write-Host "  Loaded $($response.inserted) events across $($response.agents.Count) agents" -ForegroundColor Green
} catch {
    Write-Host "  Failed to load demo data: $_" -ForegroundColor Red
}

# Start dashboard
Write-Host "[3/3] Starting dashboard..." -ForegroundColor Yellow
$dashboard = Start-Process -NoNewWindow -PassThru -FilePath "node" -ArgumentList "node_modules\vite\bin\vite.js", "--host" -WorkingDirectory "$PSScriptRoot\..\dashboard"
Start-Sleep -Seconds 3

Write-Host ""
Write-Host "=== Ready to record! ===" -ForegroundColor Green
Write-Host ""
Write-Host "  Dashboard: http://localhost:5173" -ForegroundColor White
Write-Host "  Backend:   http://localhost:8340" -ForegroundColor White
Write-Host ""
Write-Host "  Start your screen recorder and walk through:" -ForegroundColor White
Write-Host "    Overview -> Sessions -> Session Detail (tree) -> Graph -> Timeline -> Anomalies -> Live -> Done" -ForegroundColor Gray
Write-Host ""
Write-Host "  Press Ctrl+C to stop servers when done." -ForegroundColor Yellow
Write-Host ""

# Wait for Ctrl+C
try {
    Wait-Process -Id $backend.Id
} finally {
    Stop-Process -Id $backend.Id -ErrorAction SilentlyContinue
    Stop-Process -Id $dashboard.Id -ErrorAction SilentlyContinue
    Write-Host "Servers stopped." -ForegroundColor Yellow
}
