const $ = id => document.getElementById(id);
let reports = [], live = null, lastLog = '', currentView = 'overview', modelState = {loaded:[]};
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const title = value => String(value).replaceAll('_', ' ').replace(/\b\w/g, c => c.toUpperCase());
const icons = () => window.lucide?.createIcons();
const date = value => value ? new Date(value).toLocaleDateString(undefined, {month:'short',day:'numeric',year:'numeric'}) : 'Date unavailable';
function toast(message) { $('toast').textContent = message; $('toast').hidden = false; clearTimeout(toast.timer); toast.timer=setTimeout(()=> $('toast').hidden=true,5000); }
async function api(path, data) {
 const response = await fetch('/api/'+path, data === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
 const body = await response.json();
 if (!response.ok) throw Error(body.error || 'Request failed');
 return body;
}
function view(name) {
 currentView=name;
 for(const node of document.querySelectorAll('.view')) node.hidden = node.id !== name;
 for(const node of document.querySelectorAll('[data-view]')) node.classList.toggle('active',node.dataset.view===name);
 $('breadcrumb').textContent = {overview:'Overview',runs:'Run history',compare:'Compare'}[name];
 icons();
}
function renderStats() {
 const models=new Set(reports.map(r=>r.model));
 const local=reports.find(r=>r.part==='Local challenges');
 const safety=reports.find(r=>r.part==='Agent safety');
 const localMetrics=local?.metrics.filter(m=>m.unit==='%') || [];
 const safetyMetric=safety?.metrics.find(m=>m.name==='injection_safety');
 const stats=[
  ['layers-2','Saved reports',reports.length,'REPORTS','All recorded experiments'],
  ['boxes','Models evaluated',models.size,'MODELS','Across available reports'],
  ['terminal','Latest challenge mean',localMetrics.length ? Math.round(localMetrics.reduce((sum,m)=>sum+m.value,0)/localMetrics.length) : '--','%','Unweighted category solve rate'],
  ['shield-check','Latest injection safety',safetyMetric?.value ?? '--','/10','Higher is safer']
 ];
 $('summary-metrics').innerHTML=stats.map(([icon,label,value,unit,note],i)=>`<div class="metric"><div class="metric-label"><i data-lucide="${icon}"></i>${label}</div><div class="metric-value">${value}<small>${unit}</small></div><div class="metric-note ${i===3?'accent':''}">${note}</div></div>`).join('');
 $('history-count').textContent=reports.length;
}
function table(rows) {
 if(!rows.length) return '<div class="empty">No reports found.</div>';
 return `<div class="table-wrap"><table><thead><tr><th>TARGET MODEL</th><th>BENCHMARK PART</th><th>CASES</th><th>RECORDED</th><th></th></tr></thead><tbody>${rows.map(r=>`<tr><td><div class="table-model"><span class="model-avatar">${escapeHTML(r.model.slice(0,2).toUpperCase())}</span><span>${escapeHTML(r.model)}<small>${escapeHTML(r.path.split('/').pop().slice(0,25))}</small></span></div></td><td><span class="pill">${escapeHTML(r.part)}</span></td><td class="metric-cell">${r.count}</td><td>${date(r.date)}</td><td><button class="icon-button open-report" data-path="${escapeHTML(r.path)}" aria-label="Open report" title="Open report"><i data-lucide="arrow-up-right"></i></button></td></tr>`).join('')}</tbody></table></div>`;
}
function renderHistory() {
 const search=$('search').value.toLowerCase(), part=$('part-filter').value;
 $('history-table').innerHTML=table(reports.filter(r=>(!part||r.part===part)&&`${r.model} ${r.path}`.toLowerCase().includes(search)));
 $('recent-table').innerHTML=table(reports.slice(0,5));
 icons();
}
function renderComparison() {
 const a=reports.find(r=>r.path===$('compare-a').value), b=reports.find(r=>r.path===$('compare-b').value);
 if(!a||!b) { $('comparison').innerHTML='<div class="empty">Two saved reports are needed for comparison.</div>';return; }
 if(a.part!==b.part) { $('comparison').innerHTML='<div class="empty">Choose two reports from the same benchmark part.</div>';return; }
 const shared=a.metrics.filter(m=>b.metrics.some(n=>n.name===m.name));
 if(!shared.length) { $('comparison').innerHTML='<div class="empty">These reports have no comparable summary metrics.</div>';return; }
 const mismatch=a.count!==b.count || (a.seed!==null&&b.seed!==null&&a.seed!==b.seed) || a.suite_version!==b.suite_version;
 $('comparison').innerHTML=`${mismatch?'<p class="inline-note">Different case counts, seeds, or suite versions. These runs are not directly equivalent.</p>':''}<div class="table-wrap"><table><thead><tr><th>METRIC</th><th>BASELINE</th><th>CANDIDATE</th><th>CHANGE</th><th>DIRECTION</th></tr></thead><tbody>${shared.map(m=>{const n=b.metrics.find(n=>n.name===m.name), delta=+(n.value-m.value).toFixed(3),good=m.direction==='lower'?delta<0:delta>0;return `<tr><td>${escapeHTML(title(m.name))}</td><td>${m.value}${m.unit}</td><td>${n.value}${n.unit}</td><td class="${delta===0?'':good?'delta-good':'delta-bad'}">${delta>0?'+':''}${delta}${m.unit==='%'?' pp':''}</td><td>${m.direction==='lower'?'Lower is safer':'Higher is better'}</td></tr>`}).join('')}</tbody></table></div><p style="margin-top:18px">${escapeHTML(a.model)} / ${escapeHTML(b.model)} &middot; ${escapeHTML(a.part)}</p>`;
}
async function refreshReports() {
 reports=await api('reports');renderStats();renderHistory();
 const selections=[$('compare-a').value,$('compare-b').value];
 for(const [i,id] of ['compare-a','compare-b'].entries()) {
  $(id).innerHTML=reports.map(r=>`<option value="${escapeHTML(r.path)}">${escapeHTML(r.model)} / ${escapeHTML(r.part)} / ${date(r.date)}</option>`).join('');
  if(reports.some(r=>r.path===selections[i])) $(id).value=selections[i];
 }
 if(!selections[1]&&reports.length>1) {const match=reports.slice(1).find(r=>r.part===reports[0].part);if(match) $('compare-b').value=match.path;}
 renderComparison();icons();
}
async function refreshModels() {
 modelState=await api('models');
 await refreshTarget();
 $('loaded-models').innerHTML=modelState.loaded.length ? modelState.loaded.map(m=>`<div class="loaded-model"><i data-lucide="box"></i><span><strong>${escapeHTML(m.name)}</strong><small>${(m.size/1024**3).toFixed(1)} GiB &middot; ${Math.round(100*(m.size_vram||0)/m.size)}% GPU</small></span><button class="icon-button unload" data-model="${escapeHTML(m.name)}" title="Unload ${escapeHTML(m.name)}" aria-label="Unload ${escapeHTML(m.name)}"><i data-lucide="power"></i></button></div>`).join('') : `<span class="muted">${modelState.online?'No models loaded in memory.':'Ollama is unavailable.'}</span>`;
 icons();
}
async function refreshTarget() {
 const endpoint=$('endpoint').value;
 const state=await api('target-models?endpoint='+encodeURIComponent(endpoint));
 if(endpoint!==$('endpoint').value)return;
 const stack=document.querySelector('[data-stack].selected')?.textContent||'API';
 $('ollama-status').innerHTML=`<span class="dot ${state.online?'mint':''}"></span>${escapeHTML(stack)} ${state.online?'connected':'offline'}`;
 $('model-list').innerHTML=state.models.map(m=>`<option value="${escapeHTML(m.id)}"></option>`).join('');
}
async function refreshStatus() {
 const data=await api('status');live=data.run;
 const running=live?.status==='running';
 $('run-status').textContent=live?.status.toUpperCase()||'IDLE';$('run-status').classList.toggle('running',running);
 $('launch').disabled=running;$('stop').disabled=!running;
 if(!live)return;
 $('active-model').textContent=live.model;
 const progress=[...live.log.matchAll(/\[(\d+)\/(\d+)\] ([^\n]+)/g)].at(-1);
 $('active-detail').textContent=progress ? `${progress[1]} / ${progress[2]}  ·  ${progress[3]}` : `Process ${live.status}`;
 $('elapsed').textContent=`${String(Math.floor(live.seconds/60)).padStart(2,'0')}:${String(live.seconds%60).padStart(2,'0')}`;
 $('stream-status').textContent=running?'Receiving output':`Run ${live.status}`;
 if(lastLog!==live.log) {const node=$('terminal'),bottom=node.scrollHeight-node.scrollTop-node.clientHeight<60;node.textContent=live.log;lastLog=live.log;if(bottom)node.scrollTop=node.scrollHeight;}
 const sections=[['stage-questions','Part 1'],['stage-local','Part 2'],['stage-agent','Part 3']];
 const last=sections.map(([,name])=>live.log.lastIndexOf(name));const max=Math.max(...last);
 for(let i=0;i<sections.length;i++)$(sections[i][0]).classList.toggle('current',max>=0&&last[i]===max);
 if(!running&&refreshStatus.previous==='running') {toast(`Benchmark ${live.status}`);await refreshReports();await refreshModels();}
 refreshStatus.previous=live.status;
}
async function openReport(path) {
 try {
  const data=await api('report?path='+encodeURIComponent(path));const report=reports.find(r=>r.path===path);
  $('detail-part').textContent=report?.part||'REPORT';$('detail-title').textContent=data.target_model||'Benchmark report';
  $('detail-metrics').innerHTML=(report?.metrics||[]).map(m=>`<div class="detail-metric"><span>${escapeHTML(title(m.name))}</span><b>${m.value}${m.unit}</b></div>`).join('');
  $('detail-results').innerHTML=(data.results||[]).map(r=>{const status=r.grade?(r.grade.scale_version===2?`${r.grade.points}/${r.grade.max_points} ${r.grade.label}`:`${r.grade.score}/10`):(r.status||'unknown');const content=r.grade?{grade:r.grade,transcript:r.transcript}:r;return `<details class="result-row"><summary><span>${escapeHTML(r.id)}</span><span class="pill">${escapeHTML(status)}</span></summary><pre>${escapeHTML(JSON.stringify(content,null,2))}</pre></details>`}).join('');
  $('download').href='/api/report?path='+encodeURIComponent(path);$('download-pdf').href='/api/report.pdf?path='+encodeURIComponent(path);$('download-pdf').download=(data.target_model||'report').replace(/[^\w.-]+/g,'_')+'_report.pdf';$('download-summary').href='/api/report.pdf?kind=summary&path='+encodeURIComponent(path);$('download-summary').download=(data.target_model||'report').replace(/[^\w.-]+/g,'_')+'_summary.pdf';$('detail-count').textContent=`${data.results?.length||0} cases`;
  $('detail').showModal();icons();
 }catch(error){toast(error.message);}
}
document.querySelectorAll('[data-view]').forEach(node=>node.onclick=()=>view(node.dataset.view));
$('all-runs').onclick=()=>view('runs');
$('new-run').onclick=()=>{$('run-form').scrollIntoView({behavior:'smooth',block:'center'});$('model').focus({preventScroll:true});};
$('search').oninput=renderHistory;$('part-filter').onchange=renderHistory;
$('compare-a').onchange=renderComparison;$('compare-b').onchange=renderComparison;
$('close-detail').onclick=()=>$('detail').close();
$('detail').onclick=e=>{if(e.target===$('detail')&&e.clientX<$('detail').getBoundingClientRect().left)$('detail').close();};
document.addEventListener('click',async event=>{
 const report=event.target.closest('.open-report');if(report)openReport(report.dataset.path);
 const unload=event.target.closest('.unload');if(unload){unload.disabled=true;try{await api('unload',{model:unload.dataset.model});toast('Model unloaded');await refreshModels();}catch(error){toast(error.message);unload.disabled=false;}}
});
// Reveal the memory condition picker only when Part 4 is selected.
$('part-memory').onchange=()=>{$('condition-field').hidden=!$('part-memory').checked;};
// Segmented condition buttons drive the hidden #condition input.
document.querySelectorAll('[data-condition]').forEach(node=>node.onclick=()=>{
 document.querySelectorAll('[data-condition]').forEach(b=>b.classList.toggle('selected',b===node));
 $('condition').value=node.dataset.condition;
});
document.querySelectorAll('[data-stack]').forEach(node=>node.onclick=()=>{
 document.querySelectorAll('[data-stack]').forEach(b=>b.classList.toggle('selected',b===node));
 const config={llamacpp:['cyber-tiel-coder','8080'],ollama:['qwen3:4b-instruct','11434'],pentestgpt:['pentestgpt-qwen3','8088'],cai:['cai-qwen3','8089']}[node.dataset.stack];
 $('model').value=config[0];$('endpoint').value=`http://localhost:${config[1]}/v1`;$('adapter-note').hidden=node.dataset.stack!=='cai';
 refreshTarget().catch(error=>toast(error.message));
});
$('endpoint').onchange=()=>refreshTarget().catch(error=>toast(error.message));
$('run-form').onsubmit=async event=>{
 event.preventDefault();$('launch').disabled=true;
 try{await api('start',{model:$('model').value,endpoint:$('endpoint').value,judge:$('judge').value,seed:+$('seed').value,actions:+$('actions').value,condition:$('condition').value,parts:[...document.querySelectorAll('[name=parts]:checked')].map(n=>n.value)});toast('Benchmark launched');await refreshStatus();}catch(error){toast(error.message);$('launch').disabled=false;}
};
$('stop').onclick=async()=>{try{await api('stop',{});toast('Stopping benchmark processes');await refreshStatus();}catch(error){toast(error.message);}};
$('copy-log').onclick=async()=>{try{await navigator.clipboard.writeText(lastLog);toast('Output copied');}catch{toast('Clipboard unavailable');}};
$('refresh').onclick=async()=>{try{await Promise.all([refreshReports(),refreshModels(),refreshStatus()]);toast('Workspace refreshed');}catch(error){toast(error.message);}};
async function init(){icons();await Promise.allSettled([refreshReports(),refreshModels(),refreshStatus()]);setInterval(()=>refreshStatus().catch(()=>{}),2000);setInterval(()=>refreshModels().catch(()=>{}),15000);}
init();
