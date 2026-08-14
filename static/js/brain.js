/* Adaptive Brain Exercises — frontend.
 * Hydrates the per-day brain chips on the recovery page from
 * /api/brain/progress, then runs each exercise inside a modal backed by
 * /api/brain/today + /api/brain/attempts/<id>/submit. The server owns the
 * exercise (including the ground-truth answer); this file only renders the
 * redacted prompt and submits the user's response.
 */
document.addEventListener('DOMContentLoaded', () => {
  const card = document.getElementById('active-plan-card');
  if (!card) return;

  // Admin Interactive Demo Mode sets this so the /api/brain/... calls
  // below hit the admin-protected demo mirror. Empty on the player page.
  const API_BASE = window.KIVORA_DEMO_BASE || '';

  const modal = document.getElementById('brain-modal');
  const modalBody = document.getElementById('brain-modal-body');
  const modalEyebrow = document.getElementById('brain-modal-eyebrow');
  const modalClose = document.getElementById('brain-modal-close');

  let currentExercise = null;
  let currentDay = null;
  let lastTrigger = null;

  function focusableEls() {
    return Array.from(modal.querySelectorAll(
      'button:not([disabled]), [href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
    ));
  }

  function openModal() {
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    document.removeEventListener('keydown', onModalKeydown); // avoid stacking listeners on repeat opens (e.g. "Try another")
    document.addEventListener('keydown', onModalKeydown);
    // Focus lands on the close button immediately -- exercise content is
    // still loading (skeleton) at this point, so this is the first stable
    // focusable target for keyboard/screen-reader users.
    modalClose.focus();
  }
  function closeModal() {
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    modalBody.innerHTML = '';
    currentExercise = null;
    currentDay = null;
    document.removeEventListener('keydown', onModalKeydown);
    if (lastTrigger && document.body.contains(lastTrigger)) lastTrigger.focus();
    lastTrigger = null;
  }
  function onModalKeydown(e) {
    if (e.key === 'Escape') {
      e.preventDefault();
      closeModal();
      return;
    }
    if (e.key !== 'Tab') return;
    const focusable = focusableEls();
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }
  modalClose.addEventListener('click', closeModal);
  modal.addEventListener('click', (e) => { if (e.target === modal) closeModal(); });

  async function api(url, opts) {
    let res;
    try {
      res = await fetch(url, {
        method: opts && opts.method || 'GET',
        headers: { 'Content-Type': 'application/json' },
        body: opts && opts.body ? JSON.stringify(opts.body) : undefined,
      });
    } catch {
      // Network failure (offline, DNS, timeout) -- never let this reach
      // the caller as an unhandled rejection and leave the modal stuck.
      return { status: 0, data: { ok: false, error: "We couldn't reach the server. Check your connection and try again." } };
    }
    let data;
    try { data = await res.json(); } catch { data = { ok: false, error: 'Unexpected server response.' }; }
    return { status: res.status, data };
  }

  function escapeHtml(s) {
    const div = document.createElement('div');
    div.textContent = s == null ? '' : String(s);
    return div.innerHTML;
  }

  function errorBanner(message) {
    return `<div class="bg-coral-100 text-coral-600 text-sm rounded-xl px-4 py-3 mb-3">${escapeHtml(message)}</div>`;
  }

  function summaryEl() {
    return {
      streak: document.getElementById('brain-streak'),
      best: document.getElementById('brain-best'),
    };
  }

  function updateSummary(progress) {
    const el = summaryEl();
    if (el.streak) el.streak.textContent = String(progress.streak || 0);
    if (el.best) el.best.textContent = progress.best_percent ? `${progress.best_percent}%` : '—';
  }

  const kindLabels = {
    attention: 'Target scan',
    working_memory: 'Memory Arena',
    updating: 'Keep the largest',
    reframe: 'Inner Critic Battle',
    gratitude_scan: 'Specific appreciation',
    worry_reality: 'Worry vs Reality',
    night_reset: 'Night Mind Reset',
    urge_breaker: 'Urge Breaker',
  };

  // Sleep's exercise renders with extra restraint per product spec: no
  // letter/number chip grids, softer borders, slower transitions. Kept as
  // a lookup rather than an inline check so any future calm-mode kind
  // just adds a key here.
  const CALM_KINDS = new Set(['night_reset']);

  const skillLabels = {
    attention: 'Sustained attention',
    working_memory: 'Working memory & retrieval',
    updating: 'Attentional updating',
    reframe: 'Perspective flexibility',
    gratitude_scan: 'Specificity',
    worry_reality: 'Fact vs. prediction',
    night_reset: 'Controllability judgment',
    urge_breaker: 'Urge tolerance',
  };

  function statusFor(day) {
    if (!day) return { text: 'Not available yet', btn: 'Start', disabled: true };
    if (day.state === 'done') {
      return {
        text: `Best ${day.score}/${day.max_score} · ${kindLabels[day.kind] || 'brain exercise'} (Level ${day.tier})`,
        btn: 'Beat it',
        disabled: false,
      };
    }
    return {
      text: day.available ? 'A fresh exercise is waiting for this day' : 'Unlocks when this day is current',
      btn: 'Start',
      disabled: !day.available,
    };
  }

  function hydrateRows(progress) {
    card.querySelectorAll('.brain-exercise-row').forEach((row) => {
      const dayNumber = row.getAttribute('data-brain-day');
      const day = progress.days && progress.days[dayNumber];
      const status = statusFor(day);
      const textEl = row.querySelector('.brain-status-text');
      const btn = row.querySelector('.open-brain-btn');
      if (textEl) textEl.textContent = status.text;
      if (btn) {
        btn.textContent = status.btn;
        btn.disabled = status.disabled;
      }
    });
  }

  async function loadProgress() {
    const res = await api(`${API_BASE}/api/brain/progress`);
    if (res.data && res.data.ok && res.data.progress) {
      updateSummary(res.data.progress);
      hydrateRows(res.data.progress);
    }
  }

  // ---- exercise rendering -------------------------------------------------
  function chipList(items, highlight) {
    return `<div class="flex flex-wrap gap-2 my-3">
      ${items.map((item, i) => `<span class="inline-flex items-center justify-center min-w-8 h-8 px-2 rounded-lg font-mono-data text-sm font-semibold border ${
        highlight && highlight[i] ? 'border-sky-400 bg-sky-50 text-sky-700' : 'border-slate-200 bg-slate-50 text-slate-700'
      }">${escapeHtml(item)}</span>`).join('')}
    </div>`;
  }

  function renderExercise(ex) {
    modalEyebrow.textContent = `Adaptive brain exercise · Day ${ex.day_number}`;
    const lastInfo = ex.last
      ? `<p class="text-xs text-slate-400 mt-1">Last time: ${ex.last.score}/${ex.last.max_score} · Level ${ex.last.tier}</p>`
      : `<p class="text-xs text-slate-400 mt-1">Fresh exercise · Level ${ex.difficulty_tier}</p>`;

    let body = `
      <div class="mb-4">
        <p class="text-lg font-display font-bold text-ink">${escapeHtml(ex.title)}</p>
        <p class="text-xs font-medium uppercase tracking-wide text-sky-600 mt-1">Level ${ex.difficulty_tier}</p>
      </div>
      <p class="text-sm text-slate-600 leading-relaxed mb-3">${escapeHtml(ex.instructions)}</p>
      ${lastInfo}
    `;

    let controls = '';
    if (ex.kind === 'attention') {
      body += `
        <div class="rounded-xl border border-slate-200 bg-slate-50 p-4 mt-3 mb-2">
          <p class="text-[10px] font-semibold uppercase tracking-wide text-slate-400 mb-2">Letter stream — read once</p>
          ${chipList(ex.input.sequence)}
          <p class="text-sm text-slate-700 mt-2"><strong>${escapeHtml(ex.input.question)}</strong></p>
        </div>`;
      controls = `
        <div class="flex items-end gap-3 mt-2">
          <label class="flex-1">
            <span class="text-xs font-medium text-slate-500">Your answer</span>
            <input type="number" id="brain-answer" class="mt-1 w-full rounded-xl border border-slate-300 px-4 py-2.5 text-sm focus:outline-none" min="0">
          </label>
          <button type="button" class="brain-submit-btn bg-sky-600 hover:bg-sky-700 text-white text-sm font-semibold px-5 py-2.5 rounded-xl transition-colors">Check</button>
        </div>`;
    } else if (ex.kind === 'working_memory') {
      body += `
        <div class="rounded-xl border border-slate-200 bg-slate-50 p-4 mt-3 mb-2">
          <p class="text-[10px] font-semibold uppercase tracking-wide text-slate-400 mb-2">Study this list</p>
          ${chipList(ex.input.items)}
          <p class="text-sm text-slate-700 mt-2"><strong>${escapeHtml(ex.input.question)}</strong></p>
        </div>`;
      controls = `
        <div class="flex items-end gap-3 mt-2">
          <label class="flex-1">
            <span class="text-xs font-medium text-slate-500">Your answer</span>
            <input type="text" id="brain-answer" class="mt-1 w-full rounded-xl border border-slate-300 px-4 py-2.5 text-sm focus:outline-none" placeholder="The word…">
          </label>
          <button type="button" class="brain-submit-btn bg-sky-600 hover:bg-sky-700 text-white text-sm font-semibold px-5 py-2.5 rounded-xl transition-colors">Check</button>
        </div>`;
    } else if (ex.kind === 'updating') {
      body += `
        <div class="rounded-xl border border-slate-200 bg-slate-50 p-4 mt-3 mb-2">
          <p class="text-[10px] font-semibold uppercase tracking-wide text-slate-400 mb-2">Number stream — read once</p>
          ${chipList(ex.input.sequence)}
          <p class="text-sm text-slate-700 mt-2"><strong>${escapeHtml(ex.input.question)}</strong></p>
        </div>`;
      controls = `
        <div class="flex items-end gap-3 mt-2">
          <label class="flex-1">
            <span class="text-xs font-medium text-slate-500">Your answer</span>
            <input type="number" id="brain-answer" class="mt-1 w-full rounded-xl border border-slate-300 px-4 py-2.5 text-sm focus:outline-none" min="0">
          </label>
          <button type="button" class="brain-submit-btn bg-sky-600 hover:bg-sky-700 text-white text-sm font-semibold px-5 py-2.5 rounded-xl transition-colors">Check</button>
        </div>`;
    } else if (ex.kind === 'reframe') {
      body += `
        <div class="rounded-xl border border-slate-200 bg-slate-50 p-4 mt-3 mb-2">
          <p class="text-[10px] font-semibold uppercase tracking-wide text-slate-400 mb-2">The situation</p>
          <p class="text-sm text-slate-700">${escapeHtml(ex.input.situation)}</p>
          <p class="text-sm text-slate-700 mt-2 italic">“${escapeHtml(ex.input.thought)}”</p>
        </div>
        <p class="text-sm text-slate-700 font-medium mb-2">${escapeHtml(ex.input.question)}</p>
        <div class="space-y-2" id="brain-options" role="group" aria-label="Answer choices">
          ${ex.input.options.map((opt, i) => `
            <button type="button" class="brain-option-btn w-full text-left rounded-xl border border-slate-200 hover:border-sky-400 hover:bg-sky-50 px-4 py-3 text-sm text-slate-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed">
              ${escapeHtml(opt)}
            </button>`).join('')}
        </div>`;
    } else if (ex.kind === 'worry_reality') {
      body += `
        <div class="rounded-xl border border-slate-200 bg-slate-50 p-4 mt-3 mb-2">
          <p class="text-[10px] font-semibold uppercase tracking-wide text-slate-400 mb-2">The thought</p>
          <p class="text-sm text-slate-700 italic">“${escapeHtml(ex.input.thought)}”</p>
        </div>
        <p class="text-sm text-slate-700 font-medium mb-2">${escapeHtml(ex.input.question)}</p>
        <div class="space-y-2" id="brain-options" role="group" aria-label="Answer choices">
          ${ex.input.options.map((opt) => `
            <button type="button" class="brain-option-btn w-full text-left rounded-xl border border-slate-200 hover:border-sky-400 hover:bg-sky-50 px-4 py-3 text-sm text-slate-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed">
              ${escapeHtml(opt)}
            </button>`).join('')}
        </div>`;
    } else if (ex.kind === 'night_reset') {
      // Calm mode: muted borders, no chip grid, slower transitions, no
      // urgency language -- see CALM_KINDS above and prefers-reduced-motion
      // handling in style.css.
      body += `
        <div class="rounded-xl border border-slate-200 bg-slate-50/70 p-5 mt-3 mb-2 transition-colors duration-500">
          <p class="text-[10px] font-semibold uppercase tracking-wide text-slate-400 mb-2">The thought</p>
          <p class="text-sm text-slate-600 italic">“${escapeHtml(ex.input.thought)}”</p>
        </div>
        <p class="text-sm text-slate-600 font-medium mb-2">${escapeHtml(ex.input.question)}</p>
        <div class="space-y-2" id="brain-options" role="group" aria-label="Answer choices">
          ${ex.input.options.map((opt) => `
            <button type="button" class="brain-option-btn w-full text-left rounded-xl border border-slate-200 hover:border-sky-300 hover:bg-sky-50/60 px-4 py-3 text-sm text-slate-600 transition-colors duration-300 disabled:opacity-50 disabled:cursor-not-allowed">
              ${escapeHtml(opt)}
            </button>`).join('')}
        </div>`;
    } else if (ex.kind === 'urge_breaker') {
      body += `
        <div class="rounded-xl border border-slate-200 bg-slate-50 p-4 mt-3 mb-2">
          <p class="text-[10px] font-semibold uppercase tracking-wide text-slate-400 mb-2">Right now</p>
          <p class="text-sm text-slate-700">${escapeHtml(ex.input.scenario)}</p>
        </div>
        <p class="text-sm text-slate-700 font-medium mb-2">${escapeHtml(ex.input.question)}</p>
        <div class="space-y-2" id="brain-options" role="group" aria-label="Answer choices">
          ${ex.input.options.map((opt) => `
            <button type="button" class="brain-option-btn w-full text-left rounded-xl border border-slate-200 hover:border-sky-400 hover:bg-sky-50 px-4 py-3 text-sm text-slate-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed">
              ${escapeHtml(opt)}
            </button>`).join('')}
        </div>`;
    } else if (ex.kind === 'gratitude_scan') {
      controls = `
        <label class="block mt-3">
          <span class="text-sm text-slate-700 font-medium">${escapeHtml(ex.input.question)}</span>
          <span class="text-xs text-slate-400 block mt-1">Aim for ${ex.input.min_items}+ items, one per line. Generic words don't count.</span>
          <textarea id="brain-answer" rows="5" class="mt-2 w-full rounded-xl border border-slate-300 px-4 py-2.5 text-sm focus:outline-none" placeholder="1. …\n2. …\n3. …"></textarea>
        </label>
        <button type="button" class="brain-submit-btn w-full bg-sky-600 hover:bg-sky-700 text-white text-sm font-semibold px-5 py-2.5 rounded-xl transition-colors mt-3">Submit</button>`;
    }

    modalBody.innerHTML = body + controls;

    modalBody.querySelectorAll('.brain-option-btn').forEach((btn, i) => {
      btn.addEventListener('click', () => {
        modalBody.querySelectorAll('.brain-option-btn').forEach((b) => { b.disabled = true; });
        submitResponse(i);
      });
    });
    const submitBtn = modalBody.querySelector('.brain-submit-btn');
    if (submitBtn) {
      submitBtn.addEventListener('click', () => {
        const input = modalBody.querySelector('#brain-answer');
        submitResponse(input ? input.value : '');
      });
    }
  }

  async function openExercise(dayNumber) {
    currentDay = dayNumber;
    modalBody.innerHTML = '<div class="skeleton h-32 rounded-xl"></div>';
    openModal();
    const res = await api(`${API_BASE}/api/brain/today?day_number=${encodeURIComponent(dayNumber)}`);
    if (!(res.data && res.data.ok) || !res.data.exercise) {
      modalBody.innerHTML = errorBanner((res.data && res.data.error) || 'No exercise is ready for this day yet.');
      return;
    }
    currentExercise = res.data.exercise;
    renderExercise(currentExercise);
  }

  async function submitResponse(rawResponse) {
    if (!currentExercise) return;
    const optionKinds = ['reframe', 'worry_reality', 'night_reset', 'urge_breaker'];
    const submitBtn = modalBody.querySelector('.brain-submit-btn, .brain-option-btn');
    const disable = submitBtn && !optionKinds.includes(currentExercise.kind);
    if (disable) submitBtn.disabled = true;

    const res = await api(`${API_BASE}/api/brain/attempts/${currentExercise.attempt_id}/submit`, {
      method: 'POST',
      body: { response: rawResponse },
    });

    if (!(res.data && res.data.ok)) {
      modalBody.innerHTML = errorBanner((res.data && res.data.error) || "We couldn't save this challenge right now.") +
        `<div class="flex gap-3 mt-3">
          <button type="button" class="brain-retry-btn flex-1 bg-sky-600 hover:bg-sky-700 text-white text-sm font-semibold px-4 py-2.5 rounded-xl transition-colors">Try again</button>
          <button type="button" class="brain-close-btn flex-1 border border-slate-200 text-slate-600 hover:bg-slate-50 text-sm font-semibold px-4 py-2.5 rounded-xl transition-colors">Close</button>
        </div>`;
      modalBody.querySelector('.brain-close-btn').addEventListener('click', closeModal);
      modalBody.querySelector('.brain-retry-btn').addEventListener('click', () => submitResponse(rawResponse));
      return;
    }

    const r = res.data.result;
    const scoreBadge = r.correct
      ? `<span class="inline-flex items-center gap-1.5 rounded-full bg-emerald-100 text-emerald-700 px-3 py-1 text-xs font-semibold"><i class="fa-solid fa-check"></i> Correct · ${r.score}/${r.max_score}</span>`
      : `<span class="inline-flex items-center gap-1.5 rounded-full bg-coral-100 text-coral-600 px-3 py-1 text-xs font-semibold"><i class="fa-solid fa-xmark"></i> ${r.score}/${r.max_score}</span>`;

    const answerPreview = r.answer_preview
      ? `<p class="text-xs text-slate-500 mt-1">${r.correct ? 'Answer' : 'The answer'}: <strong>${escapeHtml(r.answer_preview)}</strong></p>`
      : '';

    const skillLine = skillLabels[r.kind]
      ? `<p class="text-xs text-slate-400 mt-3">Today's skill · <span class="font-semibold text-slate-500">${escapeHtml(skillLabels[r.kind])}</span></p>`
      : '';

    modalBody.innerHTML = `
      <div class="text-center py-4">
        <p class="text-4xl font-display font-bold text-ink mb-1">${r.correct ? 'Nice' : 'Close'}</p>
        ${scoreBadge}
        <p class="text-sm text-slate-600 mt-3 leading-relaxed">${escapeHtml(r.feedback)}</p>
        ${answerPreview}
        ${skillLine}
        <p class="text-xs text-slate-400 mt-2">Level now ${r.tier_after} · Brain streak ${r.streak} day(s)</p>
      </div>
      <div class="flex gap-3 mt-4">
        <button type="button" class="brain-try-btn flex-1 bg-sky-600 hover:bg-sky-700 text-white text-sm font-semibold px-4 py-2.5 rounded-xl transition-colors">Try another</button>
        <button type="button" class="brain-close-btn flex-1 border border-slate-200 text-slate-600 hover:bg-slate-50 text-sm font-semibold px-4 py-2.5 rounded-xl transition-colors">Close</button>
      </div>`;

    modalBody.querySelector('.brain-try-btn').addEventListener('click', () => openExercise(currentDay));
    modalBody.querySelector('.brain-close-btn').addEventListener('click', closeModal);

    loadProgress();
  }

  card.addEventListener('click', (e) => {
    const btn = e.target.closest('.open-brain-btn');
    if (!btn || btn.disabled) return;
    const row = btn.closest('.brain-exercise-row');
    if (!row) return;
    lastTrigger = btn;
    openExercise(row.getAttribute('data-brain-day'));
  });

  loadProgress();
});
