# paeraki

Ship computer and telemetry monitoring system for yacht *Paeraki*.

```mermaid
graph TD
    subgraph Paeraki Yacht [Onboard Yacht Paeraki]
        SRNE[12V Solar Controller] -->|BLE Modbus| Look[look 192.168.1.100 / .101]
        JBDBMS[72V JBD BMS] -->|BLE GATT| Look
        RUTGPS[Teltonika RUT955 GPS] -->|NMEA TCP :8500| LookGPS[watch_gps.service on look]
        LookGPS -->|Publish paeraki/gps/state, gps/*| RUTBroker[Teltonika RUT955 Broker 192.168.1.1:1883]
        Look -->|Publish 12v/*, 72v/*| RUTBroker
        RUTBroker -->|Subscribe #| LookDashboard[Onboard Dashboard :8080]
    end

    RUTBroker -->|Site-to-Site VPN| Hammer[Hammer Workstation 192.168.50.89]

    subgraph Hammer [Home / Remote Workstation]
        Hammer --> HammerLogger[paeraki_logger.service]
        HammerLogger -->|Buffered WAL Writes| DB[(data/paeraki.db)]

        DB --> PyQuery[Python / Pandas / Polars]
        DB --> RQuery[R / DBI / RSQLite]
        DB --> JuliaQuery[Julia / DataFrames]
    end
```

---

## 1. Onboard Telemetry Dashboard

A real-time web dashboard running on **`look`** (`192.168.1.100:8080` / `192.168.1.101:8080`) built with FastAPI, WebSockets, and a responsive nautical dark UI.

### Key Capabilities
- **Navigation & Vessel Position (RUT955 GPS)**:
  - Speed Over Ground (SOG) in knots (primary) with km/h and m/s velocity conversions.
  - Course Over Ground (COG) in degrees True with cardinal heading orientation.
  - Nautical coordinates (`dd° mm.mmm' S/E`) and decimal latitude/longitude.
  - Active satellite count, horizontal dilution of precision (HDOP), altitude (m), and 3D GNSS fix status.
  - Quick OpenStreetMap link to view current yacht location in any charting tool.
- **72V Propulsion Battery (JBD BMS)**:
  - Radial animated State of Charge (SoC %) gauge with Tri-Method comparison (Integrated Coulomb counter, Voltage OCV curve, BMS reported).
  - Pack voltage (V), current (A, dynamic charging/discharging mode), and net power (W/kW).
  - Cycle count, residual capacity (Ah), MOSFET switches (CHG/DSG), and temperatures.
  - **20-Cell Voltage Spectrum Visualizer**: Dynamic bar graph displaying all 20 individual cell voltages with min, max, and delta (mV) metrics.
- **12V House & Solar System (SRNE/Renogy)**:
  - House battery voltage with capacity progress indicator.
  - Solar PV generation power (W), PV voltage, and current.
  - Charge controller state (`MPPT Bulk Charging`, `Float`) and daily yield (kWh).
  - Live Modbus register explorer displaying all incoming 12V keys.
- **Live MQTT Stream Inspector**:
  - Auto-scrolling filterable log table displaying incoming vessel packets across topic `#`.
  - Quick filters for **All**, **72V**, **12V**, **GPS**, and **Other**.
  - Pause auto-scroll and clear buffer controls.

### Accessing the Dashboard
- **Onboard (Wi-Fi or LAN)**: Open **[`http://192.168.1.100:8080`](http://192.168.1.100:8080)** in any browser (phone, tablet, or touchscreen).
- **Remotely (via VPN on hammer)**: Open **[`http://192.168.1.100:8080`](http://192.168.1.100:8080)**.
- **Local Dev Server on hammer**:
  ```bash
  ./run_monitor.sh          # Web dashboard on http://localhost:8080
  ./run_monitor.sh --mock   # Web dashboard with simulated test telemetry
  ./run_monitor.sh --cli    # Terminal-based live dashboard (Rich TUI)
  ```

### Managing the Dashboard Service on `look`
The dashboard runs as a 24/7 background systemd service:
```bash
# Check service status
ssh jh@192.168.1.100 "systemctl status paeraki_dashboard"

# Follow live service logs
ssh jh@192.168.1.100 "journalctl -u paeraki_dashboard -f"

# Restart service after code updates
ssh jh@192.168.1.100 "sudo systemctl restart paeraki_dashboard"
```

---

## 2. Telemetry Logger Service (running on `hammer`)

A lightweight, non-blocking telemetry logger that captures every MQTT packet coming from Paeraki (`192.168.1.1:1883`) and logs them to a durable SQLite database at **`data/paeraki.db`**.

### Database Architecture
- **Engine**: SQLite configured with **Write-Ahead Logging (WAL)** mode (`PRAGMA journal_mode = WAL;`) and non-blocking read transactions. This allows continuous streaming inserts while Python, R, or Julia run analytical queries simultaneously without lock contention.
- **Dual-Layer Schema**:
  1. **`packets` table**: Verbatim archive of all raw messages (`id`, `timestamp`, `epoch_ms`, `topic`, `payload`, `is_json`).
  2. **`telemetry_72v` table**: Structured tabular data (`total_voltage`, `current`, `power`, `rsoc`, `cell_min_v`, `cell_max_v`, `cell_delta_mv`, `cell_voltages_json`, etc.).
  3. **`telemetry_12v` table**: Structured tabular data (`battery_voltage`, `battery_soc`, `solar_power`, `solar_voltage`, `solar_current`, `daily_yield_kwh`, `charging_status`).
  4. **Views**: `v_recent_72v`, `v_recent_12v`, `v_recent_packets`.

### Managing the Logger Service on `hammer`
The logger runs as a systemd user service under your account:
```bash
# Check service status
systemctl --user status paeraki_logger

# Follow live log stream
journalctl --user -u paeraki_logger -f

# Restart service
systemctl --user restart paeraki_logger

# Stop service
systemctl --user stop paeraki_logger
```

### Querying the Database

The database file `data/paeraki.db` can be queried directly across multiple languages without any server dependencies:

#### Python (sqlite3 / Pandas / Polars)
```bash
# Run bundled query script:
uv run logger/examples/query_python.py
```
```python
import sqlite3
import pandas as pd

conn = sqlite3.connect("file:data/paeraki.db?mode=ro", uri=True)
df_72v = pd.read_sql("SELECT * FROM telemetry_72v ORDER BY epoch_ms DESC LIMIT 500", conn)
print(df_72v[["timestamp", "total_voltage", "current", "power", "rsoc"]])
```

#### R (DBI / RSQLite)
```bash
# Run bundled R script:
Rscript logger/examples/query_r.R
```
```R
library(DBI)
library(RSQLite)

con <- dbConnect(RSQLite::SQLite(), "data/paeraki.db", flags = SQLITE_RO)
df <- dbGetQuery(con, "SELECT timestamp, total_voltage, current, power FROM telemetry_72v WHERE power < 0")
summary(df)
```

#### Julia (SQLite.jl / DataFrames.jl)
```bash
# Run bundled Julia script:
julia logger/examples/query_julia.jl
```
```julia
using SQLite, DataFrames

db = SQLite.DB("data/paeraki.db")
df = DBInterface.execute(db, "SELECT * FROM telemetry_72v ORDER BY epoch_ms DESC LIMIT 100") |> DataFrame
```

#### Command-Line (sqlite3 CLI / DuckDB)
```bash
sqlite3 data/paeraki.db "SELECT timestamp, total_voltage, current, power FROM telemetry_72v ORDER BY epoch_ms DESC LIMIT 10;"
```

---

## 3. Android Mobile & Cockpit Tablet App (APK & PWA)

To monitor Paeraki on Android phones, cockpit tablets, and e-ink displays, the app can be installed using two methods: a **Native Android APK** (recommended for boat reliability) or a **Progressive Web App (PWA)**.

### Architecture: WebView Container vs. Direct MQTT Broker
We evaluated connecting directly to MQTT over TCP versus wrapping the web dashboard:
- **Zero UI Duplication**: The Android app uses the exact same reactive, animated UI as the onboard touchscreen and desktop monitors. Any sensor additions (NMEA2000, CANBUS, depth) appear on the Android device instantly without rewriting Kotlin/Compose code.
- **Vessel Realities**: Both 12V SRNE solar and 72V JBD BMS sensors are read by `sing` over Bluetooth. If `sing` is off, there is no telemetry to read anyway.
- **Embedded Asset Fallback**: Static assets (`HTML/CSS/JS/icons`) are compiled directly into the APK's `assets/` directory. The app launches in 0ms without needing an active internet connection, using Wi-Fi solely for low-latency WebSocket packets (`/ws`).
- **Cockpit Display Features**: Immersive fullscreen (no URL or navigation bars) + **Keep Screen Awake** permission (`WAKE_LOCK`) so the tablet stays illuminated at the helm.

---

### Option A: Install via Android APK File (Recommended)
The native Android app is packaged as a ready-to-install APK (4.0 MB) with zero external dependencies.

#### Method 1: Direct Download on Phone / Tablet (No PC Required)
1. Connect your phone or tablet (e.g. OPPO A60, Samsung, Pixel) to **Paeraki's onboard Wi-Fi**.
2. Open your mobile browser and navigate to:
   👉 **`http://192.168.1.101:8080/download`**  
   *(or tap the **"Download Android App (APK)"** button in the dashboard footer)*.
3. Once downloaded, tap the notification or open your device's **Files / Downloads** app.
4. Tap **`paeraki-monitor.apk`** to install.
5. If prompted with *"For security, your phone is not allowed to install unknown apps from this source"*:
   - Tap **Settings**.
   - Toggle **Allow from this source** (or "Install unknown apps").
   - Tap **Install**.
6. Launch **Paeraki** from your home screen.

#### Method 2: Install via ADB (Workstation / Developer)
If your phone is connected to your development machine via USB (with Developer Options & USB Debugging enabled):
```bash
adb install -r dist/paeraki-monitor.apk
```
Or over Wi-Fi:
```bash
adb connect 192.168.1.X:5555
adb install -r dist/paeraki-monitor.apk
```

#### Rebuilding the APK After UI Updates:
When dashboard code or styles are modified:
```bash
./android/build_apk.sh  # Re-syncs web assets and compiles dist/paeraki-monitor.apk
./sync.sh               # Syncs updated APK to sing so /download serves the new build
```

---

### Option B: Install via Progressive Web App (PWA)

The dashboard includes a Web App Manifest (`manifest.json`) and an offline-caching Service Worker (`sw.js`). However, modern Android browsers (Chromium & ColorOS) enforce a strict **Secure Context (HTTPS)** requirement for PWAs. Local private IP addresses like `http://192.168.1.101:8080` are classified as insecure, which disables Service Workers and suppresses the native "Install App" prompt.

Follow the instructions below for your specific platform:

#### 1. Android (Google Chrome)
To bypass Chromium's local insecure origin restriction on your phone:
1. Open **Google Chrome** on your phone (connected to Paeraki Wi-Fi).
2. In the address bar, type:
   ```text
   chrome://flags/#unsafely-treat-insecure-origin-as-secure
   ```
3. Find the flag **"Insecure origins treated as secure"** and select **Enabled**.
4. In the text box below the flag, enter the dashboard URL:
   ```text
   http://192.168.1.101:8080
   ```
5. Tap the blue **Relaunch** button at the bottom of the screen.
6. Navigate to `http://192.168.1.101:8080`.
7. Tap the Chrome menu (**⋮**) -> **"Install app"** (or tap the **"Install PWA"** button in the dashboard footer).
8. Confirm installation. The app will appear on your home screen with its nautical icon and run in standalone fullscreen mode.

> [!NOTE]
> Chrome uses Google's cloud WebAPK minting service (`webapk.googleapis.com`) to generate system-level apps. If your phone is connected to Paeraki Wi-Fi without active upstream cellular data, WebAPK generation may stall. If this occurs, use **Option A (Native APK)** instead.

#### 2. Android (OPPO / ColorOS / HeyTap Default Browser)
OPPO's built-in ColorOS browser does not support WebAPK minting:
- Tapping **Menu -> Add to desktop** will create a browser bookmark shortcut (opening with URL bar and tabs), not a standalone app.
- For a true standalone kiosk experience on an OPPO device, use **Option A (Native APK)** or use **Google Chrome** with the flag above.

#### 3. Apple iOS (iPhone & iPad Safari)
iOS Safari permits home screen PWA installation over local HTTP without security flag workarounds:
1. Connect your iPhone or iPad to **Paeraki Wi-Fi**.
2. Open **`http://192.168.1.101:8080`** in **Safari**.
3. Tap the **Share** button (the square with an arrow pointing up).
4. Scroll down and tap **"Add to Home Screen"**.
5. Tap **Add** in the top-right corner.
6. Launch **Paeraki** from your iOS home screen — it will launch in standalone fullscreen mode without Safari navigation bars.

---

## 4. Continuous GPS & Navigation Telemetry (Teltonika RUT955 & look)

Continuous vessel navigation tracking is implemented using the built-in GNSS receiver on Paeraki's onboard **Teltonika RUT955** router (`192.168.1.1`, Quectel EC25-AU modem) streaming directly to the onboard single-board computer **`look`** (`192.168.1.100`).

### Architecture & Data Flow

```
[RUT955 Quectel EC25-AU]
        │ (Raw NMEA 0183 output on /dev/ttyUSB2)
        │ 
        ▼
[Router /etc/rc.local: nc TCP loop] ────► [TCP:8500] ──► [watch_gps.service on look]
                                                                  │
                                                                  ├─► [gps/nmea.py Parser]
                                                                  │
                                                                  ├─► [Publish: paeraki/gps/state & gps/*]
                                                                  │          │
                                                                  │          ├─► [Web Dashboard :8080 on look]
                                                                  │          └─► [paeraki_logger on hammer]
                                                                  │                     │
                                                                  │                     ▼
                                                                  └─────────────► [data/paeraki.db]
```

### Published MQTT Topics
- **`paeraki/gps/state`**: Consolidated JSON snapshot:
  ```json
  {
    "timestamp": "2026-09-14T08:58:44+00:00",
    "fix": true,
    "fix_status": "A",
    "fix_quality": 1,
    "latitude": -43.604779,
    "longitude": 172.714957,
    "latitude_nautical": "43° 36.287' S",
    "longitude_nautical": "172° 42.897' E",
    "sog_knots": 0.0,
    "sog_kmh": 0.0,
    "sog_ms": 0.0,
    "cog_true": 255.7,
    "altitude_m": 9.7,
    "satellites": 10,
    "hdop": 0.7,
    "last_sentence": "GGA"
  }
  ```
- **`gps/*`**: Discrete granular topics (`gps/fix`, `gps/sog_knots`, `gps/sog_kmh`, `gps/cog_true`, `gps/latitude`, `gps/longitude`, `gps/latitude_nautical`, `gps/longitude_nautical`, `gps/satellites`, `gps/hdop`, `gps/altitude_m`).

---

### Understanding the Router ⇄ look GPS Communications

Understanding how GPS data flows between the Teltonika RUT955 router and `look` requires knowing two crucial hardware and firmware realities:

#### 1. Why the WebUI "NMEA Forwarding" Does NOT Work (The `gpsd` Firmware Bug)
- In Teltonika RutOS, the WebUI feature **Services → GPS → NMEA Forwarding** relies entirely on the internal `/usr/sbin/gpsd` daemon.
- On Paeraki's router with the `Quectel EC25-AU` modem, Teltonika's compiled `gpsd` hardcodes an initialization query for Direct Power Optimization (DPO): `AT+QGPSCFG="dpoenable"`.
- The EC25-AU modem firmware does **not** support DPO mode and returns `ERROR`.
- `/usr/sbin/gpsd` crashes immediately on startup (`[nmea_init:890] error: Failed to set dpo enable`).
- **Consequence**: `gpsd` had to be disabled permanently (`/etc/init.d/gpsd disable && /etc/init.d/gpsd stop`). Because `gpsd` is disabled, **changing the IP in the router's WebUI NMEA Forwarder does nothing**. The router's WebUI forwarder is inactive.

#### 2. The Actual Hardware Pipe: Direct `/dev/ttyUSB2` Streaming via `/etc/rc.local`
- The Quectel EC25-AU modem exposes raw NMEA 0183 sentences directly on hardware serial port `/dev/ttyUSB2`.
- When GNSS is active, `/dev/ttyUSB2` streams real-time `$GPRMC`, `$GPGGA`, `$GPVTG`, `$GPGSA`, and `$GPGSV` sentences at 1 Hz with full multi-constellation satellite telemetry (GPS + GLONASS + Galileo, 10+ satellites locked).
- **BusyBox `nc` Limitation**: The router's BusyBox `nc` utility was compiled without UDP (`-u`) support (`Usage: nc [IPADDR PORT]`). It can **only** stream over TCP.
- The router runs an auto-reconnecting loop in `/etc/rc.local`:
  ```sh
  # Paeraki 24/7 GPS Streaming to look
  (
    sleep 15
    gsmctl -A "AT+QGPS=1,30,50,0,1"
    while true; do
      nc 192.168.1.100 8500 < /dev/ttyUSB2
      sleep 2
    done
  ) &
  ```
  *Parameter breakdown for `AT+QGPS=1,30,50,0,1`: Mode `1` (Standalone), Max Time `30s`, Max Dist `50m`, Fix Count `0` (Infinite Continuous Fixes, preventing the 30-fix timeout shutdown), Fix Rate `1s`.*

#### 3. Dual-IP Networking on `look` (`192.168.1.100` and `192.168.1.101`)
- When the vessel computer was migrated from `sing` (`192.168.1.101`) to `look` (`192.168.1.100`), the router's `/etc/rc.local` was still configured to connect to `.101`.
- To make communications bulletproof against configuration discrepancies:
  - `look` is configured with **both** IP addresses on `lan0`:
    - `192.168.1.100/24` (primary DHCP lease)
    - `192.168.1.101/24` (persistent secondary static IP in NetworkManager)
  - Configured via:
    ```bash
    sudo nmcli connection modify 'Wired connection 2' +ipv4.addresses 192.168.1.101/24
    ```
  - `watch_gps.service` on `look` binds to `0.0.0.0:8500` (listening on both TCP and UDP).
  - As a result, whether the router connects to `192.168.1.100` or `192.168.1.101`, the NMEA TCP stream connects instantly and seamlessly.

---

### Permanent Router Setup Reference

If setting up a replacement Teltonika router or editing `/etc/rc.local` on the router (`ssh root@192.168.1.1`):

#### 1. Keep the Broken RutOS `gpsd` Service Disabled
```bash
/etc/init.d/gpsd disable
/etc/init.d/gpsd stop
```

#### 2. Enable Hardware `autogps` in Modem Flash
Tells the Quectel baseband hardware to start GNSS automatically on power-up:
```bash
gsmctl -A 'AT+QGPSCFG="autogps",1'
```

#### 3. Ensure `/etc/rc.local` Contains the Streaming Loop
In `/etc/rc.local` on the router before `exit 0`:
```sh
(
  sleep 15
  gsmctl -A "AT+QGPS=1,30,50,0,1"
  while true; do
    nc 192.168.1.100 8500 < /dev/ttyUSB2
    sleep 2
  done
) &
```

---

### Service Management on `look`
The `watch_gps.service` runs continuously under systemd on `look`:

```bash
# Check service status
ssh jh@192.168.1.100 "systemctl status watch_gps.service"

# View live telemetry journal
ssh jh@192.168.1.100 "journalctl -u watch_gps.service -f"

# Restart collector
ssh jh@192.168.1.100 "sudo systemctl restart watch_gps.service"
```

### Dry-Run Voyage Simulator
For development or offline testing without satellite reception:
```bash
# Simulate realistic voyage across the Hauraki Gulf (5.2 kts on 055° True)
python3 gps/watch.py --dry-run --broker 192.168.1.1 --interval 1.0
```

---

## 5. Development & Deployment Workflow

Development takes place locally on `hammer` and changes are synced directly to `look`:

```bash
# Sync local changes to look (ignoring .venv, git, and local database files)
REMOTE_HOST=jh@192.168.1.100 ./sync.sh

# Sync and execute a command on look:
REMOTE_HOST=jh@192.168.1.100 ./sync.sh "sudo systemctl restart paeraki_dashboard"
```

---

## Roadmap

1. ~~Set up VPN~~
1. ~~Log 12V/Solar status via SRNE controller~~
1. ~~Log 72V status via JBD BMS~~
1. ~~Real-time web dashboard & terminal monitor~~
1. ~~Continuous telemetry logger & time-series database (SQLite WAL)~~
1. ~~Position via RTU / GPS~~
1. Alarms
   - SMS, email
   - low battery (12v, 72v)
   - anchor drag
1. Log 230V status via smart RCBO
1. Connect to motor controller CANBUS
1. Capture SeaTalkNG / NMEA2000 data
   - compass, attitude, accelerometer, etc.
   - GPS & AIS from Cortex
1. Wind instrument
1. Touchscreen display
1. Ultrasonic depth sensor
1. Auto-helm
