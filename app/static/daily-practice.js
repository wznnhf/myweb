import {dateRibbon} from './date-ribbon.js?v=1';
import {createChoiceBloom} from './choice-bloom.js?v=1';
export function createDailyPractice({api, app, esc, navigate, flush, refreshLibrary, getEditor, toast}) {
 let session=null, activePosition=null, overview=null, saving=null;
 const bloom=createChoiceBloom();
 const fields={ds:'数据结构',co:'计算机组成原理',os:'操作系统',cn:'计算机网络'};
 const complete=i=>!!i.choice&&!i.choice.includes('_');
 const overviewURL=(round,day='')=>`/daily-practice?subject=408${round?'&round_id='+encodeURIComponent(round):''}${day?'&day='+day:''}`;
 const itemURL=(i,round,day)=>`/papers/${i.paper_id}/questions/${i.number}?practice=${round}&day=${day}&position=${i.position}`;
 const dayAPI=data=>`/api/daily-practice/rounds/${data.round_id}/days/${data.day}`;
 const status=i=>i.result==='correct'?'✓ 正确':i.result==='wrong'?'✕ 错误':complete(i)?'已选择':i.choice?'待补全':'未作答';
 const badge=i=>`<span class="daily-result ${i.result||''} ${complete(i)?'selected':''}">${status(i)}</span>`;
 const track=(done,total,label)=>`<div class="daily-track" role="progressbar" aria-label="${label}" aria-valuemin="0" aria-valuemax="${total||1}" aria-valuenow="${done}"><span style="width:${total?done/total*100:0}%"></span></div>`;
 const formatChoice=s=>(s||'').split('').map((c,j)=>`${s.length>1?['①','②','③'][j]+' ':''}${c==='_' ?'—':c}`).join(' / ');
 function reset(){bloom.clear();session=null;activePosition=null;overview=null}
 async function wait(){if(saving)await saving;return !saving}
 async function load(){
  const params=new URLSearchParams(location.search),round=params.get('round_id');
  const data=await api('/api/daily-practice'+(round?'?round_id='+encodeURIComponent(round):''));
  if(data.started&&params.has('day'))data.day=await api(`/api/daily-practice/rounds/${data.round.id}/days/${encodeURIComponent(params.get('day'))}`);
  return data;
 }
 function submissionButton(day){return day&&!day.submitted?`<button class="button primary practice-submit" data-action="practice-submit" ${day.completed===day.total?'':'disabled'}>${day.completed===day.total?'交卷 · 解锁成绩 →':`还差 ${day.total-day.completed} 题 · 完成后交卷`}</button>`:''}
 function resultPanel(day){
  if(!day?.submitted)return '';
  const collection=day.collected_wrong?`<p>本组 ${day.collected_wrong} 道错题已收录至「每日一练错题」。<a class="text-button" data-nav href="/mistakes/${encodeURIComponent(day.mistake_folder_id)}?subject=408">查看错题 →</a></p>`:day.wrong===0?'<p>本组全部答对，继续保持。</p>':'';
  return `<section class="practice-report" aria-label="本组成绩"><div><div class="eyebrow">MISSION COMPLETE / 本组已交卷</div><h2>这一组，拿下了。</h2><p>已按十月勘误版解析核对。选择题号，复盘每一次卡住的地方。</p>${collection}</div><div class="practice-score"><strong>${Math.round(day.correct/day.total*100)}<small>%</small></strong><span>正确率 · ${day.correct} 对 / ${day.wrong} 错</span></div></section>`;
 }
 function renderOverview(data){
  overview=data;
  const header=`<div class="cyber-mode-line"><span><i></i> FOCUS SYSTEM ONLINE</span><span>408 / DAILY PROTOCOL</span></div><div class="daily-top"><div><div class="eyebrow">每天 40 题 / 把专注推到下一档</div><h1>进入状态<span class="cyber-title-dot">_</span></h1><p class="lead">408 每日一练 · 选择，前进。做完这一组，再看答案。</p></div>${dateRibbon(data.today,esc)}</div>`;
  const rules='<p class="daily-rules">选择自动保存 · 交卷前可修改 · 全组完成后统一判分，错题自动加入错题本 · 解析采用 10 月勘误版。原题跨天不重复，漏练可补做；轮末按剩余题量安排。</p>';
  if(!data.started){
   app.innerHTML=`<div class="page practice-page">${header}<section class="panel practice-welcome"><span class="practice-book-label">RELAX 1000 / 42 DAY CHALLENGE</span><h2>让今天的 40 题，<br>成为下一次突破。</h2><p class="lead">1576 道原题 · 四科同步推进 · 每一次选择都被记住</p><div class="practice-welcome-facts"><span>DS / 数据结构 411</span><span>CO / 组成原理 373</span><span>OS / 操作系统 417</span><span>CN / 计算机网络 375</span></div><button class="button primary" data-action="practice-start" ${data.ready?'':'disabled'}>${data.ready?'启动每日一练 →':'题库尚未导入'}</button><p class="tip">从今天开始逐日开放，自动保存，随时回来接着做。</p></section>${rules}</div>`;return;
  }
  const round=data.round,day=data.day,isToday=day?.day===data.today;
  const next=day&&(day.items.find(i=>!complete(i))||day.items[0]),cursor=round.last_position;
  app.innerHTML=`<div class="page practice-page">${header}<div class="practice-round-bar"><label>练习轮次 <select id="practice-round" aria-label="练习轮次">${data.rounds.map((r,i)=>`<option value="${r.id}" ${r.id===round.id?'selected':''}>第 ${data.rounds.length-i} 轮 · ${r.start_day} — ${r.end_day}</option>`).join('')}</select></label><span class="small">本轮完成 ${round.completed} / ${round.total} · 待开放 ${round.remaining}</span>${data.can_start_next?'<button class="button subtle" data-action="practice-next-round">明天开启新一轮 →</button>':''}</div>${data.upcoming?`<p class="pending-banner">新一轮于 ${esc(data.upcoming.start_day)} 开放。</p>`:''}${resultPanel(day)}<section class="panel daily-progress"><div class="daily-progress-top"><div><div class="eyebrow">${day?.submitted?'REVIEW MODE / 复盘模式':'MISSION IN PROGRESS / 专注进行中'}</div><h2>${day?`${isToday?'今日任务':day.day+' · 补做'} <span class="practice-progress-number">${day.completed}<small> / ${day.total}</small></span>`:'下一轮，已就位'}</h2><p class="lead">${day?(day.total<40?'本轮进入尾声，完成今天全部题目即可交卷。':'DS · CO · OS · CN，每科 10 道。一次只专注眼前这一题。'):`从 ${round.start_day} 起开放，可继续补做历史题组。`}</p></div><div class="practice-orbit" aria-hidden="true"><span>${day?String(day.total-day.completed).padStart(2,'0'):'40'}</span><small>${day?.submitted?'COMPLETE':'TO GO'}</small></div></div>${track(day?.completed||0,day?.total||0,'当日练习完成进度')}<div class="practice-continue">${next?`<a class="button ${day.submitted?'':'primary'}" data-nav href="${itemURL(next,round.id,day.day)}">${day.submitted?'复盘这组练习':day.completed?'继续作答':'开始今日任务'} →</a>`:''}${submissionButton(day)}${cursor?'<button class="text-button" id="practice-resume">回到上次阅读 ↗</button>':''}<span class="small">已开放 ${round.released} / ${round.total}</span></div></section>${rules}<div class="practice-subjects">${data.fields.map((f,index)=>{
   const items=day?.items.filter(i=>i.field===f.field)||[],done=items.filter(complete).length;
   return `<section class="panel practice-subject"><div class="practice-subject-title"><span class="practice-field-code">0${index+1} / ${f.field.toUpperCase()}</span><h2>${esc(f.label)}</h2><span class="small">${done} / ${items.length}</span></div>${track(done,items.length,f.label+'当日完成进度')}<div class="practice-item-list">${items.length?items.map(i=>`<a class="practice-item ${i.result||''} ${complete(i)?'is-selected':''}" data-nav href="${itemURL(i,round.id,day.day)}"><span class="practice-item-number">${String(i.position).padStart(2,'0')}</span><span><strong>${esc(i.chapter)}</strong><small>原题 ${i.number}${i.choice?' · 已选 '+esc(formatChoice(i.choice)):''}${i.correct_answer?' · 答案 '+esc(formatChoice(i.correct_answer)):''}</small></span>${badge(i)}</a>`).join(''):`<p class="practice-exhausted">${f.remaining?'题目尚未开放':'本轮已出完，可补做历史练习。'}</p>`}</div></section>`;
  }).join('')}</div><section class="daily-history"><div class="section-head"><div><div class="eyebrow">MISSION ARCHIVE</div><h2>练习日历</h2><p class="small">已开放题组随时回来，选项与进度持续保留。</p></div></div><div class="practice-calendar">${data.history.map(h=>`<a class="daily-history-item ${day?.day===h.day?'active':''}" data-nav href="${overviewURL(round.id,h.day)}"><strong>${h.day}${h.day===data.today?' · 今天':''}</strong><span>已选 ${h.completed}/${h.total}${h.submitted?` · 对 ${h.correct} / 错 ${h.wrong}`:' · 未交卷'}</span></a>`).join('')||'<p class="small">首组练习将在开始日期开放。</p>'}</div></section></div>`;
  app.querySelector('#practice-round').addEventListener('change',e=>navigate(overviewURL(e.target.value)));
  if(cursor)app.querySelector('#practice-resume').addEventListener('click',async()=>{
   try{const previous=day?.day===cursor.day?day:await api(`/api/daily-practice/rounds/${round.id}/days/${cursor.day}`),i=previous.items.find(i=>i.position===cursor.position);if(i)await navigate(itemURL(i,round.id,cursor.day));}catch(e){toast(e.message)}
  });
 }
 async function start(button,nextRound=false){
  button.disabled=true;try{if(!await flush())return;const data=await api('/api/daily-practice/'+(nextRound?'next-round':'start'),'POST');await navigate(overviewURL(data.round.id));}finally{if(button.isConnected)button.disabled=false}
 }
 async function context(pid,n,params){
  const round=params.get('practice'),day=params.get('day'),position=Number(params.get('position'));
  const data=await api(`/api/daily-practice/rounds/${encodeURIComponent(round)}/days/${encodeURIComponent(day)}`);
  if(!data.items.some(i=>i.position===position&&i.paper_id===pid&&i.number===n))throw new Error('这道题不在指定练习中，请从每日一练重新进入。');
  return {data,position};
 }
 function decorateReader(data,position){
  session=data;activePosition=position;
  const e=getEditor(),current=data.items.find(i=>i.position===position);e.practice={round:data.round_id,day:data.day,position};
  app.querySelector('.reader-page').classList.add('practice-reader');
  app.querySelector('.practice-no-answer')?.remove();
  const statusPills=app.querySelector('.status-pills');statusPills?.previousElementSibling?.remove();statusPills?.remove();
  const back=app.querySelector('.breadcrumb a');back.href=overviewURL(data.round_id,data.day);back.textContent='← 每日一练任务台';
  const intro=document.createElement('div');intro.className='daily-reader-intro practice-reader-intro';intro.innerHTML=`<span><i class="cyber-live-dot"></i> ${data.submitted?'REVIEW':'FOCUS'} / ${String(position).padStart(2,'0')} — ${data.total} · ${esc(current.field_label)}</span><span>${data.day} · 原题 ${current.number} · 书页 ${current.book_pages.join('、')}</span>`;
  app.querySelector('.reader-layout').before(intro);
  app.querySelector('.question-nav').classList.add('practice-question-nav');
  app.querySelector('.image-scroll').insertAdjacentHTML('afterend','<p class="practice-image-hint">↔ 题图可左右滑动，点击「放大题目」查看细节。</p>');
  app.querySelector('.question-bar h2').innerHTML=`任务 ${String(position).padStart(2,'0')} <span class="badge">${current.slots>1?current.slots+' 空题':'单项选择'}</span>`;
  const answer=document.createElement('section');answer.className='daily-answer practice-choice-panel';
  answer.innerHTML=`<div class="practice-choice-heading"><h3>${data.submitted?'本题作答':'锁定你的选择'}</h3><span class="small">${data.submitted?'已交卷 · 选项已锁定':'自动保存 · 交卷前可修改'}</span></div>${Array.from({length:current.slots},(_,slot)=>`<div class="practice-choice-row">${current.slots>1?`<span class="practice-slot-label">第${['①','②','③'][slot]}空</span>`:''}<div class="practice-options" role="group" aria-label="${current.slots>1?'第'+(slot+1)+'空选项':'本题选项'}">${['A','B','C','D'].map(c=>`<button class="practice-option" data-action="practice-answer" data-value="${c}" data-slot="${slot}" aria-pressed="false"><strong>${c}</strong><span>选择 ${c}</span><i aria-hidden="true">↗</i></button>`).join('')}</div></div>`).join('')}<p class="daily-answer-message" role="status" aria-live="polite"></p><div class="practice-solution"></div><div class="practice-submit-slot"></div>`;
  app.querySelector('.question-bottom').before(answer);
  app.querySelector('[data-action="previous"]').disabled=position===1;
  const next=app.querySelector('[data-action="next"]');next.disabled=false;next.textContent=position===data.total?'检查整组 / 交卷 →':'下一题 →';
  app.querySelector('.question-bottom .small').textContent=`${position} / ${data.total}`;
  updateReader();api(`/api/daily-practice/rounds/${data.round_id}/position`,'PUT',{day:data.day,position}).catch(err=>toast('阅读位置未保存：'+err.message));
 }
 function updateReader(){
  if(!session||!activePosition)return;
  const i=session.items.find(i=>i.position===activePosition),side=app.querySelector('.practice-question-nav');
  if(side)side.innerHTML=`<div class="panel-label">任务进度 <span class="small">${session.completed}/${session.total}</span></div>${track(session.completed,session.total,'本组已作答题数')}${Object.entries(fields).map(([field,label])=>{
   const items=session.items.filter(i=>i.field===field);return items.length?`<div class="practice-nav-group"><h3>${field.toUpperCase()} / ${label}</h3><div class="practice-number-grid">${items.map(i=>`<a class="number ${i.position===activePosition?'active':''} ${i.result==='correct'?'mastered':i.result==='wrong'?'review':complete(i)?'is-selected':''}" aria-label="本组第 ${i.position} 题，${status(i)}" data-nav href="${itemURL(i,session.round_id,session.day)}">${String(i.position).padStart(2,'0')}</a>`).join('')}</div></div>`:'';
  }).join('')}<p class="tip">${session.submitted?'绿色：正确 · 红色：错误':'亮色：已选择 · 描边：当前题<br>交卷前不显示答案与对错。'}</p>`;
  app.querySelectorAll('[data-action="practice-answer"]').forEach(b=>{
   const selected=b.dataset.value===i.choice?.[Number(b.dataset.slot)];b.classList.toggle('active',selected);b.setAttribute('aria-pressed',String(selected));b.disabled=session.submitted;
   b.querySelector('span').textContent=selected?(session.submitted?'你的选择':'已选择'):'选择 '+b.dataset.value;
   b.querySelector('i').textContent=selected?'●':'↗';
   b.classList.toggle('is-right',session.submitted&&b.dataset.value===i.correct_answer?.[Number(b.dataset.slot)]);
   b.classList.toggle('is-wrong',session.submitted&&selected&&b.dataset.value!==i.correct_answer?.[Number(b.dataset.slot)]);
  });
  const message=app.querySelector('.daily-answer-message');message.className=`daily-answer-message ${i.result||''}`;
  message.textContent=session.submitted?`${i.result==='correct'?'✓ 回答正确':'✕ 回答错误'} · 你的选择 ${formatChoice(i.choice)} · 正确答案 ${formatChoice(i.correct_answer)}`:i.choice?`已保存 ${formatChoice(i.choice).replaceAll('_','—')} · 本组已选 ${session.completed}/${session.total} · 交卷后统一核对。`:'选择下方 A / B / C / D，答案自动保存。完成整组后再核对。';
  const solution=app.querySelector('.practice-solution');solution.replaceChildren();
  if(session.submitted){
   solution.innerHTML=`<details class="practice-analysis"><summary>查看十月版解析原文 <span>PDF 第 ${i.analysis_page} 页 ↗</span></summary><p class="small">${i.slots>1?'本题按各空顺序判分，所有空正确才算答对。':'解析来自用户提供的十月勘误版。'} <a href="${esc(i.analysis_url)}" target="_blank" rel="noopener" class="text-button">在新标签页打开原册 ↗</a></p><div class="practice-pdf-slot"></div></details>`;
   const details=solution.querySelector('details');details.addEventListener('toggle',()=>{if(details.open&&!details.querySelector('iframe')){const frame=document.createElement('iframe');frame.src=i.analysis_url;frame.title='本题解析原文';frame.loading='lazy';details.querySelector('.practice-pdf-slot').append(frame)}});
  }
  app.querySelector('.practice-submit-slot').innerHTML=submissionButton(session);
 }
 async function answer(button,event){
  if(!session||!activePosition||session.submitted||saving)return;
  const e=getEditor(),data=session,position=activePosition,i=data.items.find(i=>i.position===position);
  const chars=(i.choice||'_'.repeat(i.slots)).split('');chars[Number(button.dataset.slot)]=button.dataset.value;
  const effect=bloom.press(button,event);
  const controls=[...app.querySelectorAll('[data-action="practice-answer"]')];controls.forEach(b=>b.disabled=true);
  app.querySelector('.daily-answer-message').textContent='正在保存选择…';
  const work=(async()=>{
   try{
    const result=await api(dayAPI(data)+`/items/${position}`,'PUT',{choice:chars.join('')});
    if(getEditor()!==e)return;session=result;updateReader();bloom.confirm(effect);
   }catch(err){bloom.fail(effect);if(getEditor()===e){const message=app.querySelector('.daily-answer-message');message.className='daily-answer-message error';message.textContent='选择未保存：'+err.message+'，请重新点击选项。';toast('选择未保存，请重试')}}
   finally{controls.forEach(b=>{if(b.isConnected)b.disabled=!!session?.submitted})}
  })();saving=work;try{await work}finally{if(saving===work)saving=null}
 }
 async function submit(button){
  const data=session||overview?.day;if(!data||data.submitted)return;
  button.disabled=true;
  try{await wait();if(!await flush())return;const result=await api(dayAPI(data)+'/submit','POST');await refreshLibrary();await navigate(overviewURL(data.round_id,data.day));toast(result.collected_wrong?`本组已交卷，${result.collected_wrong} 道错题已加入错题本`:'本组已交卷，成绩与解析已解锁')}
  catch(err){toast(err.message)}finally{if(button.isConnected)button.disabled=false}
 }
 function move(offset){if(!session||!activePosition)return false;const i=session.items.find(i=>i.position===activePosition+offset);navigate(i?itemURL(i,session.round_id,session.day):overviewURL(session.round_id,session.day));return true}
 return {reset,load,renderOverview,start,context,decorateReader,answer,submit,move,wait,isSaving:()=>!!saving};
}
