// Paeraki Vessel Telemetry Monitor - Frontend Client
(function() {
  'use strict';

  // ---------------- Cache & Service Worker Invalidation ----------------
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.getRegistrations().then(registrations => {
      for (const reg of registrations) {
        reg.unregister().then(() => console.log('[SW] Purged service worker:', reg.scope));
      }
    }).catch(() => {});
  }
  if ('caches' in window) {
    caches.keys().then(keys => {
      for (const key of keys) caches.delete(key);
    }).catch(() => {});
  }

  // DOM Elements - Connection & Header
  const connDot = document.getElementById('conn-dot');
  const connLabel = document.getElementById('conn-label');
  const brokerEndpoint = document.getElementById('broker-endpoint');
  const totalPacketsEl = document.getElementById('total-packets');
  const packetRateEl = document.getElementById('packet-rate');
  const lastSeenEl = document.getElementById('last-seen');
  const btnContrastToggle = document.getElementById('btn-contrast-toggle');

  // Home Tab DOM Elements
  const homeCardPower = document.getElementById('home-card-power');
  const homeCardSpeed = document.getElementById('home-card-speed');
  const homeCardHeading = document.getElementById('home-card-heading');
  const homeCard72v = document.getElementById('home-card-72v');
  const homeCard12v = document.getElementById('home-card-12v');

  const homeVal72vW = document.getElementById('home-val-72v-w');
  const homeVal72vSub = document.getElementById('home-val-72v-sub');
  const homeValGpsSog = document.getElementById('home-val-gps-sog');
  const homeValGpsSogSub = document.getElementById('home-val-gps-sog-sub');
  const homeValGpsCog = document.getElementById('home-val-gps-cog');
  const homeValGpsCardinal = document.getElementById('home-val-gps-cardinal');
  const homeValGpsSats = document.getElementById('home-val-gps-sats');

  const homeVal72vSoc = document.getElementById('home-val-72v-soc');
  const home72vModeBadge = document.getElementById('home-72v-mode-badge');
  const home72vBarFill = document.getElementById('home-72v-bar-fill');
  const homeVal72vCap = document.getElementById('home-val-72v-cap');
  const homeVal72vMeta = document.getElementById('home-val-72v-meta');

  const homeVal12vSoc = document.getElementById('home-val-12v-soc');
  const home12vStatusBadge = document.getElementById('home-12v-status-badge');
  const home12vBarFill = document.getElementById('home-12v-bar-fill');
  const homeVal12vCap = document.getElementById('home-val-12v-cap');
  const homeVal12vSub = document.getElementById('home-val-12v-sub');
  const homeStatusBadge = document.getElementById('home-status-badge');

  // 72V DOM Elements
  const val72vSoc = document.getElementById('val-72v-soc');
  const val72vSocMode = document.getElementById('val-72v-soc-mode');
  const socGaugeFill = document.getElementById('soc-gauge-fill');
  const socGaugeContainer = document.getElementById('soc-gauge-container');
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
  const cellHoverVal = document.getElementById('cell-hover-val');
  const cellHoverStat = document.getElementById('cell-hover-stat');
  const cellHoverSep = document.getElementById('cell-hover-sep');

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
  const pillModeIntegrated = document.getElementById('pill-mode-integrated');
  const pillModeVoltage = document.getElementById('pill-mode-voltage');
  const pillModeBms = document.getElementById('pill-mode-bms');

  // 12V DOM Elements
  const val12vBattV = document.getElementById('val-12v-batt-v');
  const val12vBattSoc = document.getElementById('val-12v-batt-soc');
  const val12vOcvSoc = document.getElementById('val-12v-ocv-soc');
  const fill12vSoc = document.getElementById('fill-12v-soc');
  const val12vSolarW = document.getElementById('val-12v-solar-w');
  const val12vSolarV = document.getElementById('val-12v-solar-v');
  const val12vSolarA = document.getElementById('val-12v-solar-a');
  const val12vState = document.getElementById('val-12v-state');
  const solarModeBadge = document.getElementById('solar-mode-badge');
  const val12vYield = document.getElementById('val-12v-yield');
  const val12vNetFlux = document.getElementById('val-12v-net-flux');
  const val12vBattTemp = document.getElementById('val-12v-batt-temp');
  const val12vCtrlTemp = document.getElementById('val-12v-ctrl-temp');
  const val12vLoad = document.getElementById('val-12v-load');

  // GPS DOM Elements
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
  let cached72v = null;
  let cached12v = null;
  let cachedGps = null;
  let selectedSocMode = 'integrated'; // Default to displaying the dashboard integrated SOC
  const GAUGE_CIRCUMFERENCE = 2 * Math.PI * 50; // 314.159

  // Initialize SVG Gauges (72V Detail Tab)
  if (socGaugeFill) {
    socGaugeFill.style.strokeDasharray = GAUGE_CIRCUMFERENCE;
    socGaugeFill.style.strokeDashoffset = GAUGE_CIRCUMFERENCE;
  }

  // Home Card Click Handlers -> Navigate to detail tabs
  if (homeCardPower) homeCardPower.addEventListener('click', () => switchTab('72v'));
  if (homeCardSpeed) homeCardSpeed.addEventListener('click', () => switchTab('gps'));
  if (homeCardHeading) homeCardHeading.addEventListener('click', () => switchTab('gps'));
  if (homeCard72v) homeCard72v.addEventListener('click', () => switchTab('72v'));
  if (homeCard12v) homeCard12v.addEventListener('click', () => switchTab('12v'));

  // ---------------- Sunlight Mode (Daylight Theme) ----------------
  const urlParams = new URLSearchParams(window.location.search);
  let isHighContrast = urlParams.get('sunlight') === '1' || (localStorage.getItem('paeraki_high_contrast') === 'true');

  function applyHighContrast(enabled) {
    document.body.classList.toggle('high-contrast', enabled);
    if (btnContrastToggle) {
      btnContrastToggle.classList.toggle('active', enabled);
      const icon = document.getElementById('theme-icon') || btnContrastToggle.querySelector('.theme-icon') || btnContrastToggle.querySelector('.contrast-icon');
      if (icon) icon.textContent = enabled ? '🌙' : '☀️';
      btnContrastToggle.title = enabled ? 'Switch to Dark Theme' : 'Switch to Daylight Theme';
    }
    localStorage.setItem('paeraki_high_contrast', enabled ? 'true' : 'false');
  }

  if (btnContrastToggle) {
    btnContrastToggle.addEventListener('click', () => {
      isHighContrast = !isHighContrast;
      applyHighContrast(isHighContrast);
    });
  }
  applyHighContrast(isHighContrast);

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

  const urlTab = urlParams.get('tab');
  const savedTab = urlTab || localStorage.getItem('paeraki_active_tab') || 'home';
  switchTab(savedTab);

  // ---------------- Cardinal Direction Helper ----------------
  function getCardinalDirection(angle) {
    if (angle === null || angle === undefined || isNaN(angle)) return '--';
    const directions = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
    const index = Math.round(((angle % 360) / 22.5)) % 16;
    return directions[index];
  }

  // ---------------- Home Tab Update Pipeline ----------------
  function updateHomeTab() {
    // 1. 72V Propulsion Instrument (SoC + Power)
    if (cached72v) {
      const vTotal = parseFloat(cached72v.total_voltage) || 0;
      const curr = parseFloat(cached72v.current) || 0;
      const pwr = parseFloat(cached72v.power) !== undefined && !isNaN(parseFloat(cached72v.power))
        ? parseFloat(cached72v.power)
        : Math.round(vTotal * curr);
      const capNom = parseFloat(cached72v.nominal_capacity_ah) || 200.0;

      let displaySoc = 0.0;
      if (selectedSocMode === 'voltage') {
        displaySoc = parseFloat(cached72v.soc_voltage) || 0.0;
      } else if (selectedSocMode === 'bms') {
        displaySoc = parseFloat(cached72v.soc_bms || cached72v.rsoc) || 0.0;
      } else {
        displaySoc = parseFloat(cached72v.soc_integrated) || 0.0;
      }

      if (homeVal72vSoc) homeVal72vSoc.textContent = displaySoc > 0 ? `${displaySoc.toFixed(1)}%` : '--.-%';
      if (home72vModeBadge) home72vModeBadge.textContent = selectedSocMode.toUpperCase();
      if (homeVal72vW) homeVal72vW.textContent = Math.abs(pwr) < 10000 ? `${Math.round(pwr)}` : `${(pwr / 1000).toFixed(1)}k`;
      if (homeVal72vSub) homeVal72vSub.textContent = `${vTotal > 0 ? vTotal.toFixed(1) : '--.-'} V · ${curr >= 0 ? '+' : ''}${curr.toFixed(1)} A`;

      if (home72vBarFill) {
        const clamped = Math.min(100, Math.max(0, displaySoc));
        home72vBarFill.style.width = `${clamped}%`;
      }

      const intAh = parseFloat(cached72v.integrated_ah) || 0;
      if (homeVal72vCap) {
        homeVal72vCap.textContent = `${intAh.toFixed(1)} / ${capNom.toFixed(0)} Ah`;
      }
      if (homeVal72vMeta) {
        const soh = cached72v.soh_percentage ? ` · ${cached72v.soh_percentage}% SoH` : '';
        homeVal72vMeta.textContent = `${vTotal > 0 ? vTotal.toFixed(1) : '--.-'} V${soh}`;
      }
    }

    // 2. 12V House AGM Instrument
    if (cached12v) {
      const battV = parseFloat(cached12v.battery_voltage) || 0;
      const soc12 = cached12v.soc_12v_active !== undefined ? parseFloat(cached12v.soc_12v_active) : (parseFloat(cached12v.battery_soc) || 0);
      const chgI = parseFloat(cached12v.battery_charge_current) || 0;
      const loadI = parseFloat(cached12v.load_current) || 0;
      const netI = cached12v.net_12v_current !== undefined ? parseFloat(cached12v.net_12v_current) : (chgI - loadI);
      const nomCap = parseFloat(cached12v.nominal_12v_capacity_ah || cached12v.nominal_capacity_ah) || 100.0;
      const intAh = parseFloat(cached12v.integrated_12v_ah || cached12v.integrated_ah) || 0.0;

      if (homeVal12vSoc) homeVal12vSoc.textContent = soc12 > 0 ? `${soc12.toFixed(0)}%` : '--%';
      if (home12vStatusBadge) home12vStatusBadge.textContent = (cached12v.charging_status || 'FLOAT').toUpperCase();
      if (homeVal12vSub) homeVal12vSub.textContent = `${battV > 0 ? battV.toFixed(2) : '--.-'} V · Net ${netI >= 0 ? '+' : ''}${netI.toFixed(1)} A`;

      if (home12vBarFill) {
        const clamped = Math.min(100, Math.max(0, soc12));
        home12vBarFill.style.width = `${clamped}%`;
      }

      if (homeVal12vCap) {
        homeVal12vCap.textContent = `${intAh.toFixed(1)} / ${nomCap.toFixed(0)} Ah`;
      }
    }

    // 3. Navigation Instrument (SOG + Heading COG)
    if (cachedGps) {
      const hasFix = Boolean(cachedGps.fix);
      const sogKnots = parseFloat(cachedGps.sog_knots) || 0.0;
      const sogKmh = parseFloat(cachedGps.sog_kmh) || (sogKnots * 1.852);
      const cogTrue = cachedGps.cog_true !== null && cachedGps.cog_true !== undefined ? parseFloat(cachedGps.cog_true) : null;
      const sats = cachedGps.satellites !== undefined ? cachedGps.satellites : '--';

      if (homeValGpsSog) homeValGpsSog.textContent = sogKnots.toFixed(1);
      if (homeValGpsSogSub) homeValGpsSogSub.textContent = `${sogKmh.toFixed(1)} km/h`;

      if (homeValGpsCog) {
        homeValGpsCog.textContent = cogTrue !== null ? `${Math.round(cogTrue)}°` : '---°';
      }
      if (homeValGpsCardinal) {
        homeValGpsCardinal.textContent = cogTrue !== null ? getCardinalDirection(cogTrue) : '--';
      }
      if (homeValGpsSats) {
        homeValGpsSats.textContent = hasFix ? `3D Fix (${sats} sats)` : 'Searching...';
      }
    }
  }


  // ---------------- 72V Subsystem ----------------
  function update72vSubsystem(data) {
    if (!data) return;
    cached72v = data;

    const vTotal = parseFloat(data.total_voltage) || 0;
    const curr = parseFloat(data.current) || 0;
    const pwr = parseFloat(data.power) || Math.round(vTotal * curr);
    const capRes = parseFloat(data.residual_capacity_ah) || 0;
    const capNom = parseFloat(data.nominal_capacity_ah) || 200.0;
    const cycles = data.cycle_times !== undefined ? data.cycle_times : '--';

    const socIntegrated = data.soc_integrated !== undefined ? parseFloat(data.soc_integrated) : 0.0;
    const socVoltage = data.soc_voltage !== undefined ? parseFloat(data.soc_voltage) : 0.0;
    const socBms = data.soc_bms !== undefined ? parseFloat(data.soc_bms) : (data.rsoc || 0);

    let activeSoc = socIntegrated;
    let modeText = 'INTEGRATED';

    if (selectedSocMode === 'voltage') {
      activeSoc = socVoltage;
      modeText = 'VOLTAGE';
    } else if (selectedSocMode === 'bms') {
      activeSoc = socBms;
      modeText = 'BMS';
    }

    if (val72vSoc) val72vSoc.textContent = activeSoc.toFixed(1);
    if (val72vSocMode) val72vSocMode.textContent = modeText;
    if (val72vVoltage) val72vVoltage.textContent = vTotal > 0 ? vTotal.toFixed(2) : '--.-';
    if (val72vCurrent) val72vCurrent.textContent = curr.toFixed(2);
    if (val72vPower) val72vPower.textContent = Math.round(pwr);

    if (socGaugeFill) {
      const offset = GAUGE_CIRCUMFERENCE - (Math.min(100, Math.max(0, activeSoc)) / 100) * GAUGE_CIRCUMFERENCE;
      socGaugeFill.style.strokeDashoffset = offset;
    }

    if (val72vCapacity) {
      val72vCapacity.textContent = `${(data.integrated_ah || capRes).toFixed(1)} / ${capNom.toFixed(0)} Ah`;
    }
    if (val72vCycles) val72vCycles.textContent = cycles;

    // Badge logic
    if (bmsStateBadge) {
      if (Math.abs(curr) < 0.3) {
        bmsStateBadge.textContent = 'IDLE';
        bmsStateBadge.className = 'card-badge green-badge';
      } else if (curr > 0.3) {
        bmsStateBadge.textContent = 'CHARGING';
        bmsStateBadge.className = 'card-badge cyan-badge';
      } else {
        bmsStateBadge.textContent = 'MOTORING';
        bmsStateBadge.className = 'card-badge amber-badge';
      }
    }

    // Switch Pills
    if (pillChgMos) {
      pillChgMos.textContent = `CHG: ${data.charge_status ? 'ON' : 'OFF'}`;
      pillChgMos.className = 'pill ' + (data.charge_status ? 'pill-on' : 'pill-off');
    }
    if (pillDsgMos) {
      pillDsgMos.textContent = `DSG: ${data.discharge_status ? 'ON' : 'OFF'}`;
      pillDsgMos.className = 'pill ' + (data.discharge_status ? 'pill-on' : 'pill-off');
    }

    // Temperatures
    if (val72vTemps) {
      const t = data.temperatures;
      if (Array.isArray(t) && t.length > 0) {
        val72vTemps.textContent = t.map(v => `${Math.round(v)}°C`).join(' • ');
      } else {
        val72vTemps.textContent = '--';
      }
    }

    // Mode Selector Pills
    if (pillModeIntegrated) {
      const elPct = pillModeIntegrated.querySelector('.soc-pill-pct');
      const elSub = pillModeIntegrated.querySelector('.soc-pill-sub');
      if (elPct) elPct.textContent = `${socIntegrated.toFixed(1)}%`;
      if (elSub) elSub.textContent = `${(data.integrated_ah || 0).toFixed(1)} Ah`;
    }
    if (pillModeVoltage) {
      const elPct = pillModeVoltage.querySelector('.soc-pill-pct');
      const elSub = pillModeVoltage.querySelector('.soc-pill-sub');
      if (elPct) elPct.textContent = `${socVoltage.toFixed(1)}%`;
      if (elSub) elSub.textContent = `${vTotal.toFixed(1)} V`;
    }
    if (pillModeBms) {
      const elPct = pillModeBms.querySelector('.soc-pill-pct');
      const elSub = pillModeBms.querySelector('.soc-pill-sub');
      if (elPct) elPct.textContent = `${socBms.toFixed(0)}%`;
      if (elSub) elSub.textContent = `${capRes.toFixed(1)} Ah`;
    }

    // Misc Tab Comparison Cards
    if (valSocIntegrated) valSocIntegrated.textContent = `${socIntegrated.toFixed(1)}%`;
    if (valSocIntegratedSub) valSocIntegratedSub.textContent = `${(data.integrated_ah || 0).toFixed(1)} / ${capNom.toFixed(0)} Ah`;

    if (valSocVoltage) valSocVoltage.textContent = `${socVoltage.toFixed(1)}%`;
    if (valSocVoltageSub) valSocVoltageSub.textContent = `${vTotal.toFixed(2)} V (${(vTotal / 20).toFixed(3)} V/cell)`;

    if (valSocBms) valSocBms.textContent = `${socBms.toFixed(0)}%`;
    if (valSocBmsSub) valSocBmsSub.textContent = `${capRes.toFixed(1)} / ${capNom.toFixed(0)} Ah`;

    // 20S Cell Bars
    renderCellBars(data.cell_voltages || []);

    // Refresh Home Tab Instrument
    updateHomeTab();
  }

  function renderCellBars(cells) {
    if (!cells || cells.length === 0) return;
    if (cellCountLabel) cellCountLabel.textContent = `${cells.length}S`;

    let minV = 999;
    let maxV = -999;
    cells.forEach(v => {
      if (v < minV) minV = v;
      if (v > maxV) maxV = v;
    });
    const deltaMv = Math.round((maxV - minV) * 1000);

    if (cellMinEl) cellMinEl.textContent = `${minV.toFixed(3)}V`;
    if (cellMaxEl) cellMaxEl.textContent = `${maxV.toFixed(3)}V`;
    if (cellDeltaEl) {
      cellDeltaEl.textContent = `${deltaMv} mV`;
      cellDeltaEl.className = 'stat-num mono' + (deltaMv > 60 ? ' delta-warn' : '');
    }

    if (!cellBarsContainer) return;
    cellBarsContainer.innerHTML = '';

    const baseMin = 3.0;
    const baseMax = 4.2;

    cells.forEach((v, idx) => {
      const barCol = document.createElement('div');
      barCol.className = 'cell-bar-column';

      const barTrack = document.createElement('div');
      barTrack.className = 'cell-bar-track';

      const barFill = document.createElement('div');
      barFill.className = 'cell-bar-fill';
      const pct = Math.max(3, Math.min(100, ((v - baseMin) / (baseMax - baseMin)) * 100));
      barFill.style.height = `${pct}%`;

      if (v === minV && cells.length > 1 && deltaMv > 30) {
        barFill.classList.add('lowest');
      } else if (v === maxV && cells.length > 1 && deltaMv > 30) {
        barFill.classList.add('highest');
      }

      barTrack.appendChild(barFill);

      const valLbl = document.createElement('span');
      valLbl.className = 'cell-val-lbl mono';
      valLbl.textContent = v.toFixed(2);

      const numLbl = document.createElement('span');
      numLbl.className = 'cell-num-lbl mono';
      numLbl.textContent = `${idx + 1}`;

      barCol.appendChild(valLbl);
      barCol.appendChild(barTrack);
      barCol.appendChild(numLbl);
      barCol.title = `Cell ${idx + 1}: ${v.toFixed(3)} V`;

      const showDetail = () => {
        if (cellHoverVal && cellHoverStat && cellHoverSep) {
          cellHoverVal.textContent = `C${idx + 1}: ${v.toFixed(3)}V`;
          cellHoverStat.style.display = 'inline-flex';
          cellHoverSep.style.display = 'inline';
        }
      };
      const hideDetail = () => {
        if (cellHoverStat && cellHoverSep) {
          cellHoverStat.style.display = 'none';
          cellHoverSep.style.display = 'none';
        }
      };

      barCol.addEventListener('mouseenter', showDetail);
      barCol.addEventListener('mouseleave', hideDetail);
      barCol.addEventListener('touchstart', showDetail, { passive: true });

      cellBarsContainer.appendChild(barCol);
    });
  }

  // ---------------- 12V House & Solar Subsystem ----------------
  function update12vSubsystem(data) {
    if (!data) return;
    cached12v = data;

    const battV = parseFloat(data.battery_voltage) || 0;
    const activeSoc = data.soc_12v_active !== undefined ? parseFloat(data.soc_12v_active) : (parseFloat(data.battery_soc) || 0);
    const ocvSoc = data.soc_12v_voltage !== undefined ? parseFloat(data.soc_12v_voltage) : (parseFloat(data.battery_soc) || 0);

    if (val12vBattV) val12vBattV.textContent = battV > 0 ? battV.toFixed(2) : '--.-';

    if (fill12vSoc) fill12vSoc.style.width = `${Math.min(100, Math.max(0, activeSoc))}%`;
    if (val12vBattSoc) val12vBattSoc.textContent = `Capacity: ${Math.round(activeSoc)}%`;
    if (val12vOcvSoc) val12vOcvSoc.textContent = `OCV: ${Math.round(ocvSoc)}%`;

    // Solar PV
    const solW = parseFloat(data.solar_power) || 0;
    const solV = parseFloat(data.solar_voltage) || 0;
    const solA = parseFloat(data.solar_current) || 0;
    if (val12vSolarW) val12vSolarW.textContent = solW.toFixed(0);
    if (val12vSolarV) val12vSolarV.textContent = `${solV.toFixed(1)} V`;
    if (val12vSolarA) val12vSolarA.textContent = `${solA.toFixed(1)} A`;

    // Status & Yield
    const rawStatus = data.charging_status || 'Active';
    if (val12vState) val12vState.textContent = rawStatus;
    if (solarModeBadge) {
      solarModeBadge.textContent = rawStatus.toUpperCase();
      if (rawStatus.toLowerCase().includes('float')) {
        solarModeBadge.className = 'card-badge green-badge';
      } else if (rawStatus.toLowerCase().includes('boost') || rawStatus.toLowerCase().includes('mppt')) {
        solarModeBadge.className = 'card-badge amber-badge';
      } else {
        solarModeBadge.className = 'card-badge';
      }
    }
    if (val12vYield) val12vYield.textContent = data.daily_yield_kwh !== undefined ? `${data.daily_yield_kwh} kWh` : '-- kWh';

    // Net Battery Flux
    const chgI = parseFloat(data.battery_charge_current) || 0;
    const loadI = parseFloat(data.load_current) || 0;
    const netI = data.net_12v_current !== undefined ? parseFloat(data.net_12v_current) : (chgI - loadI);
    if (val12vNetFlux) {
      val12vNetFlux.textContent = `${netI >= 0 ? '+' : ''}${netI.toFixed(2)} A`;
    }

    // Temperatures & DC Load Output
    if (val12vBattTemp) {
      val12vBattTemp.textContent = (data.battery_temperature !== null && data.battery_temperature !== undefined)
        ? `${data.battery_temperature} °C`
        : '-- °C';
    }
    if (val12vCtrlTemp) {
      val12vCtrlTemp.textContent = (data.controller_temperature !== null && data.controller_temperature !== undefined)
        ? `${data.controller_temperature} °C`
        : '-- °C';
    }
    if (val12vLoad) {
      const loadW = parseFloat(data.load_power) || 0;
      val12vLoad.textContent = `${loadI.toFixed(2)} A (${loadW.toFixed(0)} W)`;
    }

    // Refresh Home Tab Instrument
    updateHomeTab();
  }

  // ---------------- GPS Subsystem ----------------
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
    const latDec = data.latitude !== null && data.latitude !== undefined ? parseFloat(data.latitude) : null;
    const lonDec = data.longitude !== null && data.longitude !== undefined ? parseFloat(data.longitude) : null;
    const sats = parseInt(data.satellites, 10) || 0;
    const hdop = parseFloat(data.hdop);
    const alt = parseFloat(data.altitude_m);

    if (valGpsFixBadge) {
      valGpsFixBadge.textContent = hasFix ? '3D FIX' : 'NO FIX';
      valGpsFixBadge.className = 'card-badge ' + (hasFix ? 'teal-badge' : 'gray-badge');
    }

    if (valGpsSogKnots) valGpsSogKnots.textContent = sogKnots.toFixed(1);
    if (valGpsSogKmh) valGpsSogKmh.textContent = `${sogKmh.toFixed(1)} km/h`;
    if (valGpsSogMs) valGpsSogMs.textContent = `${sogMs.toFixed(1)} m/s`;

    if (valGpsCog) valGpsCog.textContent = cogTrue !== null ? `${Math.round(cogTrue).toString().padStart(3, '0')}°` : '---°';
    if (valGpsHeadingCardinal) valGpsHeadingCardinal.textContent = getCardinalDirection(cogTrue);
    if (valGpsMode) valGpsMode.textContent = hasFix ? 'GNSS FIX' : 'SEARCHING';

    if (valGpsLatNautical) valGpsLatNautical.textContent = latNautical;
    if (valGpsLonNautical) valGpsLonNautical.textContent = lonNautical;
    if (valGpsCoordsDec) {
      if (latDec !== null && lonDec !== null) {
        valGpsCoordsDec.textContent = `${latDec.toFixed(6)}, ${lonDec.toFixed(6)}`;
      } else {
        valGpsCoordsDec.textContent = '--.------, ---.------';
      }
    }

    if (valGpsQuality) valGpsQuality.textContent = hasFix ? 'GPS Fix (SPS)' : 'Searching';
    if (valGpsSats) valGpsSats.textContent = `${sats} sats`;
    if (valGpsHdop) valGpsHdop.textContent = !isNaN(hdop) && hdop > 0 ? hdop.toFixed(1) : '--.-';
    if (valGpsAltitude) valGpsAltitude.textContent = !isNaN(alt) ? `${alt.toFixed(1)} m` : '--.- m';

    if (linkGpsMap) {
      if (latDec !== null && lonDec !== null && !isNaN(latDec) && !isNaN(lonDec)) {
        linkGpsMap.href = `https://www.openstreetmap.org/?mlat=${latDec}&mlon=${lonDec}#map=15/${latDec}/${lonDec}`;
        linkGpsMap.classList.remove('disabled');
      } else {
        linkGpsMap.href = '#';
        linkGpsMap.classList.add('disabled');
      }
    }

    if (valGpsSentence) {
      valGpsSentence.textContent = data.last_sentence ? `NMEA: $${data.last_sentence}` : 'NMEA: --';
    }

    // Refresh Home Tab Instrument
    updateHomeTab();
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

  function renderLogRow(packet) {
    if (!logRowsContainer) return;
    const tr = document.createElement('tr');
    tr.dataset.topic = packet.topic;

    const timeTd = document.createElement('td');
    timeTd.className = 'mono';
    const dateObj = new Date(packet.timestamp);
    timeTd.textContent = dateObj.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });

    const topicTd = document.createElement('td');
    const badge = document.createElement('span');
    badge.className = 'topic-badge ' + (
      (packet.topic.includes('72v') || packet.topic.includes('charger')) ? 'topic-72v' :
      packet.topic.includes('12v') ? 'topic-12v' :
      packet.topic.includes('gps') ? 'topic-gps' : 'topic-other'
    );
    badge.textContent = packet.topic;
    topicTd.appendChild(badge);

    const payloadTd = document.createElement('td');
    payloadTd.className = 'payload-cell';
    const payloadStr = typeof packet.payload === 'object' ? JSON.stringify(packet.payload) : String(packet.payload);
    payloadTd.textContent = payloadStr.length > 180 ? payloadStr.substring(0, 180) + '…' : payloadStr;
    payloadTd.title = payloadStr;

    const srcTd = document.createElement('td');
    srcTd.className = 'mono src-cell';
    srcTd.textContent = packet.source || 'mqtt';

    tr.appendChild(timeTd);
    tr.appendChild(topicTd);
    tr.appendChild(payloadTd);
    tr.appendChild(srcTd);

    if (!matchesFilter(packet.topic, activeFilter)) {
      tr.style.display = 'none';
    }

    const firstChild = logRowsContainer.firstChild;
    if (firstChild && firstChild.classList && firstChild.classList.contains('empty-row')) {
      logRowsContainer.removeChild(firstChild);
    }
    logRowsContainer.insertBefore(tr, logRowsContainer.firstChild);

    while (logRowsContainer.children.length > MAX_LOG_ROWS) {
      logRowsContainer.removeChild(logRowsContainer.lastChild);
    }
  }

  if (btnPauseLog) {
    btnPauseLog.addEventListener('click', () => {
      isLogPaused = !isLogPaused;
      btnPauseLog.textContent = isLogPaused ? 'Resume' : 'Pause';
      btnPauseLog.classList.toggle('active-btn', isLogPaused);
    });
  }

  if (btnClearLog) {
    btnClearLog.addEventListener('click', () => {
      if (logRowsContainer) {
        logRowsContainer.innerHTML = '<tr class="empty-row"><td colspan="4">Log cleared. Waiting for new packets...</td></tr>';
      }
    });
  }

  filterBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      filterBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      activeFilter = btn.dataset.filter;

      if (logRowsContainer) {
        Array.from(logRowsContainer.children).forEach(row => {
          if (row.classList.contains('empty-row')) return;
          const topic = row.dataset.topic || '';
          row.style.display = matchesFilter(topic, activeFilter) ? '' : 'none';
        });
      }
    });
  });

  // ---------------- Tri-Method SoC Event Handlers ----------------
  const socModes = ['integrated', 'voltage', 'bms'];
  selectedSocMode = localStorage.getItem('paeraki_soc_mode') || 'integrated';

  function setSocMode(mode) {
    if (!socModes.includes(mode)) mode = 'integrated';
    selectedSocMode = mode;
    localStorage.setItem('paeraki_soc_mode', mode);

    [pillModeIntegrated, pillModeVoltage, pillModeBms].forEach(p => {
      if (p) p.classList.toggle('active', p.dataset.mode === mode);
    });

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

  if (socGaugeContainer) {
    socGaugeContainer.addEventListener('click', () => {
      const nextIdx = (socModes.indexOf(selectedSocMode) + 1) % socModes.length;
      setSocMode(socModes[nextIdx]);
    });
  }
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
      return '192.168.1.100:8080';
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

  let socket = null;
  let reconnectDelay = 1000;

  function connectWebSocket() {
    const wsUrl = getWsUrl('/ws');
    console.log('[Paeraki Monitor] Connecting to WebSocket:', wsUrl);

    try {
      socket = new WebSocket(wsUrl);
    } catch (e) {
      console.error('[Paeraki Monitor] WebSocket init error:', e);
      scheduleReconnect();
      return;
    }

    socket.onopen = function() {
      console.log('[Paeraki Monitor] WebSocket Connected');
      connDot.className = 'pulse-dot connected';
      connLabel.textContent = 'Live';
      if (homeStatusBadge) homeStatusBadge.textContent = 'ONLINE';
      reconnectDelay = 1000;
    };

    socket.onmessage = function(event) {
      try {
        const msg = JSON.parse(event.data);

        if (msg.type === 'snapshot' && msg.snapshot) {
          handleSnapshot(msg.snapshot);
        } else if (msg.type === 'packet' && msg.packet) {
          if (!isLogPaused) {
            renderLogRow(msg.packet);
          }
          if (msg.snapshot) {
            handleSnapshot(msg.snapshot);
          }
        }
      } catch (err) {
        console.error('[Paeraki Monitor] Message parse error:', err);
      }
    };

    socket.onclose = function(e) {
      console.warn('[Paeraki Monitor] WebSocket closed:', e.reason || e.code);
      connDot.className = 'pulse-dot';
      connLabel.textContent = 'Reconnecting...';
      if (homeStatusBadge) homeStatusBadge.textContent = 'CONNECTING...';
      scheduleReconnect();
    };

    socket.onerror = function(err) {
      console.error('[Paeraki Monitor] WebSocket error:', err);
      socket.close();
    };
  }

  function scheduleReconnect() {
    setTimeout(() => {
      connectWebSocket();
      reconnectDelay = Math.min(reconnectDelay * 1.5, 10000);
    }, reconnectDelay);
  }

  function handleSnapshot(snap) {
    if (!snap) return;

    if (snap.broker) {
      if (totalPacketsEl) totalPacketsEl.textContent = snap.broker.total_packets || 0;
      if (packetRateEl) packetRateEl.textContent = `${snap.broker.msg_rate || 0.0} /s`;
      if (brokerEndpoint) brokerEndpoint.textContent = `${snap.broker.host}:${snap.broker.port}`;

      const miscPkts = document.getElementById('misc-total-packets');
      const miscRate = document.getElementById('misc-packet-rate');
      const miscHost = document.getElementById('broker-host');
      if (miscPkts) miscPkts.textContent = `${snap.broker.total_packets || 0} pkts`;
      if (miscRate) miscRate.textContent = `${snap.broker.msg_rate || 0.0} msg/s`;
      if (miscHost) miscHost.textContent = `${snap.broker.host}:${snap.broker.port}`;

      if (snap.broker.last_packet_time && lastSeenEl) {
        const d = new Date(snap.broker.last_packet_time);
        lastSeenEl.textContent = d.toLocaleTimeString('en-US', { hour12: false });
      }
    }

    if (snap.server && snap.server.hostname) {
      const el = document.getElementById('server-host');
      if (el) el.textContent = snap.server.hostname ? `${snap.server.hostname} (${getServerHost()})` : getServerHost();
    }

    if (snap.subsystems) {
      if (snap.subsystems['72v']) update72vSubsystem(snap.subsystems['72v']);
      if (snap.subsystems['12v']) update12vSubsystem(snap.subsystems['12v']);
      if (snap.subsystems.gps) updateGpsSubsystem(snap.subsystems.gps);
    }

    // ---------------- Alarms Rendering ----------------
    const alarmContainer = document.getElementById('vessel-alarm-container');
    if (alarmContainer) {
      if (snap.alarms && snap.alarms.active_count > 0 && snap.alarms.active_alarms && snap.alarms.active_alarms.length > 0) {
        const active = snap.alarms.active_alarms[0];
        const isCritical = active.severity === 'CRITICAL';
        const msg = (active.last_event && active.last_event.message) || active.description || 'Active vessel alarm';
        const badgeClass = isCritical ? 'critical' : 'warning';
        alarmContainer.innerHTML = `
          <div class="alarm-banner ${isCritical ? 'critical' : 'warning'}" role="alert">
            <span class="alarm-icon">${isCritical ? '🚨' : '⚠️'}</span>
            <span class="alarm-msg">${msg}</span>
            <span class="alarm-badge ${badgeClass}">${active.severity}</span>
          </div>
        `;
      } else {
        alarmContainer.innerHTML = '';
      }
    }
  }

  // Server Host Click to configure
  const serverHostEl = document.getElementById('server-host');
  if (serverHostEl) {
    serverHostEl.addEventListener('click', () => {
      const current = getServerHost();
      const newHost = prompt('Enter Paeraki Dashboard Server (host:port):', current);
      if (newHost && newHost.trim()) {
        localStorage.setItem('paeraki_server_host', newHost.trim());
        window.location.reload();
      }
    });
  }

  // Initial HTTP snapshot fetch for instant load
  fetch(getApiUrl('/api/state'))
    .then(r => r.json())
    .then(snapshot => {
      if (snapshot) handleSnapshot(snapshot);
    })
    .catch(err => console.warn('[Paeraki Monitor] Initial state fetch failed:', err))
    .finally(() => {
      connectWebSocket();
    });

  // End of initialization
})();
