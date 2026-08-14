/* Recovery Plan — Activity Engine frontend.
 * Each day's task now opens an in-page modal with a real interactive
 * activity (journal / reflection / breathing / timer / check-in / habit /
 * AI conversation / progress review) instead of a checkbox. Every submit
 * hits a server endpoint that verifies ownership and the actual work
 * before marking the day complete — this file never marks anything done
 * on its own.
 */
document.addEventListener('DOMContentLoaded', () => {
  const card = document.getElementById('active-plan-card');
  if (!card) return;

  const modal = document.getElementById('activity-modal');
  const modalBody = document.getElementById('modal-body');
  const modalEyebrow = document.getElementById('modal-eyebrow');
  const modalClose = document.getElementById('modal-close');

  let reflectionTemplate = null;
  let quizTemplate = null;
  let assessmentDefaults = null;
  let currentTaskId = null;
  let breathingTimer = null; // cleanup handle for the breathing modal's timers
  let timerInterval = null;  // cleanup handle for the countdown modal

  // ---- modal plumbing ------------------------------------------------
  function openModal(eyebrow) {
    modalEyebrow.textContent = eyebrow;
    modal.classList.remove('hidden');
    modal.classList.add('flex');
  }
  function closeModal() {
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    modalBody.innerHTML = '';
    clearBreathingTimer();
    clearCountdown();
    currentTaskId = null;
  }
  modalClose.addEventListener('click', closeModal);
  modal.addEventListener('click', (e) => { if (e.target === modal) closeModal(); });

  function clearBreathingTimer() {
    if (breathingTimer) { clearTimeout(breathingTimer); breathingTimer = null; }
  }
  function clearCountdown() {
    if (timerInterval) { clearInterval(timerInterval); timerInterval = null; }
  }

  function updateProgress(progress) {
    const bar = document.getElementById('progress-bar');
    const label = document.getElementById('progress-label');
    if (bar) bar.style.width = `${progress.percent}%`;
    if (label) label.textContent = `${progress.completed} of ${progress.total} days complete (${progress.percent}%)`;
  }

  function markDayDone(taskId) {
    const rowEl = card.querySelector(`.activity-row[data-task-id="${taskId}"]`);
    if (!rowEl) return;
    rowEl.classList.add('opacity-90');
    const badge = rowEl.querySelector('span.w-5');
    if (badge) {
      badge.className = 'mt-0.5 w-5 h-5 shrink-0 rounded-full flex items-center justify-center text-[10px] bg-teal-500 text-white';
      badge.innerHTML = '<i class="fa-solid fa-check"></i>';
    }
    const actionSlot = rowEl.querySelector('.shrink-0:last-child');
    if (actionSlot) actionSlot.innerHTML = '<span class="text-xs font-semibold text-teal-600"><i class="fa-solid fa-check"></i> Done</span>';
    const textEl = rowEl.querySelector('p.text-sm.text-slate-700');
    if (textEl) textEl.classList.add('text-slate-500');
  }

  async function api(url, opts) {
    const res = await fetch(url, {
      method: opts && opts.method || 'GET',
      headers: { 'Content-Type': 'application/json' },
      body: opts && opts.body ? JSON.stringify(opts.body) : undefined,
    });
    let data;
    try { data = await res.json(); } catch { data = { ok: false, error: 'Unexpected server response.' }; }
    return { status: res.status, data };
  }

  function errorBanner(message) {
    return `<div class="bg-coral-100 text-coral-600 text-sm rounded-xl px-4 py-3 mb-3">${escapeHtml(message)}</div>`;
  }
  function escapeHtml(s) {
    const div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
  }

  function onActivityCompleted(taskId, planData) {
    markDayDone(taskId);
    if (planData && planData.progress) updateProgress(planData.progress);
    setTimeout(() => {
      window.location.reload(); // reload so day-group counts/lock state and progress bar all stay in sync
    }, 900);
  }

  // ---- open an activity ------------------------------------------------
  card.addEventListener('click', async (e) => {
    const btn = e.target.closest('.open-activity-btn');
    if (!btn) return;
    const rowEl = btn.closest('.activity-row');
    const taskId = rowEl.dataset.taskId;
    currentTaskId = taskId;

    const [{ data: activityRes }] = await Promise.all([
      api(`/api/recovery/activities/${taskId}`),
    ]);
    if (!activityRes.ok) {
      alert(activityRes.error || 'Could not open that activity.');
      return;
    }
    reflectionTemplate = activityRes.reflection_template;
    quizTemplate = activityRes.quiz_template;
    assessmentDefaults = activityRes.assessment_defaults;
    await api(`/api/recovery/activities/${taskId}/start`, { method: 'POST' });
    renderActivity(activityRes.activity);
  });

  function renderActivity(activity) {
    const renderers = {
      journal: renderJournal,
      reflection: renderReflection,
      breathing: renderBreathing,
      timer: renderTimer,
      checkin: renderCheckin,
      habit: renderHabit,
      ai_conversation: renderAiConversation,
      progress_review: renderProgressReview,
      quiz: renderQuiz,
      assessment: renderAssessment,
    };
    const fn = renderers[activity.activity_type] || renderCheckin;
    openModal(activity.activity_type.replace('_', ' '));
    fn(activity);
  }

  // ---- JOURNAL ---------------------------------------------------------
  function renderJournal(activity) {
    modalBody.innerHTML = `
      <h3 class="font-display font-bold text-lg text-ink mb-1">Reflection</h3>
      <p class="text-sm text-slate-500 mb-4">${escapeHtml(activity.task_text)}</p>
      <div id="journal-error"></div>
      <label class="block text-sm font-semibold text-ink mb-1.5">What's on your mind right now?</label>
      <textarea id="journal-worry" rows="3" class="w-full rounded-xl border border-slate-200 p-3 text-sm mb-4 focus:ring-2 focus:ring-teal-400 focus:outline-none" placeholder="Write freely — there's no wrong answer."></textarea>
      <label class="block text-sm font-semibold text-ink mb-1.5">What's within your control?</label>
      <textarea id="journal-control" rows="3" class="w-full rounded-xl border border-slate-200 p-3 text-sm mb-5 focus:ring-2 focus:ring-teal-400 focus:outline-none"></textarea>
      <button id="journal-submit" class="w-full bg-ink hover:bg-slate-800 text-white font-semibold py-3 rounded-xl">Analyze &amp; save reflection</button>
    `;
    document.getElementById('journal-submit').addEventListener('click', async () => {
      const worry = document.getElementById('journal-worry').value;
      const control = document.getElementById('journal-control').value;
      const submitBtn = document.getElementById('journal-submit');
      submitBtn.disabled = true;
      submitBtn.textContent = 'Saving…';
      const { data } = await api(`/api/recovery/activities/${activity.id}/journal`, {
        method: 'POST', body: { worry, control },
      });
      if (!data.ok) {
        document.getElementById('journal-error').innerHTML = errorBanner(data.error);
        submitBtn.disabled = false;
        submitBtn.textContent = 'Analyze & save reflection';
        return;
      }
      const crisisNote = data.activity.crisis_flag
        ? `<p class="text-xs text-amber-700 mt-2">If things feel heavier than usual, please consider reaching out to someone you trust or a crisis line — you're not alone in this.</p>` : '';
      modalBody.innerHTML = `
        <div class="text-center py-6">
          <div class="w-14 h-14 rounded-full bg-teal-100 text-teal-600 flex items-center justify-center mx-auto mb-4 text-2xl"><i class="fa-solid fa-check"></i></div>
          <h3 class="font-display font-bold text-lg text-ink mb-1">Reflection saved</h3>
          <p class="text-sm text-slate-500">Your reflection has been added to your Kivora journal history.</p>
          ${crisisNote}
        </div>`;
      onActivityCompleted(activity.id, data.plan);
      refreshPlanState();
    });
  }

  // ---- GUIDED REFLECTION / QUIZ -----------------------------------------
  function renderReflection(activity) {
    const questions = reflectionTemplate || [];
    modalBody.innerHTML = `
      <h3 class="font-display font-bold text-lg text-ink mb-1">Guided Reflection</h3>
      <p class="text-sm text-slate-500 mb-4">${escapeHtml(activity.task_text)}</p>
      <div id="reflection-error"></div>
      <div id="reflection-fields" class="space-y-4 mb-5"></div>
      <button id="reflection-submit" class="w-full bg-ink hover:bg-slate-800 text-white font-semibold py-3 rounded-xl">Save reflection</button>
    `;
    const fieldsEl = document.getElementById('reflection-fields');
    questions.forEach((q) => {
      const wrap = document.createElement('div');
      if (q.type === 'choice') {
        wrap.innerHTML = `
          <label class="block text-sm font-semibold text-ink mb-1.5">${escapeHtml(q.prompt)}</label>
          <div class="flex flex-wrap gap-2" data-qid="${q.id}">
            ${q.choices.map((c) => `<button type="button" class="reflection-choice-btn text-sm px-3.5 py-2 rounded-xl border border-slate-200 text-slate-600 hover:border-teal-400" data-value="${escapeHtml(c)}">${escapeHtml(c)}</button>`).join('')}
          </div>`;
      } else {
        wrap.innerHTML = `
          <label class="block text-sm font-semibold text-ink mb-1.5">${escapeHtml(q.prompt)}</label>
          <textarea rows="2" data-qid="${q.id}" class="reflection-text-input w-full rounded-xl border border-slate-200 p-3 text-sm focus:ring-2 focus:ring-teal-400 focus:outline-none"></textarea>`;
      }
      fieldsEl.appendChild(wrap);
    });
    fieldsEl.querySelectorAll('.reflection-choice-btn').forEach((b) => {
      b.addEventListener('click', () => {
        const group = b.closest('[data-qid]');
        group.querySelectorAll('.reflection-choice-btn').forEach((x) => x.classList.remove('bg-ink', 'text-white', 'border-ink'));
        b.classList.add('bg-ink', 'text-white', 'border-ink');
        group.dataset.value = b.dataset.value;
      });
    });

    document.getElementById('reflection-submit').addEventListener('click', async () => {
      const responses = questions.map((q) => {
        if (q.type === 'choice') {
          const group = fieldsEl.querySelector(`[data-qid="${q.id}"]`);
          return { id: q.id, answer: group.dataset.value || '' };
        }
        const input = fieldsEl.querySelector(`textarea[data-qid="${q.id}"]`);
        return { id: q.id, answer: input.value };
      });
      const submitBtn = document.getElementById('reflection-submit');
      submitBtn.disabled = true;
      const { data } = await api(`/api/recovery/activities/${activity.id}/reflection`, {
        method: 'POST', body: { responses },
      });
      if (!data.ok) {
        document.getElementById('reflection-error').innerHTML = errorBanner(data.error);
        submitBtn.disabled = false;
        return;
      }
      modalBody.innerHTML = `<div class="text-center py-6">
          <div class="w-14 h-14 rounded-full bg-teal-100 text-teal-600 flex items-center justify-center mx-auto mb-4 text-2xl"><i class="fa-solid fa-check"></i></div>
          <h3 class="font-display font-bold text-lg text-ink mb-1">Reflection saved</h3></div>`;
      onActivityCompleted(activity.id, data.plan);
      refreshPlanState();
    });
  }

  // ---- ASSESSMENT ---------------------------------------------------------
  function renderAssessment(activity) {
    const d = assessmentDefaults || {};
    modalBody.innerHTML = `
      <h3 class="font-display font-bold text-lg text-ink mb-1">Social-Media Assessment</h3>
      <p class="text-sm text-slate-500 mb-4">${escapeHtml(activity.task_text)}</p>
      <div id="assessment-error"></div>
      <form id="assessment-form" class="space-y-4 mb-5">
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block text-xs font-semibold text-slate-500 mb-1">Daily usage (hrs)</label>
            <input type="number" step="0.1" name="Daily_Usage_Hours" value="${d.Daily_Usage_Hours}" class="w-full rounded-lg border border-slate-200 px-2.5 py-2 text-sm">
          </div>
          <div>
            <label class="block text-xs font-semibold text-slate-500 mb-1">Notifications/day</label>
            <input type="number" name="Notifications_Per_Day" value="${d.Notifications_Per_Day}" class="w-full rounded-lg border border-slate-200 px-2.5 py-2 text-sm">
          </div>
          <div>
            <label class="block text-xs font-semibold text-slate-500 mb-1">Platforms used</label>
            <input type="number" name="Platforms_Used_Count" value="${d.Platforms_Used_Count}" class="w-full rounded-lg border border-slate-200 px-2.5 py-2 text-sm">
          </div>
          <div>
            <label class="block text-xs font-semibold text-slate-500 mb-1">Posts/week</label>
            <input type="number" name="Posts_Per_Week" value="${d.Posts_Per_Week}" class="w-full rounded-lg border border-slate-200 px-2.5 py-2 text-sm">
          </div>
        </div>
        <div>
          <label class="block text-xs font-semibold text-slate-500 mb-1">Primary platform</label>
          <select name="Primary_Platform" class="w-full rounded-lg border border-slate-200 px-2.5 py-2 text-sm bg-white">
            ${['Instagram', 'TikTok', 'YouTube', 'Facebook', 'Snapchat', 'Twitter/X'].map((p) => `<option ${p === d.Primary_Platform ? 'selected' : ''}>${p}</option>`).join('')}
          </select>
        </div>
        ${[
          ['FOMO_Score', 'FOMO'], ['Social_Comparison_Score', 'Social comparison'],
          ['Validation_Seeking_Score', 'Validation seeking'], ['Scroll_Without_Purpose', 'Scroll without purpose'],
        ].map(([field, label]) => `
          <div>
            <div class="flex items-center justify-between mb-1">
              <span class="text-xs font-semibold text-slate-500">${label}</span>
              <span class="text-xs font-mono-data text-teal-600">${d[field]}</span>
            </div>
            <input type="range" min="0" max="10" step="0.5" name="${field}" value="${d[field]}"
              class="w-full assessment-range" data-field="${field}">
          </div>`).join('')}
        <div class="grid grid-cols-3 gap-2">
          ${[
            ['Late_Night_Usage', 'Late-night use'], ['Tried_To_Cut_Back', 'Tried to cut back'], ['Failed_To_Cut_Back', 'Failed to cut back'],
          ].map(([field, label]) => `
            <div>
              <label class="block text-[11px] font-semibold text-slate-500 mb-1">${label}</label>
              <select name="${field}" class="w-full rounded-lg border border-slate-200 px-2 py-1.5 text-xs bg-white">
                <option value="0" ${d[field] === 0 ? 'selected' : ''}>No</option>
                <option value="1" ${d[field] === 1 ? 'selected' : ''}>Yes</option>
              </select>
            </div>`).join('')}
        </div>
        <div>
          <label class="block text-xs font-semibold text-slate-500 mb-1">First phone check in the morning</label>
          <select name="First_Check_Morning" class="w-full rounded-lg border border-slate-200 px-2.5 py-2 text-sm bg-white">
            <option value="0" ${d.First_Check_Morning === 0 ? 'selected' : ''}>&lt; 5 min</option>
            <option value="1" ${d.First_Check_Morning === 1 ? 'selected' : ''}>5-30 min</option>
            <option value="2" ${d.First_Check_Morning === 2 ? 'selected' : ''}>&gt; 30 min</option>
          </select>
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block text-xs font-semibold text-slate-500 mb-1">Sleep (hrs/night)</label>
            <input type="number" step="0.1" name="Sleep_Hours" value="${d.Sleep_Hours}" class="w-full rounded-lg border border-slate-200 px-2.5 py-2 text-sm">
          </div>
          <div>
            <label class="block text-xs font-semibold text-slate-500 mb-1">Activity (hrs/week)</label>
            <input type="number" step="0.1" name="Physical_Activity_Hrs_Week" value="${d.Physical_Activity_Hrs_Week}" class="w-full rounded-lg border border-slate-200 px-2.5 py-2 text-sm">
          </div>
          <div>
            <label class="block text-xs font-semibold text-slate-500 mb-1">Screen-free (hrs/day)</label>
            <input type="number" step="0.1" name="Screen_Free_Time_Hrs" value="${d.Screen_Free_Time_Hrs}" class="w-full rounded-lg border border-slate-200 px-2.5 py-2 text-sm">
          </div>
          <div>
            <label class="block text-xs font-semibold text-slate-500 mb-1">Offline relationships</label>
            <input type="number" step="0.5" min="0" max="10" name="Offline_Relationship_Quality" value="${d.Offline_Relationship_Quality}" class="w-full rounded-lg border border-slate-200 px-2.5 py-2 text-sm">
          </div>
        </div>
      </form>
      <button id="assessment-submit" class="w-full bg-ink hover:bg-slate-800 text-white font-semibold py-3 rounded-xl">Run assessment</button>
    `;
    modalBody.querySelectorAll('.assessment-range').forEach((input) => {
      input.addEventListener('input', (e) => {
        const valueLabel = e.target.closest('div').querySelector('.font-mono-data');
        if (valueLabel) valueLabel.textContent = e.target.value;
      });
    });
    document.getElementById('assessment-submit').addEventListener('click', async () => {
      const form = new FormData(document.getElementById('assessment-form'));
      const body = Object.fromEntries(form.entries());
      const submitBtn = document.getElementById('assessment-submit');
      submitBtn.disabled = true;
      submitBtn.textContent = 'Running…';
      const { data } = await api(`/api/recovery/activities/${activity.id}/assessment`, { method: 'POST', body });
      if (!data.ok) {
        document.getElementById('assessment-error').innerHTML = errorBanner(data.error);
        submitBtn.disabled = false;
        submitBtn.textContent = 'Run assessment';
        return;
      }
      const r = data.activity.result;
      modalBody.innerHTML = `<div class="text-center py-6">
          <div class="w-14 h-14 rounded-full bg-teal-100 text-teal-600 flex items-center justify-center mx-auto mb-4 text-2xl"><i class="fa-solid fa-check"></i></div>
          <h3 class="font-display font-bold text-lg text-ink mb-1">Wellbeing score: ${r.wellbeing_score.value}/10</h3>
          <p class="text-sm text-slate-500">Your usage pattern was assessed — see the full results on your dashboard.</p></div>`;
      onActivityCompleted(activity.id, data.plan);
      refreshPlanState();
    });
  }

  // ---- QUIZ / THOUGHT EXERCISE -------------------------------------------
  function renderQuiz(activity) {
    const items = quizTemplate || [];
    modalBody.innerHTML = `
      <h3 class="font-display font-bold text-lg text-ink mb-1">Thought Exercise</h3>
      <p class="text-sm text-slate-500 mb-4">${escapeHtml(activity.task_text)}</p>
      <div id="quiz-error"></div>
      <div id="quiz-fields" class="space-y-4 mb-5"></div>
      <button id="quiz-submit" class="w-full bg-ink hover:bg-slate-800 text-white font-semibold py-3 rounded-xl">Submit answers</button>
    `;
    const fieldsEl = document.getElementById('quiz-fields');
    items.forEach((q) => {
      const wrap = document.createElement('div');
      wrap.innerHTML = `
        <label class="block text-sm font-semibold text-ink mb-1.5">${escapeHtml(q.prompt)}</label>
        <div class="flex flex-wrap gap-2" data-qid="${q.id}">
          ${q.choices.map((c) => `<button type="button" class="quiz-choice-btn text-sm px-3.5 py-2 rounded-xl border border-slate-200 text-slate-600 hover:border-teal-400" data-value="${escapeHtml(c)}">${escapeHtml(c)}</button>`).join('')}
        </div>`;
      fieldsEl.appendChild(wrap);
    });
    fieldsEl.querySelectorAll('.quiz-choice-btn').forEach((b) => {
      b.addEventListener('click', () => {
        const group = b.closest('[data-qid]');
        group.querySelectorAll('.quiz-choice-btn').forEach((x) => x.classList.remove('bg-ink', 'text-white', 'border-ink'));
        b.classList.add('bg-ink', 'text-white', 'border-ink');
        group.dataset.value = b.dataset.value;
      });
    });
    document.getElementById('quiz-submit').addEventListener('click', async () => {
      const responses = items.map((q) => {
        const group = fieldsEl.querySelector(`[data-qid="${q.id}"]`);
        return { id: q.id, answer: group.dataset.value || '' };
      });
      const submitBtn = document.getElementById('quiz-submit');
      submitBtn.disabled = true;
      const { data } = await api(`/api/recovery/activities/${activity.id}/quiz`, {
        method: 'POST', body: { responses },
      });
      if (!data.ok) {
        document.getElementById('quiz-error').innerHTML = errorBanner(data.error);
        submitBtn.disabled = false;
        return;
      }
      const r = data.activity.result;
      modalBody.innerHTML = `<div class="text-center py-6">
          <div class="w-14 h-14 rounded-full bg-teal-100 text-teal-600 flex items-center justify-center mx-auto mb-4 text-2xl"><i class="fa-solid fa-check"></i></div>
          <h3 class="font-display font-bold text-lg text-ink mb-1">${r.score}/${r.total} correct</h3>
          <p class="text-sm text-slate-500">Nice work thinking through those.</p></div>`;
      onActivityCompleted(activity.id, data.plan);
      refreshPlanState();
    });
  }

  // ---- BREATHING ---------------------------------------------------------
  function renderBreathing(activity) {
    const totalRounds = 4;
    modalBody.innerHTML = `
      <h3 class="font-display font-bold text-lg text-ink mb-1">Breathing Exercise</h3>
      <p class="text-sm text-slate-500 mb-5">${escapeHtml(activity.task_text)}</p>
      <div id="breathing-error"></div>
      <div id="breathing-ready" class="text-center py-6">
        <p class="text-sm text-slate-500 mb-4">4 rounds of inhale–hold–exhale. Find a comfortable seat.</p>
        <button id="breathing-start" class="bg-ink hover:bg-slate-800 text-white font-semibold px-6 py-3 rounded-xl">Start</button>
      </div>
      <div id="breathing-active" class="hidden text-center py-4">
        <div class="w-32 h-32 mx-auto rounded-full bg-teal-400/30 border-2 border-teal-400 flex items-center justify-center mb-4 transition-transform" id="breath-circle" style="transition-duration: 4000ms;">
          <span id="breath-label" class="font-display font-semibold text-teal-700">Ready</span>
        </div>
        <p class="text-xs text-slate-400">Round <span id="breath-round">1</span> of ${totalRounds}</p>
      </div>
      <div id="breathing-done" class="hidden">
        <p class="text-sm font-semibold text-ink mb-2">How do you feel now?</p>
        <div class="flex flex-wrap gap-2 mb-5" id="breathing-mood-options">
          ${['Calmer', 'A little better', 'About the same', 'Still tense'].map((m) => `<button type="button" class="mood-btn text-sm px-3.5 py-2 rounded-xl border border-slate-200 text-slate-600 hover:border-teal-400" data-value="${m}">${m}</button>`).join('')}
        </div>
        <button id="breathing-save" class="w-full bg-ink hover:bg-slate-800 text-white font-semibold py-3 rounded-xl" disabled>Save session</button>
      </div>
    `;
    let selectedMood = null;
    let round = 0;
    let elapsedSeconds = 0;

    document.getElementById('breathing-start').addEventListener('click', () => {
      document.getElementById('breathing-ready').classList.add('hidden');
      document.getElementById('breathing-active').classList.remove('hidden');
      runRound();
    });

    function phase(name, seconds, scale, next) {
      const circle = document.getElementById('breath-circle');
      const label = document.getElementById('breath-label');
      if (!circle) return; // modal closed mid-cycle
      label.textContent = name;
      circle.style.transitionDuration = `${seconds * 1000}ms`;
      circle.style.transform = `scale(${scale})`;
      elapsedSeconds += seconds;
      breathingTimer = setTimeout(next, seconds * 1000);
    }

    function runRound() {
      phase('Inhale', 4, 1.3, () => {
        phase('Hold', 4, 1.3, () => {
          phase('Exhale', 6, 0.85, () => {
            round += 1;
            const roundEl = document.getElementById('breath-round');
            if (roundEl) roundEl.textContent = Math.min(round + 1, totalRounds);
            if (round >= totalRounds) {
              document.getElementById('breathing-active').classList.add('hidden');
              document.getElementById('breathing-done').classList.remove('hidden');
            } else {
              runRound();
            }
          });
        });
      });
    }

    modalBody.addEventListener('click', (e) => {
      const moodBtn = e.target.closest('.mood-btn');
      if (!moodBtn) return;
      modalBody.querySelectorAll('.mood-btn').forEach((b) => b.classList.remove('bg-ink', 'text-white', 'border-ink'));
      moodBtn.classList.add('bg-ink', 'text-white', 'border-ink');
      selectedMood = moodBtn.dataset.value;
      document.getElementById('breathing-save').disabled = false;
    });

    document.getElementById('breathing-done').addEventListener('click', async (e) => {
      if (e.target.id !== 'breathing-save') return;
      const saveBtn = document.getElementById('breathing-save');
      saveBtn.disabled = true;
      const { data } = await api(`/api/recovery/activities/${activity.id}/breathing`, {
        method: 'POST',
        body: { rounds_completed: totalRounds, duration_seconds: elapsedSeconds, mood_after: selectedMood },
      });
      if (!data.ok) {
        document.getElementById('breathing-error').innerHTML = errorBanner(data.error);
        saveBtn.disabled = false;
        return;
      }
      modalBody.innerHTML = `<div class="text-center py-6">
          <div class="w-14 h-14 rounded-full bg-teal-100 text-teal-600 flex items-center justify-center mx-auto mb-4 text-2xl"><i class="fa-solid fa-check"></i></div>
          <h3 class="font-display font-bold text-lg text-ink mb-1">Session saved</h3></div>`;
      onActivityCompleted(activity.id, data.plan);
      refreshPlanState();
    });
  }

  // ---- TIMER / FOCUS CHALLENGE -------------------------------------------
  function renderTimer(activity) {
    const plannedSeconds = 600; // 10 minutes, matches the plan copy's "10-minute" tasks
    let remaining = plannedSeconds;
    let running = false;

    // Resume gracefully across a refresh: the server tracks started_at,
    // so recompute remaining from real elapsed time rather than restarting.
    if (activity.started_at) {
      const elapsed = Math.floor((Date.now() - new Date(activity.started_at).getTime()) / 1000);
      remaining = Math.max(0, plannedSeconds - elapsed);
    }

    modalBody.innerHTML = `
      <h3 class="font-display font-bold text-lg text-ink mb-1">Screen-Free Challenge</h3>
      <p class="text-sm text-slate-500 mb-5">${escapeHtml(activity.task_text)}</p>
      <div id="timer-error"></div>
      <div class="text-center py-6">
        <p id="timer-display" class="text-5xl font-mono-data font-bold text-ink mb-6">${formatTime(remaining)}</p>
        <div class="flex items-center justify-center gap-3 mb-2">
          <button id="timer-toggle" class="bg-ink hover:bg-slate-800 text-white font-semibold px-6 py-3 rounded-xl">Start</button>
        </div>
        <p class="text-xs text-slate-400">Stay off your screen until the timer finishes.</p>
      </div>
      <button id="timer-complete" class="w-full bg-teal-500 hover:bg-teal-600 text-white font-semibold py-3 rounded-xl hidden">Mark complete</button>
    `;

    function formatTime(s) {
      const m = Math.floor(s / 60).toString().padStart(2, '0');
      const sec = (s % 60).toString().padStart(2, '0');
      return `${m}:${sec}`;
    }

    function tick() {
      remaining -= 1;
      document.getElementById('timer-display').textContent = formatTime(Math.max(0, remaining));
      if (remaining <= 0) {
        clearCountdown();
        running = false;
        document.getElementById('timer-toggle').classList.add('hidden');
        document.getElementById('timer-complete').classList.remove('hidden');
      }
    }

    document.getElementById('timer-toggle').addEventListener('click', async () => {
      if (!running) {
        running = true;
        document.getElementById('timer-toggle').textContent = 'Pause';
        timerInterval = setInterval(tick, 1000);
      } else {
        running = false;
        document.getElementById('timer-toggle').textContent = 'Resume';
        clearCountdown();
      }
    });

    if (remaining <= 0) {
      document.getElementById('timer-toggle').classList.add('hidden');
      document.getElementById('timer-complete').classList.remove('hidden');
    }

    document.getElementById('timer-complete').addEventListener('click', async () => {
      const btn = document.getElementById('timer-complete');
      btn.disabled = true;
      const { data } = await api(`/api/recovery/activities/${activity.id}/timer`, {
        method: 'POST', body: { planned_seconds: plannedSeconds },
      });
      if (!data.ok) {
        document.getElementById('timer-error').innerHTML = errorBanner(data.error);
        btn.disabled = false;
        return;
      }
      modalBody.innerHTML = `<div class="text-center py-6">
          <div class="w-14 h-14 rounded-full bg-teal-100 text-teal-600 flex items-center justify-center mx-auto mb-4 text-2xl"><i class="fa-solid fa-check"></i></div>
          <h3 class="font-display font-bold text-lg text-ink mb-1">Challenge complete</h3></div>`;
      onActivityCompleted(activity.id, data.plan);
      refreshPlanState();
    });
  }

  // ---- CHECK-IN ------------------------------------------------------
  function renderCheckin(activity) {
    modalBody.innerHTML = `
      <h3 class="font-display font-bold text-lg text-ink mb-1">Check-In</h3>
      <p class="text-sm text-slate-500 mb-5">${escapeHtml(activity.task_text)}</p>
      <div id="checkin-error"></div>
      <label class="block text-sm font-semibold text-ink mb-1.5">How anxious do you feel right now? (<span id="anxiety-val">5</span>/10)</label>
      <input type="range" min="0" max="10" value="5" id="checkin-anxiety" class="w-full mb-4 accent-teal-500">
      <label class="block text-sm font-semibold text-ink mb-1.5">What's your energy level? (<span id="energy-val">5</span>/10)</label>
      <input type="range" min="0" max="10" value="5" id="checkin-energy" class="w-full mb-4 accent-teal-500">
      <label class="block text-sm font-semibold text-ink mb-1.5">How would you describe your mood?</label>
      <div class="flex flex-wrap gap-2 mb-5" id="checkin-mood-options">
        ${['Good', 'Okay', 'Low', 'Stressed', 'Anxious'].map((m) => `<button type="button" class="mood-btn text-sm px-3.5 py-2 rounded-xl border border-slate-200 text-slate-600 hover:border-teal-400" data-value="${m}">${m}</button>`).join('')}
      </div>
      <button id="checkin-submit" class="w-full bg-ink hover:bg-slate-800 text-white font-semibold py-3 rounded-xl">Continue</button>
    `;
    let selectedMood = null;
    document.getElementById('checkin-anxiety').addEventListener('input', (e) => {
      document.getElementById('anxiety-val').textContent = e.target.value;
    });
    document.getElementById('checkin-energy').addEventListener('input', (e) => {
      document.getElementById('energy-val').textContent = e.target.value;
    });
    modalBody.querySelectorAll('.mood-btn').forEach((b) => {
      b.addEventListener('click', () => {
        modalBody.querySelectorAll('.mood-btn').forEach((x) => x.classList.remove('bg-ink', 'text-white', 'border-ink'));
        b.classList.add('bg-ink', 'text-white', 'border-ink');
        selectedMood = b.dataset.value;
      });
    });
    document.getElementById('checkin-submit').addEventListener('click', async () => {
      const submitBtn = document.getElementById('checkin-submit');
      submitBtn.disabled = true;
      const { data } = await api(`/api/recovery/activities/${activity.id}/checkin`, {
        method: 'POST',
        body: {
          anxiety: Number(document.getElementById('checkin-anxiety').value),
          energy: Number(document.getElementById('checkin-energy').value),
          mood: selectedMood,
        },
      });
      if (!data.ok) {
        document.getElementById('checkin-error').innerHTML = errorBanner(data.error);
        submitBtn.disabled = false;
        return;
      }
      modalBody.innerHTML = `<div class="text-center py-6">
          <div class="w-14 h-14 rounded-full bg-teal-100 text-teal-600 flex items-center justify-center mx-auto mb-4 text-2xl"><i class="fa-solid fa-check"></i></div>
          <h3 class="font-display font-bold text-lg text-ink mb-1">Check-in saved</h3></div>`;
      onActivityCompleted(activity.id, data.plan);
      refreshPlanState();
    });
  }

  // ---- HABIT CHALLENGE ---------------------------------------------------
  function renderHabit(activity) {
    modalBody.innerHTML = `
      <h3 class="font-display font-bold text-lg text-ink mb-1">Habit Challenge</h3>
      <p class="text-sm text-slate-500 mb-5">${escapeHtml(activity.task_text)}</p>
      <div id="habit-error"></div>
      <label class="block text-sm font-semibold text-ink mb-1.5">Which habit are you checking in on?</label>
      <input id="habit-name" type="text" maxlength="60" placeholder="e.g. Morning walk"
        class="w-full rounded-xl border border-slate-200 p-3 text-sm mb-5 focus:ring-2 focus:ring-teal-400 focus:outline-none">
      <button id="habit-submit" class="w-full bg-ink hover:bg-slate-800 text-white font-semibold py-3 rounded-xl">Check in</button>
    `;
    document.getElementById('habit-submit').addEventListener('click', async () => {
      const habitName = document.getElementById('habit-name').value.trim();
      const submitBtn = document.getElementById('habit-submit');
      submitBtn.disabled = true;
      const { data } = await api(`/api/recovery/activities/${activity.id}/habit`, {
        method: 'POST', body: { habit_name: habitName },
      });
      if (!data.ok) {
        document.getElementById('habit-error').innerHTML = errorBanner(data.error);
        submitBtn.disabled = false;
        return;
      }
      modalBody.innerHTML = `<div class="text-center py-6">
          <div class="w-14 h-14 rounded-full bg-teal-100 text-teal-600 flex items-center justify-center mx-auto mb-4 text-2xl"><i class="fa-solid fa-check"></i></div>
          <h3 class="font-display font-bold text-lg text-ink mb-1">Habit logged</h3></div>`;
      onActivityCompleted(activity.id, data.plan);
      refreshPlanState();
    });
  }

  // ---- AI CONVERSATION ---------------------------------------------------
  function renderAiConversation(activity) {
    modalBody.innerHTML = `
      <h3 class="font-display font-bold text-lg text-ink mb-1">Talk it through</h3>
      <p class="text-sm text-slate-500 mb-4">${escapeHtml(activity.task_text)}</p>
      <div id="ai-error"></div>
      <div id="ai-transcript" class="space-y-2 mb-3 max-h-56 overflow-y-auto"></div>
      <div class="flex gap-2 mb-4">
        <input id="ai-input" type="text" maxlength="2000" placeholder="Type a message…"
          class="flex-1 rounded-xl border border-slate-200 p-3 text-sm focus:ring-2 focus:ring-teal-400 focus:outline-none">
        <button id="ai-send" class="bg-ink hover:bg-slate-800 text-white font-semibold px-4 rounded-xl">Send</button>
      </div>
      <button id="ai-finish" class="w-full bg-teal-500 hover:bg-teal-600 text-white font-semibold py-3 rounded-xl" disabled>Finish activity</button>
    `;
    let exchanges = 0;
    const transcript = document.getElementById('ai-transcript');
    function addBubble(role, text) {
      const bubble = document.createElement('div');
      bubble.className = role === 'user'
        ? 'ml-auto max-w-[85%] bg-ink text-white text-sm rounded-xl px-3 py-2'
        : 'mr-auto max-w-[85%] bg-slate-100 text-slate-700 text-sm rounded-xl px-3 py-2';
      bubble.textContent = text;
      transcript.appendChild(bubble);
      transcript.scrollTop = transcript.scrollHeight;
    }
    async function send() {
      const input = document.getElementById('ai-input');
      const message = input.value.trim();
      if (!message) return;
      addBubble('user', message);
      input.value = '';
      const { data } = await api('/api/companion/send', { method: 'POST', body: { message } });
      if (data.ok && data.reply) {
        addBubble('model', data.reply);
        exchanges += 1;
        document.getElementById('ai-finish').disabled = exchanges < 1;
      } else {
        document.getElementById('ai-error').innerHTML = errorBanner(data.error || 'The companion is unavailable right now.');
      }
    }
    document.getElementById('ai-send').addEventListener('click', send);
    document.getElementById('ai-input').addEventListener('keydown', (e) => { if (e.key === 'Enter') send(); });
    document.getElementById('ai-finish').addEventListener('click', async () => {
      const btn = document.getElementById('ai-finish');
      btn.disabled = true;
      const { data } = await api(`/api/recovery/activities/${activity.id}/ai-conversation`, { method: 'POST' });
      if (!data.ok) {
        document.getElementById('ai-error').innerHTML = errorBanner(data.error);
        btn.disabled = false;
        return;
      }
      modalBody.innerHTML = `<div class="text-center py-6">
          <div class="w-14 h-14 rounded-full bg-teal-100 text-teal-600 flex items-center justify-center mx-auto mb-4 text-2xl"><i class="fa-solid fa-check"></i></div>
          <h3 class="font-display font-bold text-lg text-ink mb-1">Conversation saved</h3></div>`;
      onActivityCompleted(activity.id, data.plan);
      refreshPlanState();
    });
  }

  // ---- PROGRESS REVIEW ---------------------------------------------------
  async function renderProgressReview(activity) {
    modalBody.innerHTML = `<p class="text-sm text-slate-400 py-8 text-center">Loading your progress…</p>`;
    const planId = card.dataset.planId;
    const { data } = await api(`/api/recovery/plans/${planId}/progress-review`);
    if (!data.ok) {
      modalBody.innerHTML = errorBanner(data.error);
      return;
    }
    const r = data.review;
    const typeRows = Object.entries(r.by_activity_type)
      .map(([type, v]) => `<div class="flex justify-between text-sm py-1.5 border-b border-slate-100"><span class="text-slate-500 capitalize">${type.replace('_', ' ')}</span><span class="font-semibold text-ink">${v.completed}/${v.total}</span></div>`)
      .join('');
    modalBody.innerHTML = `
      <h3 class="font-display font-bold text-lg text-ink mb-1">Progress Review</h3>
      <p class="text-sm text-slate-500 mb-4">${r.title}</p>
      <div class="bg-slate-50 rounded-xl p-4 mb-4">
        <p class="text-2xl font-display font-bold text-ink">${r.activities_completed}/${r.activities_total}</p>
        <p class="text-xs text-slate-400">activities completed${r.activities_skipped ? `, ${r.activities_skipped} skipped` : ''}</p>
      </div>
      <div class="mb-5">${typeRows}</div>
      <button id="review-done" class="w-full bg-ink hover:bg-slate-800 text-white font-semibold py-3 rounded-xl">Done</button>
    `;
    document.getElementById('review-done').addEventListener('click', async () => {
      const { data: res } = await api(`/api/recovery/activities/${activity.id}/progress-review`, { method: 'POST' });
      if (res.ok) { onActivityCompleted(activity.id, res.plan); refreshPlanState(); } else { closeModal(); }
    });
  }

  // ---- refresh whole plan (progress numbers etc) after any completion --
  async function refreshPlanState() {
    const { data } = await api('/api/recovery/active');
    if (data.ok) updateProgress(data.plan.progress);
  }

  // ---- switch plan (unchanged behavior) ---------------------------------
  document.querySelectorAll('.start-plan-btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const planType = btn.dataset.planType;
      btn.disabled = true;
      const { data } = await api('/api/recovery/start', { method: 'POST', body: { plan_type: planType } });
      if (data.ok) {
        window.location.reload();
      } else {
        alert(data.error || 'Could not start that plan.');
        btn.disabled = false;
      }
    });
  });
});
