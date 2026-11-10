/* Account Pulse: interactive charts, count-ups, and filters. No libraries. */
(function () {
  const COLORS = { Critical: '#e5484d', Watch: '#f0a020', Healthy: '#2fa36b' };
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const fmt = (d) => { const p = d.split('-'); return MONTHS[+p[1] - 1] + ' ' + (+p[2]); };
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const statusFor = (v) => (v < 45 ? 'Critical' : v < 65 ? 'Watch' : 'Healthy');

  function render(el, animate) {
    const full = JSON.parse(el.dataset.series || '[]');
    if (!full.length) { el.innerHTML = '<p class="muted">No history yet.</p>'; return; }
    const range = +(el.dataset.range || 0);
    const data = range ? full.slice(-range) : full;
    const compact = el.dataset.compact === '1';
    const W = Math.max(120, el.clientWidth || 600);
    const H = compact ? 76 : 300;
    const pl = compact ? 2 : 38, pr = compact ? 6 : 14, pt = compact ? 8 : 16, pb = compact ? 6 : 30;
    const iw = W - pl - pr, ih = H - pt - pb;
    const x = (i) => pl + (data.length < 2 ? iw : (i * iw) / (data.length - 1));
    let lo = 0, hi = 100;
    if (compact) {   // stock-style autoscale so small moves are visible
      const vals = data.map((p) => p.s);
      lo = Math.max(0, Math.min(...vals) - 8); hi = Math.min(100, Math.max(...vals) + 8);
      if (hi - lo < 24) { const m = (hi + lo) / 2; lo = Math.max(0, m - 12); hi = Math.min(100, lo + 24); }
    }
    const y = (v) => pt + (1 - (Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo)) * ih;
    const band = (a, b, c, o) => { a = Math.max(a, lo); b = Math.min(b, hi); return b > a ? `<rect x="${pl}" y="${y(b)}" width="${iw}" height="${y(a) - y(b)}" fill="${c}" opacity="${o}"/>` : ''; };
    const last = data[data.length - 1];
    const col = COLORS[last.st] || COLORS[statusFor(last.s)];
    const gid = 'g' + Math.random().toString(36).slice(2);

    let s = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Health score history">`;
    s += `<defs><linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="${col}" stop-opacity=".30"/><stop offset="1" stop-color="${col}" stop-opacity="0"/></linearGradient></defs>`;
    // Zones: the grading scale lives in the chart itself
    s += band(0, 45, COLORS.Critical, .07) + band(45, 65, COLORS.Watch, .08) + band(65, 100, COLORS.Healthy, .05);
    if (!compact) {
      [0, 25, 50, 75, 100].forEach((g) => {
        s += `<line class="grid" x1="${pl}" x2="${W - pr}" y1="${y(g)}" y2="${y(g)}"/>`;
        s += `<text class="axis" x="${pl - 8}" y="${y(g) + 4}" text-anchor="end">${g}</text>`;
      });
      [[45, 'Critical zone below 45', COLORS.Critical], [65, 'Healthy zone above 65', COLORS.Healthy]].forEach(([v, l, c]) => {
        s += `<line x1="${pl}" x2="${W - pr}" y1="${y(v)}" y2="${y(v)}" stroke="${c}" stroke-width="1" stroke-dasharray="5 5" opacity=".7"/>`;
        s += `<text class="zone" x="${W - pr - 6}" y="${y(v) - 6}" text-anchor="end" fill="${c}">${l}</text>`;
      });
      const idx = [...new Set([0, Math.floor((data.length - 1) / 2), data.length - 1])];
      idx.forEach((i) => {
        const a = data.length === 1 ? 'end' : i === 0 ? 'start' : i === data.length - 1 ? 'end' : 'middle';
        s += `<text class="axis" x="${x(i)}" y="${H - 8}" text-anchor="${a}">${fmt(data[i].d)}</text>`;
      });
    }
    if (data.length > 1) {
      const pts = data.map((p, i) => `${x(i).toFixed(1)},${y(p.s).toFixed(1)}`).join('L');
      s += `<path class="area" d="M${pts}L${x(data.length - 1)},${y(0)}L${x(0)},${y(0)}Z" fill="url(#${gid})"/>`;
      s += `<path class="line draw" pathLength="1" d="M${pts}" fill="none" stroke="${col}" stroke-width="${compact ? 2 : 2.5}" stroke-linejoin="round" stroke-linecap="round"/>`;
    }
    s += `<circle class="pulse-ring" cx="${x(data.length - 1)}" cy="${y(last.s)}" r="${compact ? 3 : 5}" fill="${col}"/>`;
    s += `<circle cx="${x(data.length - 1)}" cy="${y(last.s)}" r="${compact ? 3 : 4.5}" fill="${col}"/>`;
    s += `<line class="cross" x1="0" x2="0" y1="${pt}" y2="${H - pb}"/>`;
    s += `<circle class="hdot" r="${compact ? 4 : 6}" cx="-20" cy="-20"/>`;
    s += `<rect x="0" y="0" width="${W}" height="${H}" fill="transparent" class="hit"/></svg><div class="tip"></div>`;
    el.innerHTML = s;

    if (!animate) el.querySelectorAll('.draw, .area').forEach((n) => (n.style.animation = 'none'));

    const svg = el.querySelector('svg'), cross = svg.querySelector('.cross'), hd = svg.querySelector('.hdot'), tip = el.querySelector('.tip');
    const step = data.length > 1 ? iw / (data.length - 1) : iw;
    function move(ev) {
      const r = svg.getBoundingClientRect();
      let i = Math.round((ev.clientX - r.left - pl) / step);
      i = data.length < 2 ? 0 : Math.max(0, Math.min(data.length - 1, i));
      const p = data[i], px = x(i), py = y(p.s), st = p.st || statusFor(p.s), c = COLORS[st];
      cross.setAttribute('x1', px); cross.setAttribute('x2', px); cross.style.opacity = 1;
      hd.setAttribute('cx', px); hd.setAttribute('cy', py); hd.setAttribute('fill', c); hd.style.opacity = 1;
      const prev = i > 0 ? data[i - 1].s : null;
      const d = prev == null ? '' : p.s - prev;
      const ch = d === '' ? '' : d > 0 ? `<span class="up">▲ ${d}</span>` : d < 0 ? `<span class="down">▼ ${-d}</span>` : '<span class="muted">– 0</span>';
      tip.innerHTML = `<div class="tip-d">${fmt(p.d)}</div><div class="tip-s"><b>${p.s}</b><span class="tip-st" style="background:${c}">${st}</span>${ch}</div>` +
        (p.h && !compact ? `<div class="tip-h">${esc(p.h)}</div>` : '');
      tip.style.opacity = 1;
      const tw = tip.offsetWidth;
      let left = px + 14; if (left + tw > W) left = px - tw - 14;
      tip.style.left = Math.max(0, left) + 'px';
      tip.style.top = (compact ? -6 : Math.max(0, Math.min(H - tip.offsetHeight - 30, py - 30))) + 'px';
    }
    function leave() { cross.style.opacity = 0; hd.style.opacity = 0; tip.style.opacity = 0; }
    svg.addEventListener('pointermove', move);
    svg.addEventListener('pointerdown', move);
    svg.addEventListener('pointerleave', leave);
  }

  function initCharts() {
    const charts = document.querySelectorAll('.chart');
    charts.forEach((c) => render(c, true));
    let t;
    window.addEventListener('resize', () => { clearTimeout(t); t = setTimeout(() => charts.forEach((c) => c.innerHTML && render(c, false)), 150); });
    document.querySelectorAll('[data-range-for]').forEach((btn) => btn.addEventListener('click', () => {
      const target = document.getElementById(btn.dataset.rangeFor);
      target.dataset.range = btn.dataset.range;
      btn.parentElement.querySelectorAll('button').forEach((b) => b.classList.toggle('on', b === btn));
      render(target, true);
    }));
  }

  function initCountUps() {
    document.querySelectorAll('.countup').forEach((el) => {
      const end = parseFloat(el.dataset.value), prefix = el.dataset.prefix || '', start = performance.now(), dur = 900;
      const tick = (now) => {
        const k = Math.min(1, (now - start) / dur), v = end * (1 - Math.pow(1 - k, 3));
        el.textContent = prefix + Math.round(v).toLocaleString();
        if (k < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    });
  }

  function initFilters() {
    document.querySelectorAll('[data-filter-scope]').forEach((scope) => {
      const items = document.querySelectorAll(scope.dataset.filterScope);
      const state = {};
      const search = scope.querySelector('input[type=search]');
      const apply = () => {
        const q = search ? search.value.trim().toLowerCase() : '';
        items.forEach((it) => {
          const okTags = Object.entries(state).every(([g, v]) => v === 'all' || (it.dataset[g] || '') === v);
          const okText = !q || (it.dataset.name || it.textContent).toLowerCase().includes(q);
          it.style.display = okTags && okText ? '' : 'none';
        });
      };
      scope.querySelectorAll('[data-group]').forEach((grp) => {
        state[grp.dataset.group] = 'all';
        grp.querySelectorAll('button').forEach((b) => b.addEventListener('click', () => {
          state[grp.dataset.group] = b.dataset.value;
          grp.querySelectorAll('button').forEach((x) => x.classList.toggle('on', x === b));
          apply();
        }));
      });
      if (search) search.addEventListener('input', apply);
    });
  }

  document.addEventListener('DOMContentLoaded', () => { initCharts(); initCountUps(); initFilters(); });
})();
