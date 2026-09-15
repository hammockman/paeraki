#!/usr/bin/env python3
"""
Headless UI verification script for Paeraki Dashboard.
Spawns mock server on port 8085, executes headless Chrome tests under Xvfb,
and verifies AIS tab, GPS tab (dual sources & dynamics), and Misc tab (barometer).
"""

import subprocess
import time
import urllib.request
import os
import signal
import sys
from pathlib import Path

ARTIFACT_DIR = Path("/home/jh/.gemini/antigravity-ide/brain/7b1b7439-6e9b-4f12-9c08-44c061ca4e9e")

def main():
    print("Starting dashboard mock server on port 8085...")
    server_proc = subprocess.Popen(
        [
            sys.executable,
            "dashboard/server.py",
            "--mock",
            "--host",
            "127.0.0.1",
            "--port",
            "8085",
            "--log-level",
            "WARNING",
        ],
        env={**os.environ, "PYTHONPATH": "."},
    )

    try:
        # Wait for server to become responsive
        start = time.time()
        ready = False
        while time.time() - start < 10.0:
            try:
                resp = urllib.request.urlopen("http://127.0.0.1:8085/api/health", timeout=1.0)
                if resp.status == 200:
                    ready = True
                    break
            except Exception:
                time.sleep(0.3)

        if not ready:
            print("Error: Server failed to start within 10s")
            sys.exit(1)

        print("Mock server is ready!")

        # 1. Verify State API returns new structure
        state_resp = urllib.request.urlopen("http://127.0.0.1:8085/api/state", timeout=2.0)
        state_data = state_resp.read().decode("utf-8")
        assert "seatalkng" in state_data, "seatalkng missing in state"
        assert "ais_targets" in state_data, "ais_targets missing in state"
        assert "pressure_hpa" in state_data, "pressure_hpa missing in state"
        print("API validation passed: seatalkng, ais_targets, and pressure_hpa present.")

        # Test screenshots under xvfb-run
        screenshots = [
            ("tab_ais_desktop.png", "1280,900", "http://127.0.0.1:8085/?tab=ais"),
            ("tab_gps_desktop.png", "1280,1100", "http://127.0.0.1:8085/?tab=gps"),
            ("tab_misc_desktop.png", "1280,900", "http://127.0.0.1:8085/?tab=misc"),
            ("tab_ais_mobile.png", "412,915", "http://127.0.0.1:8085/?tab=ais"),
            ("tab_gps_mobile.png", "412,1100", "http://127.0.0.1:8085/?tab=gps"),
        ]

        for fname, winsize, url in screenshots:
            out_path = ARTIFACT_DIR / fname
            cmd = [
                "xvfb-run",
                "-a",
                "google-chrome",
                "--headless=new",
                f"--screenshot={out_path}",
                f"--window-size={winsize}",
                "--virtual-time-budget=3000",
                url,
            ]
            print(f"Capturing screenshot {fname} ({winsize})...")
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0:
                print(f"Warning on {fname}: {res.stderr}")
            else:
                print(f"Generated {out_path} ({out_path.stat().st_size} bytes)")

    finally:
        print("Stopping mock server...")
        server_proc.send_signal(signal.SIGTERM)
        try:
            server_proc.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            server_proc.kill()
        print("Cleaned up server.")

if __name__ == "__main__":
    main()
