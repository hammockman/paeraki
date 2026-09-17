#!/bin/bash
set -euo pipefail

ROUTER_HOST="paeraki"
ROUTER_IP="192.168.1.1"
LOCAL_BACKUP_DIR="/home/jh/paeraki/backups/RUT955"
ROUTER_USB_DIR="/mnt/sda1/backups/router"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILENAME="backup-RUT955-${TIMESTAMP}.tar.gz"
LATEST_LINK="backup-RUT955-latest.tar.gz"

echo "[INFO] Starting RUT955 router backup from hammer ($(date))..."

# Check reachability of router
if ! ping -c 1 -W 2 "${ROUTER_IP}" >/dev/null 2>&1; then
    echo "[ERROR] Router at ${ROUTER_IP} is unreachable across WireGuard!" >&2
    exit 1
fi

mkdir -p "${LOCAL_BACKUP_DIR}"

# Determine remote destination directory (USB if mounted, fallback to /tmp)
REMOTE_DIR=$(ssh "${ROUTER_HOST}" "[ -d ${ROUTER_USB_DIR} ] && echo '${ROUTER_USB_DIR}' || echo '/tmp'")
REMOTE_FILE="${REMOTE_DIR}/${BACKUP_FILENAME}"

echo "[INFO] Generating router configuration archive on ${ROUTER_HOST}:${REMOTE_FILE}..."
ssh "${ROUTER_HOST}" "sysupgrade -b '${REMOTE_FILE}' >/dev/null 2>&1"

# Download archive to hammer
LOCAL_FILE="${LOCAL_BACKUP_DIR}/${BACKUP_FILENAME}"
echo "[INFO] Downloading backup to ${LOCAL_FILE}..."
ssh "${ROUTER_HOST}" "cat '${REMOTE_FILE}'" > "${LOCAL_FILE}"

# Validate downloaded archive integrity
if ! tar -tzf "${LOCAL_FILE}" >/dev/null 2>&1; then
    echo "[ERROR] Downloaded archive is corrupt or invalid!" >&2
    rm -f "${LOCAL_FILE}"
    exit 1
fi

# Update latest symlink and prune old backups on hammer (keep last 30)
cd "${LOCAL_BACKUP_DIR}"
ln -sfn "${BACKUP_FILENAME}" "${LATEST_LINK}"
ls -t backup-RUT955-*.tar.gz 2>/dev/null | tail -n +31 | xargs -r rm -f

# If backed up to USB drive on router, update latest symlink and prune there too (keep last 14)
if [ "${REMOTE_DIR}" = "${ROUTER_USB_DIR}" ]; then
    ssh "${ROUTER_HOST}" "
        cd ${ROUTER_USB_DIR} && \
        ln -sfn ${BACKUP_FILENAME} ${LATEST_LINK} && \
        ls -t backup-RUT955-*.tar.gz 2>/dev/null | tail -n +15 | xargs -r rm -f
    "
else
    # Clean up temporary file from router /tmp
    ssh "${ROUTER_HOST}" "rm -f '${REMOTE_FILE}'"
fi

FILESIZE=$(ls -lh "${LOCAL_FILE}" | awk '{print $5}')
echo "[SUCCESS] RUT955 backup completed: ${LOCAL_FILE} (${FILESIZE})"
