import threading
import time
import random
import numpy as np
import networkx as nx
import requests
from flask import Flask, request, jsonify, render_template_string
import matplotlib.pyplot as plt
import polyline  # for decoding encoded polyline strings

# ================================
# Configuration & Global Settings
# ================================
SIMULATION_DURATION = 60           # total simulation time in seconds
UPDATE_INTERVAL = 2                # seconds between simulation updates

# Server configuration for our Flask Emergency Response Center
SERVER_HOST = '127.0.0.1'
SERVER_PORT = 5000

# GraphHopper configuration (ensure your GraphHopper server is running with western-zone-latest.osm.pbf)
GH_API_ENDPOINT = "http://127.0.0.1:8989/route"

# Note: We no longer need a grid_to_latlon helper because we're using absolute coordinates.

# ================================
# Emergency Response Center (Flask App)
# ================================
app = Flask(__name__)
vehicle_status_db = {}

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
        <th>Route Length (meters)</th>
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

server_thread = threading.Thread(target=run_server, daemon=True)
server_thread.start()
time.sleep(1)

# ================================
# Emergency Vehicle Simulation with GraphHopper Integration
# ================================
class EmergencyVehicle(threading.Thread):
    def __init__(self, vehicle_id, start_latlon, dest_latlon):
        """
        start_latlon and dest_latlon are tuples: (latitude, longitude)
        """
        super().__init__()
        self.vehicle_id = vehicle_id
        self.start_latlon = start_latlon
        self.dest_latlon = dest_latlon
        self.current_pos = start_latlon  # current position as (lat, lon)
        self.route = ""
        self.running = True

    def compute_route(self):
        """Call GraphHopper's Directions API to get a live route using absolute coordinates."""
        params = {
            "point": [f"{self.current_pos[0]},{self.current_pos[1]}", f"{self.dest_latlon[0]},{self.dest_latlon[1]}"],
            "type": "json",
            "locale": "en",
            "profile": "car",  # using the car profile
            "elevation": "false",
            "use_miles": "false",
            "layer": "Omniscale"
        }
        try:
            response = requests.get(GH_API_ENDPOINT, params=params)
            data = response.json()
            if "paths" in data and data["paths"]:
                path_data = data["paths"][0]
                self.route = path_data.get("points", "")
                length = path_data.get("distance", float('inf'))
                return self.route, length
            else:
                return None, float('inf')
        except Exception as e:
            print(f"[{self.vehicle_id}] GraphHopper API error: {e}")
            return None, float('inf')

    def send_update(self, route, length):
        payload = {
            "vehicle_id": self.vehicle_id,
            "current_position": self.current_pos,
            "destination": self.dest_latlon,
            "route": route,
            "route_length": round(length, 2),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        }
        try:
            response = requests.post(f"http://{SERVER_HOST}:{SERVER_PORT}/update", json=payload)
            if response.status_code == 200:
                print(f"[{self.vehicle_id}] Status updated via GraphHopper route.")
        except Exception as e:
            print(f"[{self.vehicle_id}] Error sending update: {e}")

    def move_along_route(self):
        """Simulate movement along a straight line from current position to destination.
           Moves by a fixed fraction (e.g. 20%) of the remaining distance each update.
        """
        cur_lat, cur_lon = self.current_pos
        dest_lat, dest_lon = self.dest_latlon
        # Calculate difference
        dlat = dest_lat - cur_lat
        dlon = dest_lon - cur_lon
        # If the vehicle is very close to destination, stop
        if abs(dlat) < 0.0001 and abs(dlon) < 0.0001:
            self.current_pos = self.dest_latlon
            self.running = False
            return
        # Move 20% of the remaining distance
        step = 0.2
        new_lat = cur_lat + step * dlat
        new_lon = cur_lon + step * dlon
        self.current_pos = (new_lat, new_lon)

    def run(self):
        while self.running:
            route, length = self.compute_route()
            if route:
                print(f"[{self.vehicle_id}] New route via GraphHopper: {route} (Length: {length:.2f} m)")
                self.send_update(route, length)
                self.move_along_route()
            else:
                print(f"[{self.vehicle_id}] No available route from GraphHopper!")
            time.sleep(UPDATE_INTERVAL)

# ================================
# Enhanced Visualization with Fixed Scale and Landmarks
# ================================
def visualize_network(vehicles, title="GraphHopper Integrated Routes"):
    # Set fixed axis limits to cover the area (e.g., around Mumbai)
    fixed_lat_limits = (18.95, 19.20)
    fixed_lon_limits = (72.80, 73.05)
    
    plt.clf()
    ax = plt.gca()
    ax.set_title(title)
    ax.set_xlim(fixed_lon_limits)
    ax.set_ylim(fixed_lat_limits)
    ax.grid(True, linestyle='--', alpha=0.5)
    
    # Draw example landmarks (replace with actual landmarks if available)
    landmarks = [
        {"name": "Gateway of India", "lat": 18.9220, "lon": 72.8347},
        {"name": "Marine Drive", "lat": 18.9500, "lon": 72.8233},
        {"name": "Chhatrapati Shivaji Terminus", "lat": 18.9400, "lon": 72.8357}
    ]
    for lm in landmarks:
        ax.plot(lm["lon"], lm["lat"], marker="*", color="black", markersize=10)
        ax.text(lm["lon"] + 0.001, lm["lat"] + 0.001, lm["name"], fontsize=9, color="black")
    
    colors = {"EV_1": "red", "EV_2": "green", "EV_3": "blue"}
    for ev in vehicles:
        # Plot starting point with label
        start_lat, start_lon = ev.start_latlon
        ax.plot(start_lon, start_lat, marker="o", color=colors.get(ev.vehicle_id, "black"), markersize=8)
        ax.text(start_lon, start_lat, f"{ev.vehicle_id} Start", fontsize=8, color=colors.get(ev.vehicle_id, "black"))
        
        # Plot destination with label
        dest_lat, dest_lon = ev.dest_latlon
        ax.plot(dest_lon, dest_lat, marker="X", color=colors.get(ev.vehicle_id, "black"), markersize=10)
        ax.text(dest_lon, dest_lat, f"{ev.vehicle_id} Dest", fontsize=8, color=colors.get(ev.vehicle_id, "black"))
        
        # Plot current position
        cur_lat, cur_lon = ev.current_pos
        ax.plot(cur_lon, cur_lat, marker="s", color=colors.get(ev.vehicle_id, "black"), markersize=8)
        
        # Plot route if available and decode it
        if ev.route and len(ev.route) > 0:
            try:
                route_points = polyline.decode(ev.route)
                lats, lons = zip(*route_points)
                ax.plot(lons, lats, color=colors.get(ev.vehicle_id, "black"), linestyle='-', linewidth=2)
            except Exception as e:
                print(f"Error decoding route for {ev.vehicle_id}: {e}")
    
    plt.draw()
    plt.pause(0.1)

# ================================
# Main Simulation Loop
# ================================
def run_simulation():
    # Define vehicles with absolute starting and destination coordinates (lat, lon)
    vehicles = [
        EmergencyVehicle("EV_1", (19.0760, 72.8777), (19.1260, 72.9277)),
        EmergencyVehicle("EV_2", (19.0860, 72.8877), (19.1160, 72.9177)),
        EmergencyVehicle("EV_3", (19.0660, 72.8677), (19.0960, 72.8977))
    ]
    for ev in vehicles:
        ev.start()
    
    plt.ion()
    fig, ax = plt.subplots(figsize=(8,8))
    
    sim_start = time.time()
    while time.time() - sim_start < SIMULATION_DURATION:
        visualize_network(vehicles)
        time.sleep(UPDATE_INTERVAL)
    
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
    print("Starting Real‑World DERVRS Simulation with GraphHopper Integration...")
    run_simulation()
    print("All simulation threads have completed.")
