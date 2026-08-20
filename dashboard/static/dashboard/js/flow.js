/**
 * FlowDiagram — an N8N-style node graph showing live energy flows.
 *
 * Nodes are HTML cards laid out on a logical canvas (1060 x 600). Edges are
 * SVG bezier curves that light up and animate their dashed stroke in the
 * direction the energy is actually flowing.
 */
(function (global) {
    'use strict';

    const W = 1060;
    const H = 600;

    const NODES = {
        pv:       { x: 60,  y: 40,  w: 180, h: 110, color: '#ffb020', name: 'PV Panels',    icon: 'solar' },
        home:     { x: 820, y: 40,  w: 180, h: 110, color: '#a78bfa', name: 'Home',         icon: 'home' },
        inverter: { x: 440, y: 245, w: 180, h: 110, color: '#ff6d5a', name: 'Inverter',     icon: 'bolt' },
        grid:     { x: 60,  y: 450, w: 180, h: 100, color: '#3aa0ff', name: 'Grid',         icon: 'grid' },
        battery:  { x: 820, y: 450, w: 180, h: 100, color: '#37d0a0', name: 'Battery',      icon: 'battery' },
    };

    const PORTS = {
        right: (n) => [n.x + n.w, n.y + n.h / 2],
        left: (n) => [n.x, n.y + n.h / 2],
        top: (n) => [n.x + n.w / 2, n.y],
        bottom: (n) => [n.x + n.w / 2, n.y + n.h],
        bottomLeft: (n) => [n.x + 12, n.y + n.h],
        bottomRight: (n) => [n.x + n.w - 12, n.y + n.h],
    };

    const EDGES = [
        { id: 'pv',       color: '#ffb020', from: 'pv',       to: 'inverter', fp: 'right', tp: 'left' },
        { id: 'home',     color: '#a78bfa', from: 'inverter', to: 'home',     fp: 'right', tp: 'left' },
        { id: 'grid',     color: '#3aa0ff', from: 'grid',     to: 'inverter', fp: 'right', tp: 'bottomLeft',  bidirectional: true },
        { id: 'battery',  color: '#37d0a0', from: 'inverter', to: 'battery',  fp: 'bottomRight', tp: 'top',    bidirectional: true },
    ];

    const ICONS = {
        solar: '<path d="M3 12h4l2-3 3 5 2-2h7" stroke="currentColor" stroke-width="1.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/><circle cx="12" cy="12" r="3.2" fill="none" stroke="currentColor" stroke-width="1.6"/>',
        home: '<path d="M3 11.5 12 4l9 7.5M5.5 10.5V20h13v-9.5M9.5 20v-6h5v6" stroke="currentColor" stroke-width="1.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
        bolt: '<path d="M13 3 5 13.5h5L10 21l8-10.5h-5L13 3z" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linejoin="round"/>',
        grid: '<path d="M12 3v18M12 6h-4M12 10H5M12 14h-4M12 18H7M12 14h5M12 10h5M12 6h3" stroke="currentColor" stroke-width="1.6" fill="none" stroke-linecap="round"/>',
        battery: '<rect x="3" y="7" width="16" height="10" rx="1.6" stroke="currentColor" stroke-width="1.6" fill="none"/><path d="M21 10v4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><rect x="5.2" y="9.2" width="6" height="5.6" rx="1" fill="currentColor"/>',
    };

    function bezierPath(x1, y1, x2, y2) {
        const dx = x2 - x1;
        const c1x = x1 + dx * 0.42;
        const c2x = x2 - dx * 0.42;
        return `M ${x1} ${y1} C ${c1x} ${y1} ${c2x} ${y2} ${x2} ${y2}`;
    }

    function bezierMid(x1, y1, x2, y2) {
        return [
            0.125 * x1 + 0.375 * (x1 + (x2 - x1) * 0.42) + 0.375 * (x2 - (x2 - x1) * 0.42) + 0.125 * x2,
            0.125 * y1 + 0.375 * y1 + 0.375 * y2 + 0.125 * y2,
        ];
    }

    const NODE_ORDER = ['pv', 'home', 'inverter', 'grid', 'battery'];

    class FlowDiagram {
        constructor(container) {
            this.container = container;
            this._build();
            this._last = null;
        }

        _build() {
            this.container.classList.add('flow-canvas');
            this.container.style.aspectRatio = `${W} / ${H}`;

            const bg = document.createElement('div');
            bg.className = 'flow-grid-bg';
            this.container.appendChild(bg);

            const svgNS = 'http://www.w3.org/2000/svg';
            this.svg = document.createElementNS(svgNS, 'svg');
            this.svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
            this.svg.setAttribute('preserveAspectRatio', 'none');
            this.svg.classList.add('flow-edges');
            this.container.appendChild(this.svg);

            this.edgeEls = {};
            this.nodes = {};

            // edges first so nodes render on top
            for (const edge of EDGES) {
                const from = NODES[edge.from];
                const to = NODES[edge.to];
                const [x1, y1] = PORTS[edge.fp](from);
                const [x2, y2] = PORTS[edge.tp](to);
                const path = document.createElementNS(svgNS, 'path');
                path.setAttribute('d', bezierPath(x1, y1, x2, y2));
                path.setAttribute('class', 'flow-edge');
                path.style.setProperty('--edge-color', edge.color);
                this.svg.appendChild(path);

                const [mx, my] = bezierMid(x1, y1, x2, y2);
                const label = document.createElementNS(svgNS, 'text');
                label.setAttribute('class', 'edge-label');
                label.setAttribute('x', mx);
                label.setAttribute('y', my - 8);
                label.textContent = edge.label || '';
                this.svg.appendChild(label);

                this.edgeEls[edge.id] = { path, label, color: edge.color, bidirectional: !!edge.bidirectional };
            }

            for (const id of NODE_ORDER) {
                const n = NODES[id];
                const el = document.createElement('div');
                el.className = 'flow-node';
                el.style.setProperty('--node-color', n.color);
                el.style.left = (n.x / W * 100) + '%';
                el.style.top = (n.y / H * 100) + '%';
                el.style.width = (n.w / W * 100) + '%';
                el.style.height = (n.h / H * 100) + '%';

                el.innerHTML = `
                    <div class="node-head">
                        <span class="node-icon"><svg viewBox="0 0 24 24" width="16" height="16">${ICONS[n.icon]}</svg></span>
                        <span class="node-name">${n.name}</span>
                    </div>
                    <div class="node-value"><span class="v">—</span></div>
                    <div class="node-meta"></div>
                `;
                this.container.appendChild(el);
                this.nodes[id] = el;
            }
        }

        _fmt(watts, unit = 'W') {
            if (watts === null || watts === undefined || isNaN(watts)) return '—';
            if (Math.abs(watts) >= 1000) return (watts / 1000).toFixed(2) + ' kW';
            return Math.round(watts) + ` ${unit}`;
        }

        _fmtEnergy(kwh) {
            if (kwh === null || kwh === undefined || isNaN(kwh)) return '—';
            return kwh.toFixed(1) + ' kWh';
        }

        update(s) {
            this._last = s;
            const p = s.power || {};
            const e = s.energy || {};

            this._setNode('pv', this._fmt(p.generating), `today ${this._fmtEnergy(e.generating)}`);
            this._setNode('home', this._fmt(p.consuming), `today ${this._fmtEnergy(e.consuming)}`);
            const inverterW = (p.generating || 0) + (p.discharging || 0) + (p.importing || 0);
            this._setNode('inverter', this._fmt(inverterW), '');
            this._setNode('battery', `${s.battery_soc != null ? Math.round(s.battery_soc) : '—'}%`, `SoC · ${this._fmt(p.charging)} / ${this._fmt(p.discharging)}`);

            const net = (p.exporting || 0) - (p.importing || 0);
            this._setNode('grid', `${net >= 0 ? '+' : ''}${this._fmt(Math.abs(net))}`, net >= 0 ? 'exporting to grid' : 'importing from grid');

            // ---- edges ----
            const pvOn = (p.generating || 0) > 20;
            const homeOn = (p.autoconsuming || 0) > 20;
            const chargeOn = (p.charging || 0) > 20;
            const dischargeOn = (p.discharging || 0) > 20;
            const exportOn = (p.exporting || 0) > 20;
            const importOn = (p.importing || 0) > 20;

            this._edge('pv', pvOn, false, pvOn ? p.generating : null);
            this._edge('home', homeOn, false, homeOn ? p.autoconsuming : null);

            if (exportOn) this._edge('grid', true, false, p.exporting);
            else if (importOn) this._edge('grid', true, true, p.importing);
            else this._edge('grid', false, false, null);

            if (chargeOn) this._edge('battery', true, false, p.charging);
            else if (dischargeOn) this._edge('battery', true, true, p.discharging);
            else this._edge('battery', false, false, null);

            // pulse source nodes
            this._pulse('pv', pvOn);
            this._pulse('inverter', pvOn || chargeOn || exportOn);
            this._pulse('battery', chargeOn || dischargeOn);
            this._pulse('grid', exportOn || importOn);
            this._pulse('home', homeOn || importOn || dischargeOn);
        }

        _setNode(id, value, meta) {
            const el = this.nodes[id];
            if (!el) return;
            el.querySelector('.v').textContent = value;
            el.querySelector('.node-meta').textContent = meta || '';
        }

        _edge(id, active, reverse, power) {
            const edge = this.edgeEls[id];
            const path = edge.path;
            path.classList.toggle('active', active);
            path.classList.toggle('flow', active);
            path.classList.toggle('reverse', active && reverse);
            edge.label.textContent = active ? this._fmt(power) : '';
            edge.label.style.fill = active ? edge.color : '';
            if (active) edge.label.style.filter = `drop-shadow(0 0 4px ${edge.color})`;
            else edge.label.style.filter = '';
        }

        _pulse(id, on) {
            const el = this.nodes[id];
            if (el) el.classList.toggle('active', on);
        }
    }

    global.FlowDiagram = FlowDiagram;
})(window);