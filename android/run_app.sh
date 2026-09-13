#!/bin/bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
ROOT_DIR="$(cd "$DIR/.." >/dev/null 2>&1 && pwd)"

export ANDROID_HOME="/home/jh/.android-sdk"
export PATH="$ANDROID_HOME/emulator:$ANDROID_HOME/platform-tools:$PATH"
export DISPLAY="${DISPLAY:-:0}"

AVD_NAME="paeraki_phone"
APK_PATH="$ROOT_DIR/dist/paeraki-monitor.apk"

# Check if APK exists
if [ ! -f "$APK_PATH" ]; then
    echo "==> APK not found, building first..."
    bash "$DIR/build_apk.sh"
fi

# 1. Check if emulator is already running
if ! adb get-state 2>/dev/null | grep -q "device"; then
    echo "==> Starting Android Virtual Device ($AVD_NAME)..."
    "$ANDROID_HOME/emulator/emulator" -avd "$AVD_NAME" -gpu host -no-boot-anim &
    
    echo "==> Waiting for emulator device to respond..."
    adb wait-for-device
    
    echo "==> Waiting for Android OS to finish booting..."
    while [ "$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" != "1" ]; do
        sleep 2
    done
    echo "[+] Android OS boot completed successfully!"
else
    echo "[+] Connected to running emulator device."
fi

# 2. Install the latest APK
echo "==> Installing $APK_PATH..."
adb install -r "$APK_PATH"

# 3. Launch Paeraki MainActivity
echo "==> Launching Paeraki Monitor..."
adb shell am start -n nz.alientech.paeraki/.MainActivity

echo "[+] Paeraki Monitor is active on the emulator screen."
