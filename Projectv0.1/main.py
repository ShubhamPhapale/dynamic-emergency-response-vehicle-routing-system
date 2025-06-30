import threading
import time
import random
import math
import requests
from flask import Flask, request, jsonify, render_template_string
import folium
import polyline
import os
from collections import defaultdict

# ================================
# Configuration & Global Settings
# ================================
UPDATE_INTERVAL = 5       # seconds between updates
# Accident intervals are randomized using an exponential distribution (mean ~15 sec)
TOTAL_AMBULANCES = 10

# Fixed geographic boundaries for Mumbai (approximate)
FIXED_LAT_LIMITS = (18.95, 19.20)
FIXED_LON_LIMITS = (72.80, 73.05)
MAP_CENTER = [ (FIXED_LAT_LIMITS[0] + FIXED_LAT_LIMITS[1]) / 2,
               (FIXED_LON_LIMITS[0] + FIXED_LON_LIMITS[1]) / 2 ]

# For accidents, use a sub-boundary to ensure on-land incidents
ACCIDENT_LAT_LIMITS = (19.00, 19.18)
ACCIDENT_LON_LIMITS = (72.85, 73.00)

# Actual hospital locations in Mumbai (top 20 hospitals, approximate)
HOSPITALS = [
    {"name": "KEM Hospital", "lat": 19.0176, "lon": 72.8562},
    {"name": "Lilavati Hospital", "lat": 19.0738, "lon": 72.8400},
    {"name": "Hiranandani Hospital Powai", "lat": 19.1255, "lon": 72.8789},
    {"name": "Bombay Hospital", "lat": 19.0340, "lon": 72.8333},
    {"name": "J.J. Hospital", "lat": 19.0333, "lon": 72.8375},
    {"name": "S.L. Raheja Hospital", "lat": 19.0921, "lon": 72.8852},
    {"name": "P.D. Hinduja Hospital", "lat": 19.0728, "lon": 72.8594},
    {"name": "Seven Hills Hospital", "lat": 19.0916, "lon": 72.8645},
    {"name": "Breach Candy Hospital", "lat": 19.0230, "lon": 72.8330},
    {"name": "Holy Family Hospital", "lat": 19.0413, "lon": 72.8450},
    {"name": "Jaslok Hospital", "lat": 19.0628, "lon": 72.8321},
    {"name": "Nanavati Hospital", "lat": 19.0460, "lon": 72.8544},
    {"name": "Wockhardt Hospital", "lat": 19.0765, "lon": 72.8772},
    {"name": "Tata Memorial Hospital", "lat": 19.0439, "lon": 72.8331},
    {"name": "Sassoon General Hospital", "lat": 19.0360, "lon": 72.8340},
    {"name": "Tilak Municipal Medical College", "lat": 19.0710, "lon": 72.8750},
    {"name": "R.C. Patel Hospital", "lat": 19.0335, "lon": 72.8570},
    {"name": "Jupiter Hospital", "lat": 19.0750, "lon": 72.8750},
    {"name": "Saifee Hospital", "lat": 19.0570, "lon": 72.8460},
    {"name": "Hiranandani Hospital Andheri", "lat": 19.1190, "lon": 72.8460}
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

# Vulnerable bases (preferred bases) for return if needed (if no active accident)
VULNERABLE_BASES = [
    (19.00, 72.82),
    (19.16, 73.00)
]

def get_preferred_base(current_position):
    return min(VULNERABLE_BASES, key=lambda base: haversine(current_position, base))

# Server configuration for our central dashboard
SERVER_HOST = '127.0.0.1'
SERVER_PORT = 5000

# GraphHopper API endpoint (ensure your GraphHopper server is running with valid OSM data)
GH_API_ENDPOINT = "http://127.0.0.1:8989/route"

# Global performance metrics, event log, and accident timestamps
METRICS = {
    "total_accidents": 0,
    "total_dispatches": 0,
    "total_response_time": 0.0,  # seconds
    "total_hospital_dropoffs": 0
}
EVENT_LOG = []
ACCIDENT_TIMESTAMPS = []

def current_condition():
    now = time.time()
    recent = [ts for ts in ACCIDENT_TIMESTAMPS if now - ts < 60]
    if len(recent) >= 3:
        return "High Accident Load"
    elif len(recent) > 0:
        return "Moderate Accident Load"
    else:
        return "Normal"

# ================================
# Utility Functions
# ================================
def random_coordinate(boundaries=(FIXED_LAT_LIMITS[0], FIXED_LAT_LIMITS[1],
                                    FIXED_LON_LIMITS[0], FIXED_LON_LIMITS[1])):
    lat_min, lat_max, lon_min, lon_max = boundaries
    return (random.uniform(lat_min, lat_max), random.uniform(lon_min, lon_max))

def random_accident_coordinate():
    return random_coordinate((ACCIDENT_LAT_LIMITS[0], ACCIDENT_LAT_LIMITS[1],
                              ACCIDENT_LON_LIMITS[0], ACCIDENT_LON_LIMITS[1]))

def haversine(coord1, coord2):
    lat1, lon1 = coord1
    lat2, lon2 = coord2
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    return R * c

def get_nearest_hospital(position):
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

# Dashboard template with enhanced visuals and multiple charts (Chart.js)
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
      .container { display: flex; flex-wrap: wrap; gap: 20px; }
      .chart-container { flex: 1 1 300px; }
      .metrics, .event-log, .fleet-status { margin-bottom: 20px; }
      .event-log { font-size: 0.9em; color: #555; max-height: 200px; overflow-y: scroll; }
      table { border-collapse: collapse; width: 100%; margin-top: 20px; }
      th, td { padding: 8px; border: 1px solid #ddd; text-align: left; }
      tr:nth-child(even) { background-color: #f2f2f2; }
    </style>
    <!-- Chart.js CDN -->
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script>
      setInterval(function() { window.location.reload(); }, 5000);
    </script>
  </head>
  <body>
    <h2>Emergency Vehicle Dashboard</h2>
    <div class="metrics">
      <h3>Performance Metrics</h3>
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
      <p>Current Condition: {{ condition }}</p>
    </div>
    <div class="container">
      <div class="chart-container">
        <canvas id="barChart"></canvas>
      </div>
      <div class="chart-container">
        <canvas id="lineChart"></canvas>
      </div>
      <div class="chart-container">
        <canvas id="pieChart"></canvas>
      </div>
    </div>
    <div class="event-log">
      <h3>Recent Event Log</h3>
      <ul>
      {% for event in events %}
        <li>{{ event }}</li>
      {% endfor %}
      </ul>
    </div>
    <div class="fleet-status">
      <h3>Fleet Base Status</h3>
      {% for base in bases %}
        <p>Base ({{ base[0] }}, {{ base[1] }}): 
        {% set ambulances_here = [] %}
        {% for amb in vehicles %}
          {% if amb.state == "available" and (amb.current_pos[0]|round(2), amb.current_pos[1]|round(2)) == (base[0]|round(2), base[1]|round(2)) %}
            {% set _ = ambulances_here.append(amb.ambulance_id) %}
          {% endif %}
        {% endfor %}
        {{ ambulances_here|join(', ') if ambulances_here else "None" }}
        </p>
      {% endfor %}
    </div>
    <table>
      <tr>
        <th>Ambulance ID</th>
        <th>State</th>
        <th>Base Position</th>
        <th>Current Position</th>
        <th>Destination</th>
        <th>Last Update</th>
      </tr>
      {% for v in vehicles %}
      <tr>
        <td>{{ v.ambulance_id }}</td>
        <td>{{ v.state }}</td>
        <td>{{ v.base_position }}</td>
        <td>{{ v.current_pos }}</td>
        <td>{{ v.destination }}</td>
        <td>{{ v.timestamp }}</td>
      </tr>
      {% endfor %}
    </table>
    
    <script>
      // Bar Chart: Key Performance Metrics
      const barData = {
        labels: ["Accidents", "Dispatches", "Drop-offs", "Avg Response (s)"],
        datasets: [{
          label: 'Performance',
          data: [
            {{ metrics.total_accidents }},
            {{ metrics.total_dispatches }},
            {{ metrics.total_hospital_dropoffs }},
            {% if metrics.total_dispatches > 0 %}
              {{ "%.2f"|format(metrics.total_response_time / metrics.total_dispatches) }}
            {% else %}
              0
            {% endif %}
          ],
          backgroundColor: [
            'rgba(255, 99, 132, 0.7)',
            'rgba(54, 162, 235, 0.7)',
            'rgba(255, 206, 86, 0.7)',
            'rgba(75, 192, 192, 0.7)'
          ],
          borderColor: [
            'rgba(255, 99, 132, 1)',
            'rgba(54, 162, 235, 1)',
            'rgba(255, 206, 86, 1)',
            'rgba(75, 192, 192, 1)'
          ],
          borderWidth: 1
        }]
      };
      const barConfig = {
        type: 'bar',
        data: barData,
        options: { scales: { y: { beginAtZero: true } } }
      };
      new Chart(document.getElementById('barChart'), barConfig);

      // Line Chart: Accident Frequency over last 10 minutes
      const now = Date.now();
      const accidentTimes = {{ accident_times|tojson }};
      const buckets = Array(10).fill(0);
      accidentTimes.forEach(ts => {
        const diff = now - ts;
        const minutes = diff / 60000;
        if (minutes < 10) {
          buckets[9 - Math.floor(minutes)] += 1;
        }
      });
      const lineData = {
        labels: Array.from({length: 10}, (_, i) => `${10 - i} min ago`),
        datasets: [{
          label: 'Accidents per Minute',
          data: buckets,
          fill: false,
          borderColor: 'rgba(255, 159, 64, 1)',
          tension: 0.1
        }]
      };
      const lineConfig = { type: 'line', data: lineData };
      new Chart(document.getElementById('lineChart'), lineConfig);

      // Pie Chart: Ambulance State Distribution
      const ambulanceStates = {{ ambulance_states|tojson }};
      const pieData = {
        labels: Object.keys(ambulanceStates),
        datasets: [{
          data: Object.values(ambulanceStates),
          backgroundColor: [
            'rgba(75, 192, 192, 0.7)',
            'rgba(54, 162, 235, 0.7)',
            'rgba(255, 205, 86, 0.7)',
            'rgba(255, 99, 132, 0.7)',
            'rgba(153, 102, 255, 0.7)'
          ]
        }]
      };
      const pieConfig = { type: 'pie', data: pieData };
      new Chart(document.getElementById('pieChart'), pieConfig);
    </script>
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
    events = EVENT_LOG[-10:][::-1]
    condition = current_condition()
    state_counts = {}
    for v in vehicles:
        state = v.get("state", "unknown")
        state_counts[state] = state_counts.get(state, 0) + 1
    accident_times = [ts * 1000 for ts in ACCIDENT_TIMESTAMPS]
    return render_template_string(DASHBOARD_TEMPLATE, vehicles=vehicles, timestamp=timestamp, 
                                  metrics=METRICS, events=events, bases=AMBULANCE_BASES, 
                                  condition=condition, accident_times=accident_times, ambulance_states=state_counts)

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
        super().__init__()
        self.ambulance_id = ambulance_id
        self.base_position = base_position
        self.current_pos = base_position
        self.destination = base_position
        self.route = ""
        self.route_length = 0.0
        self.state = "available"  # available, en-route, at accident, to-hospital, returning
        self.timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        self.running = True
        self.dispatch_time = None

    def compute_route(self):
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
            "base_position": self.base_position,
            "current_pos": self.current_pos,
            "destination": self.destination,
            "timestamp": self.timestamp
        }
        try:
            requests.post(f"http://{SERVER_HOST}:{SERVER_PORT}/update", json=payload)
        except Exception as e:
            print(f"[{self.ambulance_id}] Error sending update: {e}")

    def move_toward(self, target, step_fraction=0.2):
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
                EVENT_LOG.append(f"{self.ambulance_id} loading patient at accident.")
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
                    EVENT_LOG.append(f"{self.ambulance_id} arrived at hospital.")
                    METRICS["total_hospital_dropoffs"] += 1
                    time.sleep(5)
                    if fleet_manager.accidents:
                        active_accidents = [acc["location"] for acc in fleet_manager.accidents]
                        nearest_acc = min(active_accidents, key=lambda loc: haversine(self.current_pos, loc))
                        self.destination = nearest_acc
                        self.state = "en-route"
                        self.dispatch_time = time.time()
                        EVENT_LOG.append(f"{self.ambulance_id} reassigned to accident at {nearest_acc}.")
                    else:
                        self.destination = self.base_position
                        self.state = "returning"
                        EVENT_LOG.append(f"{self.ambulance_id} returning to base {self.base_position}.")
                    self.send_update()
                time.sleep(UPDATE_INTERVAL)
            elif self.state == "returning":
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
        self.accidents = []  # each accident: dict with 'location', 'dispatched', 'timestamp'
    
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
            ACCIDENT_TIMESTAMPS.append(time.time())
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
            ACCIDENT_TIMESTAMPS.append(time.time())
            return best
        EVENT_LOG.append(f"Accident at {accident_location} occurred but no ambulance available!")
        METRICS["total_accidents"] += 1
        ACCIDENT_TIMESTAMPS.append(time.time())
        return None

    def simulate_accident(self):
        accident_loc = random_accident_coordinate()
        print(f"Accident occurred at {accident_loc}")
        dispatched = self.dispatch_accident(accident_loc)
        self.accidents.append({
            "location": accident_loc, 
            "dispatched": dispatched.ambulance_id if dispatched else "None", 
            "timestamp": time.time()
        })

# ================================
# Enhanced Visualization using Folium (Fleet, Accidents, and Events)
# ================================
def visualize_fleet_folium(ambulances, accidents, map_file="fleet_map.html"):
    m = folium.Map(location=MAP_CENTER, zoom_start=12)
    m.get_root().html.add_child(folium.Element('<meta http-equiv="refresh" content="5">'))
    
    # Plot hospital markers with actual names
    for hosp in HOSPITALS:
        folium.Marker(
            location=[hosp["lat"], hosp["lon"]],
            popup=hosp["name"],
            icon=folium.Icon(color="darkred", icon="plus-sign")
        ).add_to(m)
    
    # Plot accident markers for accidents within the last 120 seconds
    now = time.time()
    recent_accidents = [acc for acc in accidents if now - acc["timestamp"] < 120]
    for acc in recent_accidents:
        folium.Marker(
            location=list(acc["location"]),
            popup=f"Accident (Ambulance: {acc['dispatched']})",
            icon=folium.Icon(color="orange", icon="exclamation-sign")
        ).add_to(m)
    
    colors = {"EV_1": "red", "EV_2": "green", "EV_3": "blue", "EV_4": "purple",
              "EV_5": "darkred", "EV_6": "cadetblue", "EV_7": "lightgray", "EV_8": "orange",
              "EV_9": "darkgreen", "EV_10": "black"}
    
    for amb in ambulances:
        folium.Marker(
            location=list(amb.current_pos),
            popup=f"{amb.ambulance_id} ({amb.state})",
            icon=folium.Icon(color=colors.get(amb.ambulance_id, "gray"), icon="ambulance", prefix='fa')
        ).add_to(m)
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
        # Always plot the base marker
        folium.Marker(
            location=list(amb.base_position),
            popup=f"{amb.ambulance_id} Base",
            icon=folium.Icon(color="blue", icon="home")
        ).add_to(m)
    
    m.save(map_file)
    print(f"Fleet map updated and saved to {map_file}. Refresh your browser to see changes.")

# ================================
# Main Simulation Loop
# ================================
def run_simulation():
    ambulances = []
    for i in range(TOTAL_AMBULANCES):
        amb_id = f"EV_{i+1}"
        base = AMBULANCE_BASES[i]
        ambulances.append(Ambulance(amb_id, base))
    for amb in ambulances:
        amb.start()
    
    global fleet_manager
    fleet_manager = FleetManager(ambulances)
    map_file = "fleet_map.html"
    
    # Accident simulation thread with random intervals (exponential distribution)
    def accident_simulation():
        while True:
            fleet_manager.simulate_accident()
            sleep_time = random.expovariate(1.0/15)  # mean ~15 sec // 50
            time.sleep(sleep_time)
    accident_thread = threading.Thread(target=accident_simulation, daemon=True)
    accident_thread.start()
    
    try:
        while True:
            fleet_manager.accidents = [acc for acc in fleet_manager.accidents 
                                       if any(amb.ambulance_id == acc.get("dispatched") and amb.state in ["en-route", "at accident"] for amb in ambulances)]
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
