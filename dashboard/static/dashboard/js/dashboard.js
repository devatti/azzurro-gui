/* Dashboard live view: KPIs + energy flow diagram + charts. */
(function () {
    'use strict';

    const POLL_MS = 10000;
    const REALTIME_URL = '/api/realtime/';
    const HISTORY_URL = '/api/history/';

    const els = {
        banner: document.getElementById('error-banner'),
        grid: document.getElementById('kpi-grid'),
        statusDot: document.getElementById('sidebar-status-dot'),
        statusText: document.getElementById('sidebar-status-text'),
        batteryMetrics: document.getElementById('battery-metrics'),
        flow: document.getElementById('flow-canvas'),
        chartToday: document.getElementById('chart-today'),
        gaugeSoc: document.getElementById('gauge-soc'),
        chartEnergy: document.getElementById('chart-energy'),
        lastUpdate: document.getElementById('last-update'),
        lastUpdateWrap: document.getElementById('topbar-updated'),
    };

    let flow = null;
    let lastSnapshot = null;
    const charts = { today: null, gauge: null, energy: null };

    const COLORS = {
        generating: '#ffb020',
        consuming: '#a78bfa',
        charging: '#37d0a0',
        discharging: '#22d3ee',
        importing: '#3aa0ff',
        exporting: '#37d0a0',
        autoconsuming: '#f472b6',
        net: '#f472b6',
    };

    function fmtW(w) {
        if (w === null || w === undefined || isNaN(w)) return '—';
        if (Math.abs(w) >= 1000) return (w / 1000).toFixed(2) + ' kW';
        return Math.round(w) + ' W';
    }

    function fmtKwh(v) {
        if (v === null || v === undefined || isNaN(v)) return '—';
        return v.toFixed(1) + ' kWh';
    }

    function fmtKwhTotal(v) {
        if (v === null || v === undefined || isNaN(v)) return '—';
        if (v >= 1000) return (v / 1000).toFixed(2) + ' MWh';
        return Math.round(v).toLocaleString() + ' kWh';
    }

    function renderLastUpdate(s) {
        if (!els.lastUpdate || !els.lastUpdateWrap) return;
        const lu = s.last_update ? new Date(s.last_update) : null;
        if (lu && !isNaN(lu)) {
            els.lastUpdate.textContent = lu.toLocaleString([], {
                day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
            });
            const fu = s.first_update ? new Date(s.first_update) : null;
            const title = 'Last update from the plant';
            const first = (fu && !isNaN(fu))
                ? ` · first data ${fu.toLocaleDateString([], { day: '2-digit', month: 'short', year: 'numeric' })}`
                : '';
            els.lastUpdateWrap.title = title + first;
            els.lastUpdateWrap.classList.remove('hidden');
        } else {
            els.lastUpdateWrap.classList.add('hidden');
        }
    }

    function showError(msg) {
        if (!els.banner) return;
        els.banner.textContent = msg;
        els.banner.classList.remove('hidden');
    }

    function clearError() {
        if (els.banner) els.banner.classList.add('hidden');
    }

    function setStatus(status) {
        els.statusDot.className = 'status-dot ' + (status || 'offline');
        const text = status === 'online' ? 'Plant online' : status === 'degraded' ? 'Plant degraded' : 'Plant offline';
        els.statusText.textContent = text;
    }

    function renderKpis(s) {
        const p = s.power || {};
        const e = s.energy || {};

        set('generating', fmtW(p.generating));
        set('generating-today', fmtKwh(e.generating));
        set('consuming', fmtW(p.consuming));
        set('consuming-today', fmtKwh(e.consuming));
        set('soc', s.battery_soc != null ? Math.round(s.battery_soc) : '—');

        const chargeStatus = (p.charging || 0) > 20 ? 'charging ' + fmtW(p.charging)
            : (p.discharging || 0) > 20 ? 'discharging ' + fmtW(p.discharging)
            : 'idle';
        set('charge-status', chargeStatus);

        const net = (p.exporting || 0) - (p.importing || 0);
        const netAbs = Math.abs(net);
        set('grid', (net >= 0 ? '+' : '−') + (netAbs >= 1000 ? (netAbs / 1000).toFixed(2) + ' kW' : Math.round(netAbs) + ' W'));
        set('grid-status', net > 20 ? 'exporting' : net < -20 ? 'importing' : 'balanced');

        set('autoconsuming', fmtW(p.autoconsuming));
        set('autoconsuming-today', fmtKwh(e.autoconsuming));
        set('generating-total', fmtKwhTotal(e.generating_total));
        set('battery-cycles', s.battery_cycle != null ? Math.round(s.battery_cycle).toLocaleString() : '—');
        set('soc-2', s.battery_soc_2 != null ? Math.round(s.battery_soc_2) : '—');

        const cycles = s.battery_cycle != null ? ` · ${Math.round(s.battery_cycle).toLocaleString()} cycles` : '';
        els.batteryMetrics.innerHTML =
            `<b>${s.battery_soc != null ? s.battery_soc.toFixed(1) : '—'}%</b> SoC · charge ${fmtW(p.charging)} · discharge ${fmtW(p.discharging)}${cycles}`;

        renderLastUpdate(s);
    }

    function set(key, value) {
        const el = els.grid.querySelector(`[data-kpi="${key}"]`);
        if (el) el.textContent = value;
    }

    function renderGauge(s) {
        if (!charts.gauge) {
            charts.gauge = echarts.init(els.gaugeSoc);
        }
        const soc = s.battery_soc != null ? Math.min(100, Math.max(0, s.battery_soc)) : 0;
        const p = s.power || {};
        const discharging = (p.discharging || 0) > 0;
        charts.gauge.setOption({
            backgroundColor: 'transparent',
            series: [{
                type: 'gauge',
                startAngle: 210,
                endAngle: -30,
                min: 0, max: 100,
                progress: { show: true, width: 12, itemStyle: { color: discharging ? '#22d3ee' : '#37d0a0' } },
                axisLine: { lineStyle: { width: 12, color: [[1, '#2b3039']] } },
                axisTick: { show: false },
                splitLine: { show: false },
                axisLabel: { show: false },
                pointer: { show: false },
                detail: {
                    valueAnimation: true,
                    formatter: v => v.toFixed(0) + '%',
                    fontSize: 28, fontWeight: 700,
                    color: '#e8eaf0', offsetCenter: [0, '10%'],
                },
                title: { offsetCenter: [0, '82%'], fontSize: 11, color: '#6b707c', fontWeight: 400 },
                data: [{ value: soc, name: 'State of Charge' }],
            }],
        });
    }

    function renderEnergyChart(s) {
        if (!charts.energy) charts.energy = echarts.init(els.chartEnergy);
        const e = s.energy || {};
        const items = [
            { name: 'Generated', value: e.generating, color: '#ffb020' },
            { name: 'Consumed', value: e.consuming, color: '#a78bfa' },
            { name: 'Autoconsumed', value: e.autoconsuming, color: '#f472b6' },
            { name: 'Charged', value: e.charging, color: '#37d0a0' },
            { name: 'Discharged', value: e.discharging, color: '#22d3ee' },
            { name: 'Imported', value: e.importing, color: '#3aa0ff' },
            { name: 'Exported', value: e.exporting, color: '#37d0a0' },
        ].filter(i => i.value != null);
        charts.energy.setOption({
            backgroundColor: 'transparent',
            tooltip: {
                trigger: 'axis',
                axisPointer: { type: 'shadow' },
                backgroundColor: '#242932',
                borderColor: '#3a404d',
                textStyle: { color: '#e8eaf0' },
                valueFormatter: v => v.toFixed(1) + ' kWh',
            },
            grid: { left: 60, right: 20, top: 20, bottom: 30 },
            xAxis: {
                type: 'category',
                data: items.map(i => i.name),
                axisLabel: { color: '#9aa0ad' },
                axisLine: { lineStyle: { color: '#3a404d' } },
            },
            yAxis: {
                type: 'value',
                name: 'kWh',
                nameTextStyle: { color: '#6b707c' },
                axisLabel: { color: '#9aa0ad' },
                splitLine: { lineStyle: { color: '#2e333e' } },
            },
            series: [{
                type: 'bar',
                data: items.map(i => ({ value: i.value, itemStyle: { color: i.color, borderRadius: [4, 4, 0, 0] } })),
                barWidth: 42,
            }],
        });
    }

    function renderTodayChart(samples) {
        if (!charts.today) charts.today = echarts.init(els.chartToday);
        const ts = samples.map(s => s.ts);
        const series = [
            { name: 'PV Generation', key: 'powerGenerating', color: '#ffb020', stack: null },
            { name: 'Home Load', key: 'powerConsuming', color: '#a78bfa', stack: null },
            { name: 'Grid Net', key: 'powerNet', color: '#3aa0ff', stack: null },
            { name: 'Battery Net', key: 'powerBatt', color: '#37d0a0', stack: null },
        ];
        const prepared = samples.map(s => ({
            ts: s.ts,
            powerGenerating: s.powerGenerating,
            powerConsuming: s.powerConsuming,
            powerNet: (s.powerImporting || 0) - (s.powerExporting || 0),
            powerBatt: (s.powerDischarging || 0) - (s.powerCharging || 0),
        }));
        charts.today.setOption({
            backgroundColor: 'transparent',
            animation: false,
            tooltip: {
                trigger: 'axis',
                backgroundColor: '#242932',
                borderColor: '#3a404d',
                textStyle: { color: '#e8eaf0' },
                valueFormatter: v => (v == null ? '—' : Math.round(v) + ' W'),
            },
            legend: {
                textStyle: { color: '#9aa0ad' },
                top: 0,
            },
            grid: { left: 60, right: 20, top: 36, bottom: 40 },
            xAxis: {
                type: 'category',
                boundaryGap: false,
                data: ts,
                axisLabel: { color: '#9aa0ad', formatter: v => new Date(v).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) },
                axisLine: { lineStyle: { color: '#3a404d' } },
            },
            yAxis: {
                type: 'value',
                name: 'W',
                nameTextStyle: { color: '#6b707c' },
                axisLabel: { color: '#9aa0ad' },
                splitLine: { lineStyle: { color: '#2e333e' } },
            },
            series: series.map(s => ({
                name: s.name,
                type: 'line',
                showSymbol: false,
                smooth: true,
                lineStyle: { width: 2, color: s.color },
                areaStyle: { opacity: 0.08, color: s.color },
                data: prepared.map(r => r[s.key]),
            })),
        });
    }

    async function fetchJSON(url, query) {
        const qs = new URLSearchParams(query || {}).toString();
        const res = await fetch(url + (qs ? '?' + qs : ''));
        if (!res.ok) {
            let msg = `HTTP ${res.status}`;
            try { msg = (await res.json()).error || msg; } catch (_) { /* ignore */ }
            throw new Error(msg);
        }
        return res.json();
    }

    async function loadRealtime() {
        try {
            const s = await fetchJSON(REALTIME_URL);
            lastSnapshot = s;
            clearError();
            setStatus(s.status || 'offline');
            renderKpis(s);
            renderGauge(s);
            renderEnergyChart(s);
            if (flow) flow.update(s);
        } catch (err) {
            setStatus('offline');
            showError('Realtime data unavailable: ' + err.message);
        }
    }

    async function loadTodayHistory() {
        try {
            const end = new Date();
            const start = new Date(end.getTime() - 24 * 3600 * 1000);
            const data = await fetchJSON(HISTORY_URL, {
                start: start.toISOString(),
                end: end.toISOString(),
            });
            if (data.samples && data.samples.length) {
                renderTodayChart(data.samples);
            }
        } catch (err) {
            console.warn('History chart unavailable:', err.message);
        }
    }

    function init() {
        flow = new FlowDiagram(els.flow);
        loadRealtime();
        loadTodayHistory();
        setInterval(loadRealtime, POLL_MS);

        window.addEventListener('resize', () => {
            Object.values(charts).forEach(c => c && c.resize());
        });
    }

    document.addEventListener('DOMContentLoaded', init);
})();