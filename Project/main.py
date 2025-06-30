import threading
import time
import random
import numpy as np
import networkx as nx
import requests
from flask import Flask, request, jsonify, render_template_string
import matplotlib.pyplot as plt

# ================================
# Configuration & Global Settings
# ================================
GRID_ROWS = 6
GRID_COLS = 6
SIMULATION_DURATION = 60           # total simulation time in seconds
UPDATE_INTERVAL = 2                # seconds between simulation updates
VEHICLE_COUNT = 3                  # number of emergency vehicles
FLUCTUATION = 0.5                  # traffic fluctuation factor for live data simulation
PREDICTION_ALPHA = 0.7             # smoothing factor for predictive module

# Server (Emergency Response Center) configuration
SERVER_HOST = '127.0.0.1'
SERVER_PORT = 5000

# ================================
# Emergency Response Center (Flask App)
# ================================
app = Flask(__name__)
# In-memory database for vehicle status reports
vehicle_status_db = {}

# Template for a simple dashboard page
DASHBOARD_TEMPLATE = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>Emergency Response Center Dashboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
      body { font-family: Arial, sans-serif; margin: 20px; }
      table { border-collapse: collapse; width: 100%; }
      th, td { text-align: left; padding: 8px; border: 1px solid #ddd; }
      tr:nth-child(even) {background-color: #f2f2f2;}
    </style>
    <script>
      function refreshPage() {
         window.location.reload();
      }
      setInterval(refreshPage, 5000);
    </script>
  </head>
  <body>
    <h2>Emergency Response Center Dashboard</h2>
    <p>Last updated: {{ timestamp }}</p>
    <table>
      <tr>
        <th>Vehicle ID</th>
        <th>Current Position</th>
        <th>Destination</th>
        <th>Route</th>
        <th>Route Length</th>
        <th>Last Update</th>
      </tr>
      {% for v in vehicles %}
      <tr>
        <td>{{ v.vehicle_id }}</td>
        <td>{{ v.current_position }}</td>
        <td>{{ v.destination }}</td>
        <td>{{ v.route }}</td>
        <td>{{ v.route_length }}</td>
        <td>{{ v.timestamp }}</td>
      </tr>
      {% endfor %}
    </table>
    <p>This dashboard auto-refreshes every 5 seconds.</p>
  </body>
</html>
"""

@app.route('/update', methods=['POST'])
def update_status():
    data = request.json
    vehicle_id = data.get("vehicle_id")
    # Update the in-memory store
    vehicle_status_db[vehicle_id] = data
    print(f"[Server] Update received from {vehicle_id}: {data}")
    return jsonify({"status": "received"}), 200

@app.route('/status', methods=['GET'])
def get_status():
    return jsonify(vehicle_status_db), 200

@app.route('/dashboard', methods=['GET'])
def dashboard():
    vehicles = list(vehicle_status_db.values())
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    return render_template_string(DASHBOARD_TEMPLATE, vehicles=vehicles, timestamp=timestamp)

def run_server():
    app.run(host=SERVER_HOST, port=SERVER_PORT)

# Start the Flask server in a separate thread
server_thread = threading.Thread(target=run_server, daemon=True)
server_thread.start()
time.sleep(1)  # allow server to start

# ================================
# Road Network Construction (Graph)
# ================================
G = nx.DiGraph()

# Create grid nodes with positions for plotting
for i in range(GRID_ROWS):
    for j in range(GRID_COLS):
        G.add_node((i, j), pos=(j, -i))  # (x, y)

def base_weight(u, v):
    """Euclidean distance between nodes as base weight."""
    (x1, y1) = G.nodes[u]['pos']
    (x2, y2) = G.nodes[v]['pos']
    return np.hypot(x2 - x1, y2 - y1)

# Add horizontal and vertical edges (bidirectional)
for i in range(GRID_ROWS):
    for j in range(GRID_COLS):
        if i < GRID_ROWS - 1:
            u, v = (i, j), (i+1, j)
            w = base_weight(u, v)
            G.add_edge(u, v, base=w, weight=w, history=[w])
            G.add_edge(v, u, base=w, weight=w, history=[w])
        if j < GRID_COLS - 1:
            u, v = (i, j), (i, j+1)
            w = base_weight(u, v)
            G.add_edge(u, v, base=w, weight=w, history=[w])
            G.add_edge(v, u, base=w, weight=w, history=[w])

# ================================
# Predictive Module: Dynamic Weight Updates
# ================================
def update_edge_weights_with_prediction(G, fluctuation=FLUCTUATION, alpha=PREDICTION_ALPHA):
    """
    Update each edge's weight based on:
      - A random instantaneous congestion factor (simulating live data)
      - A predictive component using exponential smoothing
    """
    for u, v, data in G.edges(data=True):
        base = data['base']
        # Instantaneous congestion: random factor (between 1 and 1 + fluctuation)
        random_factor = 1 + random.uniform(0, fluctuation)
        observed = base * random_factor
        # Predictive smoothing: combine current observation with history average
        prev_history = data.get('history', [])
        predicted = alpha * observed + (1 - alpha) * (np.mean(prev_history) if prev_history else observed)
        data['weight'] = predicted
        # Update history (keep last 5 observations)
        data['history'].append(observed)
        if len(data['history']) > 5:
            data['history'].pop(0)

# ================================
# Emergency Vehicle Simulation (Multi-Vehicle Coordination)
# ================================
class EmergencyVehicle(threading.Thread):
    def __init__(self, vehicle_id, start, destination, graph):
        super().__init__()
        self.vehicle_id = vehicle_id
        self.current_pos = start
        self.destination = destination
        self.graph = graph
        self.route = []
        self.running = True
    
    def compute_route(self):
        """Compute the shortest path from current position to destination."""
        try:
            path = nx.shortest_path(self.graph, source=self.current_pos, target=self.destination, weight='weight')
            length = nx.shortest_path_length(self.graph, source=self.current_pos, target=self.destination, weight='weight')
            return path, length
        except nx.NetworkXNoPath:
            return None, float('inf')
    
    def send_update(self, route, length):
        """Send vehicle status to the emergency response center."""
        payload = {
            "vehicle_id": self.vehicle_id,
            "current_position": self.current_pos,
            "destination": self.destination,
            "route": route,
            "route_length": round(length, 2),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        }
        try:
            response = requests.post(f"http://{SERVER_HOST}:{SERVER_PORT}/update", json=payload)
            if response.status_code == 200:
                print(f"[{self.vehicle_id}] Status updated.")
        except Exception as e:
            print(f"[{self.vehicle_id}] Error sending update: {e}")
    
    def move_along_route(self, path):
        """Simulate moving one step along the computed route."""
        if path and len(path) > 1:
            self.current_pos = path[1]
        if self.current_pos == self.destination:
            self.running = False
    
    def run(self):
        while self.running:
            path, length = self.compute_route()
            if path:
                self.route = path
                print(f"[{self.vehicle_id}] New route: {path} (Length: {length:.2f})")
                self.send_update(path, length)
                self.move_along_route(path)
            else:
                print(f"[{self.vehicle_id}] No available path!")
            time.sleep(UPDATE_INTERVAL)

# ================================
# Visualization (Optional)
# ================================
def visualize_network(G, vehicles, title="Dynamic Road Network"):
    plt.clf()
    pos = nx.get_node_attributes(G, 'pos')
    nx.draw_networkx_nodes(G, pos, node_size=300, node_color='lightblue')
    nx.draw_networkx_edges(G, pos, arrowstyle='->', arrowsize=10, width=1)
    # Highlight routes of each vehicle in different colors
    colors = ['red', 'green', 'orange', 'purple', 'brown']
    for idx, vehicle in enumerate(vehicles):
        if vehicle.route and len(vehicle.route) > 1:
            route_edges = list(zip(vehicle.route, vehicle.route[1:]))
            nx.draw_networkx_edges(G, pos, edgelist=route_edges, edge_color=colors[idx % len(colors)], width=3)
    plt.title(title)
    plt.axis('off')
    plt.pause(0.1)

# ================================
# Main Simulation Loop
# ================================
def run_simulation():
    # Define common source and destination (can be varied per vehicle)
    source = (0, 0)
    destination = (GRID_ROWS - 1, GRID_COLS - 1)
    
    # Create emergency vehicles
    # vehicles = [EmergencyVehicle(f"EV_{i+1}", source, destination, G) for i in range(VEHICLE_COUNT)]
    vehicles = [EmergencyVehicle(f"EV_1", (0, 0), (5, 5), G), EmergencyVehicle(f"EV_2", (2, 1), (5, 3), G), EmergencyVehicle(f"EV_3", (0, 4), (2, 5), G)]
    
    # Start vehicle threads
    for ev in vehicles:
        ev.start()
    
    # Visualization setup (optional)
    plt.ion()
    fig, ax = plt.subplots(figsize=(6,6))
    
    sim_start = time.time()
    while time.time() - sim_start < SIMULATION_DURATION:
        # Update edge weights based on simulated live data and predictive model
        update_edge_weights_with_prediction(G)
        # Optional: visualize network and routes
        visualize_network(G, vehicles, title="Dynamic Road Network & EV Routes")
        time.sleep(UPDATE_INTERVAL)
    
    # Stop all vehicle threads
    for ev in vehicles:
        ev.running = False
    for ev in vehicles:
        ev.join()
    plt.ioff()
    plt.show()
    print("Simulation completed.")

# ================================
# Main Execution
# ================================
if __name__ == "__main__":
    print("Starting Real‑World DERVRS Implementation Simulation...")
    run_simulation()
    print("All simulation threads have completed.")
