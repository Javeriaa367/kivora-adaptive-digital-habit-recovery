document.addEventListener('DOMContentLoaded', async () => {
  const statCardsEl = document.getElementById('stat-cards');
  if (!statCardsEl) return;

  // Recovery Plan progress
  const recoveryEl = document.getElementById('recovery-progress');
  if (recoveryEl) {
    try {
      const rRes = await fetch('/api/recovery/active');
      const rData = await rRes.json();
      const plan = rData.ok ? rData.plan : null;
      if (plan) {
        recoveryEl.innerHTML = `
          <div class="flex items-center justify-between mb-3">
            <div>
              <p class="text-xs text-teal-600 font-semibold uppercase mb-1"><i class="fa-solid fa-route mr-1"></i>Recovery Plan</p>
              <p class="font-display font-semibold text-ink">${plan.title || 'Your recovery plan'}</p>
            </div>
            <span class="text-sm text-slate-400">Day ${plan.progress.current_day} of ${plan.duration_days}</span>
          </div>
          <div class="w-full bg-slate-100 rounded-full h-2.5 mb-3">
            <div class="bg-teal-500 h-2.5 rounded-full transition-all" style="width: ${plan.progress.percent}%"></div>
          </div>
          <div class="flex items-center justify-between">
            <p class="text-xs text-slate-400">${plan.progress.completed} of ${plan.progress.total} days complete (${plan.progress.percent}%)</p>
            <a href="/recovery" class="text-sm font-semibold text-teal-600 hover:text-teal-700">Continue Plan <i class="fa-solid fa-arrow-right ml-1"></i></a>
          </div>`;
      } else {
        recoveryEl.innerHTML = `
          <div class="flex items-center justify-between">
            <p class="text-sm text-slate-500">No active recovery plan yet.</p>
            <a href="/recovery" class="text-sm font-semibold text-teal-600 hover:text-teal-700">Start a Plan <i class="fa-solid fa-arrow-right ml-1"></i></a>
          </div>`;
      }
    } catch {
      recoveryEl.innerHTML = '<p class="text-sm text-slate-400">Could not load your recovery plan right now.</p>';
    }
  }

  const res = await fetch('/api/dashboard-data');
  const data = await res.json();

  const cards = [
    { label: 'Journal streak', value: `${data.journal_streak_days} day${data.journal_streak_days === 1 ? '' : 's'}`, icon: 'fa-fire' },
    { label: 'Journal entries', value: data.total_journal_entries, icon: 'fa-book' },
    { label: 'Most common mood', value: data.most_common_emotion || '—', icon: 'fa-face-smile' },
    { label: 'Avg. sentiment', value: data.average_sentiment !== null ? data.average_sentiment : '—', icon: 'fa-gauge' },
  ];
  statCardsEl.innerHTML = cards.map(c => `
    <div class="bg-white rounded-xl border border-slate-200 px-4 py-3">
      <div class="flex items-center gap-2 text-slate-400 text-xs mb-1"><i class="fa-solid ${c.icon} text-teal-500"></i> ${c.label}</div>
      <div class="text-ink font-display font-bold text-lg">${c.value}</div>
    </div>`).join('');

  // Daily challenge
  const challengeEl = document.getElementById('daily-challenge');
  if (challengeEl) {
    challengeEl.innerHTML = `
      <div class="flex items-center gap-3">
        <span class="w-10 h-10 rounded-xl bg-teal-500 text-white flex items-center justify-center flex-shrink-0"><i class="fa-solid fa-star"></i></span>
        <div><p class="text-xs font-semibold text-teal-700 uppercase">Today's challenge</p>
        <p class="text-sm text-slate-700">${data.daily_challenge}</p></div>
      </div>`;
  }

  // Badges
  const badgesGrid = document.getElementById('badges-grid');
  if (badgesGrid) {
    const badges = data.badges || [];
    badgesGrid.innerHTML = badges.length ? badges.map(b => `
      <div class="flex flex-col items-center text-center bg-teal-50 border border-teal-200 rounded-xl p-3">
        <span class="w-10 h-10 rounded-full bg-teal-500 text-white flex items-center justify-center mb-2"><i class="fa-solid ${b.icon}"></i></span>
        <p class="text-xs font-semibold text-ink">${b.name}</p>
        <p class="text-[10px] text-slate-500">${b.desc}</p>
      </div>`).join('') : '<p class="text-sm text-slate-400 col-span-full">No badges yet — write a journal entry or run an assessment to start earning them.</p>';
  }

  // Calendar heatmap (simple CSS grid, 7 rows x weeks)
  const calEl = document.getElementById('calendar-heatmap');
  if (calEl && data.calendar) {
    const cells = data.calendar.map(d => {
      let bg = 'bg-slate-100';
      if (d.count > 0) {
        if (d.avg_sentiment > 0.15) bg = 'bg-teal-400';
        else if (d.avg_sentiment < -0.15) bg = 'bg-coral-400';
        else bg = 'bg-amber-300';
      }
      return `<div class="w-3 h-3 rounded-sm ${bg}" title="${d.date}${d.count ? ' — ' + d.count + ' entr' + (d.count === 1 ? 'y' : 'ies') : ' — no entries'}"></div>`;
    }).join('');
    calEl.innerHTML = `<div class="grid grid-flow-col grid-rows-7 gap-1 overflow-x-auto pb-2">${cells}</div>
      <div class="flex items-center gap-3 mt-2 text-[11px] text-slate-400 px-2">
        <span class="flex items-center gap-1"><span class="w-2.5 h-2.5 rounded-sm bg-teal-400 inline-block"></span>Positive</span>
        <span class="flex items-center gap-1"><span class="w-2.5 h-2.5 rounded-sm bg-amber-300 inline-block"></span>Neutral</span>
        <span class="flex items-center gap-1"><span class="w-2.5 h-2.5 rounded-sm bg-coral-400 inline-block"></span>Negative</span>
        <span class="flex items-center gap-1"><span class="w-2.5 h-2.5 rounded-sm bg-slate-100 inline-block"></span>No entry</span>
      </div>`;
  }

  if (data.wellbeing_trend && data.wellbeing_trend.length) {
    Plotly.newPlot('wellbeing-trend-chart', [{
      x: data.wellbeing_trend.map(p => p.date),
      y: data.wellbeing_trend.map(p => p.wellbeing_score),
      type: 'scatter', mode: 'lines+markers', line: { color: '#0EA5A0' }, fill: 'tozeroy',
      fillcolor: 'rgba(14,165,160,0.08)',
    }], { title: 'Wellbeing score trend', yaxis: { range: [0, 10] }, margin: { t: 40 } },
    { responsive: true, displayModeBar: false });
  } else {
    document.getElementById('wellbeing-trend-chart').innerHTML =
      '<p class="text-sm text-slate-400 text-center py-8">Run a few predictions to see your trend here.</p>';
  }

  const dist = data.emotion_distribution || {};
  if (Object.keys(dist).length) {
    Plotly.newPlot('mood-distribution-chart', [{
      labels: Object.keys(dist), values: Object.values(dist), type: 'pie', hole: 0.5,
      marker: { colors: ['#0EA5A0', '#2DD4C4', '#94A3B8', '#F5A524', '#FB923C', '#F2545B', '#DC3A42'] },
    }], { title: 'Mood distribution', margin: { t: 40 } }, { responsive: true, displayModeBar: false });
  } else {
    document.getElementById('mood-distribution-chart').innerHTML =
      '<p class="text-sm text-slate-400 text-center py-8">Write a few journal entries to see your mood distribution.</p>';
  }
});

document.addEventListener('DOMContentLoaded', async () => {
  const btn = document.getElementById('email-report-btn');
  if (!btn) return;
  const statusEl = document.getElementById('email-report-status');
  btn.addEventListener('click', async () => {
    btn.disabled = true;
    statusEl.classList.remove('hidden');
    statusEl.textContent = 'Sending…';
    statusEl.className = 'text-xs font-semibold mt-2 text-slate-500';
    try {
      const res = await fetch('/reports/email', { method: 'POST' });
      const data = await res.json();
      if (data.ok && data.sent) {
        statusEl.textContent = 'Sent! Check your inbox (dev mode prints it to the server console).';
        statusEl.className = 'text-xs font-semibold mt-2 text-teal-600';
      } else {
        statusEl.textContent = 'Could not send the email right now. Try again later.';
        statusEl.className = 'text-xs font-semibold mt-2 text-coral-600';
      }
    } catch {
      statusEl.textContent = 'Could not send the email right now. Try again later.';
      statusEl.className = 'text-xs font-semibold mt-2 text-coral-600';
    } finally {
      btn.disabled = false;
    }
  });
});
