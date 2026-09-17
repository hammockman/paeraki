# Orange Pi R1 Plus LTS (`look`) Recovery & Backup Playbook

This document details the architecture, automated backup mechanisms, and step-by-step disaster recovery procedures for **`look`** (`192.168.1.100`), yacht **Paeraki's** primary telemetry and vessel monitoring computer.

---

## 1. System Overview & Architecture

```
                      ┌──────────────────────────────────────────────┐
                      │          Teltonika RUT955 (Paeraki)          │
                      │                 192.168.1.1                  │
                      │       Onboard USB Drive: /mnt/sda1           │
                      │        (58 GB ext2 Storage: 54 GB Free)      │
                      └───────▲──────────────────────────────▲───────┘
                              │                              │
         Daily Local Backup   │ (100 Mbps LAN,               │ Offsite Rsync Mirror
         (Zero Cellular Data) │  0 MB Mobile Data)           │ (WireGuard Tunnel)
                              │                              │
             ┌────────────────┴───────┐       ┌──────────────┴───────────────┐
             │  Orange Pi R1 Plus LTS │       │     Workstation (hammer)     │
             │         (look)         │       │        192.168.50.89         │
             │     192.168.1.100      │       │                              │
             │                        │       │ - Mirror: ~/paeraki/backups/ │
             │ - watch_12v.service    │       │ - paeraki_logger.service     │
             │ - watch_72v.service    │       │ - paeraki_dashboard.service  │
             │ - watch_gps.service    │       │ - SQLite: data/paeraki.db    │
             │ - watch_alarms.service │       └──────────────────────────────┘
             │ - backup_look.timer    │
             └────────────────────────┘
```

### Hardware Specifications
* **Board**: Orange Pi R1 Plus LTS
* **SoC**: Rockchip RK3328 (Quad-core ARM Cortex-A53 @ 1.3 GHz)
* **RAM**: 1 GB LPDDR3
* **Primary Storage**: 64 GB MicroSD card (`/dev/mmcblk0`)
* **Network Interfaces**:
  * `eth0` / `lan0`: Onboard Gigabit Ethernet (connected to RUT955 router LAN)
  * `eth1` / `wan0`: Secondary Realtek RTL8153 Gigabit Ethernet
  * `wlxecb931e7467e`: TP-Link Archer TX10UB Nano (Realtek RTL8851BU Wi-Fi 6)
  * `hci0`: Realtek Bluetooth 5.3 Controller (via USB `3625:010b`)
* **Operating System**: Armbian 22.04.4 LTS (Jammy Jellyfish)
* **Kernel**: Linux `6.6.18-current-rockchip64` (aarch64)

### Disk & Bootloader Geometry
Rockchip RK3328 does **not** boot like a standard PC. It reads firmware stages directly from raw unpartitioned sectors on `/dev/mmcblk0` before the first partition:
* **Sector 64** (32 KB): `idbloader.bin` (Rockchip Secondary Program Loader - SPL)
* **Sector 16384** (8 MB): `uboot.img` (U-Boot core bootloader)
* **Sector 24576** (12 MB): `trust.bin` (ARM Trusted Firmware / OP-TEE)
* **Sector 32768** (16 MB offset): First MBR partition (`/dev/mmcblk0p1`, ext4 root filesystem `/`)

> [!IMPORTANT]
> Because the bootloader lives in raw sectors **outside** the filesystem, copying only files or extracting a tarball to an unformatted SD card will **not** boot. A recovery requires either flashing a base Armbian image first, or writing the 16 MB raw bootloader image (`look-bootloader-rk3328.img`).

---

## 2. Onboard Local Backup Architecture

To avoid consuming expensive and metered Spark NZ cellular mobile data across the WireGuard tunnel, `look` backs itself up directly to the **Teltonika RUT955 router's onboard USB drive** (`/mnt/sda1`) across the local 100 Mbps Ethernet connection.

### USB Storage on Router (`192.168.1.1`):
* **Mount Point**: `/mnt/sda1` (ext2 filesystem, 53.9 GB available)
* **Backup Root**: `/mnt/sda1/backups/`
  * `look/`: Look's bootloader, configuration snapshots, and telemetry archives
  * `router/`: Router's own firmware recovery backup (`backup-RUT955-Paeraki-2026-09-17.tar.gz`)

### Backup Contents on Router (`/mnt/sda1/backups/look/`):
1. **`look-bootloader-rk3328.img`** (16 MB): Exact binary dump of MBR partition table + Rockchip SPL, U-Boot, and Trust binaries (sectors 0 to 32,767).
2. **`look-config-latest.tar.gz`** (~108 MB): Symlink to the most recent system archive.
3. **`look-config-YYYYMMDD_HHMMSS.tar.gz`**: Historical daily archives (the script automatically retains the last 14 snapshots).

### What `look-config-*.tar.gz` Captures:
* `/etc/` (System configurations, network, udev rules, `/etc/modules`, firewall, SSH host keys)
* `/home/jh/` (Telemetry collectors, vessel dashboard, alarm engine, scripts, SSH credentials)
* `/usr/local/bin/` (Custom maintenance and backup scripts)
* `/usr/local/src/` (Kernel module sources including `btusb-rtl8851bu`)
* `/lib/modules/6.6.18-current-rockchip64/extra/rtw89/` (Compiled out-of-tree Wi-Fi 6 driver)
* `/lib/modules/6.6.18-current-rockchip64/kernel/drivers/bluetooth/btusb.ko` (Patched Bluetooth driver for RTL8851BU)
* `/lib/firmware/rtw89/` (Realtek Wi-Fi 6 firmware `rtw8851b_fw-1.bin`)
* `/lib/firmware/rtl_bt/` (Realtek Bluetooth firmware `rtl8851bu_fw.bin` & `rtl8851bu_config.bin`)
* `/var/log.hdd/` (Persistent systemd journal and historical boat logs)

---

## 3. Automated Backup Configuration on `look`

### 1. Backup Script: `/usr/local/bin/backup-look-config.sh`
```bash
#!/bin/bash
set -euo pipefail

ROUTER_IP="192.168.1.1"
BACKUP_DIR="/mnt/sda1/backups/look"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="look-config-${TIMESTAMP}.tar.gz"
LATEST_LINK="look-config-latest.tar.gz"

echo "[INFO] Starting Paeraki look configuration backup to router USB storage (${ROUTER_IP})..."

if ! ping -c 1 -W 2 "${ROUTER_IP}" > /dev/null 2>&1; then
    echo "[ERROR] Router ${ROUTER_IP} is unreachable!" >&2
    exit 1
fi

# Stream compressed tarball directly across LAN into router USB storage
tar --exclude='/home/jh/paeraki/.git' \
    --exclude='/home/jh/paeraki/.venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='/home/jh/paeraki/data/paeraki.db-wal' \
    -czf - \
    /etc \
    /home/jh \
    /usr/local/bin \
    /lib/modules/$(uname -r)/extra \
    /lib/firmware/rtw89 /lib/firmware/rtl_bt /usr/local/src /lib/modules/$(uname -r)/kernel/drivers/bluetooth/btusb.ko \
    /var/log.hdd 2>/dev/null | \
    ssh -o BatchMode=yes -o StrictHostKeyChecking=no root@${ROUTER_IP} "cat > ${BACKUP_DIR}/${BACKUP_FILE}"

# Update latest symlink and prune old backups (keep last 14)
ssh -o BatchMode=yes -o StrictHostKeyChecking=no root@${ROUTER_IP} "
    cd ${BACKUP_DIR} && \
    ln -sfn ${BACKUP_FILE} ${LATEST_LINK} && \
    ls -t look-config-*.tar.gz 2>/dev/null | tail -n +15 | xargs -r rm -f
"

FILESIZE=$(ssh -o BatchMode=yes root@${ROUTER_IP} "ls -lh ${BACKUP_DIR}/${BACKUP_FILE}" | awk '{print $5}')
echo "[SUCCESS] Backup completed: ${BACKUP_FILE} (${FILESIZE}) on router USB drive."
```

### 2. Systemd Automation: Service & Timer
* **Service**: `/etc/systemd/system/backup_look.service`
* **Timer**: `/etc/systemd/system/backup_look.timer`
  * Runs daily at **03:00 NZST** with randomized 5-minute jitter.
  * Configured with `Persistent=true` so that if `look` is powered down at 3 AM, the backup executes immediately upon the next boot.

To manually trigger a backup at any time:
```bash
sudo systemctl start backup_look.service
journalctl -u backup_look.service -n 20 --no-pager
```

### 3. Realtek RTL8851BU Bluetooth Subsystem Driver & Firmware
The onboard TP-Link Archer TX10UB Nano dongle provides both Wi-Fi 6 and Bluetooth 5.3 under USB ID `3625:010b`.
While the Linux 6.6 kernel includes RTL8851BU firmware-loading support in `btrtl.c`, the stock `btusb.c` driver lacks the USB ID `3625:010b`.
* **Firmware**: `/lib/firmware/rtl_bt/rtl8851bu_fw.bin` and `/lib/firmware/rtl_bt/rtl8851bu_config.bin`.
* **Driver source**: `/usr/local/src/btusb-rtl8851bu/` (includes patched `btusb.c` and Makefile).
* **Driver location**: `/lib/modules/$(uname -r)/kernel/drivers/bluetooth/btusb.ko`.
* **Rebuilding driver after kernel upgrades**:
  ```bash
  cd /usr/local/src/btusb-rtl8851bu
  make
  sudo make install
  sudo modprobe -r btusb && sudo modprobe btusb
  ```

---

## 4. Disaster Recovery Playbook

### Scenario A: MicroSD Card Dies While at Sea (Hot-Spare Swap)
**Fastest Recovery Time: 30 Seconds**

If you have kept a pre-flashed spare MicroSD card onboard Paeraki (e.g., taped inside the electrical panel):
1. Cut power to `look` (turn off the dedicated 5V buck converter / 12V breaker).
2. Remove the failed MicroSD card.
3. Insert the hot-spare MicroSD card.
4. Restore power. `look` boots immediately, reconnects to the router, resumes telemetry daemons, and establishes telemetry streaming.

---

### Scenario B: Restoring to a Blank MicroSD Card (Onboard Recovery)
If you only have a blank MicroSD card and a laptop onboard:

#### Step 1: Obtain the Backups from the Router
1. Power off the RUT955 router or unmount `/mnt/sda1`:
   ```bash
   ssh root@192.168.1.1 "sync && umount /mnt/sda1"
   ```
2. Unplug the USB flash drive from the router and plug it into your laptop.
3. On the drive, navigate to `backups/look/`:
   * `look-bootloader-rk3328.img`
   * `look-config-latest.tar.gz`

#### Step 2: Flash the Bootloader & Partition the Card
Insert the blank MicroSD card into your laptop (assume card is `/dev/sdX` on Linux/Mac, or use WSL):
```bash
# 1. Write the Rockchip bootloader & partition table to raw sectors
sudo dd if=look-bootloader-rk3328.img of=/dev/sdX bs=512 count=32768 conv=fsync status=progress

# 2. Expand partition 1 to fill the rest of your MicroSD card
sudo parted -s /dev/sdX resizepart 1 100%

# 3. Format partition 1 as ext4 with the expected label 'armbi_root'
sudo mkfs.ext4 -F -L "armbi_root" /dev/sdX1

# 4. Mount the partition
sudo mkdir -p /mnt/target
sudo mount /dev/sdX1 /mnt/target
```

#### Step 3: Extract the System & Configuration Archive
```bash
# Extract the complete system snapshot onto the new card
sudo tar -xzf look-config-latest.tar.gz -C /mnt/target/

# Clean sync and unmount
sudo sync
sudo umount /mnt/target
```

#### Step 4: Boot `look`
1. Re-insert the USB drive into the RUT955 router.
2. Insert the newly prepared MicroSD card into `look`.
3. Power on `look`. Within 45 seconds:
   * Ethernet `lan0` acquires `192.168.1.100`.
   * Wi-Fi 6 driver loads and initializes.
   * Telemetry daemons (`watch_12v`, `watch_72v`, `watch_gps`, `watch_alarms`) start automatically.

---

### Scenario C: Recovery Using a Standard Armbian Base Image
If you prefer not to touch raw sectors manually:
1. Download or use the standard Armbian Jammy image for Orange Pi R1 Plus LTS:
   `Armbian_22.04_Orangepi-r1plus-lts_jammy_current.img.xz`
2. Flash it to the MicroSD card using **BalenaEtcher** or **Raspberry Pi Imager**.
3. Boot `look` with the fresh card once (it will automatically expand the root filesystem).
4. Copy `look-config-latest.tar.gz` over the network (or mount the router USB drive) and extract:
   ```bash
   sudo tar -xzf look-config-latest.tar.gz -C /
   sudo reboot
   ```
   All vessel telemetry, udev rules, custom rtw89 driver, and alarms are instantly restored.

---

### Scenario D: Restoring Specific Files / Undoing a Bad Configuration
If `look` is running but a configuration or service script was broken:

You can inspect and extract individual files directly from the router backup without leaving `look`:

```bash
# 1. List contents of the latest backup
ssh root@192.168.1.1 "tar -ztvf /mnt/sda1/backups/look/look-config-latest.tar.gz | grep 'watch_gps'"

# 2. Restore only the telemetry directory from the backup:
ssh root@192.168.1.1 "cat /mnt/sda1/backups/look/look-config-latest.tar.gz" | \
  sudo tar -xzf - -C / home/jh/paeraki/

# 3. Restart the affected service:
sudo systemctl restart watch_gps.service
```

---

## 5. Offsite Mirroring to Workstation (`hammer`)

To adhere to the **3-2-1 backup rule** (3 copies, 2 different media, 1 offsite), your home workstation `hammer` can mirror the router's USB backups across WireGuard whenever convenient.

Run from `hammer`:
```bash
# Mirror all router and look backups to hammer using scp
mkdir -p ~/paeraki/backups/router-usb
scp -r root@192.168.1.1:/mnt/sda1/backups/* ~/paeraki/backups/router-usb/
```
*(Note: Teltonika RutOS uses OpenWrt's Dropbear SSH with standard `scp`).*

---

## 6. Remote Logging to Workstation (`hammer`)

`look` forwards system, service, and kernel events across WireGuard to `hammer` (`192.168.50.89:514` UDP).

### Configuration (`/etc/rsyslog.d/60-remote-hammer.conf`)
```ini
# Suppress repetitive 1-second GPS telemetry publish lines
:msg, contains, "GPS published [FIX" stop

# Forward all remaining system, telemetry, and kernel logs to hammer
*.* @192.168.50.89:514
```

### Viewing Logs on `hammer`
Incoming messages stream in real time to `/var/log/remote/look.log`:
```bash
tail -f /var/log/remote/look.log
```

---

## 7. Verification & Health Checklist

| Component | Verification Command | Expected Output | Status / Notes |
| :--- | :--- | :--- | :--- |
| **Router USB Drive** | `ssh root@192.168.1.1 "df -h /mnt/sda1"` | `53.9G Available, mounted on /mnt/sda1` | Healthy ext2 USB flash drive |
| **Look SSH to Router**| `ssh look "ssh root@192.168.1.1 id"` | `uid=0(root) gid=0(root)` | Passwordless key authentication |
| **Daily Backup Timer**| `ssh look "systemctl status backup_look.timer"`| `active (waiting)`, daily at 03:00 NZST | Enabled and persistent |
| **Latest Archive** | `ssh root@192.168.1.1 "ls -lh /mnt/sda1/backups/look/"`| `look-config-latest.tar.gz` (~108 MB) | Valid compressed archive |
| **Raw Bootloader** | `ssh root@192.168.1.1 "ls -lh /mnt/sda1/backups/look/look-bootloader*"`| `16.0M look-bootloader-rk3328.img` | Sectors 0–32,767 binary dump |
| **Router Backup** | `ssh root@192.168.1.1 "ls -lh /mnt/sda1/backups/router/"`| `backup-RUT955-Paeraki-2026-09-17.tar.gz` | Complete RutOS 7 configuration |
| **Remote Logging** | `tail -n 5 /var/log/remote/look.log` (on hammer) | Recent live entries with host tag `look` | Filtered rsyslog UDP stream |
| **Wi-Fi 6 Driver** | `ssh look "modinfo rtw89_8851bu_git \| grep vermagic"`| `6.6.18-current-rockchip64` | Backed up in `/lib/modules/...` |
| **Bluetooth Radio**| `ssh look "bluetoothctl show \| grep Powered"`| `Powered: yes` (Realtek 8851BU `hci0`) | Patched `btusb.ko` with firmware |
| **Telemetry Daemons**| `ssh look "systemctl is-active watch_12v watch_72v watch_gps watch_alarms"`| 4 lines of `active` | All live monitors running |
