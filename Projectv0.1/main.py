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
UPDATE_INTERVAL = 5  # seconds between updates
# Accident intervals will be randomized using an exponential distribution (mean ~15 sec)
# TOTAL_AMBULANCES is fixed at 10.
TOTAL_AMBULANCES = 10

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

# Predefined ambulance fleet (base) positions – chosen to cover Mumbai
AMBULANCE_BASES = [
    (19.00, 72.82),
    (19.00, 72.87),
    (19.02, 72.90),
    (19.04, 72.93),
    (19.06, 72.88),
    (19.08, 72.91),
    (19.10, 72.87),
    (19.12, 72.90),
    (19.14, 72.93),
    (19.16, 72.95)
]

# Vulnerable bases (preferred bases) where ambulances should return after drop-off
VULNERABLE_BASES = [
    (19.00, 72.82),
    (19.16, 73.00)
]

def get_preferred_base(current_position):
    """Return the vulnerable base nearest to the current position."""
    return min(VULNERABLE_BASES, key=lambda base: haversine(current_position, base))

# Server configuration for our central dashboard
SERVER_HOST = '127.0.0.1'
SERVER_PORT = 5000

# GraphHopper configuration (ensure your GraphHopper server is running)
GH_API_ENDPOINT = "http://127.0.0.1:8989/route"

# Global performance metrics and event log
METRICS = {
    "total_accidents": 0,
    "total_dispatches": 0,
    "total_response_time": 0.0,  # in seconds
    "total_hospital_dropoffs": 0
}
EVENT_LOG = []  # list of event strings

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
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    return R * c

def get_nearest_hospital(position):
    """Return the (lat, lon) of the nearest hospital."""
    nearest = None
    min_dist = float('inf')
    for hosp in HOSPITALS:
        d = haversine(position, (hosp["lat"], hosp["lon"]))
        if d < min_dist:
            min_dist = d
            nearest = (hosp["lat"], hosp["lon"])
    return nearest

# ================================
# Flask Server (Central Dashboard)
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
      h2, h3 { color: #333; }
      table { border-collapse: collapse; width: 100%; margin-bottom: 20px; }
      th, td { padding: 8px; border: 1px solid #ddd; text-align: left; }
      tr:nth-child(even) { background-color: #f2f2f2; }
      .metrics { margin-bottom: 20px; }
      .event-log { font-size: 0.9em; color: #555; max-height: 200px; overflow-y: scroll; }
    </style>
    <script>
      setInterval(function() { window.location.reload(); }, 5000);
    </script>
  </head>
  <body>
    <h2>Emergency Vehicle Dashboard</h2>
    <div class="metrics">
      <h3>Metrics</h3>
      <p>Total Accidents: {{ metrics.total_accidents }}</p>
      <p>Total Dispatches: {{ metrics.total_dispatches }}</p>
      <p>Total Hospital Drop-offs: {{ metrics.total_hospital_dropoffs }}</p>
      <p>Average Response Time (s): 
         {% if metrics.total_dispatches > 0 %}
           {{ "%.2f"|format(metrics.total_response_time / metrics.total_dispatches) }}
         {% else %}
           0
         {% endif %}
      </p>
    </div>
    <div class="event-log">
      <h3>Event Log (Recent)</h3>
      <ul>
      {% for event in events %}
        <li>{{ event }}</li>
      {% endfor %}
      </ul>
    </div>
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
    print(f"[Dashboard] Update from {amb_id}: {data}")
    return jsonify({"status": "received"}), 200

@app.route('/dashboard', methods=['GET'])
def dashboard():
    vehicles = list(vehicle_status_db.values())
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    # Show last 10 events in reverse order
    events = EVENT_LOG[-10:][::-1]
    return render_template_string(DASHBOARD_TEMPLATE, vehicles=vehicles, timestamp=timestamp, metrics=METRICS, events=events)

def run_dashboard():
    app.run(host=SERVER_HOST, port=SERVER_PORT)

dashboard_thread = threading.Thread(target=run_dashboard, daemon=True)
dashboard_thread.start()
time.sleep(1)

# ================================
# Ambulance Simulation Class
# ================================
class Ambulance(threading.Thread):
    def __init__(self, ambulance_id, base_position):
        """
        Each ambulance starts at its fleet base.
        """
        super().__init__()
        self.ambulance_id = ambulance_id
        self.base_position = base_position  # (lat, lon)
        self.current_pos = base_position
        self.destination = base_position  # initially, at base
        self.route = ""
        self.route_length = 0.0
        self.state = "available"  # available, en-route, at accident, to-hospital, returning
        self.timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        self.running = True
        self.dispatch_time = None  # timestamp when dispatched

    def compute_route(self):
        """Call GraphHopper API to get route between current_pos and destination."""
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
        self.timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        payload = {
            "ambulance_id": self.ambulance_id,
            "state": self.state,
            "current_pos": self.current_pos,
            "destination": self.destination,
            "timestamp": self.timestamp
        }
        try:
            requests.post(f"http://{SERVER_HOST}:{SERVER_PORT}/update", json=payload)
        except Exception as e:
            print(f"[{self.ambulance_id}] Error sending update: {e}")

    def move_toward(self, target, step_fraction=0.2):
        """Move current_pos toward target by a fraction of the remaining distance.
           Return True if arrived.
        """
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
            if self.state == "available":
                time.sleep(UPDATE_INTERVAL)
            elif self.state == "en-route":
                arrived = self.move_toward(self.destination)
                self.send_update()
                if arrived:
                    if self.dispatch_time is not None:
                        response_time = time.time() - self.dispatch_time
                        METRICS["total_response_time"] += response_time
                        METRICS["total_dispatches"] += 1
                        EVENT_LOG.append(f"{self.ambulance_id} responded in {response_time:.2f} s.")
                        self.dispatch_time = None
                    self.state = "at accident"
                    self.send_update()
                    EVENT_LOG.append(f"{self.ambulance_id} arrived at accident.")
                time.sleep(UPDATE_INTERVAL)
            elif self.state == "at accident":
                print(f"[{self.ambulance_id}] At accident. Loading patient...")
                EVENT_LOG.append(f"{self.ambulance_id} loading patient.")
                time.sleep(10)
                new_dest = get_nearest_hospital(self.current_pos)
                self.state = "to-hospital"
                self.destination = new_dest
                self.send_update()
                EVENT_LOG.append(f"{self.ambulance_id} dispatched to hospital {new_dest}.")
                time.sleep(UPDATE_INTERVAL)
            elif self.state == "to-hospital":
                arrived = self.move_toward(self.destination)
                self.send_update()
                if arrived:
                    print(f"[{self.ambulance_id}] Arrived at hospital. Dropping off patient...")
                    EVENT_LOG.append(f"{self.ambulance_id} arrived at hospital.")
                    METRICS["total_hospital_dropoffs"] += 1
                    time.sleep(5)
                    preferred_base = get_preferred_base(self.current_pos)
                    self.destination = preferred_base
                    self.state = "returning"
                    self.send_update()
                    EVENT_LOG.append(f"{self.ambulance_id} returning to base at {preferred_base}.")
                time.sleep(UPDATE_INTERVAL)
            elif self.state == "returning":
                # If an accident occurs while returning, FleetManager can reassign this ambulance.
                arrived = self.move_toward(self.destination)
                self.send_update()
                if arrived:
                    self.state = "available"
                    self.send_update()
                    EVENT_LOG.append(f"{self.ambulance_id} available at base {self.destination}.")
                time.sleep(UPDATE_INTERVAL)
            else:
                time.sleep(UPDATE_INTERVAL)

# ================================
# Fleet Manager and Accident Simulation
# ================================
class FleetManager:
    def __init__(self, ambulances):
        self.ambulances = ambulances
        self.accidents = []  # list of accident events; each is a dict with 'location' and 'dispatched'
    
    def dispatch_accident(self, accident_location):
        available = [amb for amb in self.ambulances if amb.state == "available"]
        if available:
            best = min(available, key=lambda amb: haversine(amb.current_pos, accident_location))
            best.destination = accident_location
            best.state = "en-route"
            best.dispatch_time = time.time()
            best.send_update()
            EVENT_LOG.append(f"Dispatching {best.ambulance_id} to accident at {accident_location}.")
            METRICS["total_accidents"] += 1
            return best
        returning = [amb for amb in self.ambulances if amb.state == "returning"]
        if returning:
            best = min(returning, key=lambda amb: haversine(amb.current_pos, accident_location))
            best.destination = accident_location
            best.state = "en-route"
            best.dispatch_time = time.time()
            best.send_update()
            EVENT_LOG.append(f"Reassigning {best.ambulance_id} (returning) to accident at {accident_location}.")
            METRICS["total_accidents"] += 1
            return best
        EVENT_LOG.append(f"Accident at {accident_location} occurred but no ambulance available!")
        METRICS["total_accidents"] += 1
        return None

    def simulate_accident(self):
        accident_loc = random_coordinate()
        print(f"Accident occurred at {accident_loc}")
        dispatched = self.dispatch_accident(accident_loc)
        # Always record the accident event
        self.accidents.append({"location": accident_loc, "dispatched": dispatched.ambulance_id if dispatched else "None"})

# ================================
# Enhanced Visualization using Folium for Fleet & Events
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
    
    # Plot accident markers
    for acc in accidents:
        folium.Marker(
            location=list(acc["location"]),
            popup=f"Accident (Ambulance: {acc['dispatched']})",
            icon=folium.Icon(color="orange", icon="exclamation-sign")
        ).add_to(m)
    
    colors = {"EV_1": "red", "EV_2": "green", "EV_3": "blue", "EV_4": "purple",
              "EV_5": "darkred", "EV_6": "cadetblue", "EV_7": "lightgray", "EV_8": "orange",
              "EV_9": "darkgreen", "EV_10": "black"}
    
    for amb in ambulances:
        # Only display active ambulances
        if not amb.running or amb.state == "available":
            continue  # do not display those that are idle (fleet bases)
        folium.Marker(
            location=list(amb.current_pos),
            popup=f"{amb.ambulance_id} ({amb.state})",
            icon=folium.Icon(color=colors.get(amb.ambulance_id, "gray"), icon="ambulance", prefix='fa')
        ).add_to(m)
        # Draw route if available
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
    # Initialize ambulances at their fleet base positions
    ambulances = []
    for i in range(TOTAL_AMBULANCES):
        amb_id = f"EV_{i+1}"
        base = AMBULANCE_BASES[i]
        ambulances.append(Ambulance(amb_id, base))
    for amb in ambulances:
        amb.start()
    
    fleet_manager = FleetManager(ambulances)
    map_file = "fleet_map.html"
    
    # Accident simulation thread with random intervals
    def accident_simulation():
        while True:
            fleet_manager.simulate_accident()
            sleep_time = random.expovariate(1.0/15)  # average 15 sec, but random
            time.sleep(sleep_time)
    accident_thread = threading.Thread(target=accident_simulation, daemon=True)
    accident_thread.start()
    
    try:
        while True:
            # Remove accidents that are resolved: if the dispatched ambulance is no longer en-route or at accident
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
