document.addEventListener('DOMContentLoaded', () => {
  // Typical/default values -- same defaults as the dashboard form.
  const BASE_INPUTS = {
    Daily_Usage_Hours: 4.4, Platforms_Used_Count: 3, Posts_Per_Week: 4, Notifications_Per_Day: 59,
    FOMO_Score: 5.5, Social_Comparison_Score: 5.5, Validation_Seeking_Score: 5, Scroll_Without_Purpose: 5.5,
    Sleep_Hours: 6.6, Offline_Relationship_Quality: 5.4, Physical_Activity_Hrs_Week: 3, Screen_Free_Time_Hrs: 3,
    Late_Night_Usage: 1, Tried_To_Cut_Back: 1, Failed_To_Cut_Back: 1, First_Check_Morning: 0, Primary_Platform: 'Instagram',
  };

  document.getElementById('run-sim').addEventListener('click', async () => {
    const field = document.getElementById('field-select').value;
    const res = await fetch('/api/simulate', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ inputs: BASE_INPUTS, field }),
    });
    const data = await res.json();
    if (!data.ok) { alert(data.error); return; }

    Plotly.newPlot('sim-chart', [
      { x: data.points.map(p => p.value), y: data.points.map(p => p.wellbeing_score),
        name: 'Wellbeing score', type: 'scatter', mode: 'lines+markers', line: {color:'#0EA5A0'} },
      { x: data.points.map(p => p.value), y: data.points.map(p => p.at_risk_probability * 10),
        name: 'Addiction risk × 10 (scaled)', type: 'scatter', mode: 'lines+markers', line: {color:'#F2545B'}, yaxis: 'y' },
    ], {
      title: `Model sensitivity to ${field.replace(/_/g,' ')}`,
      xaxis: { title: field.replace(/_/g,' ') }, yaxis: { title: 'Score (0-10 scale)', range: [0,10] },
      margin: { t: 40 },
    }, { responsive: true, displayModeBar: false });
  });
});
