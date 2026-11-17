"""Dashboard web estatico servido por server.py en ``/`` (checklist v3 §6.2, §21.4).

HTML + JS vanilla (sin dependencias): consulta la API REST (/health, /runs,
/runs/{id}/report.html), permite lanzar corridas (POST /runs), ver el stream
de eventos SSE (/events) en vivo y ver metricas (/metrics). Todo con URLs
relativas (sirve detras del preview o detras de un proxy).
"""
from __future__ import annotations

DASHBOARD_HTML = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Harness-Candy · panel</title>
<style>
body{font-family:system-ui,sans-serif;margin:0;background:#0f1420;color:#e8eaf2}
header{padding:.8rem 1.2rem;background:#171d2e;display:flex;gap:1rem;align-items:center}
header h1{font-size:1.1rem;margin:0}
.badge{background:#2b3350;padding:.2rem .6rem;border-radius:999px;font-size:.8rem}
main{display:grid;grid-template-columns:1fr 1fr;gap:1rem;padding:1rem}
section{background:#171d2e;border-radius:10px;padding:1rem}
h2{font-size:.95rem;margin-top:0;color:#9fb0e8}
button{background:#3d5afe;color:#fff;border:0;border-radius:6px;padding:.45rem .9rem;cursor:pointer}
input,textarea{background:#0f1420;color:#e8eaf2;border:1px solid #2b3350;border-radius:6px;padding:.4rem;width:100%;box-sizing:border-box;margin:.2rem 0}
table{width:100%;border-collapse:collapse;font-size:.85rem}
td,th{padding:.3rem .4rem;border-bottom:1px solid #232a42;text-align:left}
a{color:#8ab4ff}
#eventos{font-family:ui-monospace,monospace;font-size:.75rem;max-height:260px;overflow:auto;white-space:pre-wrap}
.ok{color:#4caf50}.bad{color:#ef5350}
@media(max-width:900px){main{grid-template-columns:1fr}}
</style>
</head>
<body>
<header>
  <h1>Harness-Candy</h1>
  <span class="badge" id="salud">…</span>
  <span class="badge" id="ver"></span>
  <span style="flex:1"></span>
  <button onclick="refrescar()">Refrescar</button>
</header>
<main>
  <section>
    <h2>Nueva corrida</h2>
    <textarea id="objetivo" rows="2">informe de seguridad de examples/golden/limpio</textarea>
    <input id="inputs" value='{"root":"examples/golden/limpio"}'>
    <input id="seed" value="0" style="width:6rem">
    <button onclick="lanzar()">Ejecutar (POST /runs)</button>
    <div id="resultado"></div>
  </section>
  <section>
    <h2>Corridas guardadas (GET /runs)</h2>
    <table><thead><tr><th>run_id</th><th>objetivo</th><th>duración</th><th>reporte</th></tr></thead>
    <tbody id="tabla"></tbody></table>
  </section>
  <section>
    <h2>Eventos en vivo (SSE /events)</h2>
    <div id="eventos">conectando…</div>
  </section>
  <section>
    <h2>Métricas (GET /metrics, formato Prometheus)</h2>
    <div id="metricas" style="font-family:ui-monospace,monospace;font-size:.75rem;white-space:pre-wrap"></div>
  </section>
</main>
<script>
const $ = id => document.getElementById(id);
async function j(path, opts){ const r = await fetch(path, opts); return r; }
async function salud(){
  const r = await j('/health'); const d = await r.json();
  $('salud').textContent = d.status; $('ver').textContent = 'v' + d.version + ' · esquema ' + d.schema_version;
}
async function refrescar(){
  const r = await j('/runs?limit=20'); const d = await r.json();
  $('tabla').innerHTML = d.runs.map(x =>
    `<tr><td><a href="/runs/${x.run_id}">${x.run_id}</a></td><td>${x.objetivo||''}</td>` +
    `<td>${x.duracion ?? ''}s</td><td><a href="/runs/${x.run_id}/report.html">html</a> · <a href="/runs/${x.run_id}/report.xml">xml</a></td></tr>`).join('');
}
async function lanzar(){
  let inputs = {}; try { inputs = JSON.parse($('inputs').value || '{}'); } catch(e){ $('resultado').textContent = 'inputs no es JSON: ' + e; return; }
  $('resultado').textContent = 'ejecutando…';
  const r = await j('/runs', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({objetivo: $('objetivo').value, inputs, seed: parseInt($('seed').value||'0')})});
  const d = await r.json();
  $('resultado').innerHTML = r.status === 201
    ? `OK <a href="/runs/${d.run_id}">${d.run_id}</a> · <a href="/runs/${d.run_id}/report.html">ver reporte</a>`
    : `Error ${r.status}: ${d.error || ''}`;
  refrescar();
}
async function metricas(){
  const r = await j('/metrics'); $('metricas').textContent = await r.text();
}
const es = new EventSource('/events?timeout=120');
es.onmessage = e => { $('eventos').textContent += e.data + '\\n'; };
['run_start','run_end','node_start','node_end','alert'].forEach(ev => {
  es.addEventListener(ev, e => { $('eventos').textContent += '[' + ev + '] ' + e.data + '\\n'; });
});
salud(); refrescar(); metricas(); setInterval(refrescar, 10000); setInterval(metricas, 10000);
</script>
</body>
</html>
"""


def dashboard_html() -> str:
    return DASHBOARD_HTML
