// Paeraki Vessel Telemetry Monitor - Frontend Client
(function() {
  'use strict';

  // DOM Elements
  const connDot = document.getElementById('conn-dot');
  const connLabel = document.getElementById('conn-label');
  const brokerEndpoint = document.getElementById('broker-endpoint');
  const totalPacketsEl = document.getElementById('total-packets');
  const packetRateEl = document.getElementById('packet-rate');
  const lastSeenEl = document.getElementById('last-seen');

  // 72V DOM
  const val72vSoc = document.getElementById('val-72v-soc');
  const val72vSocMode = document.getElementById('val-72v-soc-mode');
  const socGaugeFill = document.getElementById('soc-gauge-fill');
  const val72vVoltage = document.getElementById('val-72v-voltage');
  const val72vCurrent = document.getElementById('val-72v-current');
  const val72vPower = document.getElementById('val-72v-power');
  const bmsStateBadge = document.getElementById('bms-state-badge');
  const val72vCapacity = document.getElementById('val-72v-capacity');
  const val72vCycles = document.getElementById('val-72v-cycles');
  const val72vTemps = document.getElementById('val-72v-temps');
  const pillChgMos = document.getElementById('pill-chg-mos');
  const pillDsgMos = document.getElementById('pill-dsg-mos');
  const cellCountLabel = document.getElementById('cell-count-label');
  const cellBarsContainer = document.getElementById('cell-bars-container');
  const cellMinEl = document.getElementById('cell-min');
  const cellMaxEl = document.getElementById('cell-max');
  const cellDeltaEl = document.getElementById('cell-delta');

  // Tri-SoC Comparison DOM
  const cardSocIntegrated = document.getElementById('card-soc-integrated');
  const cardSocVoltage = document.getElementById('card-soc-voltage');
  const cardSocBms = document.getElementById('card-soc-bms');
  const valSocIntegrated = document.getElementById('val-soc-integrated');
  const valSocIntegratedSub = document.getElementById('val-soc-integrated-sub');
  const valSocVoltage = document.getElementById('val-soc-voltage');
  const valSocVoltageSub = document.getElementById('val-soc-voltage-sub');
  const valSocBms = document.getElementById('val-soc-bms');
  const valSocBmsSub = document.getElementById('val-soc-bms-sub');
  const badgeBmsStatus = document.getElementById('badge-bms-status');
  const descBmsStatus = document.getElementById('desc-bms-status');
  const pillModeIntegrated = document.getElementById('pill-mode-integrated');
  const btnSyncSoc = document.getElementById('btn-sync-soc');

  // 12V DOM
  const val12vBattV = document.getElementById('val-12v-batt-v');
  const val12vBattSoc = document.getElementById('val-12v-batt-soc');
  const fill12vSoc = document.getElementById('fill-12v-soc');
  const val12vSolarW = document.getElementById('val-12v-solar-w');
  const val12vSolarV = document.getElementById('val-12v-solar-v');
  const val12vSolarA = document.getElementById('val-12v-solar-a');
  const val12vState = document.getElementById('val-12v-state');
  const solarModeBadge = document.getElementById('solar-mode-badge');
  const val12vYield = document.getElementById('val-12v-yield');
  const val12vTemp = document.getElementById('val-12v-temp');
  const val12vLoad = document.getElementById('val-12v-load');
  const val12vKeycount = document.getElementById('val-12v-keycount');
  const registerChips = document.getElementById('register-chips');

  // GPS DOM
  const valGpsFixBadge = document.getElementById('val-gps-fix-badge');
  const valGpsSogKnots = document.getElementById('val-gps-sog-knots');
  const valGpsSogKmh = document.getElementById('val-gps-sog-kmh');
  const valGpsSogMs = document.getElementById('val-gps-sog-ms');
  const valGpsCog = document.getElementById('val-gps-cog');
  const valGpsHeadingCardinal = document.getElementById('val-gps-heading-cardinal');
  const valGpsMode = document.getElementById('val-gps-mode');
  const valGpsLatNautical = document.getElementById('val-gps-lat-nautical');
  const valGpsLonNautical = document.getElementById('val-gps-lon-nautical');
  const valGpsCoordsDec = document.getElementById('val-gps-coords-dec');
  const valGpsQuality = document.getElementById('val-gps-quality');
  const valGpsSats = document.getElementById('val-gps-sats');
  const valGpsHdop = document.getElementById('val-gps-hdop');
  const valGpsAltitude = document.getElementById('val-gps-altitude');
  const linkGpsMap = document.getElementById('link-gps-map');
  const valGpsSentence = document.getElementById('val-gps-sentence');

  // Log Table DOM
  const logRowsContainer = document.getElementById('log-rows-container');
  const btnPauseLog = document.getElementById('btn-pause-log');
  const btnClearLog = document.getElementById('btn-clear-log');
  const filterBtns = document.querySelectorAll('.filter-btn');

  // Application State
  let activeFilter = 'all';
  let isLogPaused = false;
  let logBuffer = [];
  const MAX_LOG_ROWS = 120;
  let lastPacketTimestamp = 0;
  let cached72v = null;
  let cached12v = null;
  let cachedGps = null;
  let selectedSocMode = 'integrated'; // Default to displaying the dashboard integrated SOC
  const GAUGE_CIRCUMFERENCE = 2 * Math.PI * 50; // 314.159

  // Initialize Gauge
  socGaugeFill.style.strokeDasharray = GAUGE_CIRCUMFERENCE;
  socGaugeFill.style.strokeDashoffset = GAUGE_CIRCUMFERENCE;

  // Relative Time Formatter
  function formatRelativeTime(isoStr) {
    if (!isoStr) return '--';
    const seconds = Math.floor((Date.now() - new Date(isoStr).getTime()) / 1000);
    if (seconds < 2) return 'just now';
    if (seconds < 60) return `${seconds}s ago`;
    const mins = Math.floor(seconds / 60);
    if (mins < 60) return `${mins}m ago`;
    return `${Math.floor(mins / 60)}h ago`;
  }

  // Periodic UI Freshness Tick
  setInterval(() => {
    if (lastPacketTimestamp) {
      lastSeenEl.textContent = formatRelativeTime(lastPacketTimestamp);
    }
    if (cached72v) {
      update72vBadge(cached72v);
    }
    if (cached12v) {
      update12vBadge(cached12v);
    }
    if (cachedGps) {
      updateGpsSubsystem(cachedGps);
    }
  }, 1000);

  // ---------------- UI Rendering ----------------

  function updateBrokerHeader(broker, server) {
    if (!broker) return;
    if (broker.connected) {
      connDot.className = 'pulse-dot connected';
      connLabel.textContent = 'Connected to Paeraki';
    } else {
      connDot.className = 'pulse-dot error';
      connLabel.textContent = 'Reconnecting to Broker...';
    }
    brokerEndpoint.textContent = `${broker.host}:${broker.port}`;
    totalPacketsEl.textContent = broker.total_packets.toLocaleString();
    packetRateEl.textContent = `${broker.msg_rate.toFixed(1)} /s`;
    if (broker.last_packet_time) {
      lastPacketTimestamp = broker.last_packet_time;
      lastSeenEl.textContent = formatRelativeTime(broker.last_packet_time);
    }

    const serverHostEl = document.getElementById('server-host');
    const brokerHostEl = document.getElementById('broker-host');
    const miscTotalPackets = document.getElementById('misc-total-packets');
    const miscPacketRate = document.getElementById('misc-packet-rate');
    if (miscTotalPackets) miscTotalPackets.textContent = broker.total_packets.toLocaleString();
    if (miscPacketRate) miscPacketRate.textContent = `${broker.msg_rate.toFixed(1)} /s`;

    if (serverHostEl) {
      serverHostEl.textContent = server?.hostname ? `${server.hostname} (${getServerHost()})` : getServerHost();
      serverHostEl.title = 'Paeraki server endpoint (tap to change IP:port)';
      serverHostEl.style.cursor = 'pointer';
      if (!serverHostEl.dataset.hasClickListener) {
        serverHostEl.dataset.hasClickListener = 'true';
        serverHostEl.addEventListener('click', () => {
          const current = getServerHost();
          const next = prompt('Enter Paeraki Dashboard Server address (e.g. 192.168.1.101:8080):', current);
          if (next !== null && next.trim() && next.trim() !== current) {
            localStorage.setItem('paeraki_server_host', next.trim());
            window.location.reload();
          }
        });
      }
    }
    if (broker?.host && brokerHostEl) {
      brokerHostEl.textContent = `${broker.host}:${broker.port || 1883}`;
    }
  }

  function update72vBadge(data) {
    if (!data || !bmsStateBadge) return;
    const current = parseFloat(data.current) || 0;
    const lastTime = data.last_updated || data.timestamp;
    const ageSeconds = lastTime ? Math.floor((Date.now() - new Date(lastTime).getTime()) / 1000) : Infinity;

    if (ageSeconds > 30) {
      bmsStateBadge.textContent = `STALE (${formatRelativeTime(lastTime)})`;
      bmsStateBadge.className = 'card-badge stale-badge';
    } else if (current > 0.5) {
      bmsStateBadge.textContent = 'CHARGING';
      bmsStateBadge.className = 'card-badge green-badge';
    } else if (current < -0.5) {
      bmsStateBadge.textContent = 'DISCHARGING';
      bmsStateBadge.className = 'card-badge amber-badge';
    } else {
      bmsStateBadge.textContent = 'IDLE';
      bmsStateBadge.className = 'card-badge green-badge';
    }
  }

  function update12vBadge(data) {
    if (!data || !solarModeBadge) return;
    const lastTime = data.last_updated || data.timestamp;
    const ageSeconds = lastTime ? Math.floor((Date.now() - new Date(lastTime).getTime()) / 1000) : Infinity;

    if (ageSeconds > 30) {
      solarModeBadge.textContent = `STALE (${formatRelativeTime(lastTime)})`;
      solarModeBadge.className = 'card-badge stale-badge';
    } else {
      solarModeBadge.textContent = data.charging_status || 'MONITORING';
      solarModeBadge.className = 'card-badge green-badge';
    }
  }

  function update72vSubsystem(data) {
    if (!data) return;
    cached72v = data;

    const voltage = parseFloat(data.total_voltage) || 0;
    const current = parseFloat(data.current) || 0;
    const power = parseFloat(data.power) || Math.round(voltage * current);
    const nomCap = parseFloat(data.nominal_capacity_ah) || 200.0;
    const resCap = parseFloat(data.residual_capacity_ah) || 0;

    // Multi-method SoC figures
    const socIntegrated = data.soc_integrated !== undefined ? parseFloat(data.soc_integrated) : (parseFloat(data.rsoc) || 0);
    const integratedAh = data.integrated_ah !== undefined ? parseFloat(data.integrated_ah) : resCap;
    const socVoltage = data.soc_voltage !== undefined ? parseFloat(data.soc_voltage) : 0;
    const vcellAvg = data.vcell_avg !== undefined ? parseFloat(data.vcell_avg) : (voltage > 0 ? voltage / 20.0 : 0);
    const socBms = parseFloat(data.rsoc) || 0;
    const isDesynced = Boolean(data.soc_discrepancy || Math.abs(socBms - socIntegrated) > 20 || Math.abs(socBms - socVoltage) > 20);

    // Update 72V Panel Mode Switcher Pills
    const pillValIntegrated = document.getElementById('pill-val-integrated');
    const pillSubIntegrated = document.getElementById('pill-sub-integrated');
    const pillValVoltage = document.getElementById('pill-val-voltage');
    const pillSubVoltage = document.getElementById('pill-sub-voltage');
    const pillValBms = document.getElementById('pill-val-bms');
    const pillSubBms = document.getElementById('pill-sub-bms');

    if (pillValIntegrated) pillValIntegrated.textContent = `${Math.round(socIntegrated)}%`;
    if (pillSubIntegrated) pillSubIntegrated.textContent = `${integratedAh.toFixed(0)} Ah`;
    if (pillValVoltage) pillValVoltage.textContent = `${Math.round(socVoltage)}%`;
    if (pillSubVoltage) pillSubVoltage.textContent = `${voltage > 0 ? voltage.toFixed(1) : '--'}V`;
    if (pillValBms) pillValBms.textContent = `${Math.round(socBms)}%`;
    if (pillSubBms) pillSubBms.textContent = `${resCap.toFixed(0)} Ah`;

    // Update Tri-SoC cards (Misc tab)
    if (valSocIntegrated) {
      valSocIntegrated.textContent = `${Math.round(socIntegrated)}%`;
    }
    if (valSocIntegratedSub) {
      valSocIntegratedSub.textContent = `${integratedAh.toFixed(1)} / ${nomCap.toFixed(0)} Ah`;
    }

    if (valSocVoltage) {
      valSocVoltage.textContent = `${Math.round(socVoltage)}%`;
    }
    if (valSocVoltageSub) {
      valSocVoltageSub.textContent = `${voltage > 0 ? voltage.toFixed(2) : '--.-'}V • ${vcellAvg > 0 ? vcellAvg.toFixed(3) : '-.---'}V/c`;
    }

    if (valSocBms) {
      valSocBms.textContent = `${Math.round(socBms)}%`;
    }
    if (valSocBmsSub) {
      valSocBmsSub.textContent = `${resCap.toFixed(1)} / ${nomCap.toFixed(0)} Ah`;
    }

    if (badgeBmsStatus) {
      if (isDesynced) {
        badgeBmsStatus.className = 'soc-badge-pill warn-pill';
        badgeBmsStatus.textContent = 'DESYNCED';
      } else {
        badgeBmsStatus.className = 'soc-badge-pill';
        badgeBmsStatus.textContent = 'JBD BMS';
      }
    }
    if (cardSocBms) {
      cardSocBms.title = isDesynced
        ? 'JBD BMS SoC: Tripped by under-voltage sag event'
        : 'JBD BMS SoC: Raw JBD Coulomb register';
    }

    // Hero SoC Gauge (driven by selected mode, defaulting to integrated)
    let displaySoc = socIntegrated;
    if (selectedSocMode === 'voltage') {
      displaySoc = socVoltage;
      if (val72vSocMode) val72vSocMode.textContent = 'VOLTAGE';
    } else if (selectedSocMode === 'bms') {
      displaySoc = socBms;
      if (val72vSocMode) val72vSocMode.textContent = 'BMS';
    } else {
      displaySoc = socIntegrated;
      if (val72vSocMode) val72vSocMode.textContent = 'INTEGRATED';
    }

    val72vSoc.textContent = Math.round(displaySoc);
    const offset = GAUGE_CIRCUMFERENCE * (1 - Math.min(100, Math.max(0, displaySoc)) / 100);
    socGaugeFill.style.strokeDashoffset = offset;

    // Hero Readouts
    val72vVoltage.textContent = voltage > 0 ? voltage.toFixed(2) : '--.-';
    val72vCurrent.textContent = current !== 0 ? current.toFixed(2) : '0.00';
    val72vPower.textContent = Math.abs(power).toLocaleString();

    // Update Mode Badge
    update72vBadge(data);

    // Secondary
    val72vCapacity.textContent = `${resCap.toFixed(1)} / ${nomCap.toFixed(0)} Ah`;
    val72vCycles.textContent = data.cycle_times ?? '--';

    // Temperatures
    if (Array.isArray(data.temperatures) && data.temperatures.length > 0) {
      val72vTemps.textContent = data.temperatures.map(t => `${t}°C`).join(', ');
    } else {
      val72vTemps.textContent = '--';
    }

    // FET Pills
    pillChgMos.className = `pill ${data.charge_status ? 'active' : ''}`;
    pillChgMos.textContent = `CHG: ${data.charge_status ? 'ON' : 'OFF'}`;
    pillDsgMos.className = `pill ${data.discharge_status ? 'active' : ''}`;
    pillDsgMos.textContent = `DSG: ${data.discharge_status ? 'ON' : 'OFF'}`;

    // Cell Voltage Spectrum
    const cells = Array.isArray(data.cell_voltages) ? data.cell_voltages : [];
    renderCellSpectrum(cells);
  }

  function renderCellSpectrum(cells) {
    if (!cells || cells.length === 0) return;

    cellCountLabel.textContent = `${cells.length}S`;
    const minV = Math.min(...cells);
    const maxV = Math.max(...cells);
    const deltaMv = Math.round((maxV - minV) * 1000);

    cellMinEl.textContent = `${minV.toFixed(3)}V`;
    cellMaxEl.textContent = `${maxV.toFixed(3)}V`;
    cellDeltaEl.textContent = `${deltaMv} mV`;

    // Adaptive visual scale: works for both NMC/Li-ion (~3.2 - 4.25V) and LFP (~2.8 - 3.65V)
    const isHighVoltageLiIon = maxV > 3.7;
    const vFloor = isHighVoltageLiIon ? 3.2 : 2.8;
    const vCeil = isHighVoltageLiIon ? 4.25 : 3.65;

    cellBarsContainer.innerHTML = '';
    cells.forEach((v, idx) => {
      const col = document.createElement('div');
      col.className = 'cell-bar-column';
      col.title = `Cell ${idx + 1}: ${v.toFixed(3)}V`;

      // Bar percentage
      const pct = Math.max(10, Math.min(100, ((v - vFloor) / (vCeil - vFloor)) * 100));

      const fill = document.createElement('div');
      fill.className = 'cell-bar-fill';
      fill.style.height = `${pct}%`;

      // Highlight cell if deviating
      const cellDelta = Math.abs(v - minV) * 1000;
      if (cellDelta > 45) {
        fill.classList.add('delta-crit');
      } else if (cellDelta > 25) {
        fill.classList.add('delta-warn');
      }

      const num = document.createElement('span');
      num.className = 'cell-bar-num';
      num.textContent = `${idx + 1}`;

      col.appendChild(fill);
      col.appendChild(num);
      cellBarsContainer.appendChild(col);
    });
  }

  function update12vSubsystem(data) {
    if (!data) return;
    cached12v = data;
    update12vBadge(data);

    // Battery Voltage & SoC
    const battV = parseFloat(data.battery_voltage) || 0;
    const battSoc = parseFloat(data.battery_soc) || 0;
    val12vBattV.textContent = battV > 0 ? battV.toFixed(2) : '--.-';

    if (battSoc > 0) {
      fill12vSoc.style.width = `${Math.min(100, battSoc)}%`;
      val12vBattSoc.textContent = `Capacity: ${Math.round(battSoc)}%`;
    }

    // Solar PV
    const solW = parseFloat(data.solar_power) || 0;
    const solV = parseFloat(data.solar_voltage) || 0;
    const solA = parseFloat(data.solar_current) || 0;
    val12vSolarW.textContent = solW.toFixed(0);
    val12vSolarV.textContent = `${solV.toFixed(1)}V`;
    val12vSolarA.textContent = `${solA.toFixed(1)}A`;

    // Status & Yield
    val12vState.textContent = data.charging_status || 'Active';
    val12vYield.textContent = data.daily_yield_kwh ? `${data.daily_yield_kwh} kWh` : '-- kWh';

    // Temperature & Load Output
    if (val12vTemp) {
      val12vTemp.textContent = (data.controller_temperature !== null && data.controller_temperature !== undefined)
        ? `${data.controller_temperature} °C`
        : '-- °C';
    }
    if (val12vLoad) {
      const loadA = parseFloat(data.load_current) || 0;
      const loadW = parseFloat(data.load_power) || 0;
      val12vLoad.textContent = `${loadA.toFixed(2)} A (${loadW.toFixed(0)} W)`;
    }

    // Raw Register Chips
    const rawKeys = data.raw_keys || {};
    const keyNames = Object.keys(rawKeys);
    if (val12vKeycount) val12vKeycount.textContent = `${keyNames.length} topics`;

    if (keyNames.length > 0) {
      registerChips.innerHTML = '';
      keyNames.slice(0, 24).forEach(k => {
        const chip = document.createElement('div');
        chip.className = 'reg-chip';
        chip.innerHTML = `<span class="reg-chip-key">${k}:</span><span class="reg-chip-val">${rawKeys[k]}</span>`;
        registerChips.appendChild(chip);
      });
    }
  }

  // ---------------- Navigation & GPS Subsystem ----------------

  function getCardinalDirection(angle) {
    if (angle === null || angle === undefined || isNaN(angle)) return '--';
    const directions = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
    const index = Math.round(((angle % 360) / 22.5)) % 16;
    return directions[index];
  }

  function updateGpsSubsystem(data) {
    if (!data) return;
    cachedGps = data;

    const hasFix = Boolean(data.fix);
    const sogKnots = parseFloat(data.sog_knots) || 0.0;
    const sogKmh = parseFloat(data.sog_kmh) || (sogKnots * 1.852);
    const sogMs = parseFloat(data.sog_ms) || (sogKnots * 0.514444);
    const cogTrue = data.cog_true !== null && data.cog_true !== undefined ? parseFloat(data.cog_true) : null;
    const latNautical = data.latitude_nautical || "--° --.---' -";
    const lonNautical = data.longitude_nautical || "---° --.---' -";
    const latDec = data.latitude;
    const lonDec = data.longitude;
    const sats = parseInt(data.satellites, 10) || 0;
    const hdop = parseFloat(data.hdop);
    const alt = parseFloat(data.altitude_m);

    const ageSeconds = data.last_updated ? Math.floor((Date.now() - new Date(data.last_updated).getTime()) / 1000) : 9999;
    const isStale = ageSeconds > 15;

    // Fix Badge
    if (valGpsFixBadge) {
      if (isStale) {
        valGpsFixBadge.className = 'card-badge amber-badge';
        valGpsFixBadge.textContent = 'AWAITING FEED';
      } else if (hasFix) {
        valGpsFixBadge.className = 'card-badge green-badge';
        valGpsFixBadge.textContent = '3D FIX';
      } else {
        valGpsFixBadge.className = 'card-badge amber-badge';
        valGpsFixBadge.textContent = data.fix_status === 'A' ? 'FIX ACQUIRED' : 'SEARCHING';
      }
    }

    // Speed Over Ground
    if (valGpsSogKnots) valGpsSogKnots.textContent = isStale ? '--.-' : sogKnots.toFixed(1);
    if (valGpsSogKmh) valGpsSogKmh.textContent = isStale ? '--.- km/h' : `${sogKmh.toFixed(1)} km/h`;
    if (valGpsSogMs) valGpsSogMs.textContent = isStale ? '--.- m/s' : `${sogMs.toFixed(1)} m/s`;

    // Course Over Ground
    if (valGpsCog) valGpsCog.textContent = isStale || cogTrue === null ? '---°' : `${Math.round(cogTrue).toString().padStart(3, '0')}°`;
    if (valGpsHeadingCardinal) valGpsHeadingCardinal.textContent = isStale ? '--' : getCardinalDirection(cogTrue);
    if (valGpsMode) valGpsMode.textContent = isStale ? 'AWAITING NMEA' : (hasFix ? 'GNSS LOCK' : 'NO FIX');

    // Position
    if (valGpsLatNautical) valGpsLatNautical.textContent = latNautical;
    if (valGpsLonNautical) valGpsLonNautical.textContent = lonNautical;
    if (valGpsCoordsDec) {
      if (latDec !== null && lonDec !== null && !isNaN(latDec) && !isNaN(lonDec)) {
        valGpsCoordsDec.textContent = `${latDec.toFixed(5)}, ${lonDec.toFixed(5)}`;
      } else {
        valGpsCoordsDec.textContent = '--.------, ---.------';
      }
    }

    // Secondary metrics
    if (valGpsQuality) {
      const q = parseInt(data.fix_quality, 10);
      valGpsQuality.textContent = isStale ? 'Waiting for Router' : (q === 1 ? 'GPS SPS' : q === 2 ? 'DGPS' : hasFix ? 'Active Fix' : 'No Fix');
    }
    if (valGpsSats) valGpsSats.textContent = isStale ? '0 sats' : `${sats} sats`;
    if (valGpsHdop) valGpsHdop.textContent = !isStale && !isNaN(hdop) && hdop > 0 ? hdop.toFixed(1) : '--.-';
    if (valGpsAltitude) valGpsAltitude.textContent = !isStale && !isNaN(alt) ? `${alt.toFixed(1)} m` : '--.- m';

    // Map Action Link
    if (linkGpsMap) {
      if (latDec !== null && lonDec !== null && !isNaN(latDec) && !isNaN(lonDec)) {
        linkGpsMap.href = `https://www.openstreetmap.org/?mlat=${latDec}&mlon=${lonDec}#map=15/${latDec}/${lonDec}`;
        linkGpsMap.classList.remove('disabled');
      } else {
        linkGpsMap.href = '#';
        linkGpsMap.classList.add('disabled');
      }
    }

    // NMEA Sentence badge
    if (valGpsSentence) {
      valGpsSentence.textContent = data.last_sentence ? `NMEA: $${data.last_sentence}` : 'NMEA: --';
    }
  }

  // ---------------- MQTT Log Table ----------------

  function matchesFilter(topic, filter) {
    if (filter === 'all') return true;
    if (filter === '72v' && (topic.includes('72v') || topic.includes('bms') || topic.includes('charger'))) return true;
    if (filter === '12v' && (topic.includes('12v') || topic.includes('solar'))) return true;
    if (filter === 'gps' && (topic.includes('gps') || topic.includes('nmea'))) return true;
    if (filter === 'other' && !topic.includes('72v') && !topic.includes('12v') && !topic.includes('gps') && !topic.includes('charger')) return true;
    return false;
  }

  function updateChargerSubsystem(data) {
    const el = document.getElementById('val-charger-status');
    if (!el) return;
    if (!data || data.state === 'OFFLINE') {
      el.textContent = 'OFFLINE';
      el.className = 'submetric-val mono';
      return;
    }
    const curr = parseFloat(data.output_current) || 0.0;
    const volt = parseFloat(data.output_voltage) || 0.0;
    const pwr = parseFloat(data.output_power) || Math.round(curr * volt);
    const state = data.state || (curr > 0.5 ? 'CHARGING' : 'IDLE');

    if (state === 'CHARGING') {
      el.textContent = `${curr.toFixed(1)}A • ${pwr}W`;
      el.className = 'submetric-val mono glow-green';
    } else {
      el.textContent = `${state}`;
      el.className = 'submetric-val mono';
    }
  }

  function renderLogRow(packet) {
    const tr = document.createElement('tr');
    tr.dataset.topic = packet.topic;

    // Time
    const timeTd = document.createElement('td');
    timeTd.className = 'mono';
    const dateObj = new Date(packet.timestamp);
    timeTd.textContent = dateObj.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });

    // Topic
    const topicTd = document.createElement('td');
    const badge = document.createElement('span');
    badge.className = 'topic-badge ' + (
      (packet.topic.includes('72v') || packet.topic.includes('charger')) ? 'topic-72v' :
      packet.topic.includes('12v') ? 'topic-12v' :
      packet.topic.includes('gps') ? 'topic-gps' : 'topic-other'
    );
    badge.textContent = packet.topic;
    topicTd.appendChild(badge);

    // Payload
    const payloadTd = document.createElement('td');
    payloadTd.className = 'payload-cell';
    const payloadStr = typeof packet.payload === 'object' ? JSON.stringify(packet.payload) : String(packet.payload);
    payloadTd.textContent = payloadStr.length > 180 ? payloadStr.substring(0, 180) + '…' : payloadStr;
    payloadTd.title = payloadStr;

    // Source
    const srcTd = document.createElement('td');
    srcTd.style.textAlign = 'right';
    srcTd.innerHTML = `<span class="source-badge">${packet.source || 'mqtt'}</span>`;

    tr.appendChild(timeTd);
    tr.appendChild(topicTd);
    tr.appendChild(payloadTd);
    tr.appendChild(srcTd);

    if (!matchesFilter(packet.topic, activeFilter)) {
      tr.style.display = 'none';
    }

    return tr;
  }

  function addPacketToLog(packet) {
    if (isLogPaused) return;

    // Remove empty row if present
    const emptyRow = logRowsContainer.querySelector('.empty-row');
    if (emptyRow) emptyRow.remove();

    const row = renderLogRow(packet);
    logRowsContainer.prepend(row);

    // Keep under limit
    while (logRowsContainer.children.length > MAX_LOG_ROWS) {
      logRowsContainer.removeChild(logRowsContainer.lastChild);
    }
  }

  // ---------------- Event Listeners ----------------

  // Filter Buttons
  filterBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      filterBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      activeFilter = btn.dataset.filter;

      // Apply filter to visible rows
      Array.from(logRowsContainer.children).forEach(row => {
        if (!row.dataset.topic) return;
        row.style.display = matchesFilter(row.dataset.topic, activeFilter) ? '' : 'none';
      });
    });
  });

  // Pause / Resume Button
  btnPauseLog.addEventListener('click', () => {
    isLogPaused = !isLogPaused;
    btnPauseLog.textContent = isLogPaused ? 'Resume' : 'Pause';
    btnPauseLog.style.color = isLogPaused ? 'var(--amber)' : '';
  });

  // Clear Button
  btnClearLog.addEventListener('click', () => {
    logRowsContainer.innerHTML = '<tr class="empty-row"><td colspan="4">Log cleared. Waiting for new packets...</td></tr>';
  });

  // ---------------- Tab Navigation ----------------
  const navTabs = document.querySelectorAll('.nav-tab');
  const tabPanels = document.querySelectorAll('.tab-panel');

  function switchTab(tabId) {
    navTabs.forEach(btn => {
      btn.classList.toggle('active', btn.dataset.tab === tabId);
    });
    tabPanels.forEach(panel => {
      panel.classList.toggle('active', panel.id === `tab-panel-${tabId}`);
    });
    localStorage.setItem('paeraki_active_tab', tabId);
  }

  navTabs.forEach(btn => {
    btn.addEventListener('click', () => {
      const tabId = btn.dataset.tab;
      if (tabId) switchTab(tabId);
    });
  });

  const savedTab = localStorage.getItem('paeraki_active_tab') || '72v';
  switchTab(savedTab);

  // ---------------- Tri-Method SoC Event Handlers ----------------
  const socModes = ['integrated', 'voltage', 'bms'];
  selectedSocMode = localStorage.getItem('paeraki_soc_mode') || 'integrated';

  const pillModeVoltage = document.getElementById('pill-mode-voltage');
  const pillModeBms = document.getElementById('pill-mode-bms');
  const socGaugeContainer = document.getElementById('soc-gauge-container');

  function setSocMode(mode) {
    if (!socModes.includes(mode)) mode = 'integrated';
    selectedSocMode = mode;
    localStorage.setItem('paeraki_soc_mode', mode);

    // Update 72V panel pills
    [pillModeIntegrated, pillModeVoltage, pillModeBms].forEach(p => {
      if (p) p.classList.toggle('active', p.dataset.mode === mode);
    });

    // Update Misc tab cards
    [cardSocIntegrated, cardSocVoltage, cardSocBms].forEach(c => {
      if (c) c.classList.toggle('active', c.dataset.mode === mode);
    });

    if (cached72v) {
      update72vSubsystem(cached72v);
    }
  }

  [pillModeIntegrated, pillModeVoltage, pillModeBms].forEach(pill => {
    if (pill) {
      pill.addEventListener('click', () => setSocMode(pill.dataset.mode));
    }
  });

  if (cardSocIntegrated) {
    cardSocIntegrated.addEventListener('click', () => setSocMode('integrated'));
  }
  if (cardSocVoltage) {
    cardSocVoltage.addEventListener('click', () => setSocMode('voltage'));
  }
  if (cardSocBms) {
    cardSocBms.addEventListener('click', () => setSocMode('bms'));
  }

  // Tapping the big gauge cycles through modes
  if (socGaugeContainer) {
    socGaugeContainer.addEventListener('click', () => {
      const nextIdx = (socModes.indexOf(selectedSocMode) + 1) % socModes.length;
      setSocMode(socModes[nextIdx]);
    });
  }

  // Restore active SoC mode on boot
  setSocMode(selectedSocMode);

  // ---------------- Server Endpoint Detection ----------------
  function getServerHost() {
    const saved = localStorage.getItem('paeraki_server_host');
    if (saved && saved.trim()) return saved.trim();

    // If running in Capacitor / native webview or file:// or localhost without port
    const isNative = window.Capacitor !== undefined ||
                     window.location.protocol === 'capacitor:' ||
                     window.location.protocol === 'file:' ||
                     (window.location.hostname === 'localhost' && (!window.location.port || window.location.port === '80' || window.location.port === '443'));

    if (isNative) {
      return '192.168.1.101:8080';
    }
    return window.location.host;
  }

  function getApiUrl(path) {
    const host = getServerHost();
    const cleanHost = host.replace(/^https?:\/\//, '');
    const isHttps = (window.location.protocol === 'https:' && !host.includes('192.168.')) || host.startsWith('https://');
    const protocol = isHttps ? 'https:' : 'http:';
    const cleanPath = path.startsWith('/') ? path : `/${path}`;
    return `${protocol}//${cleanHost}${cleanPath}`;
  }

  function getWsUrl(path = '/ws') {
    const host = getServerHost();
    const cleanHost = host.replace(/^https?:\/\//, '').replace(/^wss?:\/\//, '');
    const isHttps = (window.location.protocol === 'https:' && !host.includes('192.168.')) || host.startsWith('https://') || host.startsWith('wss://');
    const protocol = isHttps ? 'wss:' : 'ws:';
    const cleanPath = path.startsWith('/') ? path : `/${path}`;
    return `${protocol}//${cleanHost}${cleanPath}`;
  }

  if (btnSyncSoc) {
    btnSyncSoc.addEventListener('click', async () => {
      btnSyncSoc.disabled = true;
      const originalHtml = btnSyncSoc.innerHTML;
      btnSyncSoc.textContent = 'Syncing...';
      try {
        const resp = await fetch(getApiUrl('/api/72v/calibrate_soc'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ sync_to_voltage: true }),
        });
        if (resp.ok) {
          const res = await resp.json();
          if (res.system_72v) {
            update72vSubsystem(res.system_72v);
          }
          btnSyncSoc.textContent = 'Synced ✓';
        } else {
          btnSyncSoc.textContent = 'Failed!';
        }
      } catch (err) {
        console.error('Calibration error:', err);
        btnSyncSoc.textContent = 'Error!';
      }
      setTimeout(() => {
        btnSyncSoc.innerHTML = originalHtml;
        btnSyncSoc.disabled = false;
      }, 2000);
    });
  }

  // ---------------- WebSocket Connection ----------------

  let socket = null;
  let reconnectDelay = 1000;

  function connectWebSocket() {
    const wsUrl = getWsUrl('/ws');

    console.log('[Paeraki Monitor] Connecting to WebSocket:', wsUrl);
    try {
      socket = new WebSocket(wsUrl);
    } catch (e) {
      console.error('[Paeraki Monitor] WebSocket init failed:', e);
      setTimeout(connectWebSocket, reconnectDelay);
      return;
    }

    socket.onopen = () => {
      console.log('[Paeraki Monitor] WebSocket connected to', wsUrl);
      reconnectDelay = 1000;
    };

    socket.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);

        if (msg.type === 'snapshot' && msg.snapshot) {
          updateBrokerHeader(msg.snapshot.broker, msg.snapshot.server);
          update72vSubsystem(msg.snapshot.subsystems['72v']);
          update12vSubsystem(msg.snapshot.subsystems['12v']);
          updateGpsSubsystem(msg.snapshot.subsystems['gps']);
          updateChargerSubsystem(msg.snapshot.subsystems?.['charger']);
          if (Array.isArray(msg.snapshot.recent_packets)) {
            msg.snapshot.recent_packets.slice().reverse().forEach(p => addPacketToLog(p));
          }
        } else if (msg.type === 'packet' && msg.packet) {
          addPacketToLog(msg.packet);
          if (msg.snapshot) {
            updateBrokerHeader(msg.snapshot.broker, msg.snapshot.server);
            update72vSubsystem(msg.snapshot.subsystems['72v']);
            update12vSubsystem(msg.snapshot.subsystems['12v']);
            updateGpsSubsystem(msg.snapshot.subsystems['gps']);
            updateChargerSubsystem(msg.snapshot.subsystems?.['charger']);
          }
        } else if (msg.type === 'connection_status') {
          if (msg.connected) {
            connDot.className = 'pulse-dot connected';
            connLabel.textContent = 'Connected to Paeraki';
          } else {
            connDot.className = 'pulse-dot error';
            connLabel.textContent = 'Broker Disconnected';
          }
        }
      } catch (err) {
        console.error('[Paeraki Monitor] Error processing message:', err);
      }
    };

    socket.onclose = () => {
      console.warn(`[Paeraki Monitor] WebSocket closed. Reconnecting in ${reconnectDelay}ms...`);
      connDot.className = 'pulse-dot error';
      connLabel.textContent = 'Server Offline';
      setTimeout(connectWebSocket, reconnectDelay);
      reconnectDelay = Math.min(10000, reconnectDelay * 1.5);
    };

    socket.onerror = (err) => {
      console.error('[Paeraki Monitor] WebSocket error:', err);
      socket.close();
    };
  }

  // Initial HTTP snapshot fetch for fast load
  fetch(getApiUrl('/api/state'))
    .then(r => r.json())
    .then(snapshot => {
      if (snapshot) {
        updateBrokerHeader(snapshot.broker, snapshot.server);
        update72vSubsystem(snapshot.subsystems?.['72v']);
        update12vSubsystem(snapshot.subsystems?.['12v']);
        updateGpsSubsystem(snapshot.subsystems?.['gps']);
        updateChargerSubsystem(snapshot.subsystems?.['charger']);
        if (Array.isArray(snapshot.recent_packets)) {
          snapshot.recent_packets.slice().reverse().forEach(p => addPacketToLog(p));
        }
      }
    })
    .catch((err) => {
      console.warn('[Paeraki Monitor] Initial state fetch failed:', err);
    })
    .finally(() => {
      connectWebSocket();
    });

  // Keep-alive ping
  setInterval(() => {
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send('ping');
    }
  }, 20000);

  // ---------------- PWA Service Worker & Install Prompt ----------------
  const isCapacitor = window.Capacitor !== undefined ||
                      window.location.protocol === 'capacitor:' ||
                      (window.location.hostname === 'localhost' && (!window.location.port || window.location.port === '80' || window.location.port === '443'));
  if (!isCapacitor && 'serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/sw.js')
        .then(reg => console.log('[PWA] ServiceWorker registered with scope:', reg.scope))
        .catch(err => console.warn('[PWA] ServiceWorker registration error:', err));
    });
  }

  let deferredPrompt = null;
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredPrompt = e;
    console.log('[PWA] beforeinstallprompt fired');
    const pwaBtn = document.getElementById('btn-pwa-install');
    if (pwaBtn) {
      pwaBtn.style.display = 'inline-flex';
      pwaBtn.addEventListener('click', () => {
        if (deferredPrompt) {
          deferredPrompt.prompt();
          deferredPrompt.userChoice.then(() => {
            deferredPrompt = null;
            pwaBtn.style.display = 'none';
          });
        }
      });
    }
  });

})();
