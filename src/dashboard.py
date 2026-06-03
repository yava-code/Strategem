import http.server
import socketserver
import json
import threading
import time
from typing import Dict, Any, List, Optional

# Thread-safe global store for telemetry
telemetry_lock = threading.Lock()
telemetry_data: Dict[str, Any] = {
    "step": 0,
    "extrinsic_reward": 0.0,
    "intrinsic_reward": 0.0,
    "loss": 0.0,
    "anomalies": [],
    "positions": [],
    "obstacles": [],
    "bug_zones": [],
    "player_pos": [50.0, 50.0],
    "goal_pos": [90.0, 90.0],
    "map_size": [100.0, 100.0],
    "agents": {}  # swarm roster: name -> {step, extrinsic, intrinsic, anomalies, profile}
}

class DashboardHTTPHandler(http.server.BaseHTTPRequestHandler):
    """Handler for the lightweight developer dashboard UI and telemetry API."""
    
    def log_message(self, format, *args):
        # Override to suppress printing HTTP requests to stdout to keep training output clean
        return

    def do_GET(self):
        global telemetry_data
        
        # 1. API endpoint to retrieve the live JSON packet
        if self.path == "/api/telemetry":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            with telemetry_lock:
                # Return telemetry and truncate positions list to latest 500 to keep network light
                data_copy = telemetry_data.copy()
                data_copy["positions"] = telemetry_data["positions"][-300:]
                self.wfile.write(json.dumps(data_copy).encode("utf-8"))
            return

        # 1b. Swarm roster endpoint
        if self.path == "/api/swarm":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            with telemetry_lock:
                self.wfile.write(json.dumps(telemetry_data["agents"]).encode("utf-8"))
            return

        # 2. Main HTML/CSS dashboard route
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(self.get_html_content().encode("utf-8"))
            return

        # 3. Not Found
        self.send_response(404)
        self.end_headers()

    def get_html_content(self) -> str:
        """Returns the complete, beautiful glassmorphism styled developer UI."""
        return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>The Bridge-Maker | RL Developer Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {
            --bg-color: #0f172a;
            --card-bg: rgba(30, 41, 59, 0.7);
            --card-border: rgba(255, 255, 255, 0.08);
            --neon-blue: #00f2fe;
            --neon-pink: #f107a3;
            --neon-green: #00ff87;
            --neon-yellow: #f1c40f;
            --text-main: #f8fafc;
            --text-sub: #94a3b8;
        }

        body {
            background-color: var(--bg-color);
            color: var(--text-main);
            font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            margin: 0;
            padding: 20px;
            overflow-x: hidden;
        }

        /* Glassmorphism Layout */
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 15px 30px;
            background: var(--card-bg);
            backdrop-filter: blur(12px);
            border: 1px solid var(--card-border);
            border-radius: 16px;
            margin-bottom: 20px;
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
        }

        .header h1 {
            margin: 0;
            font-size: 24px;
            font-weight: 800;
            background: linear-gradient(45deg, var(--neon-blue), var(--neon-pink));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .status-dot {
            display: inline-block;
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background-color: var(--neon-green);
            box-shadow: 0 0 10px var(--neon-green);
            margin-right: 8px;
        }

        .main-grid {
            display: grid;
            grid-template-columns: 350px 1fr;
            gap: 20px;
        }

        .side-panel {
            display: flex;
            flex-direction: column;
            gap: 20px;
        }

        .card {
            background: var(--card-bg);
            backdrop-filter: blur(12px);
            border: 1px solid var(--card-border);
            border-radius: 16px;
            padding: 20px;
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.2);
        }

        .card-title {
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 1.5px;
            color: var(--text-sub);
            margin-bottom: 15px;
            font-weight: 700;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            padding-bottom: 8px;
        }

        .stat-val {
            font-size: 32px;
            font-weight: 800;
            color: var(--text-main);
            margin: 5px 0;
        }

        .stat-unit {
            font-size: 12px;
            color: var(--text-sub);
        }

        /* 2D Canvas Map */
        #game-canvas {
            background: #020617;
            border-radius: 12px;
            width: 100%;
            height: 310px;
            border: 1px solid rgba(255, 255, 255, 0.05);
        }

        /* Live Scrolling Logger */
        .log-container {
            height: 250px;
            overflow-y: auto;
            font-family: 'Consolas', 'Courier New', monospace;
            font-size: 11px;
            display: flex;
            flex-direction: column;
            gap: 8px;
            padding-right: 5px;
        }

        .log-entry {
            padding: 8px;
            border-radius: 8px;
            background: rgba(0, 0, 0, 0.2);
            border-left: 3px solid var(--neon-blue);
        }

        .log-entry.bug {
            border-left-color: var(--neon-yellow);
        }

        .log-entry.oob {
            border-left-color: var(--neon-pink);
        }

        .charts-container {
            display: grid;
            grid-template-rows: 1fr;
            gap: 20px;
        }

        canvas.chart-canvas {
            max-height: 320px;
        }
    </style>
</head>
<body>

    <div class="header">
        <h1>THE BRIDGE-MAKER // SDK Dashboard</h1>
        <div>
            <span class="status-dot"></span>
            <span style="color: var(--text-sub); font-size: 14px;">Active Telemetry Node</span>
        </div>
    </div>

    <div class="main-grid">
        <div class="side-panel">
            <div class="card">
                <div class="card-title">Training Metrics</div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px;">
                    <div>
                        <span class="stat-unit">TIMESTEP</span>
                        <div class="stat-val" id="val-step">0</div>
                    </div>
                    <div>
                        <span class="stat-unit">ANOMALIES</span>
                        <div class="stat-val" id="val-anomalies" style="color: var(--neon-yellow);">0</div>
                    </div>
                </div>
            </div>

            <div class="card">
                <div class="card-title">QA Swarm Testers</div>
                <div id="swarm-list" style="display:flex; flex-direction:column; gap:8px;">
                    <div style="color: var(--text-sub); font-size: 12px;">No agents reporting yet...</div>
                </div>
            </div>

            <div class="card">
                <div class="card-title">Exploration Coverage Map</div>
                <canvas id="game-canvas" width="300" height="300"></canvas>
            </div>
        </div>

        <div class="charts-container">
            <div class="card">
                <div class="card-title">Training Rewards (Extrinsic vs Intrinsic)</div>
                <canvas id="rewards-chart" class="chart-canvas"></canvas>
            </div>

            <div class="card">
                <div class="card-title">Glitch & Vulnerability Stream</div>
                <div class="log-container" id="log-list">
                    <div style="color: var(--text-sub); text-align: center; margin-top: 100px;">Waiting for telemetry stream...</div>
                </div>
            </div>
        </div>
    </div>

    <script>
        const canvas = document.getElementById("game-canvas");
        const ctx = canvas.getContext("2d");
        let rewardChart;

        // Initialize Chart.js
        function initChart() {
            const chartCtx = document.getElementById("rewards-chart").getContext("2d");
            rewardChart = new Chart(chartCtx, {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [
                        {
                            label: 'Extrinsic (Manual)',
                            data: [],
                            borderColor: '#00f2fe',
                            borderWidth: 2,
                            tension: 0.3,
                            fill: false
                        },
                        {
                            label: 'Intrinsic (Curiosity)',
                            data: [],
                            borderColor: '#f107a3',
                            borderWidth: 2,
                            tension: 0.3,
                            fill: false
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        x: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#94a3b8' } },
                        y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#94a3b8' } }
                    },
                    plugins: {
                        legend: { labels: { color: '#f8fafc' } }
                    }
                }
            });
        }

        // Draw Map state (agent, player, obstacles, bugs)
        function drawMap(data) {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            const w = canvas.width;
            const h = canvas.height;
            const mapW = data.map_size[0];
            const mapH = data.map_size[1];

            // Scale factor
            const sx = w / mapW;
            const sy = h / mapH;

            // Draw obstacles
            ctx.fillStyle = "rgba(231, 76, 60, 0.4)";
            data.obstacles.forEach(o => {
                if(o.type === "rect") {
                    ctx.fillRect(o.x * sx, o.y * sy, o.w * sx, o.h * sy);
                }
            });

            // Draw bug zones
            ctx.fillStyle = "rgba(241, 196, 15, 0.3)";
            ctx.strokeStyle = "rgba(241, 196, 15, 0.8)";
            ctx.lineWidth = 1;
            data.bug_zones.forEach(bz => {
                ctx.fillRect(bz.x * sx, bz.y * sy, bz.w * sx, bz.h * sy);
                ctx.strokeRect(bz.x * sx, bz.y * sy, bz.w * sx, bz.h * sy);
            });

            // Draw agent positions trail
            ctx.fillStyle = "rgba(0, 242, 254, 0.3)";
            data.positions.forEach(pos => {
                ctx.beginPath();
                ctx.arc(pos[0] * sx, pos[1] * sy, 2, 0, Math.PI * 2);
                ctx.fill();
            });

            // Draw goal objective
            ctx.fillStyle = "#00ff87";
            ctx.beginPath();
            ctx.arc(data.goal_pos[0] * sx, data.goal_pos[1] * sy, 6, 0, Math.PI * 2);
            ctx.fill();

            // Draw player
            ctx.fillStyle = "#3498db";
            ctx.beginPath();
            ctx.arc(data.player_pos[0] * sx, data.player_pos[1] * sy, 5, 0, Math.PI * 2);
            ctx.fill();

            // Draw latest agent position
            if (data.positions.length > 0) {
                const latest = data.positions[data.positions.length - 1];
                ctx.fillStyle = "#00f2fe";
                ctx.strokeStyle = "#ffffff";
                ctx.lineWidth = 2;
                ctx.beginPath();
                ctx.arc(latest[0] * sx, latest[1] * sy, 6, 0, Math.PI * 2);
                ctx.fill();
                ctx.stroke();
            }
        }

        // Live updater
        let lastStep = -1;
        function updateDashboard() {
            fetch("/api/telemetry")
                .then(r => r.json())
                .then(data => {
                    document.getElementById("val-step").innerText = data.step;
                    document.getElementById("val-anomalies").innerText = data.anomalies.length;

                    drawMap(data);

                    // Add chart points
                    if (data.step > lastStep && data.step % 100 === 0) {
                        lastStep = data.step;
                        rewardChart.data.labels.push(data.step);
                        rewardChart.data.datasets[0].data.push(data.extrinsic_reward);
                        rewardChart.data.datasets[1].data.push(data.intrinsic_reward);
                        
                        // Limit chart length
                        if(rewardChart.data.labels.length > 50) {
                            rewardChart.data.labels.shift();
                            rewardChart.data.datasets[0].data.shift();
                            rewardChart.data.datasets[1].data.shift();
                        }
                        rewardChart.update();
                    }

                    // Render Anomalies Stream
                    const logList = document.getElementById("log-list");
                    if (data.anomalies.length === 0) {
                        logList.innerHTML = `<div style="color: var(--text-sub); text-align: center; margin-top: 100px;">No exploits detected yet. Explorer is scanning...</div>`;
                    } else {
                        logList.innerHTML = data.anomalies.map(a => {
                            let typeClass = "";
                            if(a.type === "BUG_ZONE_TRIGGER") typeClass = "bug";
                            if(a.type === "OUT_OF_BOUNDS") typeClass = "oob";
                            
                            return `
                                <div class="log-entry ${typeClass}">
                                    <strong style="color: #ffffff;">[${a.type}]</strong> 
                                    Step: ${a.step} | Coord: [${a.details.coords ? a.details.coords[0].toFixed(1) : ''}, ${a.details.coords ? a.details.coords[1].toFixed(1) : ''}] 
                                    ${a.details.zone_name ? `| Zone: ` + a.details.zone_name : ""}
                                    ${a.details.code ? `| Err: ` + a.details.code : ""}
                                </div>
                            `;
                        }).join("");
                    }
                })
                .catch(e => console.error("Telemetry API offline:", e));
        }

        // Swarm roster updater
        function updateSwarm() {
            fetch("/api/swarm")
                .then(r => r.json())
                .then(agents => {
                    const names = Object.keys(agents);
                    const list = document.getElementById("swarm-list");
                    if (names.length === 0) return;
                    list.innerHTML = names.map(n => {
                        const a = agents[n];
                        return `
                            <div style="padding:8px; border-radius:8px; background:rgba(0,0,0,0.2); border-left:3px solid var(--neon-green);">
                                <div style="display:flex; justify-content:space-between;">
                                    <strong style="color:#fff;">${n}</strong>
                                    <span style="color:var(--neon-yellow);">${a.anomalies} finds</span>
                                </div>
                                <div style="font-size:11px; color:var(--text-sub);">
                                    step ${a.step} · R ${a.extrinsic} · curio ${a.intrinsic}
                                    ${a.profile ? "· " + a.profile : ""}
                                </div>
                            </div>`;
                    }).join("");
                })
                .catch(e => {});
        }

        window.onload = () => {
            initChart();
            setInterval(updateDashboard, 500);
            setInterval(updateSwarm, 700);
        };
    </script>
</body>
</html>
"""

class DashboardServer:
    """Zero-dependency daemon thread running the HTTP telemetry server."""
    def __init__(self, port: int = 8000):
        self.port = port
        self.server: Optional[socketserver.TCPServer] = None
        self.thread: Optional[threading.Thread] = None

    def start(self):
        socketserver.TCPServer.allow_reuse_address = True
        self.server = socketserver.TCPServer(("", self.port), DashboardHTTPHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        print(f"[Dashboard-Server] Web Console online at: http://localhost:{self.port}")

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            print("[Dashboard-Server] Server stopped.")

    @staticmethod
    def update_telemetry(step: int, 
                         extrinsic_reward: float, 
                         intrinsic_reward: float, 
                         loss: float,
                         player_pos: List[float],
                         goal_pos: List[float],
                         map_size: List[float],
                         obstacles: List[Dict[str, Any]],
                         bug_zones: List[Dict[str, Any]]):
        """Update global state dictionary thread-safely."""
        global telemetry_data
        with telemetry_lock:
            telemetry_data["step"] = step
            telemetry_data["extrinsic_reward"] = float(extrinsic_reward)
            telemetry_data["intrinsic_reward"] = float(intrinsic_reward)
            telemetry_data["loss"] = float(loss)
            telemetry_data["player_pos"] = player_pos
            telemetry_data["goal_pos"] = goal_pos
            telemetry_data["map_size"] = map_size
            telemetry_data["obstacles"] = obstacles
            telemetry_data["bug_zones"] = bug_zones

    @staticmethod
    def update_agent(name: str, step: int, extrinsic_reward: float, intrinsic_reward: float,
                     anomalies: int, profile: str = ""):
        """Upsert one swarm tester's live stats into the roster."""
        global telemetry_data
        with telemetry_lock:
            telemetry_data["agents"][name] = {
                "step": int(step),
                "extrinsic": round(float(extrinsic_reward), 3),
                "intrinsic": round(float(intrinsic_reward), 3),
                "anomalies": int(anomalies),
                "profile": profile,
            }

    @staticmethod
    def update_metrics(step: int, extrinsic_reward: float, intrinsic_reward: float, loss: float):
        """Scalar-only update (reward/curiosity) that leaves map geometry intact."""
        global telemetry_data
        with telemetry_lock:
            telemetry_data["step"] = step
            telemetry_data["extrinsic_reward"] = float(extrinsic_reward)
            telemetry_data["intrinsic_reward"] = float(intrinsic_reward)
            telemetry_data["loss"] = float(loss)

    @staticmethod
    def log_position(x: float, y: float):
        global telemetry_data
        with telemetry_lock:
            telemetry_data["positions"].append([float(x), float(y)])

    @staticmethod
    def log_anomaly(anomaly_type: str, details: Dict[str, Any], step: int):
        global telemetry_data
        with telemetry_lock:
            # Avoid duplicate anomaly logging if already logged at the exact same step
            if len(telemetry_data["anomalies"]) > 0:
                if telemetry_data["anomalies"][-1]["step"] == step and telemetry_data["anomalies"][-1]["type"] == anomaly_type:
                    return
            telemetry_data["anomalies"].append({
                "step": step,
                "type": anomaly_type,
                "details": details
            })
