import threading
import time
import random
import numpy as np
import networkx as nx
import requests
from flask import Flask, request, jsonify
from concurrent.futures import ThreadPoolExecutor
import matplotlib.pyplot as plt

# ------------------------------
# Configuration & Global Settings
# ------------------------------
GRID_ROWS = 6
GRID_COLS = 6
SIMULATION_DURATION = 30          # seconds
UPDATE_INTERVAL = 2               # seconds between simulation updates
VEHICLE_COUNT = 3                 # number of emergency vehicles
FLUCTUATION = 0.5                 # traffic fluctuation factor
PREDICTION_ALPHA = 0.7            # smoothing factor for predictive congestion

# Emergency center server settings
SERVER_HOST = '127.0.0.1'
SERVER_PORT = 5000

# ------------------------------
# Emergency Response Center (Flask App)
# ------------------------------
app = Flask(__name__)
# A simple in-memory store for received vehicle updates
vehicle_status_db = {}

@app.route('/update', methods=['POST'])
def update_status():
    data = request.json
    vehicle_id = data.get("vehicle_id")
    # Store/update vehicle data
    vehicle_status_db[vehicle_id] = data
    print(f"[Emergency Center] Received update from Vehicle {vehicle_id}: {data}")
    return jsonify({"status": "received"}), 200

@app.route('/status', methods=['GET'])
def get_status():
    return jsonify(vehicle_status_db), 200

def run_server():
    app.run(host=SERVER_HOST, port=SERVER_PORT)

# Start the Flask server in a separate thread
server_thread = threading.Thread(target=run_server, daemon=True)
server_thread.start()
time.sleep(1)  # allow server to start

# ------------------------------
# Road Network Construction (Graph)
# ------------------------------
G = nx.DiGraph()

# Create grid nodes with positions (for plotting and distance computation)
for i in range(GRID_ROWS):
    for j in range(GRID_COLS):
        G.add_node((i, j), pos=(j, -i))  # using (x, y)

def base_weight(u, v):
    """Euclidean distance as base weight between two nodes."""
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

# ------------------------------
# Predictive Model (Simulated)
# ------------------------------
def update_edge_weights_with_prediction(G, fluctuation=FLUCTUATION, alpha=PREDICTION_ALPHA):
    """
    Simulate live traffic update and predictive adjustment.
    Each edge's weight is updated as a combination of:
    - Its base weight (Euclidean distance)
    - A random congestion factor (simulated fluctuation)
    - A moving average prediction based on history.
    """
    for u, v, data in G.edges(data=True):
        base = data['base']
        # Simulated instantaneous congestion factor (random component)
        random_factor = 1 + random.uniform(0, fluctuation)
        # Calculate new observed weight
        observed = base * random_factor
        # Update moving average (simulate predictive smoothing)
        prev_history = data.get('history', [])
        if prev_history:
            predicted = alpha * observed + (1 - alpha) * np.mean(prev_history)
        else:
            predicted = observed
        data['weight'] = predicted
        # Append current observed weight for history (limit history length to 5 for simplicity)
        data['history'].append(observed)
        if len(data['history']) > 5:
            data['history'].pop(0)

# ------------------------------
# Multi-Vehicle Coordination
# ------------------------------
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
        """Compute the shortest route from current position to destination using current weights."""
        try:
            path = nx.shortest_path(self.graph, source=self.current_pos, target=self.destination, weight='weight')
            length = nx.shortest_path_length(self.graph, source=self.current_pos, target=self.destination, weight='weight')
            return path, length
        except nx.NetworkXNoPath:
            return None, float('inf')
    
    def send_update(self, route, length):
        """Send current status to the emergency response center."""
        payload = {
            "vehicle_id": self.vehicle_id,
            "current_position": self.current_pos,
            "destination": self.destination,
            "route": route,
            "route_length": length,
            "timestamp": time.time()
        }
        try:
            response = requests.post(f"http://{SERVER_HOST}:{SERVER_PORT}/update", json=payload)
            if response.status_code == 200:
                print(f"[Vehicle {self.vehicle_id}] Update sent successfully.")
        except Exception as e:
            print(f"[Vehicle {self.vehicle_id}] Error sending update: {e}")
    
    def move_along_route(self, path):
        """Simulate movement along the computed path. Move one step per update interval."""
        if len(path) > 1:
            # Move to the next node in the path
            self.current_pos = path[1]
        # If at destination, remain there
        if self.current_pos == self.destination:
            self.running = False
    
    def run(self):
        while self.running:
            # Recompute route from current position to destination
            path, length = self.compute_route()
            if path is not None:
                self.route = path
                print(f"[Vehicle {self.vehicle_id}] New route: {path} (length: {length:.2f})")
                # Send update to emergency center
                self.send_update(path, length)
                # Simulate movement along the path
                self.move_along_route(path)
            else:
                print(f"[Vehicle {self.vehicle_id}] No available path!")
            time.sleep(UPDATE_INTERVAL)

# ------------------------------
# Simulation: Fleet and Dynamic Updates
# ------------------------------
def run_simulation():
    # Define source and destination for emergency vehicles (for simplicity, all share same destination)
    source = (0, 0)
    destination = (GRID_ROWS - 1, GRID_COLS - 1)
    
    # Create emergency vehicles
    vehicles = [EmergencyVehicle(f"EV_{i+1}", source, destination, G) for i in range(VEHICLE_COUNT)]
    
    # Start all vehicle threads
    for ev in vehicles:
        ev.start()
    
    # Main simulation loop: update edge weights periodically
    start_time = time.time()
    while time.time() - start_time < SIMULATION_DURATION:
        update_edge_weights_with_prediction(G)
        # (Optional) Visualize the current network and one vehicle's route
        # Here we plot the network and highlight the route of the first vehicle
        plt.clf()
        pos = nx.get_node_attributes(G, 'pos')
        nx.draw_networkx_nodes(G, pos, node_size=300, node_color='lightblue')
        nx.draw_networkx_edges(G, pos, arrowstyle='->', arrowsize=10, width=1)
        # Highlight first vehicle's route if available
        if vehicles:
            ev_route = vehicles[0].route
            if ev_route and len(ev_route) > 1:
                route_edges = list(zip(ev_route, ev_route[1:]))
                nx.draw_networkx_edges(G, pos, edgelist=route_edges, edge_color='red', width=3)
        plt.title("Dynamic Road Network (Red = EV_1 Route)")
        plt.axis('off')
        plt.pause(0.1)
        time.sleep(UPDATE_INTERVAL)
    
    # Stop all vehicles
    for ev in vehicles:
        ev.running = False
    for ev in vehicles:
        ev.join()
    print("Simulation finished.")
    plt.show()

# ------------------------------
# Main Execution
# ------------------------------
if __name__ == "__main__":
    print("Starting DERVRS simulation with live data, predictive model, multi-vehicle coordination, and real-time communication.")
    # Start simulation visualization in interactive mode
    plt.ion()
    run_simulation()
    plt.ioff()
