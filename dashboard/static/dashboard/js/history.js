/* History & analytics: fetch range from the API and render ECharts. */
(function () {
    'use strict';

    const HISTORY_URL = '/api/history/';
    const MAX_DAYS = window.PLANT_MAX_HISTORY_DAYS || 7;

    const els = {
        error: document.getElementById('history-error'),
        content: document.getElementById('history-content'),
        summary: document.getElementById('summary-strip'),
        start: document.getElementById('start'),
        end: document.getElementById('end'),
        apply: document.getElementById('apply-range'),
        power: document.getElementById('chart-power'),
        soc: document.getElementById('chart-soc'),
        energy: document.getElementById('chart-energy'),
    };

    const charts = {};
    let current = null;

    const COLORS = {
        powerGenerating: '#ffb020',
        powerConsuming: '#a78bfa',
        powerAutoconsuming: '#f472b6',
        powerCharging: '#37d0a0',
        powerDischarging: '#22d3ee',
        powerImporting: '#3aa0ff',
        powerExporting: '#37d0a0',
        batterySoC: '#37d0a0',
    };

    function localValue(dt) {
        const d = new Date(dt);
        const pad = n => String(n).padStart(2, '0');
        return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
    }

    function setDefaultRange() {
        const now = new Date();
        const dayAgo = new Date(now.getTime() - 24 * 3600 * 1000);
        els.start.value = localValue(dayAgo);
        els.end.value = localValue(now);
    }

    function applyQuick(range) {
        const now = new Date();
        let start, end = now;
        if (range === '24h') {
            start = new Date(now.getTime() - 24 * 3600 * 1000);
        } else if (range === 'yesterday') {
            const y = new Date(now);
            y.setDate(y.getDate() - 1);
            y.setHours(0, 0, 0, 0);
            start = y;
            end = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0);
        } else if (range === '7d') {
            start = new Date(now.getTime() - 7 * 24 * 3600 * 1000);
        }
        els.start.value = localValue(start);
        els.end.value = localValue(end);
        load();
    }

    function showError(msg) {
        els.error.textContent = msg;
        els.error.classList.remove('hidden');
        els.content.classList.add('hidden');
    }

    function clearError() {
        els.error.classList.add('hidden');
        els.content.classList.remove('hidden');
    }

    function toUTC(s) {
        const d = new Date(s);
        if (isNaN(d)) return null;
        return d.toISOString();
    }

    async function load() {
        const start = toUTC(els.start.value);
        const end = toUTC(els.end.value);
        if (!start || !end || end <= start) {
            showError('Please choose a valid start/end range.');
            return;
        }
        if ((end - start) > MAX_DAYS * 24 * 3600 * 1000) {
            showError(`Range too large. Maximum allowed is ${MAX_DAYS} days.`);
            return;
        }

        try {
            const res = await fetch(`${HISTORY_URL}?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`);
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
            clearError();
            current = data;
            renderAll(data);
        } catch (err) {
            showError('Failed to load history: ' + err.message);
        }
    }

    function summarize(samples) {
        const max = {};
        for (const s of samples) {
            for (const key of Object.keys(COLORS)) {
                const v = s[key];
                if (typeof v === 'number' && !isNaN(v) && (max[key] === undefined || v > max[key])) {
                    max[key] = v;
                }
            }
        }
        const n = samples.length || 1;
        max.socAvg = samples.length ? samples.reduce((a, s) => a + (s.batterySoC || 0), 0) / samples.length : null;
        return { max, n };
    }

    function renderSummary({ max }) {
        const fmt = v => (v == null ? '—' : Math.round(v).toLocaleString() + ' W');
        const items = [
            { label: 'PV Peak', value: fmt(max.powerGenerating), color: '#ffb020' },
            { label: 'Load Peak', value: fmt(max.powerConsuming), color: '#a78bfa' },
            { label: 'Self-Consumption Peak', value: fmt(max.powerAutoconsuming), color: '#f472b6' },
            { label: 'Battery Charge Peak', value: fmt(max.powerCharging), color: '#37d0a0' },
            { label: 'Battery Discharge Peak', value: fmt(max.powerDischarging), color: '#22d3ee' },
            { label: 'Import Peak', value: fmt(max.powerImporting), color: '#3aa0ff' },
            { label: 'Export Peak', value: fmt(max.powerExporting), color: '#37d0a0' },
        ];
        els.summary.innerHTML = items.map(i =>
            `<div class="summary-item" style="--s-color:${i.color}"><div class="s-label">${i.label}</div><div class="s-value">${i.value}</div></div>`
        ).join('');
    }

    function baseOption() {
        return {
            backgroundColor: 'transparent',
            animation: false,
            tooltip: {
                trigger: 'axis',
                backgroundColor: '#242932',
                borderColor: '#3a404d',
                textStyle: { color: '#e8eaf0' },
            },
            legend: { textStyle: { color: '#9aa0ad' }, top: 0 },
            grid: { left: 60, right: 24, top: 36, bottom: 46 },
            xAxis: {
                type: 'category',
                boundaryGap: false,
                data: [],
                axisLabel: {
                    color: '#9aa0ad',
                    formatter: v => new Date(v).toLocaleString([], { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }),
                },
                axisLine: { lineStyle: { color: '#3a404d' } },
            },
            yAxis: {
                type: 'value',
                axisLabel: { color: '#9aa0ad' },
                splitLine: { lineStyle: { color: '#2e333e' } },
                nameTextStyle: { color: '#6b707c' },
            },
            series: [],
        };
    }

    function getChart(id, height) {
        if (!charts[id]) {
            charts[id] = echarts.init(document.getElementById('chart-' + id));
            charts[id].resize({ height: height || undefined });
        }
        return charts[id];
    }

    function addLine(chart, name, key, color, opts = {}) {
        return {
            name,
            key,
            type: 'line',
            showSymbol: false,
            smooth: true,
            lineStyle: { width: 2, color, type: opts.type || 'solid' },
            areaStyle: opts.area ? { opacity: 0.08, color } : undefined,
            data: [],
            z: opts.z || 1,
        };
    }

    function renderPower(samples) {
        const chart = getChart('power', 360);
        const ts = samples.map(s => s.ts);
        const series = [
            addLine(chart, 'PV Generation', 'powerGenerating', COLORS.powerGenerating, { area: true }),
            addLine(chart, 'Home Load', 'powerConsuming', COLORS.powerConsuming, { area: true }),
            addLine(chart, 'Self-Consumption', 'powerAutoconsuming', COLORS.powerAutoconsuming),
            addLine(chart, 'Battery Charge', 'powerCharging', COLORS.powerCharging),
            addLine(chart, 'Battery Discharge', 'powerDischarging', COLORS.powerDischarging),
            addLine(chart, 'Grid Import', 'powerImporting', COLORS.powerImporting, { type: 'dashed' }),
            addLine(chart, 'Grid Export', 'powerExporting', COLORS.powerExporting, { type: 'dashed' }),
        ].filter(s => samples.some(x => x[s.key] != null));

        for (const s of series) {
            s.data = samples.map(x => x[s.key] != null ? Math.round(x[s.key]) : null);
        }

        const opt = baseOption();
        opt.xAxis.data = ts;
        opt.yAxis.name = 'W';
        opt.series = series;
        opt.tooltip.valueFormatter = v => (v == null ? '—' : Math.round(v) + ' W');
        chart.setOption(opt, true);
    }

    function renderSoc(samples) {
        const chart = getChart('soc', 260);
        const ts = samples.map(s => s.ts);
        const opt = baseOption();
        opt.xAxis.data = ts;
        opt.yAxis = { ...opt.yAxis, min: 0, max: 100, name: '%' };
        opt.tooltip.valueFormatter = v => (v == null ? '—' : v.toFixed(1) + ' %');
        opt.series = [{
            name: 'Battery SoC',
            type: 'line',
            showSymbol: false,
            smooth: true,
            lineStyle: { width: 3, color: COLORS.batterySoC },
            areaStyle: { color: 'rgba(55,208,160,.15)' },
            data: samples.map(s => s.batterySoC != null ? s.batterySoC : null),
        }];
        chart.setOption(opt, true);
    }

    function renderEnergy(samples) {
        const chart = getChart('energy', 300);
        const rangeDays = (new Date(current.end) - new Date(current.start)) / (24 * 3600 * 1000);
        const bucket = rangeDays <= 1.5 ? 'hour' : 'day';

        const buckets = {};
        const order = [];
        for (const s of samples) {
            const d = new Date(s.ts);
            let key;
            if (bucket === 'day') {
                key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
            } else {
                key = d.toISOString().slice(0, 13) + ':00:00';
            }
            if (!buckets[key]) {
                buckets[key] = { gen: 0, cons: 0, imp: 0, exp: 0 };
                order.push(key);
            }
            const b = buckets[key];
            const hours = 5 / 60; // 5-minute samples
            b.gen += (s.powerGenerating || 0) * hours;
            b.cons += (s.powerConsuming || 0) * hours;
            b.imp += (s.powerImporting || 0) * hours;
            b.exp += (s.powerExporting || 0) * hours;
        }

        const data = order.map(k => ({
            gen: buckets[k].gen / 1000,
            cons: buckets[k].cons / 1000,
            imp: buckets[k].imp / 1000,
            exp: buckets[k].exp / 1000,
        }));

        const opt = baseOption();
        opt.xAxis.data = order;
        opt.xAxis.boundaryGap = true;
        opt.yAxis.name = 'kWh';
        opt.tooltip.valueFormatter = v => (v == null ? '—' : v.toFixed(2) + ' kWh');
        opt.legend.data = ['Generated', 'Consumed', 'Imported', 'Exported'];
        opt.series = [
            { name: 'Generated', type: 'bar', stack: 'energy', itemStyle: { color: COLORS.powerGenerating }, data: data.map(d => d.gen) },
            { name: 'Consumed', type: 'bar', stack: 'energy', itemStyle: { color: COLORS.powerConsuming }, data: data.map(d => d.cons) },
            { name: 'Imported', type: 'bar', stack: 'grid', itemStyle: { color: COLORS.powerImporting }, data: data.map(d => d.imp) },
            { name: 'Exported', type: 'bar', stack: 'grid', itemStyle: { color: COLORS.powerExporting }, data: data.map(d => d.exp) },
        ];
        chart.setOption(opt, true);
    }

    function renderAll(data) {
        const samples = data.samples || [];
        if (!samples.length) {
            renderSummary({ sum: {} });
            Object.values(charts).forEach(c => c && c.clear && c.clear());
            showError('No data available for the selected range.');
            return;
        }
        renderSummary(summarize(samples));
        renderPower(samples);
        renderSoc(samples);
        renderEnergy(samples);
    }

    document.addEventListener('DOMContentLoaded', () => {
        setDefaultRange();
        document.querySelectorAll('[data-range]').forEach(btn => {
            btn.addEventListener('click', () => applyQuick(btn.dataset.range));
        });
        els.apply.addEventListener('click', load);
        window.addEventListener('resize', () => Object.values(charts).forEach(c => c && c.resize()));
        load();
    });
})();