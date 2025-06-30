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
ACCIDENT_INTERVAL = 15    # seconds between accident events
TOTAL_AMBULANCES = 10     # total number of ambulances

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

# Predefined ambulance base positions (fleet positions)
# These are chosen to cover the Mumbai area
AMBULANCE_BASES = [
    (19.05, 72.82),
    (19.05, 72.90),
    (19.07, 72.85),
    (19.08, 72.93),
    (19.09, 72.87),
    (19.10, 72.91),
    (19.11, 72.88),
    (19.12, 72.92),
    (19.13, 72.86),
    (19.14, 72.90)
]

# Server configuration for our Flask Emergency Response Center
SERVER_HOST = '127.0.0.1'
SERVER_PORT = 5000

# GraphHopper API endpoint (ensure your GraphHopper server is running)
GH_API_ENDPOINT = "http://127.0.0.1:8989/route"

# ================================
# Utility Functions
# ================================
def random_coordinate():
    """Generate a random (lat, lon) within Mumbai boundaries."""
    lat = random.uniform(FIXED_LAT_LIMITS[0], FIXED_LAT_LIMITS[1])
    lon = random.uniform(FIXED_LON_LIMITS[0], FIXED_LON_LIMITS[1])
    return (lat, lon)

def haversine(coord1, coord2):
    """Calculate the distance in km between two (lat, lon) points."""
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

def select_best_ambulance(accident_location, ambulances):
    """
    Given an accident location, select the available ambulance
    with the shortest estimated route distance (simulate using haversine).
    In a real system, you'd use the routing API to get travel times.
    """
    best = None
    best_dist = float('inf')
    for amb in ambulances:
        if amb.state == "available":
            dist = haversine(amb.current_pos, accident_location)
            if dist < best_dist:
                best_dist = dist
                best = amb
    return best

# ================================
# Flask Server for Dashboard
# ================================
app = Flask(__name__)
vehicle_status_db = {}

DASHBOARD_TEMPLATE = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>Emergency Vehicle Dashboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
      body { font-family: Arial, sans-serif; margin: 20px; }
      table { border-collapse: collapse; width: 100%; }
      th, td { padding: 8px; border: 1px solid #ddd; text-align: left; }
      tr:nth-child(even) { background-color: #f2f2f2; }
    </style>
    <script>
      setInterval(function() { window.location.reload(); }, 5000);
    </script>
  </head>
  <body>
    <h2>Emergency Vehicle Dashboard</h2>
    <p>Last updated: {{ timestamp }}</p>
    <table>
      <tr>
        <th>Ambulance ID</th>
        <th>Status</th>
        <th>Current Position</th>
        <th>Destination</th>
        <th>Last Update</th>
      </tr>
      {% for v in vehicles %}
      <tr>
        <td>{{ v.ambulance_id }}</td>
        <td>{{ v.state }}</td>
        <td>{{ v.current_pos }}</td>
        <td>{{ v.destination }}</td>
        <td>{{ v.timestamp }}</td>
      </tr>
      {% endfor %}
    </table>
  </body>
</html>
"""

@app.route('/update', methods=['POST'])
def update_status():
    data = request.json
    amb_id = data.get("ambulance_id")
    vehicle_status_db[amb_id] = data
    print(f"[Dashboard] Update received from {amb_id}: {data}")
    return jsonify({"status": "received"}), 200

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
# Ambulance Simulation Classes
# ================================
class Ambulance(threading.Thread):
    def __init__(self, ambulance_id, base_position):
        """
        Each ambulance has a unique base position (fleet station).
        Initially, they are "available" at their base.
        """
        super().__init__()
        self.ambulance_id = ambulance_id
        self.base_position = base_position  # (lat, lon)
        self.current_pos = base_position
        self.destination = base_position  # Initially, destination is base.
        self.route = ""
        self.route_length = 0.0
        self.state = "available"  # states: available, en-route, at accident, to-hospital, returning
        self.timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        self.running = True

    def compute_route(self):
        """Call GraphHopper API using absolute coordinates."""
        params = {
            "point": [f"{self.current_pos[0]},{self.current_pos[1]}",
                      f"{self.destination[0]},{self.destination[1]}"],
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
            print(f"[{self.ambulance_id}] GraphHopper API error: {e}")
            return None, float('inf')

    def send_update(self):
        payload = {
            "ambulance_id": self.ambulance_id,
            "state": self.state,
            "current_pos": self.current_pos,
            "destination": self.destination,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        }
        try:
            requests.post(f"http://{SERVER_HOST}:{SERVER_PORT}/update", json=payload)
        except Exception as e:
            print(f"[{self.ambulance_id}] Error sending update: {e}")

    def move_toward(self, target, step_fraction=0.2):
        """Move current_pos a fraction of the remaining distance toward target."""
        cur_lat, cur_lon = self.current_pos
        target_lat, target_lon = target
        dlat = target_lat - cur_lat
        dlon = target_lon - cur_lon
        if abs(dlat) < 0.0005 and abs(dlon) < 0.0005:
            self.current_pos = target
            return True
        new_lat = cur_lat + step_fraction * dlat
        new_lon = cur_lon + step_fraction * dlon
        self.current_pos = (new_lat, new_lon)
        return False

    def run(self):
        while self.running:
            # Behavior depends on state
            if self.state == "available":
                # Wait for a dispatch (do nothing until assigned an accident)
                time.sleep(UPDATE_INTERVAL)
            elif self.state == "en-route":
                # Move toward the accident location
                arrived = self.move_toward(self.destination)
                self.send_update()
                if arrived:
                    print(f"[{self.ambulance_id}] Arrived at accident.")
                    self.state = "at accident"
                time.sleep(UPDATE_INTERVAL)
            elif self.state == "at accident":
                # Simulate on-scene time (e.g., 10 seconds), then set destination to nearest hospital.
                print(f"[{self.ambulance_id}] At accident site. Patient being loaded.")
                time.sleep(10)
                new_dest = get_nearest_hospital(self.current_pos)
                print(f"[{self.ambulance_id}] Patient loaded. Heading to hospital: {new_dest}")
                self.destination = new_dest
                self.state = "to-hospital"
                self.send_update()
            elif self.state == "to-hospital":
                arrived = self.move_toward(self.destination)
                self.send_update()
                if arrived:
                    print(f"[{self.ambulance_id}] Arrived at hospital.")
                    time.sleep(5)  # simulate drop-off time
                    # After drop-off, return to base.
                    self.destination = self.base_position
                    self.state = "returning"
                    self.send_update()
                time.sleep(UPDATE_INTERVAL)
            elif self.state == "returning":
                arrived = self.move_toward(self.destination)
                self.send_update()
                if arrived:
                    print(f"[{self.ambulance_id}] Returned to base and now available.")
                    self.state = "available"
                    self.send_update()
                time.sleep(UPDATE_INTERVAL)
            else:
                time.sleep(UPDATE_INTERVAL)

# ================================
# Fleet Manager and Accident Simulation
# ================================
class FleetManager:
    def __init__(self, ambulances):
        self.ambulances = ambulances  # List of Ambulance objects
        self.accidents = []  # List of active accidents

    def dispatch_ambulance(self, accident_location):
        # Select the best available ambulance (using haversine as a proxy)
        available = [amb for amb in self.ambulances if amb.state == "available"]
        if not available:
            print("No available ambulances for dispatch!")
            return None
        best = min(available, key=lambda amb: haversine(amb.current_pos, accident_location))
        # Dispatch this ambulance: set its state to "en-route" and destination to accident
        best.destination = accident_location
        best.state = "en-route"
        best.send_update()
        print(f"Dispatching {best.ambulance_id} to accident at {accident_location}")
        return best

    def simulate_accident(self):
        # Generate a random accident location (only on land)
        accident_loc = random_coordinate()
        print(f"Accident occurred at {accident_loc}")
        dispatched = self.dispatch_ambulance(accident_loc)
        if dispatched:
            # Record the accident event (you could add more info, such as timestamp)
            self.accidents.append({"location": accident_loc, "dispatched": dispatched.ambulance_id})
        else:
            print("Accident occurred but no ambulance available!")

# ================================
# Enhanced Visualization using Folium (Fleet, Accidents, Ambulances)
# ================================
def visualize_fleet_folium(ambulances, accidents, map_file="fleet_map.html"):
    m = folium.Map(location=MAP_CENTER, zoom_start=12)
    m.get_root().html.add_child(folium.Element('<meta http-equiv="refresh" content="5">'))
    
    # Plot hospital markers
    for hosp in HOSPITALS:
        folium.Marker(
            location=[hosp["lat"], hosp["lon"]],
            popup=hosp["name"],
            icon=folium.Icon(color="darkred", icon="plus-sign")
        ).add_to(m)
    
    # Plot accident markers (active accidents)
    for acc in accidents:
        folium.Marker(
            location=list(acc["location"]),
            popup=f"Accident (Ambulance: {acc['dispatched']})",
            icon=folium.Icon(color="orange", icon="exclamation-sign")
        ).add_to(m)
    
    colors = {"EV_1": "red", "EV_2": "green", "EV_3": "blue",
              "EV_4": "purple", "EV_5": "darkred", "EV_6": "cadetblue",
              "EV_7": "lightgray", "EV_8": "orange", "EV_9": "darkgreen", "EV_10": "black"}
    
    for amb in ambulances:
        # Plot ambulance marker (current position)
        folium.Marker(
            location=list(amb.current_pos),
            popup=f"{amb.ambulance_id} ({amb.state})",
            icon=folium.Icon(color=colors.get(amb.ambulance_id, "gray"), icon="ambulance", prefix='fa')
        ).add_to(m)
        # Optionally, draw route if available
        if amb.route:
            try:
                route_points = polyline.decode(amb.route)
                folium.PolyLine(
                    locations=route_points,
                    color=colors.get(amb.ambulance_id, "gray"),
                    weight=4,
                    opacity=0.7,
                    popup=f"{amb.ambulance_id} Route"
                ).add_to(m)
            except Exception as e:
                print(f"Error decoding route for {amb.ambulance_id}: {e}")
    
    m.save(map_file)
    print(f"Fleet map updated and saved to {map_file}. Refresh your browser to see changes.")

# ================================
# Main Simulation Loop
# ================================
def run_simulation():
    # Initialize ambulances at fixed fleet positions (we assume 10 ambulances)
    ambulances = []
    for i in range(TOTAL_AMBULANCES):
        amb_id = f"EV_{i+1}"
        base = AMBULANCE_BASES[i]
        ambulances.append(Ambulance(amb_id, base))
    # Start all ambulance threads
    for amb in ambulances:
        amb.start()
    
    # Create a Fleet Manager to handle dispatching for accidents
    fleet_manager = FleetManager(ambulances)
    
    map_file = "fleet_map.html"
    
    # Run accident simulation in a separate thread
    def accident_simulation():
        while True:
            fleet_manager.simulate_accident()
            time.sleep(ACCIDENT_INTERVAL)
    
    accident_thread = threading.Thread(target=accident_simulation, daemon=True)
    accident_thread.start()
    
    # Main loop: update visualization
    try:
        while True:
            # Remove accidents that are resolved (for simplicity, assume if ambulance is no longer en-route or at accident, accident is cleared)
            fleet_manager.accidents = [acc for acc in fleet_manager.accidents 
                                       if any(amb.ambulance_id == acc["dispatched"] and amb.state in ["en-route", "at accident"] for amb in ambulances)]
            visualize_fleet_folium(ambulances, fleet_manager.accidents, map_file)
            time.sleep(UPDATE_INTERVAL)
    except KeyboardInterrupt:
        print("Simulation interrupted by user.")
    
    for amb in ambulances:
        amb.running = False
    for amb in ambulances:
        amb.join()
    print("Simulation completed.")

# ================================
# Main Execution
# ================================
if __name__ == "__main__":
    print("Starting Mumbai Emergency Vehicle Routing Simulation...")
    run_simulation()
    print("All simulation threads have completed.")
