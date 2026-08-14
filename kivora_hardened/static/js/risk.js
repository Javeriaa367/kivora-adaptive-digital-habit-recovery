document.addEventListener('DOMContentLoaded', async () => {
  const canvas = document.getElementById('risk-trend-chart');
  if (!canvas) return;

  const COLORS = {
    depression: '#0d9488', burnout: '#f59e0b', anxiety: '#ef4444',
    digital_addiction: '#6366f1', loneliness: '#ec4899',
  };

  try {
    const res = await fetch('/api/risk/trend');
    const data = await res.json();
    if (!data.ok) return;

    const allDates = new Set();
    Object.values(data.trend).forEach(points => points.forEach(p => allDates.add(p.date)));
    const labels = Array.from(allDates).sort();

    const datasets = Object.entries(data.trend)
      .filter(([, points]) => points.length > 0)
      .map(([category, points]) => {
        const byDate = Object.fromEntries(points.map(p => [p.date, p.score]));
        return {
          label: category.replace('_', ' '),
          data: labels.map(d => (d in byDate ? byDate[d] : null)),
          borderColor: COLORS[category] || '#64748b',
          backgroundColor: COLORS[category] || '#64748b',
          spanGaps: true,
          tension: 0.3,
        };
      });

    if (!datasets.length) {
      canvas.parentElement.innerHTML = '<p class="text-sm text-slate-400">Not enough history yet — check back after a few more journal entries and assessments.</p>';
      return;
    }

    new Chart(canvas, {
      type: 'line',
      data: { labels, datasets },
      options: {
        responsive: true,
        scales: { y: { beginAtZero: true, title: { display: true, text: 'Risk score' } } },
        plugins: { legend: { position: 'bottom' } },
      },
    });
  } catch (err) {
    console.error('risk trend load failed', err);
  }
});
