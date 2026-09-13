#!/bin/bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
ROOT_DIR="$(cd "$DIR/.." >/dev/null 2>&1 && pwd)"

export JAVA_HOME="/home/jh/.jdks/jdk-21.0.12.1+1"
export PATH="$JAVA_HOME/bin:$PATH"
export ANDROID_HOME="/home/jh/.android-sdk"

echo "==> Preparing dist_app asset bundle..."
DIST_APP="$ROOT_DIR/dist_app"
rm -rf "$DIST_APP"
mkdir -p "$DIST_APP/static"
cp -r "$ROOT_DIR/dashboard/static/"* "$DIST_APP/"
cp -r "$ROOT_DIR/dashboard/static/"* "$DIST_APP/static/"

echo "==> Syncing web assets into Android project with Capacitor..."
cd "$ROOT_DIR"
npx cap sync android

echo "==> Compiling Android APK with Gradle..."
cd "$DIR"
./gradlew assembleDebug

mkdir -p "$ROOT_DIR/dist"
cp "$DIR/app/build/outputs/apk/debug/app-debug.apk" "$ROOT_DIR/dist/paeraki-monitor.apk"

echo "==> Build complete!"
echo "    APK Output: $ROOT_DIR/dist/paeraki-monitor.apk"
ls -lh "$ROOT_DIR/dist/paeraki-monitor.apk"
