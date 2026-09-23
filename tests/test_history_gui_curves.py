"""Tests for History Explorer GUI time-series line breaking on NULL values.
Verifies that NULLs/Nones are converted to np.nan and plotted with connect='finite'
so that line paths break across missing/offline data rather than dropping to 0.0.
"""

import os
import sys
from pathlib import Path
import numpy as np
import pytest

# Ensure offscreen Qt platform to prevent any UI windows from appearing
os.environ["QT_QPA_PLATFORM"] = "offscreen"

# Add history-gui to sys.path
gui_dir = str(Path(__file__).parent.parent / "history-gui")
if gui_dir not in sys.path:
    sys.path.insert(0, gui_dir)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPainterPath
from widgets.unit_chart_stack import UnitChartStack
from widgets.tab_72v import Tab72V
from widgets.tab_12v import Tab12V
from widgets.tab_gps import TabGPS
from widgets.detail_panel import DetailPanel
import db



@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_unit_chart_stack_breaks_lines_on_null(qapp):
    stack = UnitChartStack()
    stack.update_selected_metrics({"chg_v", "chg_i"})

    # 5 points with the 3rd point having NULLs (e.g. offline charger)
    dummy_chg = [
        {"epoch_ms": 1000, "output_voltage": 79.0, "output_current": 15.0},
        {"epoch_ms": 2000, "output_voltage": 79.1, "output_current": 15.1},
        {"epoch_ms": 3000, "output_voltage": None, "output_current": None},  # NULL
        {"epoch_ms": 4000, "output_voltage": 79.2, "output_current": 14.8},
        {"epoch_ms": 5000, "output_voltage": 79.3, "output_current": 14.9},
    ]

    stack.set_table_data({"telemetry_charger": dummy_chg})
    chg_v_curve = stack._plot_containers["V"].curves["chg_v"]

    # Verify that yData contains np.nan at index 2, not 0.0
    y_data = chg_v_curve.yData
    assert np.isnan(y_data[2]), f"Expected NaN at index 2, got {y_data[2]}"
    assert y_data[0] == 79.0
    assert y_data[1] == 79.1
    assert y_data[3] == 79.2
    assert y_data[4] == 79.3

    # Verify painter path breaks across the gap (uses MoveTo instead of LineTo)
    path = chg_v_curve.curve.getPath()
    element_types = [path.elementAt(i).type for i in range(path.elementCount())]
    # Element at gap must be MoveToElement (type 0)
    assert QPainterPath.ElementType.MoveToElement in element_types[2:], "Path should break across NaN"


def test_tab_72v_breaks_lines_on_null(qapp):
    tab = Tab72V()
    dummy_72v = [
        {"epoch_ms": 1000, "total_voltage": 78.5, "current": 5.0, "power": 392.5, "cell_delta_mv": 12},
        {"epoch_ms": 2000, "total_voltage": 78.55, "current": 5.1, "power": 400.0, "cell_delta_mv": 12},
        {"epoch_ms": 3000, "total_voltage": None, "current": None, "power": None, "cell_delta_mv": None},
        {"epoch_ms": 4000, "total_voltage": 78.6, "current": 4.8, "power": 377.0, "cell_delta_mv": 11},
        {"epoch_ms": 5000, "total_voltage": 78.65, "current": 4.9, "power": 385.0, "cell_delta_mv": 11},
    ]
    tab.update_data(dummy_72v)

    assert np.isnan(tab.curve_voltage.yData[2])
    assert np.isnan(tab.curve_current.yData[2])
    assert np.isnan(tab.curve_power.yData[2])
    assert np.isnan(tab.curve_delta.yData[2])

    path = tab.curve_voltage.curve.getPath()
    # Ensure MoveTo occurs after index 1 to break line
    has_break = any(path.elementAt(i).type == QPainterPath.ElementType.MoveToElement for i in range(2, path.elementCount()))
    assert has_break, "Tab72V curve line should break across NULL data point"


def test_tab_12v_breaks_lines_on_null(qapp):
    tab = Tab12V()
    dummy_12v = [
        {"epoch_ms": 1000, "battery_voltage": 13.2, "solar_power": 120.0, "load_power": -45.0},
        {"epoch_ms": 2000, "battery_voltage": 13.25, "solar_power": 125.0, "load_power": -46.0},
        {"epoch_ms": 3000, "battery_voltage": None, "solar_power": None, "load_power": None},
        {"epoch_ms": 4000, "battery_voltage": 13.1, "solar_power": 115.0, "load_power": -40.0},
        {"epoch_ms": 5000, "battery_voltage": 13.15, "solar_power": 118.0, "load_power": -42.0},
    ]
    tab.update_data(dummy_12v)

    assert np.isnan(tab.curve_batt_v.yData[2])
    assert np.isnan(tab.curve_solar_w.yData[2])
    assert np.isnan(tab.curve_load_w.yData[2])

    path = tab.curve_batt_v.curve.getPath()
    has_break = any(path.elementAt(i).type == QPainterPath.ElementType.MoveToElement for i in range(2, path.elementCount()))
    assert has_break, "Tab12V curve line should break across NULL data point"


def test_tab_gps_breaks_lines_on_null(qapp):
    tab = TabGPS()
    dummy_gps = [
        {"epoch_ms": 1000, "sog_knots": 4.5, "cog_true": 180.0, "latitude": -41.28, "longitude": 174.77, "fix": 1},
        {"epoch_ms": 2000, "sog_knots": 4.6, "cog_true": 181.0, "latitude": -41.281, "longitude": 174.771, "fix": 1},
        {"epoch_ms": 3000, "sog_knots": None, "cog_true": None, "latitude": None, "longitude": None, "fix": 0},
        {"epoch_ms": 4000, "sog_knots": 4.8, "cog_true": 182.0, "latitude": -41.29, "longitude": 174.78, "fix": 1},
        {"epoch_ms": 5000, "sog_knots": 4.9, "cog_true": 183.0, "latitude": -41.291, "longitude": 174.781, "fix": 1},
    ]
    tab.update_data(dummy_gps)

    assert np.isnan(tab.curve_sog.yData[2])
    assert np.isnan(tab.curve_cog.yData[2])

    path = tab.curve_sog.curve.getPath()
    has_break = any(path.elementAt(i).type == QPainterPath.ElementType.MoveToElement for i in range(2, path.elementCount()))
    assert has_break, "TabGPS SOG curve line should break across lost GPS fix"


def test_compute_connect_array_and_max_gap():
    # 5 samples at 1-second intervals (median dt = 1.0s, max_gap = 600.0s)
    t = np.array([100.0, 101.0, 102.0, 1000.0, 1001.0])
    y = np.array([12.5, 12.6, 12.7, 13.0, 13.1])
    c = db.compute_connect_array(t, y)
    # Between 102.0 and 1000.0 is 898s > 600s, so c[2] must be 0 (disconnected)
    assert c[0] == 1
    assert c[1] == 1
    assert c[2] == 0
    assert c[3] == 1
    assert c[4] == 0

    # With NaN
    y_nan = np.array([12.5, np.nan, 12.7, 13.0, 13.1])
    c_nan = db.compute_connect_array(t, y_nan)
    assert c_nan[0] == 0
    assert c_nan[1] == 0
    assert c_nan[2] == 0


def test_unit_chart_stack_breaks_lines_on_downtime_gaps(qapp):
    stack = UnitChartStack()
    stack.update_selected_metrics({"12v_v"})

    # Pure finite values, but spanning a 24-hour downtime gap (no rows in database during gap)
    dummy_12v = [
        {"epoch_ms": 1_000_000, "battery_voltage": 13.4},
        {"epoch_ms": 1_005_000, "battery_voltage": 13.5},
        {"epoch_ms": 1_010_000, "battery_voltage": 13.45},
        # 24-hour offline gap (86,400,000 ms)
        {"epoch_ms": 1_010_000 + 86_400_000, "battery_voltage": 12.8},
        {"epoch_ms": 1_015_000 + 86_400_000, "battery_voltage": 12.85},
    ]

    stack.set_table_data({"telemetry_12v": dummy_12v})
    v_curve = stack._plot_containers["V"].curves["12v_v"]

    path = v_curve.curve.getPath()
    element_types = [path.elementAt(i).type for i in range(path.elementCount())]
    # Point 3 (first point after the 24h gap) must be a MoveToElement (type 0) to avoid drawing a diagonal line
    assert element_types[3] == QPainterPath.ElementType.MoveToElement, "Curve must break across downtime gap"


def test_detail_panel_shows_dashes_in_downtime_gap(qapp):
    panel = DetailPanel()
    # Select fridge_left_t and 12v_v
    panel.set_data({"fridge_left_t", "12v_v"}, {
        "telemetry_fridge": [
            {"epoch_ms": 1_000_000, "left_temp": 5.0},
            {"epoch_ms": 1_005_000, "left_temp": 5.2},
            # 70-hour gap
            {"epoch_ms": 1_000_000 + 250_000_000, "left_temp": 6.5},
            {"epoch_ms": 1_005_000 + 250_000_000, "left_temp": 6.6},
        ],
        "telemetry_12v": [
            {"epoch_ms": 1_000_000, "battery_voltage": 13.5},
            {"epoch_ms": 1_005_000, "battery_voltage": 13.6},
            # 70-hour gap
            {"epoch_ms": 1_000_000 + 250_000_000, "battery_voltage": 12.9},
            {"epoch_ms": 1_005_000 + 250_000_000, "battery_voltage": 12.95},
        ]
    })

    # 1. Cursor in the middle of the 70h gap (t = 1000 + 100000 = 101000s)
    cursor_gap_sec = (1_000_000 + 100_000_000) / 1000.0
    panel.update_cursor_position(cursor_gap_sec)

    fridge_lbl = panel._metric_val_labels["fridge_left_t"]
    v_lbl = panel._metric_val_labels["12v_v"]

    # In downtime gap, values must display as dashes (--), not 5.2 or 6.5
    assert "-- °C" in fridge_lbl.text(), f"Expected dashed readout in gap, got: {fridge_lbl.text()}"
    assert "-- V" in v_lbl.text(), f"Expected dashed readout in gap, got: {v_lbl.text()}"

    # 2. Cursor right next to the second burst (t = 251000s + 2s)
    cursor_active_sec = (1_000_000 + 250_000_000 + 2000) / 1000.0
    panel.update_cursor_position(cursor_active_sec)
    assert "6.5 °C" in fridge_lbl.text()
    assert "12.90 V" in v_lbl.text()


def test_tab_12v_breaks_lines_on_downtime_gaps(qapp):
    tab = Tab12V()
    dummy_12v = [
        {"epoch_ms": 1_000_000, "battery_voltage": 13.2, "solar_power": 120.0, "load_power": -45.0},
        {"epoch_ms": 1_005_000, "battery_voltage": 13.25, "solar_power": 125.0, "load_power": -46.0},
        # 30-hour gap
        {"epoch_ms": 1_000_000 + 108_000_000, "battery_voltage": 12.6, "solar_power": 0.0, "load_power": -20.0},
        {"epoch_ms": 1_005_000 + 108_000_000, "battery_voltage": 12.65, "solar_power": 10.0, "load_power": -22.0},
    ]
    tab.update_data(dummy_12v)

    path = tab.curve_batt_v.curve.getPath()
    assert path.elementAt(2).type == QPainterPath.ElementType.MoveToElement, "12V curve must break across gap"


def test_tab_72v_breaks_lines_on_downtime_gaps(qapp):
    tab = Tab72V()
    dummy_72v = [
        {"epoch_ms": 1_000_000, "total_voltage": 78.5, "current": 5.0, "power": 392.5, "cell_delta_mv": 12},
        {"epoch_ms": 1_005_000, "total_voltage": 78.55, "current": 5.1, "power": 400.0, "cell_delta_mv": 12},
        # Gap
        {"epoch_ms": 1_000_000 + 108_000_000, "total_voltage": 77.0, "current": 0.0, "power": 0.0, "cell_delta_mv": 14},
        {"epoch_ms": 1_005_000 + 108_000_000, "total_voltage": 77.05, "current": 0.1, "power": 7.7, "cell_delta_mv": 14},
    ]
    tab.update_data(dummy_72v)

    path = tab.curve_voltage.curve.getPath()
    assert path.elementAt(2).type == QPainterPath.ElementType.MoveToElement, "72V curve must break across gap"


def test_tab_gps_breaks_lines_on_downtime_gaps(qapp):
    tab = TabGPS()
    dummy_gps = [
        {"epoch_ms": 1_000_000, "sog_knots": 4.5, "cog_true": 180.0, "latitude": -41.28, "longitude": 174.77, "fix": 1},
        {"epoch_ms": 1_005_000, "sog_knots": 4.6, "cog_true": 181.0, "latitude": -41.281, "longitude": 174.771, "fix": 1},
        # Gap
        {"epoch_ms": 1_000_000 + 108_000_000, "sog_knots": 0.2, "cog_true": 90.0, "latitude": -41.30, "longitude": 174.80, "fix": 1},
        {"epoch_ms": 1_005_000 + 108_000_000, "sog_knots": 0.3, "cog_true": 92.0, "latitude": -41.301, "longitude": 174.801, "fix": 1},
    ]
    tab.update_data(dummy_gps)

    path_sog = tab.curve_sog.curve.getPath()
    assert path_sog.elementAt(2).type == QPainterPath.ElementType.MoveToElement, "GPS SOG curve must break across gap"

    path_track = tab.curve_track.curve.getPath()
    assert path_track.elementAt(2).type == QPainterPath.ElementType.MoveToElement, "GPS track curve must break across gap"


def test_unit_chart_stack_never_creates_secondary_y_axis(qapp):
    stack = UnitChartStack()
    # Select both 72V pack voltage and 12V house voltage
    stack.update_selected_metrics({"72v_v", "12v_v"})

    container = stack._plot_containers["V"]
    # Both metrics must be in the primary curves dictionary on the common axis
    assert "72v_v" in container.curves
    assert "12v_v" in container.curves

    # No secondary view or secondary curve attributes
    assert not hasattr(container, "secondary_view") or container.secondary_view is None
    assert not hasattr(container, "secondary_curve") or container.secondary_curve is None

    # Right axis must not be visible or linked to a separate view
    assert not container.plot_widget.plotItem.getAxis("right").isVisible()


