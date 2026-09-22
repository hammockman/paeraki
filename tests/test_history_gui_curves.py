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
