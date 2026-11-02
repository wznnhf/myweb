import {createCyber} from './cyber.js?v=3';
import {mathHomeHTML} from './parchment.js?v=1';
import {noteEditorHTML, mountNoteEditor} from './notes.js?v=3';
import {mountAnswer} from './answers.js?v=2';
import {createDailyReview} from './daily-review.js?v=7';
import {createKnowledge} from './knowledge.js?v=4';
import {createDailyPractice} from './daily-practice.js?v=5';
import {createActivity} from './activity.js?v=1';
import {createMotion,transitionBetween} from './motion.js?v=1';
import {toggleDateRibbon} from './date-ribbon.js?v=1';
const $ = (s, root=document) => root.querySelector(s);
const $$ = (s, root=document) => [...root.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const labels = {unmarked:'未标记',review:'未掌握',mastered:'已掌握'};
const app=$('#app'), modal=$('#modal');
const motion=createMotion(app);
const cyber=createCyber();
$('#workspace-date').textContent=new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'long',day:'numeric',weekday:'long'}).format(new Date());
let lib, editor=null, rendering=0, currentURL=location.pathname+location.search;
let subject=['math','408'].includes(new URLSearchParams(location.search).get('subject'))?new URLSearchParams(location.search).get('subject'):(localStorage.getItem('cuoti-subject')==='408'?'408':'math');
const subjectLabel=()=>subject==='408'?'408 计算机':'数学二';
const scopedAPI=(url,method,body)=>api(url+(url.includes('?')?'&':'?')+'subject='+subject,method,body);
function setSubject(value){if(subject!==value){homeFilter={difficulty:'全部',year:'全部年份',search:''};reviewFilter='all'}subject=value;localStorage.setItem('cuoti-subject',subject);document.body.dataset.subject=subject;cyber.setSubject(subject);document.querySelectorAll('[data-action=subject]').forEach(b=>{b.classList.toggle('active',b.dataset.value===subject);b.setAttribute('aria-pressed',String(b.dataset.value===subject))});}
let homeFilter={difficulty:'全部',year:'全部年份',search:''}, reviewFilter='all', toastTimer;
const key=(p,n)=>`${p}:${n}`;
const draftKey=(p,n)=>`cuoti-draft:${key(p,n)}`;
const questionURL=(p,n,folder='')=>`/papers/${p}/questions/${n}${folder?'?folder='+encodeURIComponent(folder):''}`;
const badge=d=>`<span class="badge ${d==='适中'?'medium':d==='较难'?'hard':''}">${d}</span>`;
const empty=(title,body)=>`<div class="empty"><strong>${esc(title)}</strong>${esc(body)}</div>`;
function toast(message){$('#toast').textContent=message;$('#toast').classList.add('visible');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').classList.remove('visible'),4500)}
async function api(url,method='GET',body,{rawBody=false,rawResponse=false}={}){
 const controller=new AbortController(), timer=setTimeout(()=>controller.abort(),12000);
 try{
  const r=await fetch(url,{method,headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:rawBody?body:JSON.stringify(body),signal:controller.signal});
  if(r.ok&&rawResponse)return await r.text();
  let data;try{data=await r.json()}catch{throw new Error('服务返回异常，请检查启动窗口')}
  if(!r.ok){const e=new Error(typeof data.detail==='string'?data.detail:'数据格式不正确，请检查输入或备份文件');e.status=r.status;throw e}
  return data;
 }catch(e){if(e.name==='AbortError')throw new Error('保存或加载超时，请检查本地服务并重试');if(e instanceof TypeError)throw new Error('无法连接本地服务，请检查启动窗口');throw e}finally{clearTimeout(timer)}
}
async function refreshLibrary(){const requested=subject,data=await api('/api/library?subject='+requested);if(subject!==requested)return;lib=data;lib.stateMap=Object.fromEntries(lib.states.map(s=>[key(s.paper_id,s.number),s]));lib.paperMap=Object.fromEntries([...lib.papers,...(lib.exercise_books||[])].map(p=>[p.id,p]));}
function hasMembership(p,n){return lib.memberships.some(m=>m.paper_id===p&&m.number===n)}
function updateState(s){lib.stateMap[key(s.paper_id,s.number)]={...s,has_note:!!s.note};const i=lib.states.findIndex(v=>v.paper_id===s.paper_id&&v.number===s.number);if(i<0)lib.states.push(lib.stateMap[key(s.paper_id,s.number)]);else lib.states[i]=lib.stateMap[key(s.paper_id,s.number)];}
function draftWrite(e){try{localStorage.setItem(draftKey(e.pid,e.n),JSON.stringify({note:e.value,revision:e.revision}))}catch{e.draftUnavailable=true}}
function draftRemove(e){try{localStorage.removeItem(draftKey(e.pid,e.n))}catch{}}
function saveStatus(e,message,error=false){if(editor!==e)return;const row=$('#save-row');if(row){row.classList.toggle('error',error);$('#save-text').textContent=message;$('#retry-save').hidden=!error}}
async function saveEditor(e=editor){
 if(!e)return true;
 clearTimeout(e.timer);
 if(e.flight){const ok=await e.flight;if(!ok)return false;return saveEditor(e)}
 if(e.value===e.saved){saveStatus(e,'已保存到本机');return true}
 const text=e.value;saveStatus(e,'正在保存…');
 e.flight=(async()=>{
  try{const s=await api(`/api/questions/${e.pid}/${e.n}`,'PATCH',{note:text,revision:e.revision});
   e.saved=text;e.revision=s.revision;updateState(s);
   if(e.value===e.saved){draftRemove(e);saveStatus(e,'已保存到本机');if(editor===e){$('#draft-banner')?.remove();updateNumberMarkers()}}
   else draftWrite(e);
   return true;
  }catch(err){draftWrite(e);saveStatus(e,err.message,true);return false}
  finally{e.flight=null}
 })();
 const ok=await e.flight;if(ok&&e.value!==e.saved)return saveEditor(e);return ok;
}
async function flush(){await practice.wait();const e=editor;await e?.noteUI?.wait();const ok=await saveEditor(e);if(!ok)toast('笔记尚未保存，已保留草稿。请重试保存后再切换页面。');return ok}
async function navigate(url,replace=false){if(!await flush())return;const from=currentURL,target=new URL(url,location.origin);if(!target.pathname.startsWith('/papers/'))target.searchParams.set('subject',subject);history[replace?'replaceState':'pushState']({},'',target.pathname+target.search);currentURL=location.pathname+location.search;await render({from,scrollTop:true})}
window.addEventListener('popstate',async()=>{const target=location.pathname+location.search;if(!await flush()){history.pushState({},'',currentURL);return}const from=currentURL;currentURL=target;await render({from})});
window.addEventListener('beforeunload',e=>{if(practice.isSaving()||(editor&&(editor.value!==editor.saved||editor.noteUI?.busy))){if(editor)draftWrite(editor);e.preventDefault();e.returnValue=''}});
function recoverDraft(pid,n){try{return JSON.parse(localStorage.getItem(draftKey(pid,n))||'null')}catch{return null}}
function pendingDrafts(){try{return Object.keys(localStorage).filter(k=>k.startsWith('cuoti-draft:')).map(k=>({ref:k.slice(12).split(':'),data:JSON.parse(localStorage.getItem(k))})).filter(x=>lib.paperMap[x.ref[0]])}catch{return []}}
async function render({from=currentURL,scrollTop=false}={}){
 const token=++rendering,route=new URL(location.href);
 editor=null;daily.reset();knowledge.reset();practice.reset();
 const ticket=motion.begin(transitionBetween(from,route.href));
 try{
  const match=route.pathname.match(/^\/papers\/([^/]+)\/questions\/(\d+)$/);
  const routePaper=match?await api('/api/papers/'+match[1]):null;
  if(token!==rendering)return;
  const params=route.searchParams,requestedSubject=params.get('subject');
  setSubject(['/knowledge-draw','/daily-practice'].includes(route.pathname)?'408':routePaper?.subject||(['math','408'].includes(requestedSubject)?requestedSubject:subject));
  await refreshLibrary();if(token!==rendering)return;
  const isMistake=route.pathname.startsWith('/mistakes')||params.has('folder');
  const isDaily=route.pathname==='/daily-review'||params.has('daily');
  const isKnowledge=route.pathname==='/knowledge-draw',isPractice=route.pathname==='/daily-practice'||params.has('practice');
  let draw;
  if(match){
   const paper=routePaper,q=await api(`/api/questions/${match[1]}/${match[2]}`);
   const dailyContext=isDaily?await daily.context(paper.id,q.number,params):null;
   const practiceContext=isPractice?await practice.context(paper.id,q.number,params):null;
   draw=()=>{renderReader(paper,q);if(dailyContext)daily.decorateReader(dailyContext.data,dailyContext.position);if(practiceContext)practice.decorateReader(practiceContext.data,practiceContext.position);api('/api/last-read','PUT',{paper_id:paper.id,number:q.number}).catch(e=>toast('阅读位置未保存：'+e.message))};
  }
  else if(isPractice){const data=await practice.load();draw=()=>{practice.renderOverview(data);const root=app.querySelector('.page'),panel=activity.mount(root,'408','daily_practice');if(panel)root.append(panel)}}
  else if(isKnowledge){const data=await knowledge.load();draw=()=>knowledge.render(data)}
  else if(route.pathname==='/daily-review'){const data=await daily.load();draw=()=>{daily.renderOverview(data);const root=app.querySelector('.page'),panel=activity.mount(root,subject,'daily_review');if(panel)root.append(panel)}}
  else if(route.pathname.startsWith('/mistakes'))draw=renderMistakes;
  else draw=renderHome;
  if(token!==rendering)return;
  await motion.commit(ticket,()=>{
   cyber.setMode(isPractice?'practice':isKnowledge?'knowledge':isDaily?'review':isMistake?'mistakes':match?'reader':'library');
   $('#nav-practice').hidden=subject!=='408';$('#nav-practice').classList.toggle('active',isPractice);
   $('#nav-knowledge').hidden=subject!=='408';$('#nav-knowledge').classList.toggle('active',isKnowledge);
   $('#nav-library').classList.toggle('active',!isMistake&&!isDaily&&!isKnowledge&&!isPractice);$('#nav-mistakes').classList.toggle('active',isMistake&&!isDaily);$('#nav-daily').classList.toggle('active',isDaily);
   document.querySelectorAll('.topbar nav a').forEach(link=>{if(link.classList.contains('active'))link.setAttribute('aria-current','page');else link.removeAttribute('aria-current')});
   return draw();
  },{scrollTop});
 }catch(e){if(token!==rendering)return;await motion.commit(ticket,()=>{app.innerHTML=`<div class="page-error"><h2>暂时没有打开这一页</h2><p>${esc(e.message)}</p><button class="button primary" data-action="reload">重新加载</button> <a class="button" href="/" data-nav>返回试卷库</a></div>`},{scrollTop})}
}

function renderHome(){
 const last=lib.last_read,paper=last&&lib.papers.find(p=>p.id===last.paper_id),first=lib.papers[0],resume=paper||first;
 const collected=new Set(lib.memberships.map(m=>key(m.paper_id,m.number))).size,drafts=pendingDrafts();
 const count=lib.papers.reduce((sum,p)=>sum+p.question_count,0);
 if(subject==='math'){app.innerHTML=mathHomeHTML({lib,collected,drafts,resume,paper,last,filter:homeFilter,esc,questionURL});homeCards();const root=app.querySelector('.page'),panel=activity.mount(root,subject,'all');if(panel)root.append(panel);return}
 const entry=(index,kicker,title,copy,href,label)=>`<a class="daily-banner" data-nav href="${href}" aria-label="${label}"><span class="entry-index" aria-hidden="true">${index}</span><div><div class="eyebrow">${kicker}</div><h2>${title}</h2><p>${copy}</p></div><span class="entry-arrow" aria-hidden="true">↗</span></a>`;
 const entries=subject==='408'?entry('01','DAILY PROTOCOL / 每日一练','40 题，进入心流。','四科同步推进。选择自动保存，整组交卷后核对。','/daily-practice?subject=408','进入每日一练')+entry('02','MEMORY DRIVE / 考点抽奖机','给记忆，重新通电。','先回忆，再揭示。让每个考点都连接起来。','/knowledge-draw?subject=408','进入考点抽奖机'):'';
 app.innerHTML=`<div class="page home-page"><div class="studio-overline"><span>拾题 / PERSONAL LEARNING SPACE</span><span><i></i> ${subjectLabel()} · 就位</span></div><section class="hero"><div class="hero-copy"><div class="eyebrow">今天的进步，由你启动</div><h1>把不会的，<br><em>变成底气。</em></h1><p class="lead">从一道题开始，让思路变清晰，让下一次更有把握。</p><div class="stats"><div class="stat"><strong>${lib.papers.length}</strong><span>套${subject==='408'?'历年真题':'精选试卷'}</span></div><div class="stat"><strong>${count.toLocaleString()}</strong><span>道题目，等你突破</span></div><div class="stat"><strong>${collected}</strong><span>道已收藏</span></div></div></div><div class="hero-aside"><div class="home-signal" aria-hidden="true"><div class="signal-orbit orbit-a"></div><div class="signal-orbit orbit-b"></div><div class="signal-orbit orbit-c"></div><div class="signal-cross cross-a"></div><div class="signal-cross cross-b"></div><span class="signal-word">${subject==='408'?'408':'∫'}</span><small class="signal-coordinate">${subject==='408'?'DS / CO / OS / CN':'THINK / SOLVE / REPEAT'}</small><span class="signal-node"></span></div>${resume?`<div class="continue-card"><div><div class="eyebrow">${paper?'CONTINUE / 接上一次思路':'FIRST MOVE / 从这里开始'}</div><h3>${esc(resume.title)}</h3><p class="lead">${paper?'上次读到第 '+last.number+' 题':subjectLabel()+' · 第一套练习'}</p><a class="text-button" data-nav href="${questionURL(resume.id,paper?last.number:1)}">${paper?'继续阅读':'开始练习'} <span>↗</span></a></div></div>`:''}</div></section><div class="home-actions">${entries}${entry(subject==='408'?'03':'01','RECALL LOOP / 每日回顾','把难题，留在昨天。','每天 5 道收藏错题，复盘比重复更有用。','/daily-review','进入每日回顾')}</div>${drafts.length?`<div class="pending-banner">有 ${drafts.length} 道题的笔记草稿等待保存。<a class="text-button" data-nav href="${questionURL(drafts[0].ref[0],drafts[0].ref[1])}">打开草稿 →</a></div>`:''}<section class="library-section"><div class="section-head library-heading"><div><div class="eyebrow">THE ARCHIVE / 试卷库</div><h2><span class="heading-phrase">下一道突破，</span><span class="heading-phrase">从这里开始<span class="accent-period">.</span></span></h2><p>${subject==='408'?'历年真题，逐年拆解。':'挑一套，拿起笔，开始思考。'}</p></div><span class="archive-years">${Math.min(...lib.papers.map(p=>p.year))}<span>—</span>${Math.max(...lib.papers.map(p=>p.year))}</span></div><div class="toolbar"><div class="tabs" aria-label="难度筛选">${['全部',...new Set(lib.papers.map(p=>p.difficulty))].map(d=>`<button data-action="difficulty" data-value="${d}" class="${homeFilter.difficulty===d?'active':''}">${d}${d==='全部'?'试卷':''}</button>`).join('')}</div><div class="filters"><input id="paper-search" type="search" placeholder="搜索年份、老师或试卷名称" aria-label="搜索试卷" value="${esc(homeFilter.search)}"><select id="year-filter" aria-label="年份筛选">${['全部年份',...new Set(lib.papers.map(p=>p.year).sort((a,b)=>b-a))].map(y=>`<option ${String(y)===homeFilter.year?'selected':''}>${y}</option>`).join('')}</select></div></div><div class="library-index-head"><span id="result-count" class="small"></span><span>${subject==='408'?'按年份排列':'按建议做题顺序排列'} / SELECT YOUR NEXT MOVE</span></div><div id="paper-grid" class="paper-grid"></div></section></div>`;
 homeCards();const root=app.querySelector('.page'),panel=activity.mount(root,subject,'all');if(panel)root.append(panel);
}
function homeCards(){
 const ps=lib.papers.filter(p=>(homeFilter.difficulty==='全部'||p.difficulty===homeFilter.difficulty)&&(homeFilter.year==='全部年份'||String(p.year)===homeFilter.year)&&p.title.toLowerCase().includes(homeFilter.search.trim().toLowerCase()));
 $('#result-count').textContent=`共 ${ps.length} 套试卷`;
 $('#paper-grid').innerHTML=ps.length?ps.map((p,index)=>{
 const states=lib.states.filter(s=>s.paper_id===p.id),notes=states.filter(s=>s.has_note).length,collect=new Set(lib.memberships.filter(m=>m.paper_id===p.id).map(m=>m.number)).size;
 return `<a href="${questionURL(p.id,lib.last_read?.paper_id===p.id?lib.last_read.number:1)}" data-nav class="paper-card"><span class="paper-index">${String(index+1).padStart(2,'0')}</span><div class="paper-name"><h3>${esc(p.title)}</h3><div class="card-meta"><span>${p.question_count} 道题</span><span> / </span><span>${p.subject==='408'?'选择 · 综合':'选择 · 填空 · 解答'}</span></div></div><span class="paper-progress">${notes||collect?`${notes} 条笔记 · ${collect} 道收藏`:'等待你的第一笔'}</span><span class="paper-difficulty ${p.difficulty==='较难'?'is-hard':''}"><i></i>${esc(p.difficulty)}</span><span class="arrow" aria-hidden="true">↗</span></a>`;
 }).join(''):empty('没有找到这套试卷','试试其他关键词，或调整难度和年份。');
}
function numberHTML(p,n,q){const s=lib.stateMap[key(p,n)]||{};return `<a href="${questionURL(p,n,q.folder)}" data-nav data-number="${n}" class="number ${n===q.number?'active':''} ${s.status==='mastered'?'mastered':s.status==='review'?'review':''}" aria-label="第 ${n} 题${s.has_note?'，有笔记':''}${hasMembership(p,n)?'，已收藏':''}，${labels[s.status||'unmarked']}">${n}${s.has_note?'<i class="dot"></i>':''}${hasMembership(p,n)?'<span class="collect">◆</span>':''}</a>`}
function updateNumberMarkers(){if(!editor)return;const q={number:editor.n,folder:editor.folder};$$('.number-grid').forEach(el=>{el.innerHTML=el.dataset.numbers.split(',').map(n=>numberHTML(editor.pid,Number(n),q)).join('')})}
function folderOptions(q){return lib.folders.length?lib.folders.map(f=>`<label class="folder-check"><input type="checkbox" data-folder="${esc(f.id)}" ${q.folder_ids.includes(f.id)?'checked':''}><span>${esc(f.name)}</span></label>`).join(''):'<p class="tip">建一个文件夹，收好值得再做的题。</p>'}
function renderReader(p,q){
 const folder=new URLSearchParams(location.search).get('folder')||'';q.folder=folder;
 const draft=recoverDraft(p.id,q.number);const conflict=draft&&draft.note!==q.note&&draft.revision!==q.revision;
 editor={pid:p.id,n:q.number,value:draft?.note??q.note,saved:q.note,revision:conflict?draft.revision:q.revision,folder,timer:null,flight:null};
 const groups=[];
 for(const item of p.questions){const last=groups.at(-1);if(last&&last[0]===item.type)last[2]=item.number;else groups.push([item.type,item.number,item.number])}
 app.innerHTML=`<div class="page reader-page"><div class="breadcrumb"><a href="${folder?'/mistakes/'+encodeURIComponent(folder):'/'}" data-nav>← ${folder?'返回错题本':'返回试卷库'}</a><span>/</span><span>第 ${q.number} 题</span></div><div class="reader-heading"><div><h1>${esc(p.title)}</h1><span class="small">${p.difficulty} · ${subjectLabel()} · 共 ${p.question_count} 道题 · ${p.source_kind==='exercise_book'?'Relax 原书章节':p.subject==='408'?'历年统考真题':'推荐顺序 '+String(p.order).padStart(3,'0')}</span></div><a class="button subtle" href="/api/papers/${p.id}/pdf${p.source_kind==='exercise_book'?'#page='+q.segments[0].page:''}" target="_blank" rel="noopener">${p.source_kind==='exercise_book'?'查看原书本页':'查看完整原卷'} ↗</a></div><div class="reader-layout"><aside class="panel question-nav"><div class="panel-label">题目目录 <span class="small">${q.number} / ${p.question_count}</span></div>${groups.map(([label,a,b])=>{const ns=Array.from({length:b-a+1},(_,i)=>a+i);return `<div class="group-label">${label}</div><div class="number-grid" data-numbers="${ns.join(',')}">${ns.map(n=>numberHTML(p.id,n,q)).join('')}</div>`}).join('')}<div class="legend">● 已写笔记　◆ 已加入错题夹<br><span class="review-legend">红色：未掌握</span>　<span class="mastered-legend">绿色：已掌握</span></div></aside><section class="panel question-body"><div class="question-bar"><h2>第 ${q.number} 题 <span class="badge">${q.type}</span></h2><button class="text-button" data-action="zoom">＋ 放大题目</button></div>${q.warning?`<div class="warning"><strong>待核对</strong> · ${esc(q.warning)}</div>`:''}<div class="image-scroll"><img class="question-image" src="${q.image}" alt="${esc(p.title)} 第 ${q.number} 题，${q.type}" width="${q.width}" height="${q.height}"></div><div class="question-bottom"><button class="button" data-action="previous" ${q.number===1?'disabled':''}>← 上一题</button><span class="small">${q.number} / ${p.question_count}</span><button class="button primary" data-action="next" ${q.number===p.question_count?'disabled':''}>下一题 →</button></div></section><aside class="panel note-panel"><div class="panel-label">这道题的笔记 <span class="small">自动保存</span></div>${draft&&draft.note!==q.note?`<div id="draft-banner" class="pending-banner">${conflict?'检测到其他页面更新，已保留你的草稿。请复制草稿后重新加载核对。':'已恢复上次未保存的草稿。'}${conflict?'<button class="text-button" data-action="copy-draft">复制草稿</button><button class="text-button" data-action="load-saved">加载已存笔记</button>':''}</div>`:''}${noteEditorHTML(editor.value,esc)}<div class="save-row" id="save-row"><span id="save-text">${draft&&draft.note!==q.note?'草稿等待保存':'已保存到本机'}</span><button class="text-button" id="retry-save" data-action="retry-save" hidden>重试</button></div><div class="divider"></div><label class="field-label">复习状态</label><div class="status-pills">${Object.entries(labels).map(([v,label])=>`<button data-action="status" data-value="${v}" class="${q.status===v?'active':''}">${label}</button>`).join('')}</div><div class="divider"></div><div class="panel-label">加入错题夹 <span class="small">可多选</span></div><div class="folder-options">${folderOptions(q)}</div><button class="folder-new" data-action="new-folder">＋ 新建错题夹</button><p class="tip">同一道题在不同文件夹中，共用这份笔记与复习状态。</p></aside></div></div>`;
 editor.noteUI=mountNoteEditor({root:$('#note-editor'),pid:p.id,number:q.number,toast,flush});
 if(p.subject==='math')mountAnswer($('.question-bottom'),p.id,q.number);
 if(p.source_kind==='exercise_book')$('.question-bottom').insertAdjacentHTML('beforebegin','<p class="practice-no-answer">十月勘误版答案已导入 · 从每日一练进入，完成整组后解锁判分与解析。</p>');
 const img=$('.question-image');img.addEventListener('error',()=>{img.parentElement.innerHTML='<p class="image-error">题图加载失败，请重新加载；也可以先查看完整原卷。</p>'});
 if(draft&&draft.note!==q.note&&!conflict)editor.timer=setTimeout(()=>saveEditor(),800);
 if(conflict)saveStatus(editor,'其他页面已有更新，请核对草稿',true);
}
function renderMistakes(){
 const fid=decodeURIComponent(location.pathname.split('/')[2]||'all');const folder=lib.folders.find(f=>f.id===fid);
 if(fid!=='all'&&!folder){app.innerHTML=empty('这个错题夹不存在','它可能已被删除，请从上方“错题本”重新进入。');return}
 const members=lib.memberships.filter(m=>fid==='all'||m.folder_id===fid);
 let refs=[...new Map(members.map(m=>[key(m.paper_id,m.number),m])).values()];
 const total=refs.length,mastered=refs.filter(m=>lib.stateMap[key(m.paper_id,m.number)]?.status==='mastered').length;
 refs=refs.filter(m=>reviewFilter==='all'||(lib.stateMap[key(m.paper_id,m.number)]?.status||'unmarked')===reviewFilter).sort((a,b)=>lib.paperMap[a.paper_id].order-lib.paperMap[b.paper_id].order||a.number-b.number);
 const allCount=new Set(lib.memberships.map(m=>key(m.paper_id,m.number))).size;
 app.innerHTML=`<div class="page mistakes-page"><div class="studio-overline"><span>${subject==='math'?'拾遗集 / 错题重读':'ERROR ARCHIVE / 错题档案'}</span><span>每一次卡住，都有迹可循</span></div><div class="section-head mistakes-heading"><div><div class="eyebrow">不放过问题，也不困在问题里</div><h1>${subject==='math'?'旧题重拾，<em>思路新生。</em>':'错题，<em>是突破口。</em>'}</h1><p class="lead">把反复卡住的地方，变成最扎实的部分。</p></div><div class="mistake-total"><strong>${total}</strong><span>道题 · ${mastered} 道已掌握</span></div></div><div class="mistake-layout"><aside class="panel folders-panel"><div class="panel-label">${subjectLabel()}错题夹 <span class="small">${lib.folders.length}</span></div><a class="folder-link ${fid==='all'?'active':''}" href="/mistakes" data-nav><span>▤ 全部错题</span><small>${allCount}</small></a>${lib.folders.map(f=>`<a class="folder-link ${fid===f.id?'active':''}" href="/mistakes/${encodeURIComponent(f.id)}" data-nav><span>▱ ${esc(f.name)}</span><small>${f.count}</small></a>`).join('')}<button class="folder-new" data-action="new-folder">＋ 新建错题夹</button></aside><section><div class="section-head"><div><h2>${esc(folder?.name||(subjectLabel()+' · 全部错题'))}</h2><p>共 ${total} 道题 · ${mastered} 道已掌握</p></div>${folder?`<div class="folder-title-actions"><button class="text-button" data-action="rename-folder" data-id="${esc(fid)}">重命名</button><button class="text-button" data-action="delete-folder" data-id="${esc(fid)}">删除</button></div>`:''}</div><div class="toolbar"><div class="tabs" aria-label="复习状态筛选">${[['all','全部'],['review','未掌握'],['mastered','已掌握'],['unmarked','未标记']].map(([v,l])=>`<button data-action="review-filter" data-value="${v}" class="${reviewFilter===v?'active':''}">${l}</button>`).join('')}</div><span class="small">${refs.length} 道题</span></div><div class="question-grid">${refs.length?refs.map((m,index)=>{const p=lib.paperMap[m.paper_id],s=lib.stateMap[key(m.paper_id,m.number)]||{};return `<a data-nav href="${questionURL(p.id,m.number,fid)}" class="mistake-card"><span class="mistake-index">${String(index+1).padStart(2,'0')}</span><div class="mistake-copy"><div class="eyebrow">第 ${m.number} 题 / ${labels[s.status||'unmarked']}</div><h3>${esc(p.title)}</h3><p class="small">${s.has_note?'● 已留下复盘笔记':'从这次复盘，写下思路'}</p></div><div class="preview"><img loading="lazy" src="/assets/questions/${p.id}/${m.number}.png" alt="第 ${m.number} 题预览"></div><span class="mistake-arrow" aria-hidden="true">↗</span></a>`}).join(''):empty(total?'这个状态下还没有题目':'留一个位置，给值得再做的题',total?'切换其他复习状态试试。':'打开试卷，勾选题目右侧的错题夹，就能收在这里。')}</div></section></div></div>`;
 const root=app.querySelector('.page'),panel=activity.mount(root,subject,'mistakes');if(panel)root.append(panel);
}
function openModal(title,content){modal.innerHTML=`<div class="modal-head"><h2 id="modal-title">${esc(title)}</h2><button class="close" data-action="close-modal" aria-label="关闭弹窗">×</button></div>${content}`;if(!modal.open)modal.showModal()}
function folderModal(id){const folder=id?lib.folders.find(f=>f.id===id):null;openModal(folder?'重命名错题夹':'新建错题夹',`<p class="modal-copy">按知识点或练习目标整理，例如「${subject==='408'?'数据结构再练一遍':'积分再练一遍'}」。</p><form id="folder-form"><input class="modal-field" name="name" aria-label="错题夹名称" placeholder="给错题夹起个名字" maxlength="60" required value="${esc(folder?.name||'')}"><div class="modal-error" id="form-error" role="alert"></div><div class="modal-actions"><button type="button" class="button" data-action="close-modal">取消</button><button type="submit" class="button primary">${folder?'保存名称':'创建文件夹'}</button></div></form>`);$('#folder-form').addEventListener('submit',async e=>{e.preventDefault();const b=$('button[type=submit]',e.target);b.disabled=true;try{await api(folder?'/api/folders/'+folder.id:'/api/folders',folder?'PATCH':'POST',{name:new FormData(e.target).get('name'),...(folder?{}:{subject})});modal.close();await refreshLibrary();if(editor){const q=await api(`/api/questions/${editor.pid}/${editor.n}`);$('.folder-options').innerHTML=folderOptions(q)}else if(location.pathname.startsWith('/mistakes'))renderMistakes();toast(folder?'名称已更新':'错题夹已创建')}catch(err){$('#form-error').textContent=err.message}finally{b.disabled=false}});$('input',modal).focus()}
async function exportBackup(){if(!await flush())return;const data=await api('/api/backup','GET',undefined,{rawResponse:true});const url=URL.createObjectURL(new Blob([data],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=`拾题备份-${new Date().toLocaleDateString('sv-SE')}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('备份已导出，原卷请另行保留')}
async function importBackup(file){if(!file)return;if(file.size>100*1024*1024)throw new Error('备份文件不能超过 100 MB');const body=await file.text();try{JSON.parse(body)}catch{throw new Error('这不是有效的 JSON 备份文件')};const preview=await api('/api/backup/preview','POST',body,{rawBody:true});openModal('恢复备份',`<p class="modal-copy">相同题目的笔记、状态和收藏关系将以备份为准。其他题目的记录保留；已有文件夹按标识或名称合并。</p><div class="summary-box">${preview.questions} 道题目记录 · ${preview.folders} 个错题夹<br>${preview.images||0} 张笔记图片 · ${preview.memberships} 条收藏关系 · ${preview.overwrites} 道题将被覆盖<br>${preview.review_days||0} 天每日回顾记录（同科目、同日期覆盖）<br>${preview.activity_records||0} 条学习打卡记录（合并保留）<br>${preview.practice_rounds||0} 轮每日一练 · ${preview.practice_answers||0} 条作答（同轮次完整覆盖）<br>${preview.knowledge_cards||0} 张考点记录 · ${preview.knowledge_reviews||0} 条考点评分 · ${preview.knowledge_sessions||0} 组连续复习（保留完整进度）</div><p class="tip">恢复前会自动保存当前数据到 app/data/backups。</p><div class="modal-error" id="restore-error" role="alert"></div><div class="modal-actions"><button class="button" data-action="close-modal">取消</button><button class="button primary" id="restore-confirm">确认恢复</button></div>`);$('#restore-confirm').addEventListener('click',async e=>{e.target.disabled=true;try{if(!await flush())return;await api('/api/backup/restore','POST',body,{rawBody:true});modal.close();await render();toast('备份已恢复，旧数据已自动备份')}catch(err){$('#restore-error').textContent=err.message}finally{e.target.disabled=false}})}
const daily=createDailyReview({api:scopedAPI,subjectLabel,esc,app,flush,refreshLibrary,getLibrary:()=>lib,getEditor:()=>editor,toast,navigate});
const activity=createActivity({api,esc});
const knowledge=createKnowledge({api,app,esc,navigate,toast,onOverview:root=>{const panel=activity.mount(root,'408','knowledge');if(panel)root.append(panel)}});
const practice=createDailyPractice({api,app,esc,navigate,flush,refreshLibrary,getLibrary:()=>lib,getEditor:()=>editor,toast});
const actions={
 'date-ribbon':toggleDateRibbon,
 'subject':async b=>{if(subject===b.dataset.value||!await flush())return;setSubject(b.dataset.value);homeFilter={difficulty:'全部',year:'全部年份',search:''};reviewFilter='all';const path=location.pathname==='/daily-review'?'/daily-review':location.pathname.startsWith('/mistakes')?'/mistakes':'/';await navigate(path+'?subject='+subject)},
 'daily-answer':b=>daily.answer(b),
 'practice-start':b=>practice.start(b), 'practice-next-round':b=>practice.start(b,true), 'practice-answer':(b,event)=>practice.answer(b,event), 'practice-submit':b=>practice.submit(b),
 'difficulty':b=>{homeFilter.difficulty=b.dataset.value;$$('[data-action=difficulty]').forEach(v=>v.classList.toggle('active',v===b));homeCards()},
 'review-filter':b=>{reviewFilter=b.dataset.value;renderMistakes()},
 'new-folder':()=>folderModal(), 'rename-folder':b=>folderModal(b.dataset.id),
 'close-modal':()=>modal.close(), 'reload':async()=>{if(await flush())await render()},
 'zoom':b=>{const zoom=$('.image-scroll').classList.toggle('zoomed');b.textContent=zoom?'－ 适应宽度':'＋ 放大题目'},
 'previous':()=>{if(!practice.move(-1)&&!daily.move(-1))return navigate(questionURL(editor.pid,editor.n-1,editor.folder))},
 'next':()=>{if(!practice.move(1)&&!daily.move(1))return navigate(questionURL(editor.pid,editor.n+1,editor.folder))},
 'retry-save':()=>saveEditor(),
 'copy-draft':async()=>{try{await navigator.clipboard.writeText(editor.value);toast('草稿已复制')}catch{toast('无法自动复制，请选中笔记文字手动复制')}},
 'load-saved':async()=>{const e=editor;openModal('加载已存笔记',`<p class="modal-copy">请先复制你想保留的草稿。继续会丢弃当前草稿，并加载数据库中最新保存的笔记。</p><div class="modal-actions"><button class="button" data-action="close-modal">取消</button><button class="button primary" id="discard-confirm">丢弃草稿并加载</button></div>`);$('#discard-confirm').onclick=async()=>{draftRemove(e);e.value=e.saved;modal.close();await render()}},
 'status':async b=>{const e=editor;b.disabled=true;try{const s=await api(`/api/questions/${e.pid}/${e.n}`,'PATCH',{status:b.dataset.value,activity_area:e.practice?'daily_practice':e.daily?'daily_review':e.folder?'mistakes':'library'});updateState(s);if(editor===e){$$('.status-pills button').forEach(x=>x.classList.toggle('active',x.dataset.value===s.status));updateNumberMarkers()}}finally{b.disabled=false}},
 'delete-folder':b=>{const f=lib.folders.find(f=>f.id===b.dataset.id);openModal('删除错题夹',`<p class="modal-copy">删除「${esc(f.name)}」会取消其中 ${f.count} 道题的归类。题目、笔记、复习状态和其他文件夹中的收藏都会保留。</p><div class="modal-error" id="delete-error" role="alert"></div><div class="modal-actions"><button class="button" data-action="close-modal">取消</button><button class="button danger" id="delete-confirm">删除文件夹</button></div>`);$('#delete-confirm').onclick=async e=>{e.target.disabled=true;try{await api('/api/folders/'+f.id,'DELETE');modal.close();await navigate('/mistakes');toast('文件夹已删除，笔记仍保留')}catch(err){$('#delete-error').textContent=err.message;e.target.disabled=false}}},
 'backup':()=>openModal('备份与恢复',`<p class="modal-copy">笔记和错题夹保存在这台电脑。定期导出一份备份，让积累更安心。</p><button class="backup-choice" data-action="export"><strong>↥ 导出学习记录</strong><span>图文笔记、错题夹、复习状态、学习打卡、每日回顾、每日一练完整排期与作答、考点记忆记录、连续复习队列与阅读位置 · JSON</span></button><button class="backup-choice" data-action="import"><strong>↧ 从备份恢复</strong><span>先预览内容，确认后恢复，自动留存旧数据</span></button><p class="tip">备份包含已上传的笔记图片，外链图片请先下载并上传。备份不包含原始试卷。请保留「独立试卷」「408试卷」和 app/data 中的题库、题图与题册副本。</p>`),
 'export':exportBackup, 'import':async()=>{if(await flush())$('#backup-file').click()}
};
document.addEventListener('click',async event=>{const link=event.target.closest('a[data-nav]');if(link&&!event.ctrlKey&&!event.metaKey&&!event.shiftKey&&!event.altKey&&event.button===0){event.preventDefault();await navigate(link.getAttribute('href'));return}const button=event.target.closest('[data-action]');if(!button||button.disabled)return;try{await actions[button.dataset.action]?.(button,event)}catch(e){toast(e.message)}});
document.addEventListener('input',event=>{if(event.target.id==='paper-search'){homeFilter.search=event.target.value;homeCards()}if(event.target.id==='note'&&editor){const e=editor;e.value=event.target.value;draftWrite(e);saveStatus(e,e.draftUnavailable?'尚未保存，请保持页面打开':'尚未保存');clearTimeout(e.timer);e.timer=setTimeout(()=>saveEditor(e),600)}});
document.addEventListener('change',async event=>{try{if(event.target.id==='year-filter'){homeFilter.year=event.target.value;homeCards()}if(event.target.dataset.folder&&editor){const el=event.target,e=editor;el.disabled=true;try{const s=await api('/api/folders/'+el.dataset.folder+'/membership','PUT',{paper_id:e.pid,number:e.n,selected:el.checked});await refreshLibrary();if(editor===e){$$('.status-pills button').forEach(x=>x.classList.toggle('active',x.dataset.value===s.status));updateNumberMarkers()}}catch(err){el.checked=!el.checked;throw err}finally{el.disabled=false}}if(event.target.id==='backup-file'){await importBackup(event.target.files[0]);event.target.value=''}}catch(e){toast(e.message);if(event.target.id==='backup-file')event.target.value=''}});
render();
