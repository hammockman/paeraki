"""GPS Navigation tab with 2D vessel geo-track map, SOG/COG time series,
and nautical distance analytics.
"""

from __future__ import annotations

import datetime
import math
from typing import Any

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from widgets.viewbox import TimeSeriesViewBox


def haversine_distance_nm(lat1, lon1, lat2, lon2) -> float:
    """Calculate the great circle distance in nautical miles between two points."""
    r_nm = 3440.065  # Earth radius in nautical miles
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r_nm * c


class TabGPS(QWidget):
    """Interactive GPS Navigation visualization tab."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.data: list[dict[str, Any]] = []
        self._timestamps: np.ndarray = np.array([])
        self._summary: dict[str, Any] = {}
        self._valid_coords: list[dict[str, Any]] = []
        self._valid_indices: list[int] = []
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(12)

        # ---------------- KPI Analytics Header ----------------
        kpi_layout = QHBoxLayout()
        kpi_layout.setSpacing(10)

        self.kpi_sog_card, self.kpi_sog_val, self.kpi_sog_sub = self._create_kpi_card(
            "SPEED OVER GROUND", "--.- kts", "Max: -- | Avg: --"
        )
        self.kpi_dist_card, self.kpi_dist_val, self.kpi_dist_sub = self._create_kpi_card(
            "DISTANCE LOG", "--.- NM", "Total track distance"
        )
        self.kpi_pos_card, self.kpi_pos_val, self.kpi_pos_sub = self._create_kpi_card(
            "VESSEL POSITION", "--° --' S", "---° --' E"
        )
        self.kpi_fix_card, self.kpi_fix_val, self.kpi_fix_sub = self._create_kpi_card(
            "GNSS FIX & PRECISION", "-- sats", "HDOP: -- | RUT955"
        )

        kpi_layout.addWidget(self.kpi_sog_card)
        kpi_layout.addWidget(self.kpi_dist_card)
        kpi_layout.addWidget(self.kpi_pos_card)
        kpi_layout.addWidget(self.kpi_fix_card)
        main_layout.addLayout(kpi_layout)

        # ---------------- Splitter: SOG/COG Plots on Left, 2D Track Map on Right ----------------
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(8)

        # Left Container: Speed and Heading curves
        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        # 1. SOG Plot (Knots & km/h)
        self.date_axis_sog = pg.DateAxisItem(orientation="bottom")
        self.plot_sog = pg.PlotWidget(viewBox=TimeSeriesViewBox(), axisItems={"bottom": self.date_axis_sog})
        self.plot_sog.setBackground("#080c16")
        self.plot_sog.showGrid(x=True, y=True, alpha=0.25)
        self.plot_sog.setTitle("<span style='color: #00e5ff; font-weight: bold;'>Speed Over Ground (SOG)</span>")
        self.plot_sog.setLabel("left", "Speed", units="kts", color="#00e5ff")

        self.curve_sog = self.plot_sog.plot(
            pen=pg.mkPen("#00e5ff", width=1.5),
            symbol="o",
            symbolSize=3,
            symbolPen=None,
            symbolBrush=pg.mkBrush("#00e5ff"),
            name="SOG (knots)",
            connect="finite",
        )

        # 2. Heading & Altitude Plot
        self.date_axis_cog = pg.DateAxisItem(orientation="bottom")
        self.plot_cog = pg.PlotWidget(viewBox=TimeSeriesViewBox(), axisItems={"bottom": self.date_axis_cog})
        self.plot_cog.setBackground("#080c16")
        self.plot_cog.showGrid(x=True, y=True, alpha=0.25)
        self.plot_cog.setTitle("<span style='color: #10b981; font-weight: bold;'>Course Over Ground (COG True)</span>")
        self.plot_cog.setLabel("left", "Heading", units="°", color="#10b981")
        self.plot_cog.setYRange(0, 360)

        self.plot_cog.setXLink(self.plot_sog)

        self.curve_cog = self.plot_cog.plot(
            pen=pg.mkPen("#10b981", width=1.5),
            symbol="o",
            symbolSize=3,
            symbolPen=None,
            symbolBrush=pg.mkBrush("#10b981"),
            name="COG (°)",
            connect="finite",
        )

        # Synchronized crosshairs for SOG and COG
        self.v_line_sog = pg.InfiniteLine(
            angle=90, movable=False, pen=pg.mkPen("#f59e0b", width=1.5, style=Qt.PenStyle.DashLine)
        )
        self.v_line_cog = pg.InfiniteLine(
            angle=90, movable=False, pen=pg.mkPen("#f59e0b", width=1.5, style=Qt.PenStyle.DashLine)
        )
        self.plot_sog.addItem(self.v_line_sog, ignoreBounds=True)
        self.plot_cog.addItem(self.v_line_cog, ignoreBounds=True)

        self.plot_sog.scene().sigMouseMoved.connect(self._on_mouse_moved)
        self.plot_cog.scene().sigMouseMoved.connect(self._on_mouse_moved)

        left_layout.addWidget(self.plot_sog, stretch=1)
        left_layout.addWidget(self.plot_cog, stretch=1)
        splitter.addWidget(left_container)

        # Right Container: 2D Vessel Geo-Track Plot
        self.plot_map = pg.PlotWidget()
        self.plot_map.plotItem.vb.wheelEvent = lambda ev, axis=None: ev.accept()
        self.plot_map.setBackground("#0d162d")
        self.plot_map.showGrid(x=True, y=True, alpha=0.3)
        self.plot_map.setAspectLocked(True, ratio=1.0)
        self.plot_map.setTitle("<span style='color: #38bdf8; font-weight: bold;'>2D Vessel Navigation Track (Lon vs Lat)</span>")
        self.plot_map.setLabel("left", "Latitude (°)", color="#38bdf8")
        self.plot_map.setLabel("bottom", "Longitude (°)", color="#38bdf8")

        # Track line & scatter points
        self.curve_track = self.plot_map.plot(
            pen=pg.mkPen(color="#0284c7", width=2, style=Qt.PenStyle.DashLine),
            connect="finite",
        )
        self.scatter_track = pg.ScatterPlotItem(size=8, pen=None)
        self.plot_map.addItem(self.scatter_track)

        # Start, Current, and Hover/Scrub position markers
        self.marker_start = pg.ScatterPlotItem(size=14, brush="#10b981", symbol="o")
        self.marker_current = pg.ScatterPlotItem(size=16, brush="#00e5ff", symbol="star")
        self.marker_scrub = pg.ScatterPlotItem(size=14, brush="#f59e0b", symbol="d")
        self.plot_map.addItem(self.marker_start)
        self.plot_map.addItem(self.marker_current)
        self.plot_map.addItem(self.marker_scrub)

        self.plot_map.scene().sigMouseMoved.connect(self._on_mouse_moved_map)

        splitter.addWidget(self.plot_map)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)

        main_layout.addWidget(splitter, stretch=1)

    def _create_kpi_card(self, title: str, val: str, sub: str) -> tuple[QFrame, QLabel, QLabel]:
        card = QFrame()
        card.setProperty("class", "kpi-card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)

        lbl_title = QLabel(title)
        lbl_title.setProperty("class", "kpi-title")

        lbl_val = QLabel(val)
        lbl_val.setProperty("class", "kpi-val")

        lbl_sub = QLabel(sub)
        lbl_sub.setProperty("class", "kpi-sub")

        layout.addWidget(lbl_title)
        layout.addWidget(lbl_val)
        layout.addWidget(lbl_sub)
        return card, lbl_val, lbl_sub

    def update_data(self, rows: list[dict[str, Any]]):
        """Update GPS time-series and 2D track map."""
        self.data = rows
        if not rows:
            self.curve_sog.clear()
            self.curve_cog.clear()
            self.curve_track.clear()
            self.scatter_track.clear()
            self.marker_start.clear()
            self.marker_current.clear()
            self.marker_scrub.clear()
            self.kpi_sog_val.setText("--.- kts")
            self.kpi_dist_val.setText("--.- NM")
            self.kpi_pos_val.setText("No GPS Fix")
            self._valid_coords = []
            self._valid_indices = []
            return

        # Filter points with valid coordinates
        valid_indices: list[int] = []
        valid_coords: list[dict[str, Any]] = []
        for idx, r in enumerate(rows):
            lat = r.get("latitude")
            lon = r.get("longitude")
            if lat is not None and lon is not None and abs(lat) > 0.1 and abs(lon) > 0.1:
                valid_indices.append(idx)
                valid_coords.append(r)
        self._valid_coords = valid_coords
        self._valid_indices = valid_indices

        timestamps_sec = np.array([r["epoch_ms"] / 1000.0 for r in rows], dtype=np.float64)
        self._timestamps = timestamps_sec
        sogs = np.array([np.nan if r.get("sog_knots") is None else float(r.get("sog_knots")) for r in rows], dtype=np.float64)
        cogs = np.array([np.nan if r.get("cog_true") is None else float(r.get("cog_true")) for r in rows], dtype=np.float64)

        self.curve_sog.setData(timestamps_sec, sogs, connect="finite")
        self.curve_cog.setData(timestamps_sec, cogs, connect="finite")
        self.plot_sog.enableAutoRange(axis="y")

        if len(timestamps_sec) > 1:
            t_min = float(timestamps_sec[0])
            t_max = float(timestamps_sec[-1])
            pad = max(1.0, (t_max - t_min) * 0.02)
            total_span = (t_max - t_min) + 2 * pad
            self.plot_sog.plotItem.vb.setLimits(xMin=t_min - pad, xMax=t_max + pad, minXRange=5.0, maxXRange=total_span)
            self.plot_cog.plotItem.vb.setLimits(xMin=t_min - pad, xMax=t_max + pad, minXRange=5.0, maxXRange=total_span)

        # Update 2D Map
        total_nm = 0.0
        lat_naut = "Awaiting Fix"
        lon_naut = "No coordinates"

        if valid_coords:
            track_lats = np.array([float(r["latitude"]) if (r.get("latitude") is not None and abs(r["latitude"]) > 0.1) else np.nan for r in rows], dtype=np.float64)
            track_lons = np.array([float(r["longitude"]) if (r.get("longitude") is not None and abs(r["longitude"]) > 0.1) else np.nan for r in rows], dtype=np.float64)
            self.curve_track.setData(track_lons, track_lats, connect="finite")

            lats = np.array([r["latitude"] for r in valid_coords], dtype=np.float64)
            lons = np.array([r["longitude"] for r in valid_coords], dtype=np.float64)
            speeds = np.array([r.get("sog_knots") or 0.0 for r in valid_coords], dtype=np.float64)

            # Color dots by speed: Blue (0 kts) -> Cyan (2-4 kts) -> Amber (5+ kts)
            spots = []
            for lon, lat, spd in zip(lons, lats, speeds):
                if spd < 1.0:
                    brush = pg.mkBrush(2, 132, 199, 160)
                elif spd < 4.0:
                    brush = pg.mkBrush(0, 229, 255, 200)
                else:
                    brush = pg.mkBrush(245, 158, 11, 230)
                spots.append({"pos": (lon, lat), "brush": brush})

            self.scatter_track.setData(spots)

            # Start and Current markers
            self.marker_start.setData([{"pos": (lons[0], lats[0])}])
            self.marker_current.setData([{"pos": (lons[-1], lats[-1])}])

            self.plot_map.autoRange()

            # Calculate total distance in nautical miles
            for i in range(len(valid_coords) - 1):
                p1 = valid_coords[i]
                p2 = valid_coords[i + 1]
                dist = haversine_distance_nm(
                    p1["latitude"], p1["longitude"], p2["latitude"], p2["longitude"]
                )
                if dist < 5.0:  # ignore sensor glitch jumps > 5 NM between consecutive packets
                    total_nm += dist

            self.kpi_dist_val.setText(f"{total_nm:.2f} NM")
            self.kpi_dist_sub.setText(f"{total_nm * 1.852:.2f} km logged")

            latest = valid_coords[-1]
            lat_naut = latest.get("latitude_nautical") or f"{latest['latitude']:.4f}°"
            lon_naut = latest.get("longitude_nautical") or f"{latest['longitude']:.4f}°"
            self.kpi_pos_val.setText(lat_naut)
            self.kpi_pos_sub.setText(lon_naut)
        else:
            self.curve_track.clear()
            self.scatter_track.clear()
            self.marker_start.clear()
            self.marker_current.clear()
            self.kpi_dist_val.setText("0.00 NM")
            self.kpi_pos_val.setText("Awaiting Fix")
            self.kpi_pos_sub.setText("No coordinates")

        # KPI Updates
        cur_sog = sogs[-1] if len(sogs) else 0.0
        max_sog = np.max(sogs) if len(sogs) else 0.0
        avg_sog = np.mean(sogs) if len(sogs) else 0.0
        self.kpi_sog_val.setText(f"{cur_sog:.1f} kts")
        self.kpi_sog_sub.setText(f"Max: {max_sog:.1f} kts | Avg: {avg_sog:.1f} kts")

        latest_all = rows[-1]
        sats = latest_all.get("satellites") or 0
        hdop = latest_all.get("hdop") or 0.0
        self.kpi_fix_val.setText(f"{sats} Sats")
        self.kpi_fix_sub.setText(f"HDOP: {hdop:.1f} | Teltonika GPS")

        self._summary = {
            "cur_sog": cur_sog,
            "max_sog": max_sog,
            "avg_sog": avg_sog,
            "total_nm": total_nm,
            "latest_lat": lat_naut,
            "latest_lon": lon_naut,
            "sats": sats,
            "hdop": hdop,
        }

    def _scrub_to_index(self, idx: int):
        """Update KPI cards, crosshairs, and 2D map position for the selected record index."""
        if not self.data:
            return
        idx = max(0, min(len(self.data) - 1, idx))
        row = self.data[idx]
        ts = row["epoch_ms"] / 1000.0

        self.v_line_sog.setPos(ts)
        self.v_line_cog.setPos(ts)

        dt = datetime.datetime.fromtimestamp(ts)
        time_str = dt.strftime("%Y-%m-%d %H:%M:%S")

        sog = row.get("sog_knots") or 0.0
        cog = row.get("cog_true") or 0.0
        self.kpi_sog_val.setText(f"{sog:.1f} kts")
        self.kpi_sog_sub.setText(f"At: {dt.strftime('%H:%M:%S')} | COG: {cog:.0f}°")

        lat = row.get("latitude")
        lon = row.get("longitude")
        if lat and lon and abs(lat) > 0.1 and abs(lon) > 0.1:
            lat_naut = row.get("latitude_nautical") or f"{lat:.4f}°"
            lon_naut = row.get("longitude_nautical") or f"{lon:.4f}°"
            self.kpi_pos_val.setText(lat_naut)
            self.kpi_pos_sub.setText(lon_naut)
            self.marker_scrub.setData([{"pos": (lon, lat)}])

        sats = row.get("satellites") or 0
        hdop = row.get("hdop") or 0.0
        self.kpi_fix_val.setText(f"{sats} Sats")
        self.kpi_fix_sub.setText(f"HDOP: {hdop:.1f} | Point #{idx+1} of {len(self.data)}")
        self.kpi_dist_sub.setText(f"Scrub: {time_str}")

    def _on_mouse_moved(self, pos):
        """Handle cursor scrubbing across SOG/COG time-series plots."""
        if not self.data or len(self._timestamps) == 0:
            return
        mouse_point = self.plot_sog.plotItem.vb.mapSceneToView(pos)
        x_val = mouse_point.x()
        if x_val < self._timestamps[0] or x_val > self._timestamps[-1]:
            return
        idx = int(np.searchsorted(self._timestamps, x_val))
        self._scrub_to_index(idx)

    def _on_mouse_moved_map(self, pos):
        """Handle cursor scrubbing across 2D vessel track map."""
        if not self._valid_coords or not self._valid_indices:
            return
        mouse_point = self.plot_map.plotItem.vb.mapSceneToView(pos)
        lon_m, lat_m = mouse_point.x(), mouse_point.y()

        lons = np.array([r["longitude"] for r in self._valid_coords], dtype=np.float64)
        lats = np.array([r["latitude"] for r in self._valid_coords], dtype=np.float64)
        dists_sq = (lons - lon_m) ** 2 + (lats - lat_m) ** 2
        nearest_sub_idx = int(np.argmin(dists_sq))
        orig_idx = self._valid_indices[nearest_sub_idx]
        self._scrub_to_index(orig_idx)
