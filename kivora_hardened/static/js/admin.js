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
});
