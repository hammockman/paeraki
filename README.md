# paeraki

Ship computer and telemetry monitoring system for yacht *Paeraki*.

```mermaid
graph TD
    subgraph Paeraki Yacht [Onboard Yacht Paeraki]
        SRNE[12V Solar Controller] -->|BLE Modbus| Look[look 192.168.1.100 / .101]
        JBDBMS[72V JBD BMS] -->|BLE GATT| Look
        Fridge[Brass Monkey 35L Fridge] -->|BLE GATT 5-min Poll| LookFridge[watch_fridge.service on look]
        RUTGPS[Teltonika RUT955 GPS] -->|NMEA TCP :8500| LookGPS[watch_gps.service on look]

        subgraph SeaTalkNG [SeaTalkNG / NMEA 2000 Backbone]
            EV1[Raymarine EV-1 0xCC\nHeading, Attitude & ROT] -->|CAN 250k| CAN115[PUSR USR-CAN115\n192.168.174.10]
            Cortex[Vesper Cortex 0x16\nGNSS, AIS & Barometer] -->|CAN 250k| CAN115
            ACU[Raymarine ACU / p70 0x00\nAutopilot Mode & Rudder] -->|CAN 250k| CAN115
        end

        CAN115 -->|TCP :8234 eth0| LookSTNG[paeraki_seatalkng.service on look]

        LookGPS -->|Publish paeraki/gps/state, gps/*| RUTBroker[Teltonika RUT955 Broker 192.168.1.1:1883]
        Look -->|Publish 12v/*, 72v/*| RUTBroker
        LookFridge -->|Publish paeraki/fridge/state| RUTBroker
        LookSTNG -->|Publish paeraki/seatalkng/*| RUTBroker
        CortexHub[Vesper Cortex M1 Hub] -->|TCP / WebSocket :8000| LookCortex[watch_cortex.service on look]
        LookCortex -->|Publish paeraki/cortex/*| RUTBroker
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
- **Navigation & Dual GPS Sources (SeaTalkNG & RUT955)**:
  - Selectable GNSS receiver: **SeaTalkNG (Vesper Cortex)**, **Router (RUT955)**, or **Both (Side-by-Side Comparison)**.
  - High-precision 10 Hz Cortex navigation with 15+ satellites, sub-meter HDOP (0.49), and centimeter geodetic altitude.
  - SOG in knots (primary), km/h, and m/s velocity conversions; COG in degrees True with cardinal orientation.
  - Dual-receiver comparison table calculating geodetic displacement $\Delta\text{ meters}$ between antenna locations.
  - Nautical coordinates (`dd° mm.mmm' S/E`), decimal coordinates, and direct OpenStreetMap charting links.
- **SeaTalkNG Vessel Dynamics & Heading (Raymarine EV-1)**:
  - 10 Hz Raymarine fluxgate compass: Magnetic Heading, True Heading, and local magnetic variation (`24.9° E`).
  - Rate of Turn (°/s) and dynamic rudder position angle.
  - Dynamic horizontal level meters for **Pitch** (-15° to +15° bow down/up) and **Roll** (-30° to +30° port/stbd list) with center-zero lines.
  - Real-time Raymarine autopilot status badge (`AUTO TRACK`, `WIND`, `STANDBY`).
- **AIS Traffic Directory & Transponder Status (Vesper Cortex)**:
  - Paeraki transponder health card: Vesper Cortex Class B SOTDMA status (`ONLINE • SOTDMA`, `Transmitting & Receiving`), active target count, and range to closest vessel.
  - Vessel directory sorted by distance from Paeraki (**closest first**) with geodetic range (NM) and initial bearing (° True).
  - High-visibility amber badges (`UNKNOWN VESSEL`) and left-accented borders for vessels without a broadcasted name.
  - Target filtering pills: `All (N)`, `Unknown (N)`, and `Named (N)`.
- **Atmospheric Barometer (Misc Tab)**:
  - Clean atmospheric pressure display in **`hPa` only** (e.g. `1012.9 hPa`) from the Vesper Cortex solid-state sensor (`PGN 130314`).
  - Barometric pressure tendency indicator (`STEADY`, `RISING`, `FALLING`).
- **72V Propulsion Battery (JBD BMS)**:
  - Compact horizontal State of Charge (SoC %) bar with Tri-Method comparison (Integrated Coulomb counter, Voltage OCV curve, BMS reported).
  - Pack voltage (V), current (A, dynamic charging/discharging mode), and net power (W/kW).
  - Cycle count, residual capacity (Ah), MOSFET switches (CHG/DSG), and temperatures.
  - **20-Cell Voltage Spectrum Visualizer**: Dynamic bar graph displaying all 20 individual cell voltages with min, max, and delta (mV) metrics.
- **12V House & Solar System (SRNE/Renogy)**:
  - House battery voltage with horizontal progress indicator.
  - Solar PV generation power (W), PV voltage, and current.
  - Charge controller state (`MPPT Bulk Charging`, `Float`) and daily yield (kWh).
  - Live Modbus register explorer displaying all incoming 12V keys.
  - **Brass Monkey 35L Dual-Zone Fridge**: Dual-compartment temperatures (current vs target setpoint), compressor status (`Idle`/`Running`), input supply voltage, run mode (`Eco`/`Max`), and battery cutout protection level.
- **Live MQTT Stream Inspector**:
  - Auto-scrolling filterable log table displaying incoming vessel packets across topic `#`.
  - Quick filters for **All**, **72V**, **12V**, **GPS**, **SeaTalkNG**, and **Other**.
  - Pause auto-scroll and clear buffer controls.
- **Vesper Cortex M1 Safety & Emergency Controls**:
  - **Man Overboard (MoB) Emergency Action**: A prominent, protected MoB button on the primary **Home** tab allows instant emergency triggering. Activating MoB logs the current high-precision GPS fix as an emergency waypoint, sounds vessel sirens, and broadcasts an active alert banner with coordinates across all connected dashboards.
  - **Anchor Watch Card**: Displays real-time anchor drop coordinates, drift distance from drop point, safe swing radius, and drag alarm status on the GPS/Navigation tab.
  - **Per-Alarm Silencing**: Any active Cortex hub alert (collision risk, anchor drag, sensor failure) can be acknowledged and silenced directly from the alarm banner by authorized controllers.
- **Role-Based Device Authorization & Control Security**:
  - **Default Read-Only (`VIEWER`) Access**: Any mobile phone, tablet, or laptop connecting to the boat Wi-Fi can immediately monitor real-time vessel telemetry without requiring credentials.
  - **Control Role Elevation (`CONTROLLER`)**: Control endpoints (such as battery SOC calibration, remote alarm silencing, and vessel emergency controls) require `CONTROLLER` authorization via FastAPI dependency `require_control_auth`.
  - **Skipper PIN**: Entering the vessel Skipper PIN (default `1234` or configured via `PAERAKI_SKIPPER_PIN` environment variable) verifies against a salted SHA-256 hash and issues a 256-bit bearer token saved to `localStorage`.
  - **Console Pairing Approval**: Mobile devices can submit a pairing request from the UI, which can be approved from an authorized helm console.
  - **Persistent Registry**: Approved devices and tokens persist in `data/authorized_devices.json`.
  - **Responsive UI**: Header lock indicator (`🔒 Read-Only` / `🔓 Controller`) and modal dialog supporting both Dark and Daylight/Sunlight themes.

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
- **Multi-Layer Schema**:
  1. **`packets` table**: Verbatim archive of all raw messages (`id`, `timestamp`, `epoch_ms`, `topic`, `payload`, `is_json`), including all individual SeaTalkNG PGN frames.
  2. **`telemetry_seatalkng` table**: High-rate navigation, EV-1 attitude, heading, and barometer (`heading_deg`, `heading_ref`, `variation_deg`, `pitch_deg`, `roll_deg`, `yaw_deg`, `rate_of_turn_dps`, `rudder_deg`, `pressure_hpa`, `pilot_mode`, `latitude`, `longitude`, `sog_knots`, `cog_true`, `satellites`, `hdop`, `altitude_m`, `ais_target_count`).
  3. **`telemetry_ais` table**: Real-time directory of all AIS vessels in VHF range (`mmsi`, `vessel_name`, `call_sign`, `ship_type`, `ais_class`, `latitude`, `longitude`, `sog_knots`, `cog_true`, `true_heading`, `nav_status`, `range_nm`, `bearing_deg`).
  4. **`telemetry_72v` table**: Structured propulsion data (`total_voltage`, `current`, `power`, `rsoc`, `cell_min_v`, `cell_max_v`, `cell_delta_mv`, `cell_voltages_json`, etc.).
  5. **`telemetry_12v` table**: Structured house & solar data (`battery_voltage`, `battery_soc`, `solar_power`, `solar_voltage`, `solar_current`, `daily_yield_kwh`, `charging_status`).
  6. **`telemetry_fridge` table**: Structured dual-zone refrigeration telemetry (`left_temp`, `left_target`, `right_temp`, `right_target`, `voltage`, `compressor_running`, `run_mode`, `battery_saver`, `powered_on`).
  7. **Views**: `v_recent_seatalkng`, `v_recent_ais`, `v_recent_72v`, `v_recent_12v`, `v_recent_fridge`, `v_recent_packets`.

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

# Query recent SeaTalkNG dynamics & attitude
df_stng = pd.read_sql("SELECT timestamp, heading_deg, pitch_deg, roll_deg, pilot_mode FROM telemetry_seatalkng ORDER BY epoch_ms DESC LIMIT 10", conn)
print(df_stng)

# Query nearby AIS vessels ordered by distance
df_ais = pd.read_sql("SELECT mmsi, vessel_name, ais_class, range_nm, bearing_deg, sog_knots FROM telemetry_ais ORDER BY range_nm ASC LIMIT 10", conn)
print(df_ais)
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
df_stng <- dbGetQuery(con, "SELECT timestamp, heading_deg, pitch_deg, roll_deg FROM telemetry_seatalkng ORDER BY epoch_ms DESC LIMIT 20")
summary(df_stng)
```

#### Julia (SQLite.jl / DataFrames.jl)
```bash
# Run bundled Julia script:
julia logger/examples/query_julia.jl
```
```julia
using SQLite, DataFrames

db = SQLite.DB("data/paeraki.db")
df = DBInterface.execute(db, "SELECT timestamp, heading_deg, pitch_deg, roll_deg, pressure_hpa FROM telemetry_seatalkng ORDER BY epoch_ms DESC LIMIT 20") |> DataFrame
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

---

## 5. SeaTalkNG & NMEA 2000 Bus Capture (PUSR USR-CAN115 & look)

Paeraki's **SeaTalkNG (NMEA 2000)** backbone carries critical vessel heading, vessel attitude, rate of turn, rudder feedback, high-rate GNSS navigation, AIS target tracking, and barometric pressure.

The telemetry capture daemon (`paeraki_seatalkng.service`) runs on the single-board computer **`look`**, ingesting raw CAN 2.0B frames from an Ethernet-to-CAN converter, decoding standard and proprietary PGNs, and streaming real-time JSON packets over MQTT to the broker (`192.168.1.1:1883`).

```
[Raymarine EV-1 (0xCC)] ──┐
                          ├─► [SeaTalkNG Backbone (250 kbps)] ──► [PUSR USR-CAN115]
[Vesper Cortex (0x16)]  ──┤                                              │ (CAN-over-TCP: 8234)
                          │                                              ▼
[Raymarine ACU (0x00)]  ──┘                                        [eth0 on look]
                                                                         │
                                                                         ▼
                                                            [paeraki_seatalkng.service]
                                                                         │
                                                ┌────────────────────────┴────────────────────────┐
                                                ▼                                                 ▼
                                  [paeraki/seatalkng/state]                          [paeraki/seatalkng/pgn/*]
                                  (10 Hz Consolidated Snapshot)                      (Universal Frame Stream)
                                                │                                                 │
                                                └────────────────────────┬────────────────────────┘
                                                                         ▼
                                                          [Mosquitto Broker 192.168.1.1]
                                                                         │
                                                ┌────────────────────────┴────────────────────────┐
                                                ▼                                                 ▼
                                   [Web Dashboard & Android App]                     [paeraki_logger on hammer]
                                   (:8080 on look / APK)                             (data/paeraki.db SQLite WAL)
```

---

### Hardware Interface & Network Configuration

- **Hardware Converter**: **PUSR USR-CAN115** bidirectional Ethernet-to-CAN converter.
- **Physical Bus**: NMEA 2000 / SeaTalkNG micro-C spur connection, differential CAN signaling at **250 kbps**, 120 Ω bus termination.
- **Converter Network Config**:
  - IP: `192.168.174.10/24`
  - Operating Mode: **TCP Client**
  - Destination Target: `192.168.1.108:8234`
- **SBC `look` Interface Config (`eth0`)**:
  - Configured in NetworkManager with dual IP assignment to establish direct connectivity to the converter:
    - Primary IP: `192.168.174.1/24`
    - Secondary Alias IP: `192.168.1.108/32`
    - Gateway: None (isolated CAN telemetry segment, preserving `lan0` default routing to the router).
    - `connection.autoconnect yes`
  - `paeraki_seatalkng.service` binds a TCP server to `0.0.0.0:8234` and auto-reconnects when frames arrive.

---

### CAN 2.0B Frame Protocol & Packet Format

The PUSR USR-CAN115 streams CAN 2.0B Extended Frames across TCP port 8234. Each frame consists of a frame header, a 29-bit CAN identifier, and up to 8 bytes of data payload:

```
┌─────────────┬───────────────────────────┬─────────────────────────────────┐
│ Byte 0      │ Bytes 1 - 4               │ Bytes 5 .. 5+DLC                │
│ Frame Info  │ 29-bit CAN Identifier     │ Data Payload (0 to 8 bytes)     │
└─────────────┴───────────────────────────┴─────────────────────────────────┘
```

#### 1. Frame Info Byte (Byte 0)
- **Bit 7 (`FF`)**: Frame Format (`1` = Extended 29-bit CAN 2.0B, `0` = Standard 11-bit).
- **Bit 6 (`RTR`)**: Remote Transmission Request (`0` = Data frame).
- **Bits 3-0 (`DLC`)**: Data Length Code (number of payload bytes, `0` to `8`).

#### 2. 29-Bit Extended CAN Identifier (Bytes 1 - 4)
The 29-bit CAN ID maps directly to the SAE J1939 / NMEA 2000 address and parameter scheme:

```
Bits: 28 ── 26 | 25 | 24 | 23 ────────── 16 | 15 ────────── 8 | 7 ────────── 0
Field:  Prio   | ED | DP |  PDU Format (PF) | PDU Specific(PS)|  Source (SA)
```
- **Priority** (3 bits, 28-26): Message bus arbitration priority (`0` = highest, `7` = lowest).
- **Extended Data Page / ED** (bit 25): Reserved (`0`).
- **Data Page / DP** (bit 24): Parameter page selector.
- **PDU Format / PF** (8 bits, 23-16): Parameter Group identifier.
- **PDU Specific / PS** (8 bits, 15-8):
  - If `PF < 240` (PDU1 - Addressable): `PS` specifies the **Destination Address** (`DA`).
  - If `PF >= 240` (PDU2 - Broadcast): `PS` specifies the **Group Extension** (`GE`).
- **Source Address / SA** (8 bits, 7-0): Address of the transmitting hardware device.
- **Parameter Group Number (PGN)** calculation:
  $$\text{PGN} = (\text{DP} \ll 16) | (\text{PF} \ll 8) | (\text{PS if PF} \ge 240 \text{ else } 0)$$

#### 3. Fast Packet Protocol Reassembly
NMEA 2000 messages exceeding 8 bytes (e.g. `PGN 129029` GNSS position, `PGN 129038` AIS Class A, `PGN 129809` vessel names) use the NMEA 2000 Fast Packet protocol:
- **Byte 0**: Protocol Header containing:
  - **Bits 7-5**: Sequence Counter (0 to 7, grouping multi-packet streams).
  - **Bits 4-0**: Frame Counter (`0x00` = First Frame, `0x01..0x1F` = Consecutive Frames).
- **First Frame (`Frame Counter == 0`)**:
  - Byte 1: Total payload length in bytes ($N$).
  - Bytes 2-7: Initial 6 bytes of payload data.
- **Consecutive Frames (`Frame Counter >= 1`)**:
  - Bytes 1-7: Next 7 sequential bytes of payload data.
- `seatalkng/decoder.py` maintains state machines keyed by `(Source, PGN, Sequence)` with a 500 ms reassembly timeout to reliably reassemble fast packet sequences without packet loss.

---

### Onboard SeaTalkNG Devices

| Source Address | Device | Location | Key Telemetry Broadcasted |
| :---: | :--- | :--- | :--- |
| **`0xCC`** (204) | **Raymarine EV-1 Sensor Core** | Bilge (vessel centerline) | 10 Hz Heading, 10 Hz Pitch/Roll/Yaw, 10 Hz Rate of Turn, 20 Hz Rudder Angle, Magnetic Variation |
| **`0x16`** (22) | **Vesper Cortex Class B SOTDMA** | Cabin Wall Mount | 10 Hz GNSS Navigation (Position, SOG, COG, Sats, HDOP), Class A & B AIS reports, Barometer |
| **`0x00`** (0) | **Raymarine ACU / p70 Autopilot** | Helm / Cockpit | Autopilot Operating Mode (`Wind`, `Auto`, `Track`, `Standby`), Rudder Command |

---

### CAN Bus PGN Packet Reference & Decoding Specification

Every packet appearing on Paeraki's SeaTalkNG backbone is decoded and published. The table below details all active PGNs, frame types, rates, source devices, and decoded data fields:

| PGN | Name | Type | Rate | Source | Decoded Fields & Resolution |
| :---: | :--- | :---: | :---: | :---: | :--- |
| **`129025`** | **Position, Rapid Update** | Single | 10 Hz | Cortex (`0x16`) | `latitude` (deg, $10^{-7}$), `longitude` (deg, $10^{-7}$) |
| **`129026`** | **COG & SOG, Rapid Update** | Single | 10 Hz | Cortex (`0x16`) | `sog_knots` (m/s $\to$ kts, res 0.01 m/s), `cog_true` (rad $\to$ deg, res $10^{-4}$ rad) |
| **`129029`** | **GNSS Position Data** | Fast | 1 Hz | Cortex (`0x16`) | Full fix: Date/Time UTC, `latitude`, `longitude`, `altitude_m` ($10^{-6}$ m), `satellites` (count), `hdop` (res 0.01), `pdop`, `fix_type` |
| **`127250`** | **Vessel Heading** | Single | 10 Hz | EV-1 (`0xCC`) | `heading_deg` (rad $\to$ deg, res $10^{-4}$ rad), `heading_reference` (`Magnetic` / `True`), `variation_deg` ($10^{-4}$ rad) |
| **`127251`** | **Rate of Turn** | Single | 10 Hz | EV-1 (`0xCC`) | `rate_of_turn_dps` (rad/s $\to$ °/s, res $3.125 \times 10^{-5}$ rad/s) |
| **`127257`** | **Attitude** | Single | 10 Hz | EV-1 (`0xCC`) | `yaw_deg` ($10^{-4}$ rad), `pitch_deg` ($10^{-4}$ rad, bow $+$/$-$), `roll_deg` ($10^{-4}$ rad, stbd $+$, port $-$) |
| **`127258`** | **Magnetic Variation** | Single | 1 Hz | EV-1 (`0xCC`) | `variation_deg` (rad $\to$ deg, local NZ variation $+24.9^\circ\text{ E}$) |
| **`127245`** | **Rudder** | Single | 20 Hz | ACU (`0x00`) / EV-1 | `rudder_deg` (rad $\to$ deg, port/stbd angle), `rudder_order_deg` |
| **`129038`** | **AIS Class A Position Report** | Fast | Event | Cortex (`0x16`) | `mmsi`, `latitude`, `longitude`, `sog_knots`, `cog_true`, `true_heading`, `nav_status` (Underway, Moored, At Anchor), `rate_of_turn_dps` |
| **`129039`** | **AIS Class B Position Report** | Fast | Event | Cortex (`0x16`) | `mmsi`, `latitude`, `longitude`, `sog_knots`, `cog_true`, `true_heading` |
| **`129809`** | **AIS Class B Static Data Part A** | Fast | Event | Cortex (`0x16`) | `mmsi`, `vessel_name` (ASCII decoded vessel broadcast name) |
| **`129810`** | **AIS Class B Static Data Part B** | Fast | Event | Cortex (`0x16`) | `mmsi`, `call_sign`, `ship_type`, length, beam, dimensions |
| **`130314`** | **Actual Pressure (Barometer)** | Single | 1 Hz | Cortex (`0x16`) | `pressure_hpa` (Pascals $\to$ hPa, res 100 Pa, Vesper Cortex atmospheric sensor) |
| **`65379`** | **Raymarine Autopilot Mode** | Single | 1 Hz | ACU (`0x00`) / EV-1 | Raymarine proprietary pilot state: `Wind`, `Track`, `Auto`, `Standby` |
| **`126208`** | **NMEA Request / Ack Group** | Single | Event | Any | Bus control commands and acknowledgments |
| **`126996`** | **Product Information** | Fast | Event | Any | Model ID, software version, hardware serial number |

---

### Detailed Packet Breakdown

#### 1. PGN 127250: Vessel Heading (10 Hz from Raymarine EV-1)
```text
Byte 0:    SID (Sequence ID)
Bytes 1-2: Heading Angle (unsigned 16-bit, Little Endian, res: 0.0001 rad, 0 to 2*PI)
Bytes 3-4: Deviation (signed 16-bit, Little Endian, res: 0.0001 rad)
Bytes 5-6: Variation (signed 16-bit, Little Endian, res: 0.0001 rad, + = East, - = West)
Byte 7:    Heading Reference (bits 0-1: 0 = True, 1 = Magnetic, 2 = Error, 3 = Null)
```

#### 2. PGN 127257: Attitude Dynamics (10 Hz from Raymarine EV-1)
```text
Byte 0:    SID (Sequence ID)
Bytes 1-2: Yaw Angle (signed 16-bit, Little Endian, res: 0.0001 rad, -PI to +PI)
Bytes 3-4: Pitch Angle (signed 16-bit, Little Endian, res: 0.0001 rad, + = Bow Up, - = Bow Down)
Bytes 5-6: Roll Angle (signed 16-bit, Little Endian, res: 0.0001 rad, + = Starboard List, - = Port List)
Byte 7:    Reserved (0xFF)
```

#### 3. PGN 130314: Actual Pressure (1 Hz from Vesper Cortex Barometer)
```text
Byte 0:    SID (Sequence ID)
Byte 1:    Pressure Instance (0 = Atmospheric Barometer)
Byte 2:    Pressure Source (0 = Atmospheric)
Bytes 3-6: Pressure in Pascals (unsigned 32-bit, Little Endian, res: 0.1 Pa or 100 Pa)
           Converted to hPa via: pressure_hpa = raw_val / 100.0
Byte 7:    Reserved (0xFF)
```

#### 4. PGN 65379: Raymarine Proprietary Autopilot State
```text
Bytes 0-1: Raymarine Manufacturer Code (0x003B) & Industry Group (4 = Marine)
Bytes 2-7: Proprietary Mode Payload
           Decodes operating pilot states: Standby, Auto (Heading Hold), Wind Vane Mode, Track
```

---

### Universal Capture Policy & Novel PGN Fallback

To guarantee zero data loss, **every packet arriving on the CAN bus is preserved and published**:
1. **Mapped PGNs**: Decoded into engineering units and published to discrete structured topics.
2. **Novel / Unmapped PGNs**: Published to `paeraki/seatalkng/pgn/<pgn>` with complete raw byte and hexadecimal payloads:
   ```json
   {
     "pgn": 126208,
     "name": "NMEA Request / Command / Acknowledge Group Function",
     "src": 0,
     "prio": 3,
     "len": 8,
     "timestamp": "2026-09-15T01:14:16.077856+00:00",
     "decoded": false,
     "hex": "6350ffffffffffff",
     "bytes": [99, 80, 255, 255, 255, 255, 255, 255]
   }
   ```
3. **Live Bus Catalog (`paeraki/seatalkng/catalog`)**: Published every 5 seconds, providing an active inventory of every PGN on the bus, total frame count, real-time message frequency (Hz), and sending source addresses.

---

### Published MQTT Topics

| Topic | Frequency | Description |
| :--- | :---: | :--- |
| **`paeraki/seatalkng/state`** | 10 Hz | Consolidated telemetry snapshot (Lat, Lon, SOG, COG, Heading, Pitch, Roll, ROT, Rudder, Barometer, Sats, HDOP, AIS count). |
| **`paeraki/seatalkng/gps`** | 10 Hz | High-precision Cortex GNSS fix, nautical coordinates, velocity conversions, satellite count, and dilution of precision. |
| **`paeraki/seatalkng/heading`** | 10 Hz | Raymarine EV-1 fluxgate compass: Magnetic Heading, True Heading, local variation, Cardinal direction, Rate of Turn, and Rudder angle. |
| **`paeraki/seatalkng/attitude`** | 10 Hz | Vessel attitude dynamics: Pitch (°), Roll (°), Yaw (°), Rate of Turn (°/s), and active Autopilot Mode. |
| **`paeraki/seatalkng/environment`** | 1 Hz | Atmospheric pressure in **hPa** from the Cortex solid-state barometer. |
| **`paeraki/seatalkng/ais/targets`** | 1 Hz | Array of all active AIS vessels detected in VHF range, sorted by geodetic range (**closest first**). |
| **`paeraki/seatalkng/ais/target/<mmsi>`** | Event | Individual vessel updates including MMSI, vessel name, range (NM), bearing (°), SOG, COG, status, and class. |
| **`paeraki/seatalkng/pgn/<pgn>`** | Stream | Granular feed for every individual PGN broadcast on the SeaTalkNG bus. |
| **`paeraki/seatalkng/catalog`** | 0.2 Hz | Comprehensive bus directory of all active PGNs, rates (Hz), source addresses, and latest frame payloads. |

---

### SeaTalkNG CLI Monitor & Service Management

#### 1. Interactive Terminal Monitor
You can inspect the live SeaTalkNG bus directly in your terminal on `look` or over SSH from `hammer`:
```bash
# Rich terminal dashboard displaying heading, attitude, navigation, and closest AIS vessels
ssh look "python3 ~/paeraki/seatalkng/cli.py"

# Raw CAN frame stream showing 29-bit CAN IDs, PGNs, and hex byte dumps
ssh look "python3 ~/paeraki/seatalkng/cli.py --raw"
```

#### 2. Service Management on `look`
The daemon runs as a continuous systemd background service:
```bash
# Check service status
ssh look "systemctl status paeraki_seatalkng.service"

# Stream live service logs
ssh look "journalctl -u paeraki_seatalkng.service -f"

# Restart daemon after updates
ssh look "sudo systemctl restart paeraki_seatalkng.service"
```

---

## 6. Brass Monkey Dual-Zone Fridge Monitoring (`watch_fridge.service`)

The onboard 35-liter Brass Monkey dual-zone fridge/freezer is monitored over Bluetooth Low Energy (BLE) by `watch_fridge.service` running on `look`.

### Hardware & Protocol
- **Device**: Brass Monkey 35L Dual-Zone Refrigerator / Freezer (OEM Alpicool controller).
- **BLE Identifier**: MAC `FF:FF:11:73:D1:71` (`A1-FFFF1173D171`).
- **GATT Interface**:
  - Service: `00001234-0000-1000-8000-00805f9b34fb`
  - Command (Write): `00001235-0000-1000-8000-00805f9b34fb`
  - Notification (Read): `00001236-0000-1000-8000-00805f9b34fb`
- **Framing**: Binary packets framed with `0xFE 0xFE`, length byte, command byte, payload, and a 16-bit big-endian checksum of all preceding bytes.

### Operating Strategy: Periodic Connect-Poll-Disconnect
Because the Alpicool controller allows only one active BLE client at a time and ceases advertising while connected, `watch_fridge.service` operates in **periodic connect-poll-disconnect mode** by default:
1. Every **5 minutes** (`--interval 300.0`), the daemon establishes a BLE connection to the fridge (~1.9 s).
2. It sends a query packet (`0xFE 0xFE 0x03 0x01 0x02 0x00`), awaits the notification frame, and decodes telemetry.
3. It publishes the readings to the Paeraki MQTT broker.
4. It immediately disconnects, freeing the Bluetooth link so mobile apps (Brass Monkey / Alpicool) can connect without service interference.

### Published MQTT Topics
| Topic | Payload | Description |
|---|---|---|
| `paeraki/fridge/state` | JSON | Complete telemetry snapshot (temperatures, setpoints, voltage, modes) |
| `paeraki/fridge/left/temperature` | Float/Int | Left zone current temperature (°C) |
| `paeraki/fridge/left/target` | Float/Int | Left zone target setpoint (°C) |
| `paeraki/fridge/right/temperature` | Float/Int | Right zone current temperature (°C) |
| `paeraki/fridge/right/target` | Float/Int | Right zone target setpoint (°C) |
| `paeraki/fridge/voltage` | Float | Terminal input voltage (V) |
| `paeraki/fridge/compressor` | `0` or `1` | Compressor operating status (`0`=Idle, `1`=Running) |
| `paeraki/fridge/mode` | `Eco` or `Max` | Energy mode |

### Managing `watch_fridge.service` on `look`
The daemon runs as a continuous systemd service on `look`:

```bash
# Check service status
ssh look "systemctl status watch_fridge.service"

# Follow live service logs
ssh look "journalctl -u watch_fridge.service -f"

# Restart service after code updates
ssh look "sudo systemctl restart watch_fridge.service"

# Manual one-shot test
ssh look "uv run --python /home/jh/paeraki/.venv /home/jh/paeraki/fridge/watch.py --broker 192.168.1.1 --once"
```

---

## 7. Vesper Cortex M1 Hub Integration & Safety Controls (`watch_cortex.service`)

The onboard **Vesper Cortex M1 Hub** (VHF/AIS/Anchor Watch/Safety transponder) connects to the vessel network and provides bidirectional telemetry and alarm control via `watch_cortex.service` running on `look`.

### Features
- **Dynamic Discovery**: Automatically discovers the Cortex hub on the boat LAN via mDNS / UDP broadcast with automatic fallback to static IP (`192.168.1.50`).
- **Telemetry Streaming**: Subscribes to the Cortex internal WebSocket interface on port `8000`, receiving real-time anchor watch coordinates, drift distance, safe swing radius, active alarms (CPA collision risk, anchor drag), battery voltage, and barometric pressure.
- **Per-Alarm Silencing**: Authorized controllers can temporarily silence or acknowledge alarms directly from the dashboard via MQTT topic `paeraki/cortex/command`.
- **Man Overboard (MoB) Protection**: The dashboard emergency action button on the Home tab broadcasts MoB alerts to `paeraki/cortex/mob/alert`, logs emergency GPS fix coordinates, and formats NMEA 2000 / SeaTalkNG alert frames (`PGN 127233` and `PGN 126983`).

### Published MQTT Topics
| Topic | Payload | Description |
|---|---|---|
| `paeraki/cortex/anchor` | JSON | Anchor watch state (`active`, `anchor_lat`, `anchor_lon`, `radius_m`, `distance_m`, `drag_alarm`) |
| `paeraki/cortex/alarms` | JSON | Active alarms list (`id`, `type`, `severity`, `message`, `silenced`, `silenceable`) |
| `paeraki/cortex/telemetry` | JSON | Cortex system telemetry (`battery_v`, `pressure_hpa`, `host`, `port`) |
| `paeraki/cortex/mob/alert` | JSON | Emergency Man Overboard state (`active`, `latitude`, `longitude`, `timestamp`, `source`) |
| `paeraki/cortex/command` | JSON | Inbound control commands (`silence`, `mob`, `mob_cancel`, `set_anchor_watch`) |

### Managing `watch_cortex.service` on `look`
The daemon runs as a continuous systemd service on `look`:

```bash
# Check service status
ssh look "systemctl status watch_cortex.service"

# Follow live service logs
ssh look "journalctl -u watch_cortex.service -f"

# Restart service after code updates
ssh look "sudo systemctl restart watch_cortex.service"

# Manual test with mock data
uv run python cortex/watch.py --mock --broker 192.168.1.1
```

---

## 8. Development & Deployment Workflow

Development takes place locally on `hammer` and changes are synced directly to `look`:

```bash
# Sync local changes to look (ignoring .venv, git, and local database files)
REMOTE_HOST=jh@192.168.1.100 ./sync.sh

# Sync and restart services on look:
REMOTE_HOST=jh@192.168.1.100 ./sync.sh "sudo systemctl restart paeraki_seatalkng watch_fridge watch_cortex paeraki_dashboard"
```

---

## Roadmap

1. ~~Set up VPN~~
1. ~~Log 12V/Solar status via SRNE controller~~
1. ~~Log 72V status via JBD BMS~~
1. ~~Real-time web dashboard & terminal monitor~~
1. ~~Continuous telemetry logger & time-series database (SQLite WAL)~~
1. ~~Position via RTU / GPS~~
1. ~~Capture SeaTalkNG / NMEA2000 data~~
   - ~~compass, attitude, accelerometer, etc.~~
   - ~~GPS & AIS from Cortex~~
1. ~~Log Brass Monkey Dual-Zone Fridge via BLE (`watch_fridge.service`)~~
1. ~~Vesper Cortex M1 Hub telemetry & safety control (`watch_cortex.service`)~~
   - ~~Remote alarm silencing & per-alarm acknowledgement~~
   - ~~Anchor watch monitoring card~~
   - ~~Emergency Man Overboard (MoB) trigger on Home tab~~
1. Alarms
   - SMS, email
   - low battery (12v, 72v)
   - anchor drag
1. Log 230V status via smart RCBO
1. Connect to motor controller CANBUS
1. Wind instrument
1. Touchscreen display
1. Ultrasonic depth sensor
1. Auto-helm

