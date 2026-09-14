#!/bin/bash
# Helper script to launch the Paeraki Android emulator on hammer
export ANDROID_HOME="/home/jh/.android-sdk"
export PATH="$ANDROID_HOME/emulator:$ANDROID_HOME/platform-tools:$PATH"

AVD_NAME="paeraki_phone"

echo "==> Starting Android Virtual Device ($AVD_NAME) configured as OPPO A60..."
echo "    Display: 6.67\" 720x1604 (20:9) @ 90Hz | RAM: 4GB | CPU: Snapdragon 680 (Octa-core)"
echo "    Tip: To build, install, and launch the latest Paeraki app, run: ./android/run_app.sh"
echo "    Press Ctrl+C to close or run adb commands in another terminal."
"$ANDROID_HOME/emulator/emulator" -avd "$AVD_NAME" -gpu host -no-snapshot-load -crash-report-mode never "$@"
