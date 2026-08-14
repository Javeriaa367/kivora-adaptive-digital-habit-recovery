document.addEventListener('DOMContentLoaded', () => {
  const listEl = document.getElementById('habits-list');
  const form = document.getElementById('habit-form');
  const input = document.getElementById('habit-name');

  function render(habits) {
    if (!habits.length) {
      listEl.innerHTML = '<p class="text-sm text-slate-400">No habits yet — add one above to get started.</p>';
      return;
    }
    listEl.innerHTML = habits.map(h => `
      <div class="bg-white rounded-xl border border-slate-200 p-4 flex items-center justify-between">
        <div>
          <p class="font-semibold text-ink text-sm">${h.name}</p>
          <p class="text-xs text-slate-400">
            <i class="fa-solid fa-fire text-amber-500"></i> ${h.streak} day streak · ${h.total_checkins} total check-ins
          </p>
        </div>
        <button data-id="${h.id}" class="checkin-btn text-sm font-semibold px-4 py-2 rounded-lg transition-colors
          ${h.checked_today ? 'bg-teal-100 text-teal-700 cursor-default' : 'bg-ink text-white hover:bg-slate-800'}"
          ${h.checked_today ? 'disabled' : ''}>
          ${h.checked_today ? '<i class="fa-solid fa-check mr-1"></i> Done today' : 'Check in'}
        </button>
      </div>`).join('');

    listEl.querySelectorAll('.checkin-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const id = btn.dataset.id;
        const res = await fetch(`/api/habits/${id}/checkin`, { method: 'POST' });
        const data = await res.json();
        if (data.ok) render(data.habits);
      });
    });
  }

  async function load() {
    const res = await fetch('/api/habits');
    const data = await res.json();
    if (data.ok) render(data.habits);
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = input.value.trim();
    if (!name) return;
    const res = await fetch('/api/habits', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    const data = await res.json();
    if (data.ok) { render(data.habits); input.value = ''; }
    else alert(data.error);
  });

  load();
});
