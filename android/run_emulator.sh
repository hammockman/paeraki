#!/bin/bash
# Helper script to launch the Paeraki Android emulator on hammer
export ANDROID_HOME="/home/jh/.android-sdk"
export PATH="$ANDROID_HOME/emulator:$ANDROID_HOME/platform-tools:$PATH"

AVD_NAME="paeraki_phone"

echo "==> Starting Android Virtual Device ($AVD_NAME)..."
echo "    Press Ctrl+C to close or run adb commands in another terminal."
"$ANDROID_HOME/emulator/emulator" -avd "$AVD_NAME" -gpu host "$@"
