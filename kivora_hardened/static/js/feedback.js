document.addEventListener('DOMContentLoaded', () => {
  let rating = 0;
  const stars = document.querySelectorAll('#rating-stars i');
  stars.forEach(s => s.addEventListener('click', () => {
    rating = parseInt(s.dataset.value, 10);
    stars.forEach(st => st.classList.toggle('text-amber-400', parseInt(st.dataset.value,10) <= rating));
    stars.forEach(st => st.classList.toggle('text-slate-300', parseInt(st.dataset.value,10) > rating));
  }));

  document.getElementById('feedback-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const message = document.getElementById('feedback-message').value.trim();
    if (!message) return;
    const res = await fetch('/api/feedback', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ message, rating: rating || null }),
    });
    const data = await res.json();
    const el = document.getElementById('feedback-result');
    el.textContent = data.ok ? 'Thanks for the feedback!' : data.error;
    el.className = 'text-sm mt-2 ' + (data.ok ? 'text-teal-600' : 'text-coral-600');
    if (data.ok) document.getElementById('feedback-message').value = '';
  });

  document.getElementById('testimonial-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const quote = document.getElementById('testimonial-quote').value.trim();
    if (!quote) return;
    const res = await fetch('/api/testimonial', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ quote }),
    });
    const data = await res.json();
    const el = document.getElementById('testimonial-result');
    el.textContent = data.ok ? data.message : data.error;
    el.className = 'text-sm mt-2 ' + (data.ok ? 'text-teal-600' : 'text-coral-600');
    if (data.ok) document.getElementById('testimonial-quote').value = '';
  });
});
