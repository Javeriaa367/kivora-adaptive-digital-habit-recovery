document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.plan-select').forEach(sel => {
    sel.addEventListener('change', async () => {
      await fetch(`/api/admin/users/${sel.dataset.userId}/plan`, {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ plan: sel.value }),
      });
    });
  });

  const couponForm = document.getElementById('coupon-form');
  if (couponForm) couponForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const code = document.getElementById('c-code').value.trim();
    const discount_percent = parseInt(document.getElementById('c-discount').value, 10);
    const max_uses = parseInt(document.getElementById('c-uses').value, 10) || 1;
    const res = await fetch('/api/admin/coupons', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ code, discount_percent, max_uses }),
    });
    const data = await res.json();
    if (data.ok) location.reload(); else alert(data.error);
  });

  document.querySelectorAll('.approve-testimonial-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      await fetch(`/api/admin/testimonials/${btn.dataset.id}/approve`, { method: 'POST' });
      btn.closest('div.flex').remove();
    });
  });

  document.querySelectorAll('.role-select').forEach(sel => {
    sel.addEventListener('change', async () => {
      const res = await fetch(`/api/admin/users/${sel.dataset.userId}/role`, {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ role: sel.value }),
      });
      const data = await res.json();
      if (!data.ok) {
        alert(data.error || 'Could not change role.');
        location.reload();
      }
    });
  });

  document.querySelectorAll('.status-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const res = await fetch(`/api/admin/users/${btn.dataset.userId}/status`, {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ status: btn.dataset.status }),
      });
      const data = await res.json();
      if (!data.ok) {
        alert(data.error || 'Could not change status.');
      }
      location.reload();
    });
  });

  document.querySelectorAll('.user-detail-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const row = document.getElementById(`user-detail-row-${btn.dataset.userId}`);
      if (!row) return;
      const collapsed = row.classList.contains('hidden');
      if (collapsed) {
        row.classList.remove('hidden');
        row.querySelector('div').innerHTML = '<div class="text-sm text-slate-600">Loading…</div>';
        try {
          const res = await fetch(`/api/admin/users/${btn.dataset.userId}/detail`);
          if (!res.ok) throw new Error('Failed to load');
          renderUserDetail(row.querySelector('div'), await res.json());
        } catch {
          row.querySelector('div').innerHTML = '<div class="text-sm text-coral-600">Failed to load user detail.</div>';
        }
      } else {
        row.classList.add('hidden');
      }
    });
  });
});

function renderUserDetail(container, d) {
  const fmt = (ts) => ts ? String(ts).slice(0, 10) : '—';
  const counts = d.counts || {};
  const chips = Object.entries(counts).map(([k, v]) =>
    `<span class="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">${k.replace(/_/g, ' ')}: <b>${v ?? '—'}</b></span>`).join(' ');
  const journalRows = (d.recent_journals || []).map(j =>
    `<li class="flex items-center justify-between text-sm text-slate-600">
       <span class="capitalize">${(j.emotion_label || '—').replace(/_/g, ' ')}</span>
       <span>${j.overall_sentiment || '—'} · ${j.crisis_flag ? '<b class="text-coral-600">crisis</b>' : 'ok'} · ${fmt(j.created_at)}</span>
     </li>`).join('') || '<li class="text-sm text-slate-400">No journal entries.</li>';
  const riskRows = (d.recent_risk || []).slice(0, 5).map(r =>
    `<li class="flex items-center justify-between text-sm text-slate-600">
       <span class="capitalize">${(r.category || '—').replace(/_/g, ' ')}</span>
       <span>${r.level || '—'} · score ${r.score ?? '—'} · ${fmt(r.created_at)}</span>
     </li>`).join('') || '<li class="text-sm text-slate-400">No risk snapshots.</li>';

  container.innerHTML = `
    <div class="grid md:grid-cols-3 gap-4">
      <div>
        <p class="text-xs uppercase text-slate-400 font-semibold mb-1">Account</p>
        <p class="text-sm text-slate-600">Plan: <b>${d.plan}</b>${d.premium_until ? ` until ${fmt(d.premium_until)}` : ''}</p>
        <p class="text-sm text-slate-600">Role: <b>${d.role}</b> (${d.is_admin ? 'admin' : 'member'})</p>
        <p class="text-sm text-slate-600">Status: <b>${d.account_status}</b></p>
        <p class="text-sm text-slate-600">Joined: ${fmt(d.created_at)}</p>
        <p class="text-sm text-slate-600">Consent: ${d.consent_given ? 'yes' : 'no'}${d.country_code ? ` · ${d.country_code}` : ''}</p>
      </div>
      <div>
        <p class="text-xs uppercase text-slate-400 font-semibold mb-1">Usage</p>
        <div class="flex flex-wrap gap-1.5">${chips}</div>
      </div>
      <div>
        <p class="text-xs uppercase text-slate-400 font-semibold mb-1">Recent Journal</p>
        <ul class="space-y-1">${journalRows}</ul>
        <p class="text-xs uppercase text-slate-400 font-semibold mt-3 mb-1">Recent Risk</p>
        <ul class="space-y-1">${riskRows}</ul>
      </div>
    </div>`;
}
