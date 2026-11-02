import {dateRibbon} from './date-ribbon.js?v=1';
// Book practice shares the existing question reader, note editor and mistake folders.
export function createDailyPractice({api, app, esc, navigate, flush, refreshLibrary, getLibrary, getEditor, toast}) {
 let session=null, activePosition=null;
 const fields={ds:'数据结构',co:'计算机组成原理',os:'操作系统',cn:'计算机网络'};
 const overviewURL=(round,day='')=>`/daily-practice?subject=408${round?'&round_id='+encodeURIComponent(round):''}${day?'&day='+day:''}`;
 const itemURL=(i,round,day)=>`/papers/${i.paper_id}/questions/${i.number}?practice=${round}&day=${day}&position=${i.position}`;
 const badge=result=>`<span class="daily-result ${result||''}">${result==='correct'?'✓ 做对':result==='wrong'?'✕ 做错':'待练习'}</span>`;
 const track=(done,total,label)=>`<div class="daily-track" role="progressbar" aria-label="${label}" aria-valuemin="0" aria-valuemax="${total||1}" aria-valuenow="${done}"><span style="width:${total?done/total*100:0}%"></span></div>`;
 function reset(){session=null;activePosition=null}
 async function load(){
  const params=new URLSearchParams(location.search),round=params.get('round_id');
  const data=await api('/api/daily-practice'+(round?'?round_id='+encodeURIComponent(round):''));
  if(data.started&&params.has('day'))data.day=await api(`/api/daily-practice/rounds/${data.round.id}/days/${encodeURIComponent(params.get('day'))}`);
  return data;
 }
 function renderOverview(data){
  const header=`<div class="daily-top"><div><div class="eyebrow">FORTY QUESTIONS, ONE STEP FORWARD</div><h1>408 · 每日一练</h1><p class="lead">每天 40 道，四科一起向前。</p></div>${dateRibbon(data.today,esc)}</div>`;
  const rules='<p class="daily-rules">按章节题量比例安排，整轮跨天不重复。同一天题组固定；漏练可补做，尾期按剩余题量减量。暂未导入答案，完成后手动标记对错。</p>';
  if(!data.started){
   app.innerHTML=`<div class="page practice-page">${header}<section class="panel practice-welcome"><span class="practice-book-label">RELAX 1000 · 7.29 勘误版</span><h2>1576 道原题，安排好每一天。</h2><p class="lead">数据结构 411 · 组成原理 373 · 操作系统 417 · 计算机网络 375</p><div class="practice-welcome-facts"><span>四科每天各 10 道</span><span>42 天完成一轮</span><span>原题图文完整保留</span></div><button class="button primary" data-action="practice-start" ${data.ready?'':'disabled'}>${data.ready?'开始每日一练 →':'题库尚未导入'}</button><p class="tip">点击后从今天开始，按日历逐日开放。关闭网站期间的安排也会保留。</p></section>${rules}</div>`;
   return;
  }
  const round=data.round,day=data.day,isToday=day?.day===data.today;
  const next=day&&(day.items.find(i=>!i.result)||day.items[0]);
  const cursor=round.last_position;
  app.innerHTML=`<div class="page practice-page">${header}<div class="practice-round-bar"><label>练习轮次 <select id="practice-round" aria-label="练习轮次">${data.rounds.map((r,i)=>`<option value="${r.id}" ${r.id===round.id?'selected':''}>第 ${data.rounds.length-i} 轮 · ${r.start_day} — ${r.end_day}</option>`).join('')}</select></label><span class="small">本轮完成 ${round.completed} / ${round.total} · 尚待开放 ${round.remaining} 道</span>${data.can_start_next?'<button class="button subtle" data-action="practice-next-round">从明天开启新一轮 →</button>':''}</div>${data.upcoming?`<p class="pending-banner">新一轮将于 ${esc(data.upcoming.start_day)} 开放。过去轮次的练习仍可补做。</p>`:''}<section class="panel daily-progress"><div class="daily-progress-top"><div><h2>${day?`${isToday?'今日练习':day.day+' · 补做练习'} ${day.completed} / ${day.total}`:'新一轮已安排好'}</h2><p class="lead">${day?(day.total<40?'部分科目已到本轮尾声，今天出完剩余新题。':'数据结构、组成原理、操作系统、计算机网络，各 10 道。'):`从 ${round.start_day} 起逐日开放，今天可以继续补做历史练习。`}</p></div>${day?`<div class="daily-counts"><span class="correct">✓ 做对 ${day.correct} 道</span><span class="wrong">✕ 做错 ${day.wrong} 道</span></div>`:''}</div>${track(day?.completed||0,day?.total||0,'当日练习完成进度')}<div class="practice-continue">${next?`<a class="button primary" data-nav href="${itemURL(next,round.id,day.day)}">${day.completed===day.total?'查看题组':day.completed?'继续这组练习':'开始这组练习'} →</a>`:''}${cursor?`<button class="button subtle" id="practice-resume">回到上次阅读 →</button>`:''}<span class="small">已开放 ${round.released} / ${round.total} 道 · ${round.start_day} — ${round.end_day}</span></div></section>${rules}<div class="practice-subjects">${data.fields.map(f=>{
   const items=day?.items.filter(i=>i.field===f.field)||[],done=items.filter(i=>i.result).length;
   return `<section class="panel practice-subject"><div class="practice-subject-title"><span class="practice-field-code">${f.field.toUpperCase()}</span><h2>${esc(f.label)}</h2><span class="small">${done} / ${items.length}</span></div>${track(done,items.length,f.label+'当日完成进度')}<p class="small">本轮完成 ${f.completed} / ${f.total} · ${f.remaining?'待开放 '+f.remaining+' 道':'本轮已出完'}</p><div class="practice-item-list">${items.length?items.map(i=>`<a class="practice-item ${i.result||''}" data-nav href="${itemURL(i,round.id,day.day)}"><span class="practice-item-number">${String(i.position).padStart(2,'0')}</span><span><strong>${esc(i.chapter)}</strong><small>原题 ${i.number} · 书页 ${i.book_pages.join('、')}</small></span>${badge(i.result)}</a>`).join(''):`<p class="practice-exhausted">${f.remaining?'题目尚未开放':'本轮已出完，可补做历史练习。'}</p>`}</div></section>`;
  }).join('')}</div><section class="daily-history"><div class="section-head"><div><h2>练习日历</h2><p class="small">所有已开放题组均可查看和补做。</p></div></div><div class="practice-calendar">${data.history.map(h=>`<a class="daily-history-item ${day?.day===h.day?'active':''}" data-nav href="${overviewURL(round.id,h.day)}"><strong>${h.day}${h.day===data.today?' · 今天':''}</strong><span>完成 ${h.completed}/${h.total} · 对 ${h.correct||0} · 错 ${h.wrong||0}</span></a>`).join('')||'<p class="small">首组练习将在开始日期开放。</p>'}</div></section></div>`;
  app.querySelector('#practice-round').addEventListener('change',e=>navigate(overviewURL(e.target.value)));
  if(cursor){
   // Only fetch an older day when needed to resolve the persisted reading position.
   const resume=app.querySelector('#practice-resume');
   const open=async()=>{try{const previous=day?.day===cursor.day?day:await api(`/api/daily-practice/rounds/${round.id}/days/${cursor.day}`);const i=previous.items.find(i=>i.position===cursor.position);if(i)await navigate(itemURL(i,round.id,cursor.day));}catch(e){toast(e.message)}};
   resume.addEventListener('click',open);
  }
 }
 async function start(button,nextRound=false){
  button.disabled=true;
  try{if(!await flush())return;const data=await api('/api/daily-practice/'+(nextRound?'next-round':'start'),'POST');await navigate(overviewURL(data.round.id));}
  finally{if(button.isConnected)button.disabled=false}
 }
 async function context(pid,n,params){
  const round=params.get('practice'),day=params.get('day'),position=Number(params.get('position'));
  const data=await api(`/api/daily-practice/rounds/${encodeURIComponent(round)}/days/${encodeURIComponent(day)}`);
  if(!data.items.some(i=>i.position===position&&i.paper_id===pid&&i.number===n))throw new Error('这道题不在指定练习中，请从“每日一练”重新进入。');
  return {data,position};
 }
 function decorateReader(data,position){
  session=data;activePosition=position;
  const e=getEditor(),current=data.items.find(i=>i.position===position);
  e.practice={round:data.round_id,day:data.day,position};
  const back=app.querySelector('.breadcrumb a');back.href=overviewURL(data.round_id,data.day);back.textContent='← 返回每日一练';
  const intro=document.createElement('div');intro.className='daily-reader-intro practice-reader-intro';intro.innerHTML=`<span>${data.day} · 每日一练 ${position} / ${data.total} · ${esc(current.field_label)} · ${esc(current.chapter)}</span><span>原题 ${current.number} · 书页 ${current.book_pages.join('、')}</span>`;
  app.querySelector('.reader-layout').before(intro);
  app.querySelector('.question-nav').classList.add('practice-question-nav');
  const answer=document.createElement('section');answer.className='daily-answer';answer.innerHTML='<h3>这次做得怎么样？</h3><div class="daily-answer-buttons"><button class="button correct" data-action="practice-answer" data-value="correct">✓ 做对了</button><button class="button wrong" data-action="practice-answer" data-value="wrong">✕ 做错了</button></div><p class="daily-answer-message" role="status" aria-live="polite"></p>';
  app.querySelector('.question-bottom').before(answer);
  app.querySelector('[data-action="previous"]').disabled=position===1;
  const next=app.querySelector('[data-action="next"]');next.disabled=false;next.textContent=position===data.total?'返回练习概览 →':'下一题 →';
  app.querySelector('.question-bottom .small').textContent=`本组 ${position} / ${data.total}`;
  updateReader();
  api(`/api/daily-practice/rounds/${data.round_id}/position`,'PUT',{day:data.day,position}).catch(err=>toast('阅读位置未保存：'+err.message));
 }
 function updateReader(){
  if(!session||!activePosition)return;
  const i=session.items.find(i=>i.position===activePosition),side=app.querySelector('.practice-question-nav');
  if(side)side.innerHTML=`<div class="panel-label">本组练习 <span class="small">${session.completed}/${session.total}</span></div>${Object.entries(fields).map(([field,label])=>{
   const items=session.items.filter(i=>i.field===field);return items.length?`<div class="practice-nav-group"><h3>${label}</h3><div class="practice-number-grid">${items.map(i=>`<a class="number ${i.position===activePosition?'active':''} ${i.result==='correct'?'mastered':i.result==='wrong'?'review':''}" aria-label="本组第 ${i.position} 题，${i.chapter}，${i.result==='correct'?'做对':i.result==='wrong'?'做错':'待练习'}" data-nav href="${itemURL(i,session.round_id,session.day)}">${i.position}</a>`).join('')}</div></div>`:'';
  }).join('')}<p class="tip">绿色：做对 · 红色：做错<br>章节与题号沿用原书。</p>`;
  app.querySelectorAll('[data-action="practice-answer"]').forEach(b=>{b.classList.toggle('active',b.dataset.value===i.result);b.setAttribute('aria-pressed',String(b.dataset.value===i.result))});
  const message=app.querySelector('.daily-answer-message');message.className=`daily-answer-message ${i.result||''}`;message.textContent=i.result?`已记录：${i.result==='correct'?'做对':'做错'}，可随时改标。`:'暂未导入答案，请独立完成并自行核对后标记。';
 }
 async function answer(button){
  if(!session||!activePosition)return;
  const e=getEditor(),data=session,position=activePosition;
  const controls=[...app.querySelectorAll('[data-action="practice-answer"]')];controls.forEach(b=>b.disabled=true);
  try{
   if(!await flush())return;
   const result=await api(`/api/daily-practice/rounds/${data.round_id}/days/${data.day}/items/${position}`,'PUT',{result:button.dataset.value});
   await refreshLibrary();if(getEditor()!==e)return;
   session=result;updateReader();
   const status=getLibrary().stateMap[`${e.pid}:${e.n}`]?.status;
   app.querySelectorAll('.status-pills button').forEach(b=>b.classList.toggle('active',b.dataset.value===status));
   toast('练习结果已保存');
  }catch(err){if(getEditor()===e){const message=app.querySelector('.daily-answer-message');message.className='daily-answer-message error';message.textContent=err.message+'，请重试。';}}
  finally{controls.forEach(b=>b.disabled=false)}
 }
 function move(offset){
  if(!session||!activePosition)return false;
  const i=session.items.find(i=>i.position===activePosition+offset);
  navigate(i?itemURL(i,session.round_id,session.day):overviewURL(session.round_id,session.day));return true;
 }
 return {reset,load,renderOverview,start,context,decorateReader,answer,move};
}
