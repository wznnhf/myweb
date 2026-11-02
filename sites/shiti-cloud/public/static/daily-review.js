import {dateRibbon} from './date-ribbon.js?v=1';
// Shared helpers are passed by the main app; daily review uses the existing reader and notes.
export function createDailyReview({api,subjectLabel,esc,app,flush,refreshLibrary,getLibrary,getEditor,toast,navigate}) {
 let session=null, activePosition=null;
 const labels={correct:'做对',wrong:'做错'};
 const itemURL=(item,day)=>`/papers/${item.paper_id}/questions/${item.number}?daily=${day}&position=${item.position}`;
 const resultBadge=result=>`<span class="daily-result ${result||''}">${result==='correct'?'✓ 做对':result==='wrong'?'✕ 做错':'待回顾'}</span>`;
 function reset(){session=null;activePosition=null}
 async function load(){return api('/api/daily-review','POST')}
 function renderOverview(data){
  session=data;
  const done=data.total>0&&data.completed===data.total;
  const next=data.items.find(i=>!i.result)||data.items[0];
  const rules=`同一天题目固定，刷新不会重抽。优先抽到较少、做错较多的题，尽量避开上一次回顾。${data.repeated_previous?`<br><strong>错题数量有限，今天有 ${data.repeated_previous} 道来自上一次回顾。</strong>`:''}${data.total>0&&data.total<5?`<br><strong>生成时只有 ${data.pool_size} 道已收藏错题，今天先回顾这 ${data.total} 道。</strong>`:''}`;
  const history=data.history.filter(h=>h.day!==data.day);
  app.innerHTML=`<div class="page"><div class="daily-top"><div><div class="eyebrow">A LITTLE REVIEW, EVERY DAY</div><h1>${subjectLabel()} · 每日回顾</h1><p class="lead">每天 5 道，让记住的东西留得更久。</p></div>${dateRibbon(data.day,esc)}</div><section class="panel daily-progress"><div class="daily-progress-top"><div><h2>${done?'今天的回顾完成了！':data.total?`今日进度 ${data.completed} / ${data.total}`:'从你的错题夹开始'}</h2><p class="lead">${done?'认真复盘过的每一道，都在帮你向前。':'从已收藏的错题中抽取，不会混入未收藏的题。'}</p></div><div class="daily-counts"><span class="correct">✓ 做对 ${data.correct} 道</span><span class="wrong">✕ 做错 ${data.wrong} 道</span></div></div><div class="daily-track" role="progressbar" aria-label="今日回顾完成进度" aria-valuemin="0" aria-valuemax="${data.total||5}" aria-valuenow="${data.completed}"><span style="width:${data.total?data.completed/data.total*100:0}%"></span></div>${next?`<a class="button primary" data-nav href="${itemURL(next,data.day)}">${done?'查看今日回顾':data.completed?'继续回顾':'开始今日回顾'} →</a>`:'<a class="button primary" data-nav href="/">去试卷库收藏题目 →</a>'}</section><p class="daily-rules">${rules}</p><div class="daily-grid">${data.items.map(i=>`<a class="daily-card ${i.result||''}" data-nav href="${itemURL(i,data.day)}"><div class="card-top"><span class="paper-num">今日第 ${i.position} 题</span>${resultBadge(i.result)}</div><h3>${esc(i.title)} · 第 ${i.number} 题</h3><span class="small">${esc(i.type)} · ${esc(i.difficulty)}</span><div class="preview"><img loading="lazy" src="${i.image}" alt="第 ${i.number} 题预览"></div><div class="card-foot"><span>抽取 ${i.drawn_count} 次 · 做错 ${i.wrong_count} 次</span><span>去回顾 ↗</span></div></a>`).join('')}</div>${!data.total?'<div class="empty"><strong>还没有已收藏的错题</strong>先在题目右侧勾选一个错题夹，再打开这里生成今日回顾。</div>':''}${history.length?`<section class="daily-history"><h2>最近的回顾</h2><div class="daily-history-list">${history.map(h=>`<div class="daily-history-item"><strong>${esc(h.day)}</strong><span>完成 ${h.completed}/${h.total} · 对 ${h.correct} · 错 ${h.wrong}</span></div>`).join('')}</div></section>`:''}</div>`;
 }
 async function context(pid,n,params){
  const data=await api('/api/daily-review');
  const position=Number(params.get('position'));
  if(params.get('daily')!==data.day)throw new Error('日期已变化，请从上方“每日回顾”打开今天的题目。');
  const item=data.items.find(i=>i.position===position&&i.paper_id===pid&&i.number===n);
  if(!item)throw new Error('这道题不在今天的回顾列表中，请从“每日回顾”重新进入。');
  return {data,position};
 }
 function decorateReader(data,position){
  session=data;activePosition=position;
  const e=getEditor();e.daily={day:data.day,position};
  const back=app.querySelector('.breadcrumb a');back.href='/daily-review';back.textContent='← 返回每日回顾';
  const intro=document.createElement('div');intro.className='daily-reader-intro';intro.innerHTML=`<span>每日回顾 · ${esc(data.day)} · 今日第 ${position} / ${data.total} 题</span><a class="daily-source-link" data-nav href="/papers/${e.pid}/questions/${e.n}">查看所属试卷 →</a>`;
  app.querySelector('.reader-layout').before(intro);
  const side=app.querySelector('.question-nav');side.classList.add('daily-question-nav');
  const answer=document.createElement('section');answer.className='daily-answer';answer.id='daily-answer';
  answer.innerHTML='<h3>这次做得怎么样？</h3><div class="daily-answer-buttons"><button class="button correct" data-action="daily-answer" data-value="correct">✓ 做对了</button><button class="button wrong" data-action="daily-answer" data-value="wrong">✕ 做错了</button></div><p class="daily-answer-message" role="status" aria-live="polite"></p>';
  app.querySelector('.question-bottom').before(answer);
  const previous=app.querySelector('[data-action="previous"]'),next=app.querySelector('[data-action="next"]');
  previous.disabled=position===1;next.disabled=false;
  next.textContent=position===data.total?'返回今日回顾 →':'下一题 →';
  app.querySelector('.question-bottom .small').textContent=`今日 ${position} / ${data.total}`;
  updateReader();
 }
 function updateReader(){
  if(!session||!activePosition)return;
  const side=app.querySelector('.daily-question-nav');
  if(side)side.innerHTML=`<div class="panel-label">今日回顾 <span class="small">${session.completed} / ${session.total}</span></div>${session.items.map(i=>`<a class="daily-question-link ${i.position===activePosition?'active':''}" data-nav href="${itemURL(i,session.day)}"><strong>今日第 ${i.position} 题</strong><span class="daily-q-title">${esc(i.title)}<br>原卷第 ${i.number} 题</span>${resultBadge(i.result)}</a>`).join('')}`;
  const item=session.items.find(i=>i.position===activePosition);
  app.querySelectorAll('[data-action="daily-answer"]').forEach(b=>{b.classList.toggle('active',b.dataset.value===item.result);b.setAttribute('aria-pressed',String(b.dataset.value===item.result))});
  const message=app.querySelector('.daily-answer-message');
  message.className=`daily-answer-message ${item.result||''}`;
  message.textContent=`${item.result?`已记录：${labels[item.result]}，可改标。`:'先独立完成，再标记结果。'}累计抽取 ${item.drawn_count} 次 · 做对 ${item.correct_count} 次 · 做错 ${item.wrong_count} 次。`;
 }
 async function answer(button){
  if(!session||!activePosition||button.disabled)return;
  const e=getEditor(),day=session.day,position=activePosition;
  const controls=[...app.querySelectorAll('[data-action="daily-answer"]')];controls.forEach(b=>b.disabled=true);
  try{
   if(!await flush())return;
   const data=await api(`/api/daily-review/${day}/items/${position}`,'PUT',{result:button.dataset.value});
   await refreshLibrary();
   if(getEditor()!==e)return;
   session=data;updateReader();
   const status=getLibrary().stateMap[`${e.pid}:${e.n}`]?.status;
   app.querySelectorAll('.status-pills button').forEach(b=>b.classList.toggle('active',b.dataset.value===status));
   toast(button.dataset.value==='correct'?'已记为做对，继续保持！':'已记为做错，下次会优先复习。');
  }catch(err){
   if(getEditor()===e){const message=app.querySelector('.daily-answer-message');message.className='daily-answer-message error';message.textContent=`${err.message} 结果尚未确认，请重试。`;}
  }finally{controls.forEach(b=>b.disabled=false)}
 }
 function move(offset){
  if(!session||!activePosition)return false;
  const item=session.items.find(i=>i.position===activePosition+offset);
  navigate(item?itemURL(item,session.day):'/daily-review');return true;
 }
 return {reset,load,renderOverview,context,decorateReader,answer,move};
}
