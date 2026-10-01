'use strict';
const $ = id => document.getElementById(id);
const token = location.hash.slice(1) || sessionStorage.getItem('ge-control-token') || '';
if (token) sessionStorage.setItem('ge-control-token', token);
history.replaceState(null, '', location.pathname);
window.addEventListener('hashchange',()=>{if(location.hash.slice(1)&&location.hash.slice(1)!==token)location.reload();});
let checked = '', busy = false, active = false, lastSnapshot = null;
const cards=new Map(), signatures=new Map();
const stateLabels = {preflight:'检查中',running:'运行中', 'stop-requested':'已请求停止 · 等待当前步骤',stop_requested:'已请求停止 · 等待当前步骤',stopped:'已停止 · 可以继续',paused:'已暂停 · 可以继续',cancelled:'已取消 · 尚未计算',blocked:'受阻',failed:'失败',completed:'完成',completed_with_native_failures:'处理完成 · 有 native 失败',queued:'等待中'};
function values(){return {name:$('name').value,detector:$('detector').value};}
function key(){return JSON.stringify(values());}
function message(text, error=false){$('notice').textContent=text;$('notice').className='message '+(error?'error':'ok');}
function controls(){ $('check').disabled=busy||active;$('run').disabled=busy||active||checked!==key();$('name').disabled=busy||active;$('detector').disabled=busy||active; }
function resolved(){const d=$('detector').value;$('resolved').textContent=d==='AK02'?'AK02：3 个完整初级粒子，91 条原始 Ge 沉积行；固定 +500 V。':'SAP22：3 个完整初级粒子，33 条原始 Ge 沉积行（包含零能量行）；固定 +700 V。';}
async function api(path,data){const response=await fetch(path,{method:data?'POST':'GET',headers:{'X-Control-Token':token,...(data?{'Content-Type':'application/json'}:{})},...(data?{body:JSON.stringify(data)}:{}),cache:'no-store'});const result=await response.json();if(!response.ok)throw new Error(result.error||'本地操作失败');return result;}
function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function btn(label,action){const b=el('button',label);b.addEventListener('click',async()=>{b.disabled=true;try{await action();await poll();}catch(e){message(e.message,true);}finally{if(b.isConnected)b.disabled=false;}});return b;}
function downloadLink(label,name,file){const a=el('a','下载'+label,'link');a.href='/api/file?'+new URLSearchParams({name,file});return a;}
function table(caption,heads,rows){const box=el('div',undefined,'table-scroll'),t=el('table');t.append(el('caption',caption));const h=el('tr');for(const name of heads)h.append(el('th',name));const head=el('thead');head.append(h);t.append(head);const body=el('tbody');for(const row of rows){const r=el('tr');for(const value of row)r.append(el('td',value==null?'未知 / 未定义':String(value)));body.append(r);}t.append(body);box.append(t);return box;}
async function showEvents(job){const response=await fetch('/api/file?'+new URLSearchParams({name:job.name,file:'worker/'+job.detector+'/scalars.jsonl'}),{headers:{'X-Control-Token':token},cache:'no-store'});if(!response.ok)throw new Error((await response.json()).error);const lines=(await response.text()).trim().split('\n');const records=lines.map(line=>JSON.parse(line));const panel=el('div',undefined,'events');panel.append(el('p','全部初级粒子与全部脉冲组分别列出。Edep 是整个初级粒子的 Ge 真值沉积；Erec 属于单个读出组。两者不作为逐事件增益校准。真实零沉积没有伪造的 ADC / 波形。'));
 panel.append(table('初级粒子统计（包含真实零沉积）',['原始 ID','Ge Edep / keV','零沉积'],records.filter(r=>r.record_kind==='decay').map(r=>[r.global_decay_id,r.event.ge_energy_keV,r.zero_deposit])));
 panel.append(table('全部读出脉冲组',['原始 ID / 组','Erec / keV','状态','接受','尾部可能截断'],records.filter(r=>r.record_kind==='pulse').map(r=>[r.global_decay_id+' / '+r.group_id,r.readout?.reconstructed_energy_keV,r.status,r.accepted,r.readout?.tail_truncated_possible])));
 const details=el('details');details.append(el('summary','每条完整记录：原始沉积、时间、单位与所有标记'));for(const [index,record] of records.entries()){const d=el('details');d.append(el('summary',record.record_kind+' · ID '+record.global_decay_id+(record.group_id==null?'':' / group '+record.group_id)));d.append(el('pre',lines[index]));details.append(d);}panel.append(details);const card=cards.get(job.id);if(!card?.isConnected)return;card.querySelector('.events')?.remove();card.append(panel);
}
function render(snapshot){active=!!snapshot.active;controls();const container=$('jobs');if(!snapshot.jobs.length){container.textContent='尚无任务。';return;}
 for(const child of [...container.childNodes])if(child.nodeType===Node.TEXT_NODE)child.remove();const present=new Set();let index=0;
 for(const job of snapshot.jobs){present.add(job.id);const signature=JSON.stringify([job,snapshot.active?.id||null]);const old=cards.get(job.id);if(old&&signatures.get(job.id)===signature){if(container.children[index]!==old)container.insertBefore(old,container.children[index]||null);index++;continue;}
  const card=el('article',undefined,'job');const title=el('strong',job.name+' · '+(job.detector||'保存的设置'));title.append(el('span',stateLabels[job.status]||job.status,'pill'));card.append(title);
  const backend=job.backend||job.result||{};const stages=backend.stages||{};const counts=backend.completed_counts||stages.completed_counts||{};const expected=backend.expected_counts||stages.expected_counts||{};
  const progressText=['charge','calibration','electronics'].filter(k=>counts[k]!=null).map(k=>({charge:'电荷',calibration:'校准',electronics:'电子学'}[k])+': '+counts[k]+' / '+(expected[k]??'?')).join(' · ');if(progressText)card.append(el('p',progressText));
  const census=backend.selected_census;if(census)card.append(el('p','原始事件统计：'+[['initial_primaries','初级粒子'],['zero_ge_primaries','零沉积'],['nonzero_primaries','非零沉积'],['groups','脉冲组']].map(([k,label])=>label+' '+(census[k]??'未知')).join(' · ')));
  if(job.error)card.append(el('p',job.error.message||JSON.stringify(job.error),'error'));
  const actions=el('div',undefined,'actions');if(snapshot.active&&snapshot.active.id===job.id&&['preflight','running','queued'].includes(job.status))actions.append(btn('停止（当前步骤结束后）',()=>api('/api/stop',{job_id:job.id})));
  if(!snapshot.active&&job.can_resume&&['stopped','paused','failed','blocked'].includes(job.status))actions.append(btn('验证并继续此任务',()=>api('/api/resume',{name:job.name})));
  if(['completed','completed_with_native_failures'].includes(job.status)){if(!job.complete_sha256)actions.append(btn('验证已保存结果',()=>api('/api/resume',{name:job.name})));else{actions.append(btn('查看全部事件结果',()=>showEvents(job)));for(const [label,file] of [['结果与标记','worker/'+job.detector+'/scalars.jsonl'],['完整保存波形','worker/'+job.detector+'/traces.jsonl'],['运行记录','run.json'],['设置与来源','manifest.json'],['完成凭据','COMPLETE.json']])actions.append(downloadLink(label,job.name,file));}}
  card.append(actions);const details=el('details');details.append(el('summary','记录 / 等价命令 / 输出位置'));details.append(el('p',job.output||''));if(job.runtime_choice)details.append(el('p','运行环境选择：'+job.runtime_choice.label+'；实际版本与程序字节由后端核对。'));details.append(el('pre',(job.command||[]).join(' ')));details.append(el('pre',(job.logs||[]).join('\n')||'等待后端记录。'));card.append(details);
  if(old){details.open=old.querySelector('details')?.open||false;const events=old.querySelector('.events');if(events)card.append(events);old.replaceWith(card);}else container.insertBefore(card,container.children[index]||null);cards.set(job.id,card);signatures.set(job.id,signature);index++;
 }
 for(const [id,card] of cards)if(!present.has(id)){card.remove();cards.delete(id);signatures.delete(id);}
}
async function poll(){try{const s=await api('/api/state');$('connection').textContent='已连接到本机 · 状态来自保存的后端记录';if(JSON.stringify(s)!==JSON.stringify(lastSnapshot)){render(s);lastSnapshot=s;}}catch(e){$('connection').textContent=e.message+'；重开 Control.cmd 后使用新会话链接。';$('run').disabled=true;}}
for(const id of ['name','detector'])$(id).addEventListener('input',()=>{checked='';resolved();controls();message('设置已更改，请重新检查输入。');});
$('check').addEventListener('click',async()=>{busy=true;controls();message('正在读取并验证输入；不会启动计算。');try{const r=await api('/api/check',values());if(!r.verification_final||r.status!=='planned')throw new Error((r.findings||[]).map(x=>x.message||JSON.stringify(x)).join('\n')||'输入未通过检查');checked=key();message('输入检查通过。点击“开始运行”才会计算；运行时还会核对软件与来源。');}catch(e){checked='';message(e.message,true);}finally{busy=false;controls();}});
$('run').addEventListener('click',async()=>{busy=true;controls();try{await api('/api/start',values());checked='';message('任务已明确启动。可以查看进度，或请求在当前步骤后停止。');await poll();}catch(e){message(e.message,true);}finally{busy=false;controls();}});
resolved();controls();poll();setInterval(poll,1000);
