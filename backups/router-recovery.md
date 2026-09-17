# Teltonika RUT955 Router Recovery & Recommissioning Playbook

This document details the step-by-step procedure to recover, upgrade, and completely reconfigure the onboard **Teltonika RUT955** router (`192.168.1.1`) for yacht **Paeraki**.

---

## 1. Overview & Recovery Architecture

```
                      ┌─────────────────────────────────────────┐
                      │        Teltonika RUT955 (Paeraki)       │
                      │               192.168.1.1               │
                      │  Hostname: RUT955-Paeraki (RutOS 7)     │
                      └──────┬────────────────────┬─────────────┘
                             │                    │
        Direct NMEA stream   │                    │ WireGuard Site-to-Site VPN
        (TCP/UDP :8500)      │                    │ (Tunnel: 10.6.0.2 -> 10.6.0.1)
                             ▼                    ▼
                ┌────────────────────────┐   ┌──────────────────────────────┐
                │   Raspberry Pi (look)  │   |   Home ASUS Router (RT-AX52) │
                │     192.168.1.100      │   │   Public: 219.89.200.207:51820  │
                │                        │   │   Subnet: 10.6.0.0/24        │
                │  - watch_gps.service   │   └──────────────┬───────────────┘
                │  - MQTT broker :1883   │                  │
                │  - Web Dashboard :8080 │                  ▼
                └────────────────────────┘   ┌──────────────────────────────┐
                                             │   Workstation (hammer)       │
                                             │       192.168.50.89          │
                                             │  - syslog-ng (:514 UDP/TCP)  │
                                             │  - paeraki_logger.service    │
                                             │  - SQLite: data/paeraki.db   │
                                             └──────────────────────────────┘
```

---

## Step 1: Factory Reset / Firstboot

If the router is unresponsive, in a boot loop, or unreachable over the network:

### Option A: Physical Reset Button
1. Power on the router and wait ~1–2 minutes for the LEDs to stabilize.
2. Locate the **Reset** button on the front/side panel (the side with the
   antenna connections, unfortunately it's very hard to get at in the antenna
   housing so you probably need to release the router from its rails)
3. Using a paperclip or SIM pin, press and hold the button:
   * **Hold for 12 to 20 seconds** (the signal strength LEDs will light up sequentially).
   * Release between 12s and 20s to trigger **`firstboot`** (factory default reset).
   *(Note: Holding <6s only reboots; holding 6–11s restores user defaults if configured).*
4. The router will reboot cleanly into factory state (~2 minutes).

### Option B: SMS Command (if cellular link is up)
If the router answers status SMS queries, send:
```text
<router_password> restore
```
*(If password was unchanged from default, `admin01 restore`).*

### Option C: CLI / SSH (if shell access is available)
```bash
firstboot -y && reboot
```

### Option D: Emergency Bootloader (U-Boot) Web Recovery
Use this method if the router is bricked, in an unrecoverable crash loop, or unreachable via normal reset:

1. **Power off** the router (unplug the power connector).
2. **Press and hold the Reset button** with a pin.
3. While holding the Reset button, **plug the power cable back in**.
4. **Hold for 5 to 8 seconds** until all Ethernet/LAN port LEDs start flashing simultaneously, then release the button.
5. **Configure Static IP on PC**:
   * U-Boot's minimal web server has **no DHCP server**.
   * Manually assign your PC's Ethernet interface:
     * **IP Address**: `192.168.1.2` (or `192.168.1.10`)
     * **Subnet Mask**: `255.255.255.0` (`/24`)
     * **Default Gateway**: `192.168.1.1`
6. Connect an Ethernet cable between your PC and **LAN Port 1**.
7. Open a web browser and navigate to **`http://192.168.1.1`** (or `http://192.168.1.1/index.html`). The U-Boot recovery page will load.

> [!WARNING]
> **MUST FLASH RUTOS 6 FIRMWARE IN U-BOOT RECOVERY**:
> The factory `uboot.bin` bootloader on this router has **not** been updated to a RutOS 7-aware version.
> Legacy U-Boot does **not** recognize RutOS 7 partition tables or image structures and will fail/reject RutOS 7 images uploaded through this menu.
> * **You MUST flash a RutOS 6 firmware image** (e.g. `RUT9XX_R_00.06.09.5_WEB.bin` or earlier).
> * Once the router successfully flashes and reboots into RutOS 6, log in and perform the RutOS 7 upgrade via the standard RutOS WebUI (**System → Firmware**) with **"Keep settings: OFF"** as documented in Step 3.

---

## Step 2: Initial Login & Setup

1. Connect your PC directly to LAN port 1, 2, or 3 using an Ethernet cable (or connect to the default Wi-Fi SSID `RUT955_XXXX`).
2. Your PC will receive a DHCP address in `192.168.1.0/24`.
3. Open a browser to `http://192.168.1.1`.
4. **Initial Credentials**:
   * Username: `admin`
   * Password: `admin01`
5. The setup wizard will force you to set a **new strong administrator password** (P0ppad0m!)
6. Set the system timezone to **Pacific/Auckland (NZST/NZDT)**.

---

## Step 3: RutOS 6 to RutOS 7 Firmware Upgrade

> [!CAUTION]
> **CRITICAL**: Upgrading from RutOS 6 (`RUT9XX_R_00.06.x`) to RutOS 7 (`RUT9_R_00.07.x`) transitions the underlying operating system from legacy OpenWrt 15.05/18.06 to OpenWrt 21.02.
> **You MUST UNCHECK "Keep settings"**. Migrating old UCI configurations across major versions will break routing and corrupt services.

1. **Firmware Compatibility Check**:
   * If currently on an early RutOS 6 build, ensure the router is first on the bridge release **`RUT9XX_R_00.06.09.5`**.
   * Target RutOS 7 image: **`RUT9_R_00.07.06.21`** (or latest stable RUT955 release).
2. **Upgrade via WebUI**:
   * Navigate to: **System → Firmware → Update from file**.
   * Browse and upload the RutOS 7 `.bin` image.
   * In the verification popup:
     * **Keep settings**: Set to **OFF / UNCHECKED**.
   * Click **Proceed** / **Flash image**.
3. **Flashing Process**:
   * The process takes approximately 3–5 minutes. The LEDs will flash during writing.
   * **Do NOT remove power** during flashing.
4. After the router reboots, log in at `http://192.168.1.1` and complete the initial RutOS 7 wizard.

---


## Step 4: WireGuard Site-to-Site VPN Setup

RutOS 7 has native WireGuard support. This connects the boat network (`192.168.1.0/24`) to the home network (`192.168.50.0/24`) via the ASUS RT-AX52 router.

### WireGuard Connection Parameters
* **Local VPN IP (RUT955)**: `10.6.0.2/24`
* **Local Private Key**: `WJaXcwoLezAb1UvlCWbuqRJrNCEVIR0NEsDDBnF/o10=`
* **Listen Port**: `51820`
* **Server Public Key (ASUS)**: `9H/j2GOEo3bomK5TNWYMR0PyQmTSIyXA94scWBaGeBA=`
* **Server Endpoint**: `219.89.200.207:51820`
* **AllowedIPs**: `10.6.0.0/24, 192.168.50.0/24`
* **PersistentKeepalive**: `25` *(critical for 4G CGNAT traversal)*

### Via WebUI
1. Navigate to **Services → VPN → WireGuard**.
2. Under **Add new instance**:
   * Name: `wg0` (or `asus_home`)
   * Role: **Client** (or Peer)
   * Click **Add**.
3. **Interface Settings**:
   * **Private Key**: `WJaXcwoLezAb1UvlCWbuqRJrNCEVIR0NEsDDBnF/o10=`
   * **IP Address**: `10.6.0.2`
   * **Netmask**: `255.255.255.0` (or `/24`)
   * **Listen Port**: `51820`
4. **Peer Settings**:
   * Click **Add Peer**:
   * **Public Key**: `9H/j2GOEo3bomK5TNWYMR0PyQmTSIyXA94scWBaGeBA=`
   * **Endpoint Host**: `219.89.200.207`
   * **Endpoint Port**: `51820`
   * **Allowed IPs**: `10.6.0.0/24, 192.168.50.0/24`
   * **Persistent Keepalive**: `25`
   * **Route Allowed IPs**: Enabled
5. Click **Save & Apply**.

### Firewall Zone Assignment
1. Navigate to **Network → Firewall → General Settings**.
2. Ensure the `wg0` interface is assigned to a firewall zone that allows traffic:
   * Edit the **wireguard** / **vpn** zone (or assign `wg0` to `wan`).
   * Input: **ACCEPT**, Output: **ACCEPT**, Forward: **ACCEPT**.
   * Set **Inter-Zone Forwarding**: Allow forward to destination zones: `lan` and `wan`; allow forward from source zones: `lan`.

### Testing WireGuard Link
From the router SSH terminal:
```bash
# Ping the VPN gateway
ping -c 3 10.6.0.1

# Ping hammer across the VPN
ping -c 3 192.168.50.89
```

---

## Step 5: Hostname & Remote Syslog to Hammer

Configuring the hostname to `RUT955-Paeraki` ensures that `syslog-ng` on `hammer` automatically appends logs to `/var/log/remote/RUT955-Paeraki.log`.

### Via CLI / SSH (Recommended)
```bash
# 1. Set hostname
uci set system.@system[0].hostname='RUT955-Paeraki'

# 2. Configure remote syslog forwarding to hammer (192.168.50.89:514 UDP)
uci set system.@system[0].log_ip='192.168.50.89'
uci set system.@system[0].log_port='514'
uci set system.@system[0].log_proto='udp'

# 3. CRITICAL: Instruct logread to include the hostname in transmitted syslog headers
# Without this, logread omits the hostname, causing syslog-ng to fall back to the IP (10.6.0.2.log)
uci set system.@system[0].log_hostname='1'

# 4. Commit and restart daemons
uci commit system
/etc/init.d/system restart
/etc/init.d/log restart
```

### Via WebUI
1. **System → Administration → General**:
   * Set **Hostname**: `RUT955-Paeraki`
   * Click **Save & Apply**.
2. **System → Maintenance → Troubleshoot → Logging Settings**:
   * Check **Enable remote logging**.
   * **Remote server host / IP**: `192.168.50.89`
   * **Port**: `514`
   * **Protocol**: `UDP`
   * Check **Include hostname** / **Log hostname** (enables `-h RUT955-Paeraki` in `logread`).
   * Click **Save & Apply**.

*(Note: Logs will start reaching hammer once the WireGuard tunnel below is established).*

---

## Step 6: Onboard MQTT Broker (Mosquitto)

On clean RutOS 7 installations, the built-in Mosquitto MQTT broker package needs
to be installed via System > Package Manager and after installation is disabled by default.

### Via CLI / SSH
```bash
# Enable Mosquitto broker on port 1883 with anonymous access
uci set mosquitto.mqtt.enabled='1'
uci add_list mosquitto.mqtt.local_port='1883'
uci set mosquitto.mqtt.anonymous_access='1'
uci commit mosquitto
/etc/init.d/mosquitto restart
```

### Via WebUI
1. Navigate to **Services → MQTT Broker**.
2. Check **Enable**.
3. Set **Port**: `1883`.
4. Check **Allow anonymous access**.
5. Click **Save & Apply**.

---

## Step 7: GPS GNSS Telemetry & rc.local Setup

### Background: RutOS 7 / Quectel EC25-AU Bug
On RutOS 7 with the Quectel EC25-AU modem (`EC25AUFAR02A04M4G`):
1. The factory `gpsd` daemon hardcodes a query for DPO (`AT+QGPSCFG="dpoenable"`), which the EC25-AU rejects with `ERROR`.
2. `gpsd` crashes in a loop, breaking the WebUI NMEA forwarder and `gpsctl`.
3. The BusyBox `nc` binary lacks UDP (`-u`) flags.
4. **Resolution**: Disable `gpsd`, configure modem hardware NVRAM directly, and use a lightweight TCP netcat stream from `/dev/ttyUSB2` directly into `watch_gps.service` on `look` (`192.168.1.100:8500`).

### 1. Disable Broken gpsd Service
Run on RUT955:
```bash
/etc/init.d/gpsd disable
/etc/init.d/gpsd stop
```

### 2. Enable Hardware Auto-GPS in Modem NVRAM
Tells the baseband modem to start GNSS automatically on modem power-up:
```bash
gsmctl -A 'AT+QGPSCFG="autogps",1'
```

### 3. Add Auto-Reconnecting NMEA Stream to `/etc/rc.local`
Edit `/etc/rc.local` on the router:
```bash
vi /etc/rc.local
```

Ensure the contents match:
```sh
# Put your custom commands here that should be executed once
# the system init finished. By default this file does nothing.

# Paeraki 24/7 Continuous GPS Streaming to look (TCP:8500)
(
  sleep 15
  gsmctl -A "AT+QGPS=1,30,50,0,1"
  while true; do
    nc 192.168.1.100 8500 < /dev/ttyUSB2
    sleep 2
  done
) &

exit 0
```

> **Important Notes on GPS & nc:**
> * `AT+QGPS=1,30,50,0,1`: Mode 1 (Standalone), MaxTime 30s, MaxDist 50m, **FixCount 0 (Infinite fixes)**, FixRate 1s. A bare `AT+QGPS=1` terminates after ~30 fixes.
> * `while true; do nc ... sleep 2; done`: If `look` is powered off or rebooting, `nc` exits and sleeps 2 seconds before retrying. Running `ps | grep nc` while `look` is offline will catch the process in `sleep 2`.
> * **Reading /dev/ttyUSB2 directly**: Do **not** use bare `cat /dev/ttyUSB2` (it blocks in `open()` waiting for carrier detect). Use `microcom -s 115200 /dev/ttyUSB2` (exit with `Ctrl+X`).

Ensure `/etc/rc.local` is executable:
```bash
chmod +x /etc/rc.local
/etc/rc.local
```

---

## Step 8: SSH Keys & Remote Management

Copy your SSH public key from `hammer` to avoid password prompts:
```bash
# Run from hammer:
ssh-copy-id -i ~/.ssh/id_rsa.pub root@192.168.1.1
```

---

## Step 9: Spark NZ Captive Portal Bypass & WireGuard Internet Failover

When using a Spark NZ mobile/phone SIM (e.g. Endless Mobile), Spark detects tethered devices behind the router (TTL 63) and redirects HTTP traffic to `http://www.spark.co.nz/myspark/freedom-tethering/` while blocking HTTPS when mobile full-speed data is exhausted.

To solve this, we configure:
1. **TTL Normalization (`TTL=64`)**: Ensures packets exiting via cellular look like they originated on the primary device.
2. **WireGuard Default Gateway with Automatic Failover**: Routes all boat internet traffic through the Home ASUS router (`10.6.0.1`) across the WireGuard tunnel at full home broadband speed with zero boat data usage. If the VPN tunnel goes down, traffic automatically fails over to direct cellular.
3. **TCP MSS Clamping**: Clamps TCP MSS on `HomeASUS` to avoid MTU packet black-holing over the tunnel.

### 1. Firewall Custom Rules (`/etc/firewall.user`)
Add to `/etc/firewall.user`:
```bash
# Normalize outgoing cellular TTL to 64 to bypass Spark NZ freedom-tethering redirect
iptables -t mangle -C POSTROUTING -o qmimux0 -j TTL --ttl-set 64 2>/dev/null || \
iptables -t mangle -I POSTROUTING 1 -o qmimux0 -j TTL --ttl-set 64

# WireGuard TCP MSS Clamping to prevent packet fragmentation over tunnel
iptables -t mangle -C FORWARD -o HomeASUS -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || \
iptables -t mangle -A FORWARD -o HomeASUS -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu
iptables -t mangle -C FORWARD -i HomeASUS -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || \
iptables -t mangle -A FORWARD -i HomeASUS -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu
```

### 2. WireGuard Network Configuration
Ensure `HomeASUS` peer allows all traffic (`0.0.0.0/0`) with metric 1:
```bash
uci set network.HomeASUS.metric='1'
uci set network.jhome.allowed_ips='0.0.0.0/0'
uci commit network
```

### 3. Failover Watchdog (`/usr/bin/vpn-failover.sh`)
Create `/usr/bin/vpn-failover.sh`:
```bash
#!/bin/sh
IFACE="HomeASUS"
PEER="9H/j2GOEo3bomK5TNWYMR0PyQmTSIyXA94scWBaGeBA="
VPN_METRIC=1
TIMEOUT=120

while true; do
    LATEST=$(wg show "$IFACE" latest-handshakes 2>/dev/null | grep "$PEER" | awk '{print $2}')
    NOW=$(date +%s)
    
    if [ -n "$LATEST" ] && [ "$LATEST" -gt 0 ]; then
        DIFF=$((NOW - LATEST))
    else
        DIFF=999999
    fi

    if [ "$DIFF" -lt "$TIMEOUT" ]; then
        if ! ip route show default dev "$IFACE" metric "$VPN_METRIC" 2>/dev/null | grep -q "default"; then
            ip route add default dev "$IFACE" metric "$VPN_METRIC" 2>/dev/null
            logger -t vpn-failover "WireGuard tunnel is UP (handshake ${DIFF}s ago). Default route -> VPN ($IFACE)."
        fi
    else
        if ip route show default dev "$IFACE" metric "$VPN_METRIC" 2>/dev/null | grep -q "default"; then
            ip route del default dev "$IFACE" metric "$VPN_METRIC" 2>/dev/null
            logger -t vpn-failover "WireGuard tunnel is DOWN (handshake ${DIFF}s ago). Fallback to cellular."
        fi
    fi
    sleep 15
done
```
Make executable:
```bash
chmod +x /usr/bin/vpn-failover.sh
```

### 4. Enable in `/etc/rc.local`
Add before `exit 0` in `/etc/rc.local`:
```bash
/usr/bin/vpn-failover.sh &
```

---

## Verification Checklist

| Check | Command / Action | Expected Result | Status / Notes |
| :--- | :--- | :--- | :--- |
| **Remote Access** | Hammer: `ping -c 3 192.168.1.1` | 0% packet loss | Active across WireGuard VPN tunnel |
| **WireGuard Gateway**| Router: `ping -c 3 10.6.0.1` | 0% packet loss | Active to ASUS RT-AX52 |
| **Hammer Workstation**| Router: `ping -c 3 192.168.50.89` | 0% packet loss | Active across VPN |
| **VPN Egress IP** | Look: `curl -s https://ifconfig.me` | `219.89.200.207` | All internet routed via Home ASUS fiber |
| **Cellular Fallback**| Look: `curl -s https://ifconfig.me` (with VPN down) | `122.63.133.210` | Cellular direct without captive portal (TTL 64) |
| **MQTT Broker** | Router: `netstat -tlpn \| grep 1883` | `0.0.0.0:1883 LISTEN (mosquitto)` | Active; connects `paeraki_logger` on hammer |
| **Remote Syslog** | Router: `logger "RUT955 Recovery Test"`<br>Hammer: `tail -n 5 /var/log/remote/RUT955-Paeraki.log` | Log entry appears with tag `RUT955-Paeraki` | Active (`log_hostname=1`) |
| **GPS Serial Pipe** | Router: `microcom -s 115200 /dev/ttyUSB2` | Raw `$GPRMC`, `$GPGGA`, `$GPVTG` sentences | Active (Exit with `Ctrl+X`) |
| **GNSS Modem Fix** | Router: `gsmctl -A 'AT+QGPSLOC=2'` | Returns Lat, Lon, Alt, Fix Type | Active |
| **GPS Stream Process**| Router: `ps \| grep nc` | Running: `nc 192.168.1.100 8500 < /dev/ttyUSB2` | Runs actively once `look` is powered on |
| **look Telemetry** | Browser: `http://192.168.1.100:8080` | Green 3D FIX, satellites locked | Requires `look` powered on |
| **Telemetry DB Logging**| Hammer: `systemctl --user status paeraki_logger` | Connected to `192.168.1.1:1883` | Active, recording to `data/paeraki.db` |

---

## 5. Automated Router Backups

RUT955 backups are automated from `hammer` using a systemd user timer. The process invokes `sysupgrade -b` on the router, saves a snapshot to the router's onboard USB storage (`/mnt/sda1/backups/router/`), downloads a copy across WireGuard to `hammer` (`paeraki/backups/RUT955/`), verifies archive integrity, and maintains rolling snapshots.

### Backup Locations
* **Hammer (Workstation)**: `/home/jh/paeraki/backups/RUT955/`
  * `backup-RUT955-YYYYMMDD_HHMMSS.tar.gz` (~91 KB, keeps last 30)
  * `backup-RUT955-latest.tar.gz` (symlink to newest archive)
* **Router Onboard USB**: `/mnt/sda1/backups/router/`
  * `backup-RUT955-YYYYMMDD_HHMMSS.tar.gz` (keeps last 14)
  * `backup-RUT955-latest.tar.gz` (symlink to newest archive)

### Automation Architecture
* **Script**: [`/home/jh/paeraki/scripts/backup-router.sh`](file:///home/jh/paeraki/scripts/backup-router.sh)
* **Systemd Service**: `~/.config/systemd/user/backup_router.service`
* **Systemd Timer**: `~/.config/systemd/user/backup_router.timer` (runs daily at 03:30 NZST, persistent)

### Manual Trigger & Status Check
```bash
# Run backup immediately
systemctl --user start backup_router.service

# Check backup timer schedule
systemctl --user list-timers backup_router.timer

# View backup logs
journalctl --user -u backup_router.service -n 20 --no-pager
```