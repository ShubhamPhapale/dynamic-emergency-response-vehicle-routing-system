# 🚑 Dynamic Emergency Response Vehicle Routing System (DERVRS)

A real-world simulation of a dynamic ambulance dispatch and routing system for Mumbai, featuring live GPS tracking, accident simulation, predictive traffic modeling, multi-vehicle coordination, and interactive dashboards with geospatial visualization.

---

## 🔧 Features

- **Live Accident Simulation**  
  Randomized accident generation (~15 seconds interval) using an exponential distribution, triggering real-time dispatch logic.

- **Ambulance Fleet Management**  
  - 10 ambulances initialized across Mumbai  
  - Dynamically dispatches nearest available ambulance  
  - Full life-cycle: Base → Accident → Hospital → Return to Base  
  - Tracks response time, dispatches, hospital drop-offs

- **Routing & Navigation**  
  Integrates with a local **GraphHopper API** for real-time routing (distance + polyline route path)

- **Predictive & Scalable Architecture**  
  - Multi-threaded ambulance movement and accident simulation  
  - Flask-based backend for updates and dashboard  
  - Real-time communication between ambulance clients and server

- **Interactive Dashboard & Map Visualization**  
  - Live dashboard (`/dashboard`) with **Chart.js** graphs  
  - Auto-refreshing map (`fleet_map.html`) with markers for ambulances, hospitals, and active accidents using **Folium**

---

## 🧰 Technology Stack

- **Language:** Python 3.x  
- **Backend:** Flask  
- **Routing Engine:** GraphHopper (running locally)  
- **Visualization:** Folium, Polyline, Leaflet, Chart.js  
- **Concurrency:** Python threading  
- **APIs:** REST (for ambulance updates), GraphHopper routing  
- **Frontend:** HTML5, JS, Chart.js

---

## 📦 Installation

### ✅ Prerequisites

- Python 3.8+
- GraphHopper routing server (with Mumbai OSM map)
- Install required Python dependencies:

```bash
pip install flask folium polyline requests
```

> ⚠️ Make sure your GraphHopper server is running on `http://localhost:8989/` before starting the simulation.

---

## 🚀 Getting Started

### 1. Clone the Repository

```bash
git clone https://github.com/ShubhamPhapale/dynamic-emergency-response-vehicle-routing-system.git
cd dynamic-emergency-response-vehicle-routing-system
```

### 2. Start the Simulation

```bash
python main.py
```

- A local Flask server will start at `http://127.0.0.1:5000/dashboard`
- Fleet positions and live route tracking will be saved to `fleet_map.html`

---

## 📊 Live Visualization

- **Dashboard (Flask):**  
  View performance metrics, fleet status, and accident logs at  
  👉 `http://127.0.0.1:5000/dashboard`

- **Live Map (Folium):**  
  Open `fleet_map.html` in your browser to track real-time ambulance and accident updates  
  (automatically refreshes every 5 seconds)

---

## 📈 Expected Behavior

1. Accident is simulated randomly across Mumbai.
2. Nearest available ambulance is dispatched using haversine distance + GraphHopper routing.
3. Ambulance navigates to accident → then to nearest hospital → returns to base.
4. All events are logged on the dashboard.
5. System handles multiple simultaneous accidents gracefully.
6. If no ambulance is available, incidents are logged as "unserved".

---

## 📁 File Structure

```
main.py                 # Main simulation logic and entry point
fleet_map.html                # Auto-updating live map
server/                 # Setup Locally
graphhopper/                  # Setup Locally 
```

---

## ⚙️ Advanced Extensions (Ideas)

- Integrate live **GPS tracking** from real emergency vehicles  
- Fetch **traffic congestion data** using Google Maps or OpenStreetMap  
- Incorporate **ML-based predictive modeling** (LSTM, regression)  
- Multi-commodity vehicle dispatch logic  
- Use **MQTT/WebSockets** for faster real-time communication  
- Deploy on AWS EC2/GCP with Kubernetes scaling

---

## 🤝 Contributing

We welcome contributions to improve routing, visualization, or system robustness!

### Suggestions:

- Integrate real-time IoT feeds
- Improve dashboard responsiveness and layout
- Add unit tests and CI pipelines
- Migrate to async/event-based architecture using FastAPI + asyncio

Please fork the repo and raise a pull request with detailed changes.

---

## 👨‍💻 Authors

- **Shubham Phapale**
- **Aditya Mohite**
- **Aniket Wani**

---

## 📄 License

This project is open-source.

---

## 🌐 Links

- [GraphHopper Routing Engine](https://www.graphhopper.com/)
- [Folium Docs](https://python-visualization.github.io/folium/)
- [Chart.js](https://www.chartjs.org/)
- [Haversine Formula](https://en.wikipedia.org/wiki/Haversine_formula)

---

## 🧠 Summary

> This system simulates an end-to-end emergency vehicle routing system capable of handling urban-scale traffic dynamics and multiple incidents. The architecture supports integration of real-time data streams, predictive routing, and dispatch optimization — paving the way for real-world deployment.

``` 
