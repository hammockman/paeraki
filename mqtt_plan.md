# Out-of-Band MQTT Egress Architecture & Implementation Plan (`mqtt_plan.md`)

**Status**: PARKED / READY FOR PROVISIONING  
**Vessel**: Yacht Paeraki  
**Primary Target Device**: Teltonika RUT955 Router (`192.168.1.1`, RutOS 7)  
**Companion Nodes**: `sing` (Raspberry Pi 4B, `192.168.1.x`), `look` (Orange Pi R1 Plus, `192.168.1.100`)

---

## 1. Objective & Problem Statement

Yacht Paeraki's primary off-boat telemetry link relies on a WireGuard site-to-site VPN tunnel (`10.6.0.2` $\leftrightarrow$ `10.6.0.1`) terminating at the home ASUS router and workstation (`hammer`, `192.168.50.89`).

However, during offshore voyages, home internet disruptions, home WAN IP shifts, or WireGuard daemon dropouts, the VPN tunnel becomes unavailable. The onboard **Teltonika RUT955 4G cellular connection** (via Spark NZ) remains functional, but local telemetry cannot egress without a dedicated out-of-band path.

The goal of this plan is to enable **out-of-band transmission of critical vessel telemetry, alarms, and periodic heartbeats** to an external endpoint directly over cellular WAN **without requiring the WireGuard VPN link**.

---

## 2. Architectural Overview

```
 ┌────────────────────────────────────────────────────────┐
 │                   ONBOARD VESSEL LAN                   │
 │                                                        │
 │  [ look / sing Services ]                              │
 │   - cortex/watch.py        (Alarms, MoB)               │
 │   - alarms/watch.py        (Battery SoC, Bilge)        │
 │   - logger/heartbeat.py    (Hourly Status Digest)      │
 │            │                                           │
 │            ▼ publish to local topics                   │
 │  [ Local MQTT Broker (sing / look:1883) ]              │
 │            │                                           │
 └────────────┼───────────────────────────────────────────┘
              │ Local bridge or direct publish
              ▼
 ┌────────────────────────────────────────────────────────┐
 │             TELTONIKA RUT955 (192.168.1.1)             │
 │                                                        │
 │  [ RUT955 Mosquitto Outbound Bridge ]                  │
 │   - Subscribes: paeraki/outbound/#                     │
 │   - Queueing: Persistent local spool on flash / USB    │
 │   - Egress: Spark 4G Cellular Interface (qmimux0)      │
 │   - Packet Mangling: TTL=64 (Spark portal bypass)      │
 └────────────┬───────────────────────────────────────────┘
              │
              │ Public Internet / Cellular WAN (TLS :8883)
              │ (Zero VPN dependency)
              ▼
 ┌────────────────────────────────────────────────────────┐
 │                    OUTSIDE WORLD                       │
 │                                                        │
 │  [ Public Secure MQTT Endpoint ]                       │
 │   - Option A: Self-hosted Mosquitto (mqtt.aliente.ch)  │
 │   - Option B: AWS IoT Core or HiveMQ Cloud             │
 │            │                                           │
 │            ▼                                           │
 │  [ Ingestion, Alerting, & Remote Monitoring ]          │
 │   - Telegram / Pushover / SMS / Phone Push Alerts      │
 │   - Remote Historian Mirror (cloud database)           │
 └────────────────────────────────────────────────────────┘
```

---

## 3. Scope of Outbound Messages (Bandwidth Preservation)

Offshore cellular data is metered and precious. Raw high-frequency sensor streams (e.g. 1 Hz battery, GPS, or SeaTalkNG CAN frames) **must NOT** be forwarded over this bridge.

Only two categories of payloads are routed to `paeraki/outbound/`:

### A. Critical Event Alarms (Immediate, QoS 1)
* **Man Overboard (MoB)**: Active waypoint drop, GPS coordinates, timestamp (`paeraki/cortex/mob/alert`).
* **Vesper Cortex Marine Alarms**: Collision risk (CPA/TCPA), anchor drag (`paeraki/cortex/alarms/active`).
* **Power Criticals**: 12V house battery $< 40\%$ SoC or $< 11.8\text{ V}$, 72V propulsion pack low voltage or cell delta spike.
* **Hull Safety**: Bilge pump continuous run exceeding 60s, high water sensor trigger.

### B. Hourly Status Heartbeat (Compressed JSON, QoS 0/1)
* Published every 60 minutes while underway or anchored.
* Format: Compact JSON (~250 bytes) containing:
  ```json
  {
    "v": "paeraki",
    "ts": "2026-09-23T13:30:00Z",
    "lat": -41.2865,
    "lon": 174.7762,
    "sog": 5.2,
    "cog": 182.0,
    "b12_v": 13.2,
    "b12_soc": 88.5,
    "b72_v": 78.4,
    "b72_soc": 91.0,
    "fridge_t": 4.5,
    "status": "OK"
  }
  ```

---

## 4. Implementation Options

### Option 1 (Primary / Recommended): RUT955 Mosquitto Outbound Bridge

Because the RUT955 runs Mosquitto, configuring it as an outbound bridge to a remote broker is the cleanest, most resilient solution.

#### 1. Configuration File: `/etc/mosquitto/conf.d/bridge_outbound.conf`
```conf
# Paeraki Out-of-Band Cellular Egress Bridge
connection paeraki_cloud_bridge
address <public-endpoint.domain.com>:8883

# Outbound mapping: Map local paeraki/outbound/# to remote paeraki/vessel/#
topic # out 1 paeraki/outbound/ paeraki/vessel/

# Credentials & TLS
remote_clientid paeraki-rut955-egress
remote_username paeraki_vessel
remote_password <secure_cloud_token>
bridge_cafile /etc/ssl/certs/ca-certificates.crt
bridge_insecure false

# Resilience & Offline Queueing
cleansession false
start_type automatic
notifications true
notification_topic paeraki/vessel/bridge/state
restart_timeout 20 120

# Local persistence during cellular dead zones
max_queued_messages 1000
```

#### 2. Why this is superior:
* **Automatic Offline Buffering**: If the vessel sails out of cellular range, Mosquitto stores QoS 1 alert messages on the router. As soon as a 4G tower connects, all queued messages flush immediately.
* **Separation of Concerns**: Onboard daemons simply publish to `paeraki/outbound/<topic>` on the local broker; they need no internet awareness or cloud credentials.

---

### Option 2 (Secondary / Minimal): RutOS Native "Data to Server"

If custom Mosquitto bridge configuration is not desired on the router:
1. Navigate to RutOS WebUI: **Services → Data to Server**.
2. Add a new server instance:
   * **Format Type**: JSON.
   * **Type**: MQTT (or HTTP POST / Webhook).
   * **Host / Port**: Remote public broker on port 8883.
   * **Source**: MQTT Broker on `localhost` (subscribing to `paeraki/outbound/#`).
3. Advantage: Fully manageable via the WebUI and automatically preserved across router firmware updates and user backup archives.

---

### Option 3 (Application-Level Fallback): Egress Daemon on `sing` with Direct Webhook

If external MQTT broker hosting is deferred:
* Deploy a lightweight daemon (`logger/egress_worker.py`) on `sing`.
* Subscribes to local MQTT for alerts.
* Instead of MQTT, it performs direct HTTPS POST requests via `curl`/`urllib` to:
  * **Telegram Bot API**: Sends instant phone alerts to a private Paeraki Telegram channel.
  * **Pushover / NTFY.sh**: Delivers instant push notifications directly to skipper phones.
* Because it uses outbound HTTPS (:443), it requires no open ports or dedicated MQTT cloud server.

---

## 5. Step-by-Step Execution Plan (When Unparked)

| Step | Task | Location / Machine | Deliverables |
| :---: | :--- | :--- | :--- |
| **1** | **Target Broker Provisioning** | Cloud / External VPS | Setup TLS MQTT listener on port 8883 with username/password ACLs (e.g. `mqtt.aliente.ch` or HiveMQ Cloud free instance). |
| **2** | **Deploy Router Bridge Config** | RUT955 (`192.168.1.1`) | Install `/etc/mosquitto/conf.d/bridge_outbound.conf` with CA certs and restart Mosquitto daemon. |
| **3** | **Add Egress Publisher Hook** | `sing` (`logger/`) | Add an hourly heartbeat cron/timer and route critical alarms from `alarms/watch.py` and `cortex/watch.py` to `paeraki/outbound/`. |
| **4** | **Firewall & TTL Verification** | RUT955 | Ensure cellular TTL normalization (`TTL=64` on `qmimux0`) is verified so egress packets bypass Spark portal redirection. |
| **5** | **Offline Queueing Validation** | Bench / Vessel | Disconnect WAN, publish 3 test alerts, reconnect WAN, and verify messages arrive at the cloud receiver in chronological order. |

---

## 6. Current Status & Parking Notes

* **Status**: **PARKED**
* **Dependencies Required Prior to Resuming**:
  1. Selection/creation of the destination endpoint (self-hosted broker on `aliente.ch`, AWS IoT, or webhook service like Telegram/NTFY).
  2. Provisioning of TLS credentials/tokens for the router.
* **All local vessel telemetry, 3-day buffer logging, dashboard migration to `sing`, audio streaming, and WireGuard networking remain operational and unaffected.**
