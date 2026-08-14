document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('input[type="range"]').forEach((slider) => {
    const out = document.getElementById(slider.id + '-value');
    const paint = () => {
      const min = parseFloat(slider.min), max = parseFloat(slider.max), val = parseFloat(slider.value);
      const pct = ((val - min) / (max - min)) * 100;
      slider.style.background = `linear-gradient(to right, #0EA5A0 ${pct}%, #E2E8F0 ${pct}%)`;
      if (out) out.textContent = slider.value;
    };
    slider.addEventListener('input', paint);
    paint();
  });

  const form = document.getElementById('predict-form');
  if (!form) return;
  const btn = document.getElementById('submit-btn');
  const btnLabel = document.getElementById('submit-btn-label');
  const resultsEl = document.getElementById('results-container');
  const errorEl = document.getElementById('error-container');

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    btn.disabled = true;
    btnLabel.textContent = 'Running…';
    errorEl.classList.add('hidden');

    const formData = new FormData(form);
    const payload = {};
    formData.forEach((v, k) => { payload[k] = v; });

    try {
      const res = await fetch('/api/predict', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!data.ok) {
        if (data.upgrade_required) {
          throw new Error(data.error + ' Visit the Pricing page to upgrade.');
        }
        throw new Error(data.error || 'Prediction failed');
      }
      renderResults(data.results, data.recommendations, data.coach_report, data.explanations);
    } catch (err) {
      errorEl.innerHTML = `<div class="flex items-start gap-3 bg-coral-100 border border-coral-500/30 text-coral-600 rounded-2xl px-5 py-4">
        <i class="fa-solid fa-triangle-exclamation mt-0.5"></i>
        <div><p class="font-semibold text-sm">Error</p><p class="text-sm">${err.message}</p></div></div>`;
      errorEl.classList.remove('hidden');
    } finally {
      btn.disabled = false;
      btnLabel.textContent = 'Run Prediction Pipeline';
    }
  });

  function renderResults(r, recommendations, coachReport, explanations) {
    const risk = r.addiction_risk_flag,
          wb = r.wellbeing_score, wbFlag = r.wellbeing_risk_flag;
    const recCards = (recommendations || []).map(c => `
      <div class="bg-${c.color}-50 border border-${c.color}-200 rounded-xl p-4">
        <p class="font-semibold text-ink text-sm mb-2"><i class="fa-solid ${c.icon} text-${c.color}-600 mr-2"></i>${c.title}</p>
        <ul class="space-y-1">
          ${c.actions.map(a => `<li class="text-xs text-slate-600 flex gap-1.5"><span class="text-${c.color}-500">•</span>${a}</li>`).join('')}
        </ul>
      </div>`).join('');

    const explainKey = { addiction_risk_flag: 'Addiction Risk',
      wellbeing_score: 'Wellbeing Score', wellbeing_risk_flag: 'Wellbeing Flag' };
    const explainCards = explanations ? Object.entries(explanations)
      .filter(([key]) => key !== 'addiction_level_detail')
      .map(([key, e]) => `
      <details class="bg-white border border-slate-200 rounded-xl p-4">
        <summary class="text-sm font-semibold text-ink cursor-pointer flex items-center justify-between">
          <span><i class="fa-solid fa-circle-info text-teal-600 mr-1.5"></i>Why "${explainKey[key] || key}"?</span>
          <span class="text-xs text-slate-400 font-normal">${typeof e.confidence === 'number' ? (e.confidence*100).toFixed(0) + '% confidence' : e.confidence + ' confidence'}</span>
        </summary>
        <p class="text-sm text-slate-600 mt-3">${e.explanation}</p>
        <div class="mt-2 flex flex-wrap gap-1.5">
          ${e.top_factors.map(f => `<span class="text-xs bg-slate-100 text-slate-600 px-2 py-1 rounded-full">${f.label}${f.direction ? ' ' + f.direction : ''}</span>`).join('')}
        </div>
        <p class="text-xs text-slate-400 mt-3">${e.limitations}</p>
      </details>`).join('') : '';

    resultsEl.innerHTML = `
      <div class="bg-white rounded-2xl border border-slate-200 shadow-xl overflow-hidden">
        <div class="bg-ink px-6 sm:px-8 py-5">
          <h4 class="text-white font-display font-semibold"><i class="fa-solid fa-chart-line text-teal-400 mr-2"></i>Analysis Results</h4>
        </div>
        <div class="p-6 sm:p-8 grid grid-cols-1 md:grid-cols-3 gap-6">
          <div class="rounded-2xl border border-slate-200 p-5 ${risk.label === 'At-risk' ? 'bg-coral-100/40' : 'bg-teal-50/40'}">
            <p class="text-xs text-slate-500 font-semibold uppercase mb-1">Addiction Risk</p>
            <p class="text-2xl font-display font-bold ${risk.label === 'At-risk' ? 'text-coral-600' : 'text-teal-700'}">${risk.label}</p>
            <p class="text-sm text-slate-500 mt-1">Confidence: ${(risk.confidence*100).toFixed(0)}%</p>
          </div>
          <div class="rounded-2xl border border-slate-200 p-5 bg-slate-50">
            <p class="text-xs text-slate-500 font-semibold uppercase mb-1">Wellbeing Score</p>
            <p class="text-2xl font-display font-bold text-ink">${wb.value} <span class="text-sm text-slate-400">/ 10</span></p>
          </div>
          <div class="rounded-2xl border border-slate-200 p-5 ${wbFlag.label === 'Above median' ? 'bg-teal-50/40' : 'bg-amber-100/40'}">
            <p class="text-xs text-slate-500 font-semibold uppercase mb-1">Wellbeing Flag</p>
            <p class="text-2xl font-display font-bold ${wbFlag.label === 'Above median' ? 'text-teal-700' : 'text-amber-600'}">${wbFlag.label}</p>
            <p class="text-sm text-slate-500 mt-1">Confidence: ${(wbFlag.confidence*100).toFixed(0)}%</p>
          </div>
        </div>
        ${recCards ? `<div class="px-6 sm:px-8 pb-8"><p class="text-sm font-semibold text-slate-500 uppercase mb-3">Recommended for you</p>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-3">${recCards}</div></div>` : ''}
        ${explainCards ? `<div class="px-6 sm:px-8 pb-8"><p class="text-sm font-semibold text-slate-500 uppercase mb-3">Explain these predictions</p>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-3">${explainCards}</div></div>` : ''}
        ${coachReport ? `<div class="px-6 sm:px-8 pb-8">
          <div class="bg-slate-50 border border-slate-200 rounded-2xl p-5">
            <p class="text-sm font-semibold text-slate-500 uppercase mb-2"><i class="fa-solid fa-user-doctor text-teal-600 mr-1.5"></i>Your Wellness Report</p>
            <p class="text-sm text-slate-700 leading-relaxed">${coachReport.report}</p>
          </div>
        </div>` : ''}
      </div>`;
    resultsEl.classList.remove('hidden');
    resultsEl.scrollIntoView({ behavior: 'smooth', block: 'start' });

    const params = new URLSearchParams(location.search);
    if (params.get('onboard') === '1') {
      const cta = document.createElement('div');
      cta.className = 'mt-6 text-center';
      cta.innerHTML = `
        <a href="/journal?onboard=1" class="inline-flex items-center gap-2 bg-ink hover:bg-slate-800 text-white font-semibold text-sm px-6 py-3 rounded-xl transition-colors">
          Next: write your first journal entry <i class="fa-solid fa-arrow-right"></i>
        </a>
        <p class="text-xs text-slate-400 mt-2">Step 1 of 3 done — your results are saved to your history.</p>`;
      resultsEl.appendChild(cta);
    }
  }
});
