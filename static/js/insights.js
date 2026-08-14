document.addEventListener('DOMContentLoaded', () => {
  const metadata = JSON.parse(document.getElementById('metadata-json').textContent);
  const targets = metadata.targets;
  const targetKeys = Object.keys(targets);

  // ---- Tabs ----
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab-btn').forEach(b => {
        b.classList.remove('border-teal-500', 'text-teal-600');
        b.classList.add('border-transparent', 'text-slate-500');
      });
      btn.classList.add('border-teal-500', 'text-teal-600');
      btn.classList.remove('border-transparent', 'text-slate-500');
      document.querySelectorAll('.tab-panel').forEach(p => p.classList.add('hidden'));
      document.getElementById(`tab-${btn.dataset.tab}`).classList.remove('hidden');
    });
  });

  // ---- Metric cards ----
  const metricCardsEl = document.getElementById('metric-cards');
  metricCardsEl.innerHTML = targetKeys.map(key => {
    const t = targets[key];
    const metric = t.cv_accuracy_mean ?? t.cv_r2_mean ?? 0;
    const metricLabel = t.cv_accuracy_mean !== undefined ? 'Accuracy' : 'R²';
    const strong = t.confidence === 'strong';
    return `<div class="bg-white rounded-xl border border-slate-200 p-4">
      <p class="text-xs text-slate-400 mb-1">${key.replace(/_/g,' ')}</p>
      <p class="text-2xl font-display font-bold ${strong ? 'text-teal-600' : 'text-amber-600'}">${(metric*100).toFixed(0)}%</p>
      <p class="text-[10px] text-slate-400">${metricLabel} · ${t.model} · ${strong ? 'validated' : 'experimental'}</p>
    </div>`;
  }).join('');

  // ---- Performance chart ----
  const values = targetKeys.map(k => (targets[k].cv_accuracy_mean ?? targets[k].cv_r2_mean ?? 0));
  const colors = targetKeys.map(k => targets[k].confidence === 'strong' ? '#0EA5A0' : '#F5A524');
  Plotly.newPlot('perf-chart', [{ x: targetKeys, y: values, type: 'bar', marker: { color: colors } }], {
    title: 'Cross-validated performance by target', yaxis: { range: [0, 1] }, margin: { t: 40 },
  }, { responsive: true, displayModeBar: false });

  // ---- Feature importance ----
  const impSelect = document.getElementById('importance-target-select');
  const importableTargets = targetKeys.filter(k => targets[k].feature_importance);
  impSelect.innerHTML = importableTargets.map(k => `<option value="${k}">${k.replace(/_/g,' ')}</option>`).join('');

  function renderImportance(key) {
    const fi = targets[key].feature_importance || [];
    Plotly.newPlot('importance-chart', [{
      x: fi.map(f => f.importance).reverse(), y: fi.map(f => f.feature.replace(/_/g,' ')).reverse(),
      type: 'bar', orientation: 'h', marker: { color: '#0EA5A0' },
    }], { title: `Top features — ${key.replace(/_/g,' ')}`, margin: { t: 40, l: 160 } },
    { responsive: true, displayModeBar: false });
  }
  if (importableTargets.length) { renderImportance(importableTargets[0]); impSelect.addEventListener('change', () => renderImportance(impSelect.value)); }

  // ---- Confusion matrices ----
  const cmSelect = document.getElementById('confusion-target-select');
  const cmTargets = targetKeys.filter(k => targets[k].confusion_matrix);
  cmSelect.innerHTML = cmTargets.map(k => `<option value="${k}">${k.replace(/_/g,' ')}</option>`).join('');

  function renderConfusion(key) {
    const t = targets[key];
    const cm = t.confusion_matrix;
    const labels = t.confusion_matrix_labels || (cm.length === 2 ? ['Not at-risk','At-risk'] : cm.map((_,i)=>`Class ${i}`));
    Plotly.newPlot('confusion-chart', [{
      z: cm, x: labels, y: labels, type: 'heatmap', colorscale: 'Teal',
      texttemplate: '%{z}', showscale: false,
    }], { title: `Confusion matrix — ${key.replace(/_/g,' ')} (${t.model})`,
          xaxis: { title: 'Predicted' }, yaxis: { title: 'Actual', autorange: 'reversed' }, margin: { t: 40 } },
    { responsive: true, displayModeBar: false });
  }
  if (cmTargets.length) { renderConfusion(cmTargets[0]); cmSelect.addEventListener('change', () => renderConfusion(cmSelect.value)); }

  // ---- Dead targets accordion ----
  const dead = metadata.dead_targets_transparency || {};
  const accordionEl = document.getElementById('dead-targets-accordion');
  accordionEl.innerHTML = Object.entries(dead).map(([name, info], i) => `
    <div class="bg-white rounded-xl border border-slate-200 overflow-hidden">
      <button class="accordion-toggle w-full flex items-center justify-between px-4 py-3 text-left" data-idx="${i}">
        <span class="text-sm font-semibold text-ink">${name.replace(/_/g,' ')}</span>
        <i class="fa-solid fa-chevron-down text-slate-400 text-xs transition-transform"></i>
      </button>
      <div class="accordion-body hidden px-4 pb-4 text-sm text-slate-500">
        ${info.note} (strongest correlation: <span class="font-mono-data">${info.strongest_feature}</span> at r=${info.max_abs_correlation})
      </div>
    </div>`).join('') || '<p class="text-sm text-slate-400">No transparency data available.</p>';

  accordionEl.querySelectorAll('.accordion-toggle').forEach(btn => {
    btn.addEventListener('click', () => {
      const body = btn.nextElementSibling;
      body.classList.toggle('hidden');
      btn.querySelector('i').classList.toggle('rotate-180');
    });
  });
});
