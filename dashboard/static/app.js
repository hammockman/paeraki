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

  // Fridge DOM Elements
  const valFridgeLeftTemp = document.getElementById('val-fridge-left-temp');
  const valFridgeLeftTarget = document.getElementById('val-fridge-left-target');
  const valFridgeRightTemp = document.getElementById('val-fridge-right-temp');
  const valFridgeRightTarget = document.getElementById('val-fridge-right-target');
  const valFridgeCompressor = document.getElementById('val-fridge-compressor');
  const valFridgeVoltage = document.getElementById('val-fridge-voltage');
  const valFridgeMode = document.getElementById('val-fridge-mode');
  const valFridgeSaver = document.getElementById('val-fridge-saver');
  const valFridgePower = document.getElementById('val-fridge-power');
  const valFridgeUpdated = document.getElementById('val-fridge-updated');
  const fridgeStatusBadge = document.getElementById('fridge-status-badge');

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

  // GNSS Source Selector & Dual Compare DOM
  const btnGpsSourceSeatalkng = document.getElementById('btn-gps-source-seatalkng');
  const btnGpsSourceRouter = document.getElementById('btn-gps-source-router');
  const btnGpsSourceBoth = document.getElementById('btn-gps-source-both');
  const gpsActiveSourceBadge = document.getElementById('gps-active-source-badge');
  const gpsPanelTitle = document.getElementById('gps-panel-title');
  const gpsCompareCard = document.getElementById('gps-compare-card');
  const gpsCompareDeltaBadge = document.getElementById('gps-compare-delta-badge');

  // SeaTalkNG Heading & Dynamics DOM
  const valHeadingSourceBadge = document.getElementById('val-heading-source-badge');
  const valSeatalkHeadingMag = document.getElementById('val-seatalk-heading-mag');
  const valSeatalkHeadingTrue = document.getElementById('val-seatalk-heading-true');
  const valSeatalkHeadingVar = document.getElementById('val-seatalk-heading-var');
  const valSeatalkHeadingCardinal = document.getElementById('val-seatalk-heading-cardinal');
  const valSeatalkRot = document.getElementById('val-seatalk-rot');
  const valSeatalkRudder = document.getElementById('val-seatalk-rudder');
  const valAttitudePitch = document.getElementById('val-attitude-pitch');
  const attitudePitchBar = document.getElementById('attitude-pitch-bar');
  const valAttitudeRoll = document.getElementById('val-attitude-roll');
  const attitudeRollBar = document.getElementById('attitude-roll-bar');
  const valAttitudePilotMode = document.getElementById('val-attitude-pilot-mode');

  // Barometer DOM (Misc Tab)
  const valBaroHpa = document.getElementById('val-baro-hpa');
  const valBaroTrend = document.getElementById('val-baro-trend');
  const miscBaroTrendBadge = document.getElementById('misc-baro-trend-badge');

  // AIS Tab DOM
  const aisOwnStatusBadge = document.getElementById('ais-own-status-badge');
  const aisOwnHardware = document.getElementById('ais-own-hardware');
  const aisOwnTxState = document.getElementById('ais-own-tx-state');
  const aisTargetCountMetric = document.getElementById('ais-target-count-metric');
  const aisClosestDistance = document.getElementById('ais-closest-distance');
  const aisCountAll = document.getElementById('ais-count-all');
  const aisCountUnknown = document.getElementById('ais-count-unknown');
  const aisCountNamed = document.getElementById('ais-count-named');
  const btnAisFilterAll = document.getElementById('btn-ais-filter-all');
  const btnAisFilterUnknown = document.getElementById('btn-ais-filter-unknown');
  const btnAisFilterNamed = document.getElementById('btn-ais-filter-named');
  const aisTargetsList = document.getElementById('ais-targets-list');

  // Auth & Security DOM
  const btnAuthToggle = document.getElementById('btn-auth-toggle');
  const authLockIcon = document.getElementById('auth-lock-icon');
  const authLockText = document.getElementById('auth-lock-text');
  const authModal = document.getElementById('auth-modal');
  const authModalDesc = document.getElementById('auth-modal-desc');
  const btnCloseAuthModal = document.getElementById('btn-close-auth-modal');
  const inputSkipperPin = document.getElementById('input-skipper-pin');
  const btnSubmitSkipperPin = document.getElementById('btn-submit-skipper-pin');
  const authPinFeedback = document.getElementById('auth-pin-feedback');
  const btnRequestPairingAction = document.getElementById('btn-request-pairing-action');

  // Cortex Anchor & MoB DOM
  const cortexAnchorCard = document.getElementById('cortex-anchor-card');
  const cortexAnchorStatusBadge = document.getElementById('cortex-anchor-status-badge');
  const valAnchorCoords = document.getElementById('val-anchor-coords');
  const valAnchorDist = document.getElementById('val-anchor-dist');
  const valAnchorRadius = document.getElementById('val-anchor-radius');
  const valAnchorAlarm = document.getElementById('val-anchor-alarm');
  const btnMobTrigger = document.getElementById('btn-mob-trigger');

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
  let cachedGpsSeatalkng = null;
  let cachedGpsRouter = null;
  let cachedAisStatus = null;
  let cachedAisTargets = [];
  let activeGpsSource = localStorage.getItem('paeraki_gps_source') || 'seatalkng';
  let activeAisFilter = 'all';
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

      const isStale72v = !cached72v.last_updated || (Date.now() - new Date(cached72v.last_updated).getTime() > 15000) || vTotal <= 0;
      if (homeVal72vSoc) homeVal72vSoc.textContent = displaySoc > 0 ? `${displaySoc.toFixed(1)}%` : '--.-%';
      if (home72vModeBadge) {
        if (isStale72v) {
          home72vModeBadge.textContent = 'OFFLINE';
          home72vModeBadge.className = 'inst-badge red-badge';
        } else {
          home72vModeBadge.textContent = selectedSocMode.toUpperCase();
          home72vModeBadge.className = 'inst-badge cyan-badge';
        }
      }
      if (homeVal72vW) homeVal72vW.textContent = isStale72v ? '--' : (Math.abs(pwr) < 10000 ? `${Math.round(pwr)}` : `${(pwr / 1000).toFixed(1)}k`);
      if (homeVal72vSub) {
        if (isStale72v) {
          homeVal72vSub.textContent = vTotal > 0 ? `${vTotal.toFixed(1)} V · OFFLINE` : 'OFFLINE · NO COMMS';
        } else {
          homeVal72vSub.textContent = `${vTotal > 0 ? vTotal.toFixed(1) : '--.-'} V · ${curr >= 0 ? '+' : ''}${curr.toFixed(1)} A`;
        }
      }

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
      const isStale = !data.last_updated || (Date.now() - new Date(data.last_updated).getTime() > 15000) || vTotal <= 0;
      if (isStale) {
        bmsStateBadge.textContent = 'OFFLINE';
        bmsStateBadge.className = 'card-badge red-badge';
      } else if (Math.abs(curr) < 0.3) {
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
    const isStale12v = !data.last_updated || (Date.now() - new Date(data.last_updated).getTime() > 15000) || battV <= 0;
    const rawStatus = isStale12v ? 'Offline' : (data.charging_status || 'Active');
    if (val12vState) val12vState.textContent = rawStatus;
    if (solarModeBadge) {
      if (isStale12v) {
        solarModeBadge.textContent = 'OFFLINE';
        solarModeBadge.className = 'card-badge red-badge';
      } else {
        solarModeBadge.textContent = rawStatus.toUpperCase();
        if (rawStatus.toLowerCase().includes('float')) {
          solarModeBadge.className = 'card-badge green-badge';
        } else if (rawStatus.toLowerCase().includes('boost') || rawStatus.toLowerCase().includes('mppt')) {
          solarModeBadge.className = 'card-badge amber-badge';
        } else {
          solarModeBadge.className = 'card-badge';
        }
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

  // ---------------- Brass Monkey Fridge Subsystem ----------------
  function updateFridgeSubsystem(data) {
    if (!data) return;
    const left = data.left_zone || {};
    const right = data.right_zone || {};

    if (valFridgeLeftTemp) {
      valFridgeLeftTemp.textContent = (left.current_temperature !== undefined && left.current_temperature !== null)
        ? left.current_temperature
        : '--';
    }
    if (valFridgeLeftTarget) {
      valFridgeLeftTarget.textContent = (left.target_temperature !== undefined && left.target_temperature !== null)
        ? `${left.target_temperature} °C`
        : '-- °C';
    }

    if (valFridgeRightTemp) {
      valFridgeRightTemp.textContent = (right.current_temperature !== undefined && right.current_temperature !== null)
        ? right.current_temperature
        : '--';
    }
    if (valFridgeRightTarget) {
      valFridgeRightTarget.textContent = (right.target_temperature !== undefined && right.target_temperature !== null)
        ? `${right.target_temperature} °C`
        : '-- °C';
    }

    if (valFridgeCompressor) {
      const running = Boolean(data.compressor_running);
      valFridgeCompressor.textContent = running ? 'Running' : 'Idle';
      valFridgeCompressor.style.color = running ? 'var(--color-teal)' : 'var(--text-dim)';
    }

    if (valFridgeVoltage) {
      const v = parseFloat(data.battery_voltage) || 0;
      valFridgeVoltage.textContent = v > 0 ? `${v.toFixed(1)} V` : '--.- V';
    }

    if (valFridgeMode) {
      valFridgeMode.textContent = data.run_mode || 'Eco';
    }

    if (valFridgeSaver) {
      valFridgeSaver.textContent = data.battery_saver || 'Mid';
    }

    if (valFridgePower) {
      valFridgePower.textContent = data.powered_on ? 'ON' : 'OFF';
      valFridgePower.style.color = data.powered_on ? 'var(--color-green)' : 'var(--color-red)';
    }

    if (valFridgeUpdated) {
      if (data.last_updated) {
        const d = new Date(data.last_updated);
        valFridgeUpdated.textContent = isNaN(d.getTime())
          ? data.last_updated
          : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      } else {
        valFridgeUpdated.textContent = '--';
      }
    }

    if (fridgeStatusBadge) {
      fridgeStatusBadge.textContent = data.powered_on ? 'ONLINE' : 'OFFLINE';
      fridgeStatusBadge.className = data.powered_on ? 'card-badge teal-badge' : 'card-badge red-badge';
    }
  }

  // ---------------- Geodetic & Navigation Helpers ----------------
  function haversineMeters(lat1, lon1, lat2, lon2) {
    if (lat1 === null || lon1 === null || lat2 === null || lon2 === null || isNaN(lat1) || isNaN(lon1) || isNaN(lat2) || isNaN(lon2)) return null;
    const R = 6371000;
    const phi1 = (Number(lat1) * Math.PI) / 180;
    const phi2 = (Number(lat2) * Math.PI) / 180;
    const dphi = ((Number(lat2) - Number(lat1)) * Math.PI) / 180;
    const dlambda = ((Number(lon2) - Number(lon1)) * Math.PI) / 180;
    const a = Math.sin(dphi / 2) ** 2 + Math.cos(phi1) * Math.cos(phi2) * Math.sin(dlambda / 2) ** 2;
    const c = 2 * Math.atan2(Math.sqrt(Math.max(0, a)), Math.sqrt(Math.max(0, 1 - a)));
    return R * c;
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
    let altWgs84 = null;
    if (data.altitude_wgs84_m !== undefined && data.altitude_wgs84_m !== null) {
      altWgs84 = parseFloat(data.altitude_wgs84_m);
    } else if (data.source === 'router' && data.altitude_m !== null && data.geoidal_sep_m !== null && data.geoidal_sep_m !== undefined) {
      altWgs84 = parseFloat(data.altitude_m) + parseFloat(data.geoidal_sep_m);
    } else if (data.altitude_m !== null && data.altitude_m !== undefined) {
      altWgs84 = parseFloat(data.altitude_m);
    }

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
    if (valGpsAltitude) valGpsAltitude.textContent = altWgs84 !== null && !isNaN(altWgs84) ? `${altWgs84.toFixed(1)} m` : '--.- m';

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
      valGpsSentence.textContent = data.last_sentence ? `NMEA: $${data.last_sentence}` : (data.source === 'seatalkng' ? 'SeaTalkNG: PGN 129029' : 'NMEA: --');
    }

    // Refresh Home Tab Instrument
    updateHomeTab();
  }

  // ---------------- Dual GPS View & Switching ----------------
  function renderGpsView() {
    const stGps = cachedGpsSeatalkng || cachedGps || {};
    const rtGps = cachedGpsRouter || {};

    let activeData = stGps;
    let badgeText = 'SEATALKNG GNSS';
    let panelTitle = 'GPS Navigation';

    if (activeGpsSource === 'router') {
      activeData = rtGps;
      badgeText = 'ROUTER GNSS (RUT955)';
      panelTitle = 'GPS Navigation (Router)';
      if (gpsCompareCard) gpsCompareCard.style.display = 'none';
    } else if (activeGpsSource === 'both') {
      activeData = stGps;
      badgeText = 'SEATALKNG (PRIMARY)';
      panelTitle = 'Dual GNSS System (SeaTalkNG & Router)';
      if (gpsCompareCard) {
        gpsCompareCard.style.display = '';
        renderGpsComparison(stGps, rtGps);
      }
    } else {
      if (gpsCompareCard) gpsCompareCard.style.display = 'none';
    }

    if (gpsActiveSourceBadge) gpsActiveSourceBadge.textContent = badgeText;
    if (gpsPanelTitle) gpsPanelTitle.textContent = panelTitle;

    updateGpsSubsystem(activeData);
  }

  function renderGpsComparison(st, rt) {
    const cmpStFix = document.getElementById('cmp-st-fix');
    const cmpRtFix = document.getElementById('cmp-rt-fix');
    const cmpStSog = document.getElementById('cmp-st-sog');
    const cmpRtSog = document.getElementById('cmp-rt-sog');
    const cmpStCog = document.getElementById('cmp-st-cog');
    const cmpRtCog = document.getElementById('cmp-rt-cog');
    const cmpStLat = document.getElementById('cmp-st-lat');
    const cmpRtLat = document.getElementById('cmp-rt-lat');
    const cmpStLon = document.getElementById('cmp-st-lon');
    const cmpRtLon = document.getElementById('cmp-rt-lon');
    const cmpStSats = document.getElementById('cmp-st-sats');
    const cmpRtSats = document.getElementById('cmp-rt-sats');
    const cmpStHdop = document.getElementById('cmp-st-hdop');
    const cmpRtHdop = document.getElementById('cmp-rt-hdop');
    const cmpStAlt = document.getElementById('cmp-st-alt');
    const cmpRtAlt = document.getElementById('cmp-rt-alt');

    if (cmpStFix) cmpStFix.textContent = st.fix ? '3D FIX' : 'NO FIX';
    if (cmpRtFix) cmpRtFix.textContent = rt.fix ? '3D FIX' : 'NO FIX';

    const stSog = parseFloat(st.sog_knots) || 0.0;
    const rtSog = parseFloat(rt.sog_knots) || 0.0;
    if (cmpStSog) cmpStSog.textContent = `${stSog.toFixed(1)} kn`;
    if (cmpRtSog) cmpRtSog.textContent = `${rtSog.toFixed(1)} kn`;

    const stCog = st.cog_true !== null && st.cog_true !== undefined ? `${Math.round(st.cog_true)}°` : '---°';
    const rtCog = rt.cog_true !== null && rt.cog_true !== undefined ? `${Math.round(rt.cog_true)}°` : '---°';
    if (cmpStCog) cmpStCog.textContent = stCog;
    if (cmpRtCog) cmpRtCog.textContent = rtCog;

    if (cmpStLat) cmpStLat.textContent = st.latitude_nautical || '--° --.--- \' -';
    if (cmpRtLat) cmpRtLat.textContent = rt.latitude_nautical || '--° --.--- \' -';

    if (cmpStLon) cmpStLon.textContent = st.longitude_nautical || '---° --.--- \' -';
    if (cmpRtLon) cmpRtLon.textContent = rt.longitude_nautical || '---° --.--- \' -';

    if (cmpStSats) cmpStSats.textContent = `${st.satellites || 0} sats`;
    if (cmpRtSats) cmpRtSats.textContent = `${rt.satellites || 0} sats`;

    if (cmpStHdop) cmpStHdop.textContent = st.hdop ? Number(st.hdop).toFixed(2) : '--.-';
    if (cmpRtHdop) cmpRtHdop.textContent = rt.hdop ? Number(rt.hdop).toFixed(2) : '--.-';

    const stAlt = st.altitude_wgs84_m !== undefined && st.altitude_wgs84_m !== null
      ? parseFloat(st.altitude_wgs84_m)
      : (st.altitude_m !== null && st.altitude_m !== undefined ? parseFloat(st.altitude_m) : null);

    const rtAlt = rt.altitude_wgs84_m !== undefined && rt.altitude_wgs84_m !== null
      ? parseFloat(rt.altitude_wgs84_m)
      : (rt.altitude_m !== null && rt.geoidal_sep_m !== null && rt.geoidal_sep_m !== undefined
        ? parseFloat(rt.altitude_m) + parseFloat(rt.geoidal_sep_m)
        : (rt.altitude_m !== null && rt.altitude_m !== undefined ? parseFloat(rt.altitude_m) : null));

    if (cmpStAlt) cmpStAlt.textContent = stAlt !== null && !isNaN(stAlt) ? `${stAlt.toFixed(1)} m` : '--.- m';
    if (cmpRtAlt) cmpRtAlt.textContent = rtAlt !== null && !isNaN(rtAlt) ? `${rtAlt.toFixed(1)} m` : '--.- m';

    const dM = haversineMeters(st.latitude, st.longitude, rt.latitude, rt.longitude);
    if (gpsCompareDeltaBadge) {
      if (dM !== null) {
        gpsCompareDeltaBadge.textContent = `Δ ${dM.toFixed(1)} m`;
        gpsCompareDeltaBadge.className = 'card-badge ' + (dM < 15 ? 'teal-badge' : 'amber-badge');
      } else {
        gpsCompareDeltaBadge.textContent = 'Δ --.- m';
        gpsCompareDeltaBadge.className = 'card-badge gray-badge';
      }
    }
  }

  function setGpsSource(source) {
    if (!['seatalkng', 'router', 'both'].includes(source)) source = 'seatalkng';
    activeGpsSource = source;
    localStorage.setItem('paeraki_gps_source', source);

    if (btnGpsSourceSeatalkng) btnGpsSourceSeatalkng.classList.toggle('active', source === 'seatalkng');
    if (btnGpsSourceRouter) btnGpsSourceRouter.classList.toggle('active', source === 'router');
    if (btnGpsSourceBoth) btnGpsSourceBoth.classList.toggle('active', source === 'both');

    renderGpsView();
  }

  if (btnGpsSourceSeatalkng) btnGpsSourceSeatalkng.addEventListener('click', () => setGpsSource('seatalkng'));
  if (btnGpsSourceRouter) btnGpsSourceRouter.addEventListener('click', () => setGpsSource('router'));
  if (btnGpsSourceBoth) btnGpsSourceBoth.addEventListener('click', () => setGpsSource('both'));
  setGpsSource(activeGpsSource);

  // ---------------- SeaTalkNG Attitude & Heading ----------------
  function updateSeaTalkNgAttitudeAndHeading(heading, attitude) {
    if (heading) {
      const mag = heading.heading_deg !== null && heading.heading_deg !== undefined ? parseFloat(heading.heading_deg) : null;
      const varDeg = parseFloat(heading.variation_deg) || 24.87;
      const trueHdg = mag !== null ? (mag + varDeg + 360.0) % 360.0 : null;

      if (valSeatalkHeadingMag) {
        valSeatalkHeadingMag.textContent = mag !== null ? `${Math.round(mag).toString().padStart(3, '0')}°` : '---°';
      }
      if (valSeatalkHeadingTrue) {
        valSeatalkHeadingTrue.textContent = trueHdg !== null ? `${Math.round(trueHdg).toString().padStart(3, '0')}° T` : '---° T';
      }
      if (valSeatalkHeadingVar) {
        valSeatalkHeadingVar.textContent = `${Math.abs(varDeg).toFixed(1)}° ${varDeg >= 0 ? 'E' : 'W'}`;
      }
      if (valSeatalkHeadingCardinal) {
        valSeatalkHeadingCardinal.textContent = getCardinalDirection(mag !== null ? mag : trueHdg);
      }
    }

    if (attitude) {
      const pitch = attitude.pitch_deg !== null && attitude.pitch_deg !== undefined ? parseFloat(attitude.pitch_deg) : null;
      const roll = attitude.roll_deg !== null && attitude.roll_deg !== undefined ? parseFloat(attitude.roll_deg) : null;
      const rot = attitude.rate_of_turn_dps !== null && attitude.rate_of_turn_dps !== undefined ? parseFloat(attitude.rate_of_turn_dps) : null;
      const rudder = attitude.rudder_deg !== null && attitude.rudder_deg !== undefined ? parseFloat(attitude.rudder_deg) : null;
      const mode = attitude.pilot_mode || 'Standby';

      if (valSeatalkRot) {
        valSeatalkRot.textContent = rot !== null ? `${rot >= 0 ? '+' : ''}${rot.toFixed(1)} °/s` : '--.- °/s';
      }
      if (valSeatalkRudder) {
        valSeatalkRudder.textContent = rudder !== null ? `${rudder >= 0 ? 'STBD ' : 'PORT '}${Math.abs(rudder).toFixed(1)}°` : '--.-°';
      }
      if (valAttitudePilotMode) {
        valAttitudePilotMode.textContent = mode.toUpperCase();
        valAttitudePilotMode.className = 'card-badge ' + (mode.toLowerCase().includes('auto') ? 'teal-badge' : 'gray-badge');
      }

      // Pitch level bar (-15 deg to +15 deg)
      if (valAttitudePitch) {
        valAttitudePitch.textContent = pitch !== null ? `${pitch >= 0 ? '+' : ''}${pitch.toFixed(1)}°` : '--.-°';
      }
      if (attitudePitchBar) {
        if (pitch !== null) {
          const maxPitch = 15.0;
          const clamped = Math.max(-maxPitch, Math.min(maxPitch, pitch));
          const pct = (Math.abs(clamped) / maxPitch) * 50;
          if (clamped >= 0) {
            attitudePitchBar.style.left = '50%';
            attitudePitchBar.style.width = `${pct}%`;
          } else {
            attitudePitchBar.style.left = `${50 - pct}%`;
            attitudePitchBar.style.width = `${pct}%`;
          }
        } else {
          attitudePitchBar.style.width = '0%';
          attitudePitchBar.style.left = '50%';
        }
      }

      // Roll level bar (-30 deg to +30 deg)
      if (valAttitudeRoll) {
        valAttitudeRoll.textContent = roll !== null ? `${roll >= 0 ? '+' : ''}${roll.toFixed(1)}°` : '--.-°';
      }
      if (attitudeRollBar) {
        if (roll !== null) {
          const maxRoll = 30.0;
          const clamped = Math.max(-maxRoll, Math.min(maxRoll, roll));
          const pct = (Math.abs(clamped) / maxRoll) * 50;
          if (clamped >= 0) {
            attitudeRollBar.style.left = '50%';
            attitudeRollBar.style.width = `${pct}%`;
          } else {
            attitudeRollBar.style.left = `${50 - pct}%`;
            attitudeRollBar.style.width = `${pct}%`;
          }
        } else {
          attitudeRollBar.style.width = '0%';
          attitudeRollBar.style.left = '50%';
        }
      }
    }
  }

  // ---------------- Atmospheric Barometer ----------------
  function updateEnvironment(env) {
    if (!env) return;
    const p = env.pressure_hpa !== null && env.pressure_hpa !== undefined ? parseFloat(env.pressure_hpa) : null;
    if (valBaroHpa) {
      valBaroHpa.textContent = p !== null ? p.toFixed(1) : '----.-';
    }
    if (valBaroTrend) {
      valBaroTrend.textContent = env.trend || 'Steady';
    }
    if (miscBaroTrendBadge) {
      miscBaroTrendBadge.textContent = (env.trend || 'STEADY').toUpperCase();
    }
  }

  // ---------------- AIS Transponder & Target Directory ----------------
  function updateAisDirectory(status, targets) {
    cachedAisStatus = status;
    cachedAisTargets = Array.isArray(targets) ? targets : [];

    if (status) {
      const isOnline = Boolean(status.online);
      if (aisOwnStatusBadge) {
        aisOwnStatusBadge.textContent = isOnline ? 'ONLINE · SOTDMA' : 'OFFLINE';
        aisOwnStatusBadge.className = 'card-badge ' + (isOnline ? 'teal-badge' : 'gray-badge');
      }
      if (aisOwnHardware) aisOwnHardware.textContent = status.hardware || 'Class B SOTDMA (5W)';
      if (aisOwnTxState) {
        aisOwnTxState.textContent = isOnline ? 'Transmitting & Receiving' : 'No Signal / Offline';
      }
      if (aisTargetCountMetric) {
        aisTargetCountMetric.textContent = `${status.target_count || cachedAisTargets.length} vessels`;
      }
      if (aisClosestDistance) {
        const closest = status.closest_range_nm;
        aisClosestDistance.textContent = closest !== null && closest !== undefined ? `${Number(closest).toFixed(2)} NM` : '--.- NM';
      }

      if (aisCountAll) aisCountAll.textContent = status.target_count || cachedAisTargets.length;
      if (aisCountUnknown) aisCountUnknown.textContent = status.unknown_count || 0;
      if (aisCountNamed) aisCountNamed.textContent = status.named_count || 0;
    }

    renderAisTargets();
  }

  function renderAisTargets() {
    if (!aisTargetsList) return;
    const targets = cachedAisTargets || [];

    const filtered = targets.filter(t => {
      if (activeAisFilter === 'unknown') return t.is_unknown;
      if (activeAisFilter === 'named') return !t.is_unknown;
      return true;
    });

    if (filtered.length === 0) {
      aisTargetsList.innerHTML = `
        <div class="ais-empty-state">
          <span>${targets.length === 0 ? 'Scanning VHF AIS frequencies... No vessels in range.' : 'No vessels match the selected filter.'}</span>
        </div>
      `;
      return;
    }

    let html = '';
    filtered.forEach((t, idx) => {
      const isUnknown = Boolean(t.is_unknown);
      const isClosest = idx === 0 && t.range_nm !== null && t.range_nm !== undefined;
      const vesselName = (!isUnknown && t.vessel_name) ? t.vessel_name : (t.call_sign ? `Callsign ${t.call_sign}` : `MMSI ${t.mmsi}`);
      const rangeStr = t.range_nm !== null && t.range_nm !== undefined ? Number(t.range_nm).toFixed(2) : '--.-';
      const bearingStr = t.bearing_deg !== null && t.bearing_deg !== undefined ? `${Math.round(t.bearing_deg)}° ${getCardinalDirection(t.bearing_deg)}` : '---°';
      const sogStr = t.sog_knots !== null && t.sog_knots !== undefined ? `${Number(t.sog_knots).toFixed(1)} kn` : '--.- kn';
      const cogStr = t.cog_true !== null && t.cog_true !== undefined ? `${Math.round(t.cog_true)}°` : '---°';
      const navStatus = t.nav_status || 'Underway';
      const aisClass = t.ais_class ? `Class ${t.ais_class}` : 'AIS';
      const ageStr = t.last_seen_sec !== null && t.last_seen_sec !== undefined ? `${t.last_seen_sec}s ago` : 'just now';

      html += `
        <div class="ais-target-card ${isUnknown ? 'is-unknown' : ''} ${isClosest ? 'is-closest' : ''}">
          <div class="ais-card-header">
            <div class="ais-card-title-wrap">
              <span class="ais-vessel-name">${vesselName}</span>
              ${isUnknown ? '<span class="ais-badge unknown-badge">UNKNOWN VESSEL</span>' : ''}
              ${isClosest ? '<span class="ais-badge closest-badge">CLOSEST</span>' : ''}
              <span class="ais-badge class-badge">${aisClass}</span>
            </div>
            <div class="ais-distance-hero">
              <span class="ais-distance-val mono">${rangeStr}</span>
              <span class="ais-distance-unit">NM</span>
            </div>
          </div>

          <div class="ais-card-body">
            <div class="ais-stat-item">
              <span class="ais-stat-label">Navigation Status</span>
              <span class="ais-stat-val"><strong>${navStatus}</strong></span>
            </div>
            <div class="ais-stat-item">
              <span class="ais-stat-label">Bearing</span>
              <span class="ais-stat-val mono">${bearingStr}</span>
            </div>
            <div class="ais-stat-item">
              <span class="ais-stat-label">Speed &amp; Course</span>
              <span class="ais-stat-val mono">${sogStr} · ${cogStr}</span>
            </div>
            <div class="ais-stat-item">
              <span class="ais-stat-label">MMSI</span>
              <span class="ais-stat-val mono">${t.mmsi || '--'}</span>
            </div>
          </div>

          <div class="ais-card-footer">
            <span>Coordinates: ${t.latitude !== null && t.longitude !== null && t.latitude !== undefined && t.longitude !== undefined ? `${Number(t.latitude).toFixed(4)}, ${Number(t.longitude).toFixed(4)}` : '--'}</span>
            <span class="mono">Heard: ${ageStr}</span>
          </div>
        </div>
      `;
    });

    aisTargetsList.innerHTML = html;
  }

  function setAisFilter(filter) {
    if (!['all', 'unknown', 'named'].includes(filter)) filter = 'all';
    activeAisFilter = filter;
    if (btnAisFilterAll) btnAisFilterAll.classList.toggle('active', filter === 'all');
    if (btnAisFilterUnknown) btnAisFilterUnknown.classList.toggle('active', filter === 'unknown');
    if (btnAisFilterNamed) btnAisFilterNamed.classList.toggle('active', filter === 'named');
    renderAisTargets();
  }

  if (btnAisFilterAll) btnAisFilterAll.addEventListener('click', () => setAisFilter('all'));
  if (btnAisFilterUnknown) btnAisFilterUnknown.addEventListener('click', () => setAisFilter('unknown'));
  if (btnAisFilterNamed) btnAisFilterNamed.addEventListener('click', () => setAisFilter('named'));

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

  // ---------------- Helper Utilities ----------------
  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function formatNautical(lat, lon) {
    if (lat === null || lat === undefined || lon === null || lon === undefined) return "--° --.---' -";
    const latH = lat >= 0 ? 'N' : 'S';
    const aLat = Math.abs(lat);
    const latD = Math.floor(aLat);
    const latM = (aLat - latD) * 60;

    const lonH = lon >= 0 ? 'E' : 'W';
    const aLon = Math.abs(lon);
    const lonD = Math.floor(aLon);
    const lonM = (aLon - lonD) * 60;

    return `${latD.toString().padStart(2, '0')}° ${latM.toFixed(3)}' ${latH}, ${lonD.toString().padStart(3, '0')}° ${lonM.toFixed(3)}' ${lonH}`;
  }

  // ---------------- Device Authorization & Token Management ----------------
  let currentAuthRole = 'VIEWER';
  let isAuthorized = false;
  let pairingPollInterval = null;

  function getAuthToken() {
    return localStorage.getItem('paeraki_token') || '';
  }

  function getDeviceUuid() {
    let uuid = localStorage.getItem('paeraki_device_uuid');
    if (!uuid) {
      uuid = (typeof crypto !== 'undefined' && crypto.randomUUID)
        ? crypto.randomUUID()
        : 'dev-' + Math.random().toString(36).substring(2, 15) + Math.random().toString(36).substring(2, 15);
      localStorage.setItem('paeraki_device_uuid', uuid);
    }
    return uuid;
  }

  function getDeviceName() {
    let name = localStorage.getItem('paeraki_device_name');
    if (!name) {
      const isMobile = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
      name = isMobile ? 'Mobile Browser' : 'Helm Display';
      localStorage.setItem('paeraki_device_name', name);
    }
    return name;
  }

  async function apiFetch(path, options = {}) {
    const url = getApiUrl(path);
    const opts = { ...options };
    opts.headers = { ...opts.headers };
    const token = getAuthToken();
    if (token) {
      opts.headers['Authorization'] = `Bearer ${token}`;
      opts.headers['x-device-token'] = token;
    }
    opts.headers['x-device-uuid'] = getDeviceUuid();
    return fetch(url, opts);
  }

  function isDeviceAuthorized() {
    return isAuthorized && currentAuthRole === 'CONTROLLER';
  }

  function updateAuthUi(status) {
    if (status && status.authenticated && status.role === 'CONTROLLER') {
      isAuthorized = true;
      currentAuthRole = 'CONTROLLER';
      if (btnAuthToggle) {
        btnAuthToggle.className = 'auth-toggle-btn authorized';
        btnAuthToggle.title = `Authorized as Controller (${status.name || 'Device'})`;
      }
      if (authLockIcon) authLockIcon.textContent = '🔓';
      if (authLockText) authLockText.textContent = 'Controller';
      if (authModalDesc) {
        authModalDesc.innerHTML = `This device is <strong>Authorized as CONTROLLER</strong> (${escapeHtml(status.name || 'Device')}). Controls are unlocked.`;
      }
    } else {
      isAuthorized = false;
      currentAuthRole = 'VIEWER';
      if (btnAuthToggle) {
        btnAuthToggle.className = 'auth-toggle-btn';
        btnAuthToggle.title = 'Device Authorization: Read-Only (Click to Unlock)';
      }
      if (authLockIcon) authLockIcon.textContent = '🔒';
      if (authLockText) authLockText.textContent = 'Read-Only';
      if (authModalDesc) {
        authModalDesc.innerHTML = 'This device currently has <strong>Read-Only</strong> access. Enter the Skipper PIN to unlock vessel controls (alarm silencing, system control, calibrations):';
      }
    }
  }

  async function checkAuthStatus() {
    try {
      const res = await apiFetch('/api/auth/status');
      if (res.ok) {
        const data = await res.json();
        updateAuthUi(data);
        return data;
      }
    } catch (e) {
      console.warn('Auth status check failed:', e);
    }
    updateAuthUi({ authenticated: false, role: 'VIEWER' });
    return { authenticated: false, role: 'VIEWER' };
  }

  function showAuthModal(customDesc) {
    if (authPinFeedback) {
      authPinFeedback.style.display = 'none';
      authPinFeedback.textContent = '';
      authPinFeedback.className = 'auth-feedback';
    }
    if (inputSkipperPin) {
      inputSkipperPin.value = '';
    }
    if (customDesc && authModalDesc) {
      authModalDesc.innerHTML = `<span class="auth-modal-alert-notice">${escapeHtml(customDesc)}</span><br><br>Enter Skipper PIN to unlock controls:`;
    }
    if (authModal) {
      authModal.style.display = 'flex';
      if (inputSkipperPin) inputSkipperPin.focus();
    }
  }

  function hideAuthModal() {
    if (authModal) authModal.style.display = 'none';
    if (pairingPollInterval) {
      clearInterval(pairingPollInterval);
      pairingPollInterval = null;
    }
  }

  async function submitSkipperPin() {
    const pin = inputSkipperPin ? inputSkipperPin.value.trim() : '';
    if (!pin) {
      if (authPinFeedback) {
        authPinFeedback.textContent = 'Please enter the Skipper PIN';
        authPinFeedback.className = 'auth-feedback error';
        authPinFeedback.style.display = 'block';
      }
      return;
    }

    try {
      const res = await fetch(getApiUrl('/api/auth/verify_pin'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          uuid: getDeviceUuid(),
          pin: pin,
          name: getDeviceName()
        })
      });
      const data = await res.json();
      if (res.ok && data.status === 'ok' && data.token) {
        localStorage.setItem('paeraki_token', data.token);
        if (authPinFeedback) {
          authPinFeedback.textContent = '✓ Skipper PIN verified! Controller access unlocked.';
          authPinFeedback.className = 'auth-feedback success';
          authPinFeedback.style.display = 'block';
        }
        updateAuthUi({ authenticated: true, role: 'CONTROLLER', name: getDeviceName() });
        setTimeout(() => {
          hideAuthModal();
        }, 1000);
      } else {
        if (authPinFeedback) {
          authPinFeedback.textContent = data.error || 'Invalid Skipper PIN';
          authPinFeedback.className = 'auth-feedback error';
          authPinFeedback.style.display = 'block';
        }
      }
    } catch (err) {
      if (authPinFeedback) {
        authPinFeedback.textContent = 'Connection error: ' + err.message;
        authPinFeedback.className = 'auth-feedback error';
        authPinFeedback.style.display = 'block';
      }
    }
  }

  async function requestPairing() {
    try {
      if (btnRequestPairingAction) btnRequestPairingAction.disabled = true;
      const res = await fetch(getApiUrl('/api/auth/register'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          uuid: getDeviceUuid(),
          name: getDeviceName()
        })
      });
      const data = await res.json();
      if (res.ok && data.status === 'ok') {
        if (authPinFeedback) {
          authPinFeedback.textContent = 'Pairing request sent to helm console. Waiting for approval...';
          authPinFeedback.className = 'auth-feedback info';
          authPinFeedback.style.display = 'block';
        }
        if (pairingPollInterval) clearInterval(pairingPollInterval);
        pairingPollInterval = setInterval(async () => {
          const auth = await checkAuthStatus();
          if (auth && auth.authenticated && auth.role === 'CONTROLLER') {
            clearInterval(pairingPollInterval);
            pairingPollInterval = null;
            if (authPinFeedback) {
              authPinFeedback.textContent = '✓ Pairing approved by helm console!';
              authPinFeedback.className = 'auth-feedback success';
            }
            setTimeout(() => {
              hideAuthModal();
            }, 1000);
          }
        }, 3000);
      } else {
        if (authPinFeedback) {
          authPinFeedback.textContent = data.error || 'Pairing request failed';
          authPinFeedback.className = 'auth-feedback error';
          authPinFeedback.style.display = 'block';
        }
      }
    } catch (err) {
      if (authPinFeedback) {
        authPinFeedback.textContent = 'Error sending request: ' + err.message;
        authPinFeedback.className = 'auth-feedback error';
        authPinFeedback.style.display = 'block';
      }
    } finally {
      if (btnRequestPairingAction) btnRequestPairingAction.disabled = false;
    }
  }

  // Attach Auth DOM Listeners
  if (btnAuthToggle) {
    btnAuthToggle.addEventListener('click', () => {
      showAuthModal();
    });
  }
  if (btnCloseAuthModal) {
    btnCloseAuthModal.addEventListener('click', hideAuthModal);
  }
  if (btnSubmitSkipperPin) {
    btnSubmitSkipperPin.addEventListener('click', submitSkipperPin);
  }
  if (inputSkipperPin) {
    inputSkipperPin.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        submitSkipperPin();
      }
    });
  }
  if (btnRequestPairingAction) {
    btnRequestPairingAction.addEventListener('click', requestPairing);
  }
  if (authModal) {
    authModal.addEventListener('click', (e) => {
      if (e.target === authModal) {
        hideAuthModal();
      }
    });
  }

  // ---------------- Cortex Anchor Watch & MoB Handlers ----------------
  function updateCortexSubsystem(cortex) {
    if (!cortex) return;
    const anchor = cortex.anchor;
    if (anchor) {
      const isActive = Boolean(anchor.active);
      if (cortexAnchorStatusBadge) {
        cortexAnchorStatusBadge.textContent = isActive ? (anchor.drag_alarm ? 'DRAGGING!' : 'ACTIVE') : 'INACTIVE';
        cortexAnchorStatusBadge.className = 'card-badge ' + (isActive ? (anchor.drag_alarm ? 'critical' : 'teal-badge') : 'gray-badge');
      }
      if (valAnchorCoords) {
        if (anchor.anchor_lat != null && anchor.anchor_lon != null) {
          valAnchorCoords.textContent = formatNautical(anchor.anchor_lat, anchor.anchor_lon);
        } else {
          valAnchorCoords.textContent = "--° --.---' -";
        }
      }
      if (valAnchorDist) {
        valAnchorDist.textContent = anchor.distance_m != null ? `${Number(anchor.distance_m).toFixed(1)} m` : '--.- m';
      }
      if (valAnchorRadius) {
        valAnchorRadius.textContent = anchor.radius_m != null ? `${Math.round(anchor.radius_m)} m` : '-- m';
      }
      if (valAnchorAlarm) {
        if (anchor.drag_alarm) {
          valAnchorAlarm.textContent = 'DRAG ALARM';
          valAnchorAlarm.className = 'submetric-val critical mono';
        } else if (isActive) {
          valAnchorAlarm.textContent = 'HOLDING OK';
          valAnchorAlarm.className = 'submetric-val mono';
        } else {
          valAnchorAlarm.textContent = 'OK';
          valAnchorAlarm.className = 'submetric-val mono';
        }
      }
    }
  }

  async function handleSilenceAlarm(alarmId, btnEl) {
    if (!isDeviceAuthorized()) {
      showAuthModal('Please authenticate with the Skipper PIN to silence vessel alarms.');
      return;
    }
    try {
      if (btnEl) {
        btnEl.disabled = true;
        btnEl.textContent = 'Silencing...';
      }
      const res = await apiFetch('/api/cortex/silence', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ alarm_id: alarmId })
      });
      const data = await res.json();
      if (!res.ok) {
        alert(data.detail || data.error || 'Failed to silence alarm');
        if (btnEl) {
          btnEl.disabled = false;
          btnEl.textContent = 'Silence';
        }
      }
    } catch (err) {
      console.error('Failed to silence alarm:', err);
      alert('Error silencing alarm: ' + err.message);
      if (btnEl) {
        btnEl.disabled = false;
        btnEl.textContent = 'Silence';
      }
    }
  }

  async function handleMobTrigger() {
    if (!isDeviceAuthorized()) {
      showAuthModal('Please authenticate with the Skipper PIN to authorize emergency vessel actions.');
      return;
    }
    const confirmed = confirm(
      '⚠️ EMERGENCY MAN OVERBOARD (MoB)\n\n' +
      'Are you sure you want to trigger a Man Overboard alert?\n\n' +
      'This will:\n' +
      '• Log the current GPS coordinates as an emergency waypoint\n' +
      '• Sound vessel alarms and activate MoB state across all displays'
    );
    if (!confirmed) return;

    try {
      const res = await apiFetch('/api/cortex/mob', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirm: true })
      });
      const data = await res.json();
      if (!res.ok) {
        alert(data.detail || data.error || 'Failed to trigger MoB');
      }
    } catch (err) {
      console.error('Failed to trigger MoB:', err);
      alert('Error triggering MoB: ' + err.message);
    }
  }

  async function handleMobCancel() {
    if (!isDeviceAuthorized()) {
      showAuthModal('Please authenticate with the Skipper PIN to cancel MoB alert.');
      return;
    }
    if (!confirm('Are you sure you want to cancel the active Man Overboard alert?')) {
      return;
    }
    try {
      const res = await apiFetch('/api/cortex/mob/cancel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });
      const data = await res.json();
      if (!res.ok) {
        alert(data.detail || data.error || 'Failed to cancel MoB');
      }
    } catch (err) {
      console.error('Failed to cancel MoB:', err);
      alert('Error cancelling MoB: ' + err.message);
    }
  }

  if (btnMobTrigger) {
    btnMobTrigger.addEventListener('click', handleMobTrigger);
  }

  function updateMobAndAlarms(alarmsData, cortexAlarms, mobData) {
    const alarmContainer = document.getElementById('vessel-alarm-container');
    if (!alarmContainer) return;

    let html = '';

    // Render MoB Active Banner if MoB is active
    if (mobData && mobData.active) {
      const lat = mobData.latitude;
      const lon = mobData.longitude;
      const coordStr = (lat != null && lon != null) ? formatNautical(lat, lon) : 'Coordinates Logged';
      const timeStr = mobData.timestamp ? new Date(mobData.timestamp).toLocaleTimeString('en-US', { hour12: false }) : '';
      html += `
        <div class="mob-active-banner" role="alert">
          <div>
            <span style="font-size: 1.4rem; margin-right: 8px;">🛟</span>
            <strong>MAN OVERBOARD ALERT ACTIVE</strong> — 
            <span class="mono">${coordStr}</span>
            <span style="margin-left: 10px; font-size: 0.85rem; opacity: 0.9;">(${escapeHtml(mobData.source || 'Dashboard')} ${timeStr})</span>
          </div>
          <button class="mob-cancel-btn" id="btn-mob-cancel" style="background: white; color: #dc2626; border: none; border-radius: 6px; padding: 6px 14px; font-weight: 800; cursor: pointer;">CANCEL MoB</button>
        </div>
      `;
    }

    // Active Cortex alarms
    const activeCortex = (cortexAlarms || []).filter(a => !a.silenced);
    activeCortex.forEach(a => {
      const isCrit = a.severity === 'CRITICAL';
      const badgeClass = isCrit ? 'critical' : 'warning';
      html += `
        <div class="alarm-banner ${isCrit ? 'critical' : 'warning'}" role="alert">
          <span class="alarm-icon">${isCrit ? '🚨' : '⚠️'}</span>
          <span class="alarm-msg"><strong>[Cortex]</strong> ${escapeHtml(a.message || a.type || 'Cortex Alert')}</span>
          <span class="alarm-badge ${badgeClass}">${escapeHtml(a.severity)}</span>
          ${a.silenceable !== false ? `<button class="alarm-silence-btn" data-cortex-alarm-id="${escapeHtml(a.id)}">Silence</button>` : ''}
        </div>
      `;
    });

    // System Engine Alarms
    if (alarmsData && alarmsData.active_count > 0 && alarmsData.active_alarms && alarmsData.active_alarms.length > 0) {
      alarmsData.active_alarms.forEach(active => {
        const isCritical = active.severity === 'CRITICAL';
        const msg = (active.last_event && active.last_event.message) || active.description || 'Active vessel alarm';
        const badgeClass = isCritical ? 'critical' : 'warning';
        html += `
          <div class="alarm-banner ${isCritical ? 'critical' : 'warning'}" role="alert">
            <span class="alarm-icon">${isCritical ? '🚨' : '⚠️'}</span>
            <span class="alarm-msg">${escapeHtml(msg)}</span>
            <span class="alarm-badge ${badgeClass}">${escapeHtml(active.severity)}</span>
          </div>
        `;
      });
    }

    alarmContainer.innerHTML = html;

    // Attach event listener for MoB cancel button if present
    const btnMobCancel = document.getElementById('btn-mob-cancel');
    if (btnMobCancel) {
      btnMobCancel.addEventListener('click', handleMobCancel);
    }

    // Attach event listeners for Cortex silence buttons
    const silenceButtons = alarmContainer.querySelectorAll('.alarm-silence-btn');
    silenceButtons.forEach(btn => {
      btn.addEventListener('click', (e) => {
        const alarmId = e.currentTarget.getAttribute('data-cortex-alarm-id');
        if (alarmId) handleSilenceAlarm(alarmId, e.currentTarget);
      });
    });
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
      if (snap.subsystems.fridge) updateFridgeSubsystem(snap.subsystems.fridge);

      if (snap.subsystems.gps_seatalkng) cachedGpsSeatalkng = snap.subsystems.gps_seatalkng;
      if (snap.subsystems.gps_router) cachedGpsRouter = snap.subsystems.gps_router;
      if (snap.subsystems.gps) cachedGps = snap.subsystems.gps;

      renderGpsView();

      if (snap.subsystems.cortex) {
        updateCortexSubsystem(snap.subsystems.cortex);
      }

      if (snap.subsystems.seatalkng) {
        const st = snap.subsystems.seatalkng;
        if (st.heading || st.attitude) updateSeaTalkNgAttitudeAndHeading(st.heading, st.attitude);
        if (st.environment) updateEnvironment(st.environment);
        if (st.ais_status || st.ais_targets) updateAisDirectory(st.ais_status, st.ais_targets);
      }
    }

    // ---------------- Alarms & MoB Rendering ----------------
    const cortexAlarms = (snap.subsystems && snap.subsystems.cortex) ? snap.subsystems.cortex.alarms : null;
    const mobData = (snap.subsystems && snap.subsystems.mob) ? snap.subsystems.mob : null;
    updateMobAndAlarms(snap.alarms, cortexAlarms, mobData);
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

  // Check auth status right away
  checkAuthStatus().then(() => {
    if (urlParams.get('auth_modal') === '1') {
      showAuthModal();
    }
  });

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
