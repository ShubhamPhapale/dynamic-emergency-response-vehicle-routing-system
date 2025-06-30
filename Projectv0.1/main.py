import threading
import time
import random
import math
import requests
from flask import Flask, request, jsonify, render_template_string
import folium
import polyline
import os

# ================================
# Configuration & Global Settings
# ================================
UPDATE_INTERVAL = 5       # seconds between map updates
SPAWN_INTERVAL = 10       # seconds between new vehicle spawns
INITIAL_VEHICLE_COUNT = 3 # initial number of vehicles

# Fixed geographic boundaries for Mumbai (adjust as needed)
FIXED_LAT_LIMITS = (18.95, 19.20)
FIXED_LON_LIMITS = (72.80, 73.05)
MAP_CENTER = [ (FIXED_LAT_LIMITS[0] + FIXED_LAT_LIMITS[1]) / 2,
               (FIXED_LON_LIMITS[0] + FIXED_LON_LIMITS[1]) / 2 ]

# Predefined hospital locations (example list)
HOSPITALS = [
    {"name": "Hospital A", "lat": 19.0800, "lon": 72.8800},
    {"name": "Hospital B", "lat": 19.1000, "lon": 72.9000},
    {"name": "Hospital C", "lat": 19.1200, "lon": 72.9100},
    {"name": "Hospital D", "lat": 19.0700, "lon": 72.8600}
]

# Server configuration for our Flask Emergency Response Center
SERVER_HOST = '127.0.0.1'
SERVER_PORT = 5000

# GraphHopper configuration (ensure your GraphHopper server is running with your OSM data)
GH_API_ENDPOINT = "http://127.0.0.1:8989/route"

# ================================
# Utility Functions
# ================================
def random_coordinate():
    """Generate a random (lat, lon) within fixed boundaries."""
    lat = random.uniform(FIXED_LAT_LIMITS[0], FIXED_LAT_LIMITS[1])
    lon = random.uniform(FIXED_LON_LIMITS[0], FIXED_LON_LIMITS[1])
    return (lat, lon)

def haversine(coord1, coord2):
    """Calculate distance in km between two (lat, lon) points using Haversine formula."""
    lat1, lon1 = coord1
    lat2, lon2 = coord2
    R = 6371  # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    return R * c

def get_nearest_hospital(position):
    """Return the (lat, lon) of the nearest hospital from the HOSPITALS list."""
    nearest = None
    min_dist = float('inf')
    for hosp in HOSPITALS:
        d = haversine(position, (hosp["lat"], hosp["lon"]))
        if d < min_dist:
            min_dist = d
            nearest = (hosp["lat"], hosp["lon"])
    return nearest

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
      tr:nth-child(even) { background-color: #f2f2f2; }
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
        start_latlon and dest_latlon are absolute (lat, lon) tuples.
        """
        super().__init__()
        self.vehicle_id = vehicle_id
        self.start_latlon = start_latlon
        self.dest_latlon = dest_latlon
        self.current_pos = start_latlon
        self.route = ""
        self.route_length = 0.0
        self.running = True

    def compute_route(self):
        """Call GraphHopper's Directions API using absolute coordinates."""
        params = {
            "point": [f"{self.current_pos[0]},{self.current_pos[1]}",
                      f"{self.dest_latlon[0]},{self.dest_latlon[1]}"],
            "type": "json",
            "locale": "en",
            "profile": "car",
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
                self.route_length = path_data.get("distance", float('inf'))
                return self.route, self.route_length
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
                print(f"[{self.vehicle_id}] Status updated.")
        except Exception as e:
            print(f"[{self.vehicle_id}] Error sending update: {e}")

    def move_along_route(self):
        """Move the vehicle by a fraction of the remaining distance.
           When destination is reached, mark this vehicle as finished.
        """
        cur_lat, cur_lon = self.current_pos
        dest_lat, dest_lon = self.dest_latlon
        dlat = dest_lat - cur_lat
        dlon = dest_lon - cur_lon

        # If vehicle is very close to destination, mark it finished
        if abs(dlat) < 0.0005 and abs(dlon) < 0.0005:
            print(f"[{self.vehicle_id}] Reached destination.")
            self.running = False
            return

        step = 0.2  # fraction of remaining distance to move
        new_lat = cur_lat + step * dlat
        new_lon = cur_lon + step * dlon
        self.current_pos = (new_lat, new_lon)

    def run(self):
        while self.running:
            route, length = self.compute_route()
            if route:
                print(f"[{self.vehicle_id}] New route (Length: {length:.2f} m)")
                self.send_update(route, length)
            else:
                print(f"[{self.vehicle_id}] No route available!")
            self.move_along_route()
            time.sleep(UPDATE_INTERVAL)

# ================================
# Enhanced Visualization using Folium
# ================================
def visualize_network_folium(vehicles, map_file="map.html"):
    m = folium.Map(location=MAP_CENTER, zoom_start=12)
    m.get_root().html.add_child(folium.Element('<meta http-equiv="refresh" content="5">'))
    
    # Add hospital markers
    for hosp in HOSPITALS:
        folium.Marker(
            location=[hosp["lat"], hosp["lon"]],
            popup=hosp["name"],
            icon=folium.Icon(color="darkred", icon="plus-sign")
        ).add_to(m)
    
    colors = {"EV_1": "red", "EV_2": "green", "EV_3": "blue"}
    # Only display active vehicles
    for ev in vehicles:
        if not ev.running:
            continue
        # Plot destination marker
        folium.Marker(
            location=list(ev.dest_latlon),
            popup=f"{ev.vehicle_id} Hospital",
            icon=folium.Icon(color="darkred", icon="hospital-o")
        ).add_to(m)
        # Plot current position marker
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
    vehicles = []
    vehicle_counter = 1

    # Spawn initial vehicles with random start positions and destination as nearest hospital.
    for _ in range(INITIAL_VEHICLE_COUNT):
        start = random_coordinate()
        dest = get_nearest_hospital(start)
        veh_id = f"EV_{vehicle_counter}"
        vehicle_counter += 1
        new_vehicle = EmergencyVehicle(veh_id, start, dest)
        new_vehicle.start()
        vehicles.append(new_vehicle)
        print(f"Spawned {veh_id}: Start: {start}, Hospital: {dest}")
    
    map_file = "map.html"
    last_spawn_time = time.time()
    
    try:
        while True:
            # Remove finished vehicles
            vehicles = [v for v in vehicles if v.running]
            # Spawn a new vehicle every SPAWN_INTERVAL seconds
            if time.time() - last_spawn_time > SPAWN_INTERVAL:
                start = random_coordinate()
                dest = get_nearest_hospital(start)
                veh_id = f"EV_{vehicle_counter}"
                vehicle_counter += 1
                new_vehicle = EmergencyVehicle(veh_id, start, dest)
                new_vehicle.start()
                vehicles.append(new_vehicle)
                print(f"Spawned {veh_id}: Start: {start}, Hospital: {dest}")
                last_spawn_time = time.time()
            
            visualize_network_folium(vehicles, map_file)
            time.sleep(UPDATE_INTERVAL)
    except KeyboardInterrupt:
        print("Simulation interrupted by user.")
    
    for v in vehicles:
        v.running = False
    for v in vehicles:
        v.join()
    print("Simulation completed.")

# ================================
# Main Execution
# ================================
if __name__ == "__main__":
    print("Starting Real‑World DERVRS Simulation with GraphHopper Integration...")
    run_simulation()
    print("All simulation threads have completed.")
