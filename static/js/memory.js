// "Your Memory" management page: lists every stored memory fact,
// grouped into user-facing categories, with per-item delete and a
// clear-all reset. Mirrors the read-only panel in journal.js but adds
// ids so individual memories can actually be deleted (see routes/memory.py).

// fact_type (ml/memory.py FACT_TYPES) -> display group. Order here is the
// render order.
const GROUPS = [
  { label: 'Goals', icon: 'fa-bullseye', types: ['goal'] },
  { label: 'Preferences', icon: 'fa-heart', types: ['habit'] },
  { label: 'Recurring Patterns', icon: 'fa-arrows-rotate', types: ['stressor', 'trigger', 'sleep_pattern', 'theme'] },
  { label: 'Achievements', icon: 'fa-star', types: ['achievement'] },
];

function typeToGroupLabel(type) {
  const g = GROUPS.find((g) => g.types.includes(type));
  return g ? g.label : 'Other';
}

function cardMeta(fact) {
  const times = fact.occurrences === 1 ? '1 time' : `${fact.occurrences} times`;
  return `${fact.type.replace('_', ' ')} · mentioned ${times} · since ${fact.created}`;
}

function buildCard(fact, template) {
  const node = template.content.cloneNode(true);
  const wrap = node.querySelector('[data-fact-id]');
  wrap.dataset.factId = fact.id;
  node.querySelector('.memory-card-text').textContent = fact.text;
  node.querySelector('.memory-card-meta').textContent = cardMeta(fact);
  node.querySelector('.memory-delete-btn').addEventListener('click', () => deleteFact(fact.id, wrap));
  return node;
}

async function deleteFact(factId, cardEl) {
  const wrapper = document.querySelector(`[data-fact-id="${factId}"]`);
  const target = wrapper || cardEl;
  try {
    const res = await fetch(`/api/memory/facts/${factId}/delete`, { method: 'POST' });
    const data = await res.json();
    if (!data.ok) {
      alert(data.error || 'Could not delete that memory.');
      return;
    }
    if (target) {
      const group = target.closest('.memory-group');
      target.remove();
      // If that was the last card in its group, drop the whole group header.
      if (group && group.querySelectorAll('[data-fact-id]').length === 0) {
        group.remove();
      }
    }
    if (document.querySelectorAll('#memory-groups [data-fact-id]').length === 0) {
      document.getElementById('memory-empty').classList.remove('hidden');
    }
  } catch (err) {
    console.error('delete memory failed', err);
    alert('Could not delete that memory — please try again.');
  }
}

async function loadMemories() {
  const groupsEl = document.getElementById('memory-groups');
  const emptyEl = document.getElementById('memory-empty');
  const template = document.getElementById('memory-card-template');

  try {
    const res = await fetch('/api/memory/manage');
    const data = await res.json();
    if (!data.ok || data.total === 0) {
      emptyEl.classList.remove('hidden');
      return;
    }

    const byGroup = {};
    data.facts.forEach((fact) => {
      const label = typeToGroupLabel(fact.type);
      (byGroup[label] = byGroup[label] || []).push(fact);
    });

    groupsEl.innerHTML = '';
    GROUPS.forEach(({ label, icon }) => {
      const facts = byGroup[label];
      if (!facts || facts.length === 0) return;

      const section = document.createElement('div');
      section.className = 'memory-group';
      section.innerHTML = `
        <h2 class="text-sm font-display font-semibold text-ink uppercase tracking-wide mb-3">
          <i class="fa-solid ${icon} text-teal-500 mr-1.5"></i>${label}
        </h2>
        <div class="space-y-2 cards"></div>`;
      const cardsEl = section.querySelector('.cards');
      facts.forEach((fact) => cardsEl.appendChild(buildCard(fact, template)));
      groupsEl.appendChild(section);
    });
  } catch (err) {
    console.error('load memories failed', err);
    groupsEl.innerHTML = '<p class="text-sm text-coral-500">Could not load your memories right now.</p>';
  }
}

async function loadInsight() {
  const insightEl = document.getElementById('memory-insight-text');
  try {
    const res = await fetch('/api/memory/insights');
    const data = await res.json();
    insightEl.textContent = data.ok ? data.insight : "Couldn't load your memory insight right now.";
  } catch {
    insightEl.textContent = "Couldn't load your memory insight right now.";
  }
}

document.addEventListener('DOMContentLoaded', () => {
  loadInsight();
  loadMemories();

  document.getElementById('clear-all-btn').addEventListener('click', async () => {
    if (!confirm('Clear ALL of your stored memory? This deletes every pattern, goal, and preference the app has learned about you, and can\'t be undone.')) return;
    try {
      const res = await fetch('/api/memory/clear', { method: 'POST' });
      const data = await res.json();
      if (!data.ok) {
        alert('Could not clear your memories right now.');
        return;
      }
      document.getElementById('memory-groups').innerHTML = '';
      document.getElementById('memory-empty').classList.remove('hidden');
      loadInsight();
    } catch (err) {
      console.error('clear all failed', err);
      alert('Could not clear your memories right now.');
    }
  });
});
