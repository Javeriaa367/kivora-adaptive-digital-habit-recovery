document.addEventListener('DOMContentLoaded', () => {
  const subjectsList = document.getElementById('subjects-list');
  const assignmentsList = document.getElementById('assignments-list');
  const assignmentSubjectSelect = document.getElementById('assignment-subject');

  function daysUntil(dateStr) {
    if (!dateStr) return null;
    const diff = (new Date(dateStr) - new Date()) / (1000 * 60 * 60 * 24);
    return Math.ceil(diff);
  }

  function renderSubjects(subjects) {
    subjectsList.innerHTML = subjects.length ? subjects.map(s => {
      const days = daysUntil(s.exam_date);
      const urgency = days !== null && days <= 3 ? 'text-coral-600' : days !== null && days <= 7 ? 'text-amber-600' : 'text-slate-500';
      return `<div class="flex items-center justify-between bg-slate-50 rounded-lg px-3 py-2">
        <div><p class="text-sm font-semibold text-ink">${s.name}</p>
        <p class="text-xs ${urgency}">${days !== null ? (days >= 0 ? days + ' days until exam' : 'Exam passed') : 'No exam date'}</p></div>
        <button data-id="${s.id}" class="del-subject text-coral-500 text-xs"><i class="fa-solid fa-trash"></i></button>
      </div>`;
    }).join('') : '<p class="text-sm text-slate-400">No subjects yet.</p>';

    assignmentSubjectSelect.innerHTML = '<option value="">No subject</option>' +
      subjects.map(s => `<option value="${s.id}">${s.name}</option>`).join('');

    subjectsList.querySelectorAll('.del-subject').forEach(btn => {
      btn.addEventListener('click', async () => {
        const res = await fetch(`/api/student/subjects/${btn.dataset.id}`, { method: 'DELETE' });
        const data = await res.json();
        if (data.ok) renderSubjects(data.subjects);
      });
    });
  }

  function renderAssignments(assignments) {
    assignmentsList.innerHTML = assignments.length ? assignments.map(a => `
      <div class="flex items-center justify-between bg-slate-50 rounded-lg px-3 py-2">
        <div class="flex items-center gap-2">
          <input type="checkbox" ${a.completed ? 'checked' : ''} data-id="${a.id}" class="toggle-assignment">
          <div>
            <p class="text-sm font-semibold ${a.completed ? 'line-through text-slate-400' : 'text-ink'}">${a.title}</p>
            <p class="text-xs text-slate-400">${a.subject_name || 'No subject'}${a.due_date ? ' · due ' + a.due_date : ''}</p>
          </div>
        </div>
      </div>`).join('') : '<p class="text-sm text-slate-400">No assignments yet.</p>';

    assignmentsList.querySelectorAll('.toggle-assignment').forEach(cb => {
      cb.addEventListener('change', async () => {
        const res = await fetch(`/api/student/assignments/${cb.dataset.id}/toggle`, { method: 'POST' });
        const data = await res.json();
        if (data.ok) renderAssignments(data.assignments);
      });
    });
  }

  document.getElementById('subject-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = document.getElementById('subject-name').value.trim();
    const exam_date = document.getElementById('subject-exam-date').value;
    if (!name) return;
    const res = await fetch('/api/student/subjects', {
      method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ name, exam_date }),
    });
    const data = await res.json();
    if (data.ok) { renderSubjects(data.subjects); document.getElementById('subject-name').value = ''; }
  });

  document.getElementById('assignment-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const title = document.getElementById('assignment-title').value.trim();
    const subject_id = document.getElementById('assignment-subject').value || null;
    const due_date = document.getElementById('assignment-due').value;
    if (!title) return;
    const res = await fetch('/api/student/assignments', {
      method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ title, subject_id, due_date }),
    });
    const data = await res.json();
    if (data.ok) { renderAssignments(data.assignments); document.getElementById('assignment-title').value = ''; }
  });

  document.getElementById('gen-plan').addEventListener('click', async () => {
    const daily_hours = parseFloat(document.getElementById('daily-hours').value) || 2;
    const planEl = document.getElementById('study-plan');
    planEl.textContent = 'Generating...';
    const res = await fetch('/api/student/study-plan', {
      method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ daily_hours }),
    });
    const data = await res.json();
    planEl.textContent = data.ok ? data.plan : (data.error || 'Something went wrong.');
  });

  // Initial load
  fetch('/api/student/subjects').then(r => r.json()).then(d => d.ok && renderSubjects(d.subjects));
  fetch('/api/student/assignments').then(r => r.json()).then(d => d.ok && renderAssignments(d.assignments));
});
