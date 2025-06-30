import threading
import time
import requests
from flask import Flask, request, jsonify, render_template_string
import folium
import polyline
import os

# ================================
# Configuration & Global Settings
# ================================
SIMULATION_DURATION = 60           # Total simulation time in seconds
UPDATE_INTERVAL = 5                # Interval (in seconds) between map updates

# Server configuration for our Flask Emergency Response Center
SERVER_HOST = '127.0.0.1'
SERVER_PORT = 5000

# GraphHopper configuration (ensure your GraphHopper server is running with your OSM data)
GH_API_ENDPOINT = "http://127.0.0.1:8989/route"

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
      function refreshPage() { window.location.reload(); }
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
        self.current_pos = start_latlon  # (lat, lon)
        self.route = ""
        self.running = True

    def compute_route(self):
        """Call GraphHopper's Directions API using absolute coordinates."""
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
        """Move the vehicle a fixed fraction (e.g., 20%) of the remaining distance toward the destination."""
        cur_lat, cur_lon = self.current_pos
        dest_lat, dest_lon = self.dest_latlon
        dlat = dest_lat - cur_lat
        dlon = dest_lon - cur_lon
        # If very close to destination, set current_pos to destination and stop
        if abs(dlat) < 0.0001 and abs(dlon) < 0.0001:
            self.current_pos = self.dest_latlon
            self.running = False
            return
        step = 0.2  # fraction of remaining distance
        new_lat = cur_lat + step * dlat
        new_lon = cur_lon + step * dlon
        self.current_pos = (new_lat, new_lon)

    def run(self):
        while self.running:
            route, length = self.compute_route()
            if route:
                print(f"[{self.vehicle_id}] New route via GraphHopper: (Length: {length:.2f} m)")
                self.send_update(route, length)
                self.move_along_route()
            else:
                print(f"[{self.vehicle_id}] No available route from GraphHopper!")
            time.sleep(UPDATE_INTERVAL)

# ================================
# Enhanced Visualization using Folium (Leaflet)
# ================================
def visualize_network_folium(vehicles, map_file="map.html"):
    # Define the extent for Mumbai (adjust as necessary)
    map_center = [19.0760, 72.8777]
    m = folium.Map(location=map_center, zoom_start=12)
    
    # Add a meta refresh tag to auto-refresh the page every 5 seconds
    m.get_root().html.add_child(folium.Element('<meta http-equiv="refresh" content="5">'))
    
    # Example landmarks
    landmarks = [
        {"name": "Gateway of India", "lat": 18.9220, "lon": 72.8347},
        {"name": "Marine Drive", "lat": 18.9500, "lon": 72.8233},
        {"name": "Chhatrapati Shivaji Terminus", "lat": 18.9400, "lon": 72.8357}
    ]
    for lm in landmarks:
        folium.Marker(
            location=[lm["lat"], lm["lon"]],
            popup=lm["name"],
            icon=folium.Icon(color="black", icon="info-sign")
        ).add_to(m)
    
    # Add vehicle markers and routes
    colors = {"EV_1": "red", "EV_2": "green", "EV_3": "blue"}
    for ev in vehicles:
        # Start marker
        folium.Marker(
            location=list(ev.start_latlon),
            popup=f"{ev.vehicle_id} Start",
            icon=folium.Icon(color="blue", icon="play")
        ).add_to(m)
        # Destination marker
        folium.Marker(
            location=list(ev.dest_latlon),
            popup=f"{ev.vehicle_id} Destination",
            icon=folium.Icon(color="red", icon="stop")
        ).add_to(m)
        # Current position marker
        folium.Marker(
            location=list(ev.current_pos),
            popup=f"{ev.vehicle_id} Current",
            icon=folium.Icon(color=colors.get(ev.vehicle_id, "gray"), icon="arrow-up")
        ).add_to(m)
        # Draw route if available
        if ev.route:
            try:
                route_points = polyline.decode(ev.route)
                folium.PolyLine(
                    locations=route_points,
                    color=colors.get(ev.vehicle_id, "gray"),
                    weight=4,
                    opacity=0.7,
                    popup=f"{ev.vehicle_id} Route"
                ).add_to(m)
            except Exception as e:
                print(f"Error decoding route for {ev.vehicle_id}: {e}")
    
    m.save(map_file)
    print(f"Map updated and saved to {map_file}. Refresh your browser to see changes.")

# ================================
# Main Simulation Loop
# ================================
def run_simulation():
    # Define vehicles with absolute coordinates (latitude, longitude)
    vehicles = [
        EmergencyVehicle("EV_1", (19.0760, 72.8777), (19.1260, 72.9277)),
        EmergencyVehicle("EV_2", (19.0860, 72.8877), (19.1160, 72.9177)),
        EmergencyVehicle("EV_3", (19.0660, 72.8677), (19.0960, 72.8977))
    ]
    for ev in vehicles:
        ev.start()
    
    # Generate an initial map
    map_file = "map.html"
    visualize_network_folium(vehicles, map_file)
    
    sim_start = time.time()
    while time.time() - sim_start < SIMULATION_DURATION:
        visualize_network_folium(vehicles, map_file)
        time.sleep(UPDATE_INTERVAL)
    
    for ev in vehicles:
        ev.running = False
    for ev in vehicles:
        ev.join()
    print("Simulation completed.")

# ================================
# Main Execution
# ================================
if __name__ == "__main__":
    print("Starting Real‑World DERVRS Simulation with GraphHopper Integration...")
    run_simulation()
    print("All simulation threads have completed.")
