import {noteEditorHTML, mountNoteEditor} from './notes.js?v=3';
import {mountAnswer} from './answers.js?v=2';
import {createDailyReview} from './daily-review.js?v=5';
import {createKnowledge} from './knowledge.js?v=3';
import {createDailyPractice} from './daily-practice.js?v=2';
import {createActivity} from './activity.js?v=1';
import {createMotion,transitionBetween} from './motion.js?v=1';
import {toggleDateRibbon} from './date-ribbon.js?v=1';
const $ = (s, root=document) => root.querySelector(s);
const $$ = (s, root=document) => [...root.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const labels = {unmarked:'未标记',review:'未掌握',mastered:'已掌握'};
const app=$('#app'), modal=$('#modal');
const motion=createMotion(app);
$('#workspace-date').textContent=new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'long',day:'numeric',weekday:'long'}).format(new Date());
let lib, editor=null, rendering=0, currentURL=location.pathname+location.search;
let subject=new URLSearchParams(location.search).get('subject')==='408'?'408':(localStorage.getItem('cuoti-subject')==='408'?'408':'math');
const subjectLabel=()=>subject==='408'?'408 计算机':'数学二';
const scopedAPI=(url,method,body)=>api(url+(url.includes('?')?'&':'?')+'subject='+subject,method,body);
function setSubject(value){if(subject!==value){homeFilter={difficulty:'全部',year:'全部年份',search:''};reviewFilter='all'}subject=value;localStorage.setItem('cuoti-subject',subject);document.body.dataset.subject=subject;document.querySelectorAll('[data-action=subject]').forEach(b=>{b.classList.toggle('active',b.dataset.value===subject);b.setAttribute('aria-pressed',String(b.dataset.value===subject))});}
let homeFilter={difficulty:'全部',year:'全部年份',search:''}, reviewFilter='all', toastTimer;
const key=(p,n)=>`${p}:${n}`;
const draftKey=(p,n)=>`cuoti-draft:${key(p,n)}`;
const questionURL=(p,n,folder='')=>`/papers/${p}/questions/${n}${folder?'?folder='+encodeURIComponent(folder):''}`;
const badge=d=>`<span class="badge ${d==='适中'?'medium':d==='较难'?'hard':''}">${d}</span>`;
const empty=(title,body)=>`<div class="empty"><strong>${esc(title)}</strong>${esc(body)}</div>`;
function toast(message){$('#toast').textContent=message;$('#toast').classList.add('visible');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').classList.remove('visible'),4500)}
async function api(url,method='GET',body){
 const controller=new AbortController(), timer=setTimeout(()=>controller.abort(),12000);
 try{
  const r=await fetch(url,{method,headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),signal:controller.signal});
  let data;try{data=await r.json()}catch{throw new Error('云端服务返回异常，请稍后重试')}
  if(!r.ok){const e=new Error(typeof data.detail==='string'?data.detail:'数据格式不正确，请检查输入或备份文件');e.status=r.status;throw e}
  return data;
 }catch(e){if(e.name==='AbortError')throw new Error('保存或加载超时，请检查网络并重试');if(e instanceof TypeError)throw new Error('暂时无法连接云端，请检查网络');throw e}finally{clearTimeout(timer)}
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
 if(e.value===e.saved){saveStatus(e,'已同步到云端');return true}
 const text=e.value;saveStatus(e,'正在保存…');
 e.flight=(async()=>{
  try{const s=await api(`/api/questions/${e.pid}/${e.n}`,'PATCH',{note:text,revision:e.revision});
   e.saved=text;e.revision=s.revision;updateState(s);
   if(e.value===e.saved){draftRemove(e);saveStatus(e,'已同步到云端');if(editor===e){$('#draft-banner')?.remove();updateNumberMarkers()}}
   else draftWrite(e);
   return true;
  }catch(err){draftWrite(e);saveStatus(e,err.message,true);return false}
  finally{e.flight=null}
 })();
 const ok=await e.flight;if(ok&&e.value!==e.saved)return saveEditor(e);return ok;
}
async function flush(){const e=editor;await e?.noteUI?.wait();const ok=await saveEditor(e);if(!ok)toast('笔记尚未保存，已保留草稿。请重试保存后再切换页面。');return ok}
async function navigate(url,replace=false){if(!await flush())return;const from=currentURL,target=new URL(url,location.origin);if(!target.pathname.startsWith('/papers/'))target.searchParams.set('subject',subject);history[replace?'replaceState':'pushState']({},'',target.pathname+target.search);currentURL=location.pathname+location.search;await render({from,scrollTop:true})}
window.addEventListener('popstate',async()=>{const target=location.pathname+location.search;if(!await flush()){history.pushState({},'',currentURL);return}const from=currentURL;currentURL=target;await render({from})});
window.addEventListener('beforeunload',e=>{if(editor&&(editor.value!==editor.saved||editor.noteUI?.busy)){draftWrite(editor);e.preventDefault();e.returnValue=''}});
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
  else if(isPractice){const data=await practice.load();draw=()=>{practice.renderOverview(data);activity.mount(app.querySelector('.page'),'408','daily_practice')}}
  else if(isKnowledge){const data=await knowledge.load();draw=()=>knowledge.render(data)}
  else if(route.pathname==='/daily-review'){const data=await daily.load();draw=()=>{daily.renderOverview(data);activity.mount(app.querySelector('.page'),subject,'daily_review')}}
  else if(route.pathname.startsWith('/mistakes'))draw=renderMistakes;
  else draw=renderHome;
  if(token!==rendering)return;
  await motion.commit(ticket,()=>{
   $('#nav-practice').hidden=subject!=='408';$('#nav-practice').classList.toggle('active',isPractice);
   $('#nav-knowledge').classList.toggle('active',isKnowledge);
   $('#nav-library').classList.toggle('active',!isMistake&&!isDaily&&!isKnowledge&&!isPractice);$('#nav-mistakes').classList.toggle('active',isMistake&&!isDaily);$('#nav-daily').classList.toggle('active',isDaily);
   document.querySelectorAll('.topbar nav a').forEach(link=>{if(link.classList.contains('active'))link.setAttribute('aria-current','page');else link.removeAttribute('aria-current')});
   return draw();
  },{scrollTop});
 }catch(e){if(token!==rendering)return;await motion.commit(ticket,()=>{app.innerHTML=`<div class="page-error"><h2>暂时没有打开这一页</h2><p>${esc(e.message)}</p><button class="button primary" data-action="reload">重新加载</button> <a class="button" href="/" data-nav>返回试卷库</a></div>`},{scrollTop})}
}

function renderHome(){
 const last=lib.last_read,paper=last&&lib.papers.find(p=>p.id===last.paper_id),first=lib.papers[0];
 const collected=new Set(lib.memberships.map(m=>key(m.paper_id,m.number))).size,drafts=pendingDrafts();
 const practiceCard=subject==='408'?`<section class="daily-banner practice-banner"><div><div class="eyebrow">01 · 每日练习</div><h2>每天 40 道，一点点向前。</h2><p>四科各 10 道，按章节比例安排。<br>整轮不重复，漏练也能补做。</p></div><a class="button" data-nav href="/daily-practice?subject=408">进入每日一练 ↗</a></section><section class="daily-banner"><div><div class="eyebrow">02 · 主动回忆</div><h2>给知识，一次回响。</h2><p>四科考点，先回忆，再核对。<br>让容易忘的内容，按时回来。</p></div><a class="button" data-nav href="/knowledge-draw?subject=408">背一组记忆卡 ↗</a></section>`:'';
 app.innerHTML=`<div class="page home-page"><section class="hero"><div class="hero-copy"><div class="eyebrow">${subject==='408'?'408 计算机':'数学二'} / 我的自习室</div><h1>今天，也向前一点。</h1><p class="lead">从一道题开始，把不会的，慢慢变成会的。</p><div class="stats"><div class="stat"><strong>${lib.papers.length}</strong><span>套${subject==='408'?'历年真题':'精选试卷'}</span></div><div class="stat"><strong>${lib.papers.reduce((sum,p)=>sum+p.question_count,0).toLocaleString()}</strong><span>道题目</span></div><div class="stat"><strong>${collected}</strong><span>道已收藏</span></div></div></div><div class="continue-card"><div><div class="eyebrow">${paper?'接着上次的思路':'从这里开始'}</div><h3>${esc((paper||first).title)}</h3><p class="lead">${paper?'上次读到第 '+last.number+' 题':subjectLabel()+' · 第一套练习'}</p><a class="button primary" data-nav href="${questionURL((paper||first).id,paper?last.number:1)}">${paper?'继续阅读':'开始练习'} ↗</a></div></div></section><div class="home-actions">${practiceCard}<section class="daily-banner"><div><div class="eyebrow">${subject==='408'?'03':'每天'} · 温故知新</div><h2>再遇见，曾经的难题。</h2><p>从错题夹里选出今天的 5 道题。<br>少做过的、常错的，优先回来。</p></div><a class="button" data-nav href="/daily-review">进入每日回顾 ↗</a></section></div>${drafts.length?`<div class="pending-banner">有 ${drafts.length} 道题的笔记草稿等待保存。<a class="text-button" data-nav href="${questionURL(drafts[0].ref[0],drafts[0].ref[1])}">打开草稿 →</a></div>`:''}<section><div class="section-head"><div><h2>${subjectLabel()} · 试卷库</h2><p>${subject==='408'?'按年份浏览，从一道真题开始。':'按推荐顺序练习，也可以挑选今天想做的一套。'}</p></div><span class="small">${Math.min(...lib.papers.map(p=>p.year))} — ${Math.max(...lib.papers.map(p=>p.year))}</span></div><div class="toolbar"><div class="tabs" aria-label="难度筛选">${['全部',...new Set(lib.papers.map(p=>p.difficulty))].map(d=>`<button data-action="difficulty" data-value="${d}" class="${homeFilter.difficulty===d?'active':''}">${d}${d==='全部'?'试卷':''}</button>`).join('')}</div><div class="filters"><input id="paper-search" type="search" placeholder="搜索年份、老师或试卷名称" aria-label="搜索试卷" value="${esc(homeFilter.search)}"><select id="year-filter" aria-label="年份筛选">${['全部年份',...new Set(lib.papers.map(p=>p.year).sort((a,b)=>b-a))].map(y=>`<option ${String(y)===homeFilter.year?'selected':''}>${y}</option>`).join('')}</select></div></div><div class="section-head"><span id="result-count" class="small"></span><span class="small">${subject==='408'?'按真题年份排列':'按建议做题顺序排列'}</span></div><div id="paper-grid" class="paper-grid"></div></section></div>`;
 homeCards();activity.mount(app.querySelector('.page'),subject,'all');
}
function homeCards(){
 const ps=lib.papers.filter(p=>(homeFilter.difficulty==='全部'||p.difficulty===homeFilter.difficulty)&&(homeFilter.year==='全部年份'||String(p.year)===homeFilter.year)&&p.title.toLowerCase().includes(homeFilter.search.trim().toLowerCase()));
 $('#result-count').textContent=`共 ${ps.length} 套试卷`;
 $('#paper-grid').innerHTML=ps.length?ps.map(p=>{
 const states=lib.states.filter(s=>s.paper_id===p.id), notes=states.filter(s=>s.has_note).length,collect=new Set(lib.memberships.filter(m=>m.paper_id===p.id).map(m=>m.number)).size;
 return `<a href="${questionURL(p.id,lib.last_read?.paper_id===p.id?lib.last_read.number:1)}" data-nav class="paper-card"><div class="card-top"><span class="paper-num">NO. ${String(p.order).padStart(3,'0')}</span>${badge(p.difficulty)}</div><h3>${esc(p.title)}</h3><div class="card-meta"><span>${subjectLabel()}</span><span>·</span><span>${p.question_count} 道题</span><span>·</span><span>${p.subject==='408'?'选择 / 综合':'选择 / 填空 / 解答'}</span></div><div class="card-foot"><span>${notes||collect?`${notes} 条笔记 · ${collect} 道已收藏`:'还未留下笔记，从第一题开始吧'}</span><span class="arrow">↗</span></div></a>`
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
 app.innerHTML=`<div class="page reader-page"><div class="breadcrumb"><a href="${folder?'/mistakes/'+encodeURIComponent(folder):'/'}" data-nav>← ${folder?'返回错题本':'返回试卷库'}</a><span>/</span><span>第 ${q.number} 题</span></div><div class="reader-heading"><div><h1>${esc(p.title)}</h1><span class="small">${p.difficulty} · ${subjectLabel()} · 共 ${p.question_count} 道题 · ${p.source_kind==='exercise_book'?'Relax 原书章节':p.subject==='408'?'历年统考真题':'推荐顺序 '+String(p.order).padStart(3,'0')}</span></div><a class="button subtle" href="/api/papers/${p.id}/pdf${p.source_kind==='exercise_book'?'#page='+q.segments[0].page:''}" target="_blank" rel="noopener">${p.source_kind==='exercise_book'?'查看原书本页':'查看完整原卷'} ↗</a></div><div class="reader-layout"><aside class="panel question-nav"><div class="panel-label">题目目录 <span class="small">${q.number} / ${p.question_count}</span></div>${groups.map(([label,a,b])=>{const ns=Array.from({length:b-a+1},(_,i)=>a+i);return `<div class="group-label">${label}</div><div class="number-grid" data-numbers="${ns.join(',')}">${ns.map(n=>numberHTML(p.id,n,q)).join('')}</div>`}).join('')}<div class="legend">● 已写笔记　◆ 已加入错题夹<br><span class="review-legend">红色：未掌握</span>　<span class="mastered-legend">绿色：已掌握</span></div></aside><section class="panel question-body"><div class="question-bar"><h2>第 ${q.number} 题 <span class="badge">${q.type}</span></h2><button class="text-button" data-action="zoom">＋ 放大题目</button></div>${q.warning?`<div class="warning"><strong>待核对</strong> · ${esc(q.warning)}</div>`:''}<div class="image-scroll"><img class="question-image" src="${q.image}" alt="${esc(p.title)} 第 ${q.number} 题，${q.type}" width="${q.width}" height="${q.height}"></div><div class="question-bottom"><button class="button" data-action="previous" ${q.number===1?'disabled':''}>← 上一题</button><span class="small">${q.number} / ${p.question_count}</span><button class="button primary" data-action="next" ${q.number===p.question_count?'disabled':''}>下一题 →</button></div></section><aside class="panel note-panel"><div class="panel-label">这道题的笔记 <span class="small">自动保存</span></div>${draft&&draft.note!==q.note?`<div id="draft-banner" class="pending-banner">${conflict?'检测到其他页面更新，已保留你的草稿。请复制草稿后重新加载核对。':'已恢复上次未保存的草稿。'}${conflict?'<button class="text-button" data-action="copy-draft">复制草稿</button><button class="text-button" data-action="load-saved">加载已存笔记</button>':''}</div>`:''}${noteEditorHTML(editor.value,esc)}<div class="save-row" id="save-row"><span id="save-text">${draft&&draft.note!==q.note?'草稿等待保存':'已同步到云端'}</span><button class="text-button" id="retry-save" data-action="retry-save" hidden>重试</button></div><div class="divider"></div><label class="field-label">复习状态</label><div class="status-pills">${Object.entries(labels).map(([v,label])=>`<button data-action="status" data-value="${v}" class="${q.status===v?'active':''}">${label}</button>`).join('')}</div><div class="divider"></div><div class="panel-label">加入错题夹 <span class="small">可多选</span></div><div class="folder-options">${folderOptions(q)}</div><button class="folder-new" data-action="new-folder">＋ 新建错题夹</button><p class="tip">同一道题在不同文件夹中，共用这份笔记与复习状态。</p></aside></div></div>`;
 editor.noteUI=mountNoteEditor({root:$('#note-editor'),pid:p.id,number:q.number,toast,flush});
 if(p.subject==='math')mountAnswer($('.question-bottom'),p.id,q.number);
 if(p.source_kind==='exercise_book')$('.question-bottom').insertAdjacentHTML('beforebegin','<p class="practice-no-answer">暂未导入答案 · 请自行核对后标记对错。笔记和收藏会保存在本机。</p>');
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
 app.innerHTML=`<div class="page"><div class="section-head"><div><div class="eyebrow">LEARN FROM EVERY MISTAKE</div><h1>把错题，变成底气。</h1><p class="lead">收好每一次卡住的地方，下次就能走得更远。</p></div></div><div class="mistake-layout"><aside class="panel folders-panel"><div class="panel-label">${subjectLabel()}错题夹 <span class="small">${lib.folders.length}</span></div><a class="folder-link ${fid==='all'?'active':''}" href="/mistakes" data-nav><span>▤ 全部错题</span><small>${allCount}</small></a>${lib.folders.map(f=>`<a class="folder-link ${fid===f.id?'active':''}" href="/mistakes/${encodeURIComponent(f.id)}" data-nav><span>▱ ${esc(f.name)}</span><small>${f.count}</small></a>`).join('')}<button class="folder-new" data-action="new-folder">＋ 新建错题夹</button></aside><section><div class="section-head"><div><h2>${esc(folder?.name||(subjectLabel()+' · 全部错题'))}</h2><p>共 ${total} 道题 · ${mastered} 道已掌握</p></div>${folder?`<div class="folder-title-actions"><button class="text-button" data-action="rename-folder" data-id="${esc(fid)}">重命名</button><button class="text-button" data-action="delete-folder" data-id="${esc(fid)}">删除</button></div>`:''}</div><div class="toolbar"><div class="tabs" aria-label="复习状态筛选">${[['all','全部'],['review','未掌握'],['mastered','已掌握'],['unmarked','未标记']].map(([v,l])=>`<button data-action="review-filter" data-value="${v}" class="${reviewFilter===v?'active':''}">${l}</button>`).join('')}</div><span class="small">${refs.length} 道题</span></div><div class="question-grid">${refs.length?refs.map(m=>{const p=lib.paperMap[m.paper_id],s=lib.stateMap[key(m.paper_id,m.number)]||{};return `<a data-nav href="${questionURL(p.id,m.number,fid)}" class="mistake-card"><div class="card-top"><span class="badge">第 ${m.number} 题</span><span class="review-badge ${s.status==='mastered'?'mastered':s.status==='review'?'review':''}">${labels[s.status||'unmarked']}</span></div><h3>${esc(p.title)}</h3><div class="preview"><img loading="lazy" src="/assets/questions/${p.id}/${m.number}.png" alt="第 ${m.number} 题预览"></div><div class="card-foot"><span>${s.has_note?'● 有复盘笔记':'还没有笔记'}</span><span>打开复习 ↗</span></div></a>`}).join(''):empty(total?'这个状态下还没有题目':'留一个位置，给值得再做的题',total?'切换其他复习状态试试。':'打开试卷，勾选题目右侧的错题夹，就能收在这里。')}</div></section></div></div>`;
 activity.mount(app.querySelector('.page'),subject,'mistakes');
}
function openModal(title,content){modal.innerHTML=`<div class="modal-head"><h2 id="modal-title">${esc(title)}</h2><button class="close" data-action="close-modal" aria-label="关闭弹窗">×</button></div>${content}`;if(!modal.open)modal.showModal()}
function folderModal(id){const folder=id?lib.folders.find(f=>f.id===id):null;openModal(folder?'重命名错题夹':'新建错题夹',`<p class="modal-copy">按知识点或练习目标整理，例如「${subject==='408'?'数据结构再练一遍':'积分再练一遍'}」。</p><form id="folder-form"><input class="modal-field" name="name" aria-label="错题夹名称" placeholder="给错题夹起个名字" maxlength="60" required value="${esc(folder?.name||'')}"><div class="modal-error" id="form-error" role="alert"></div><div class="modal-actions"><button type="button" class="button" data-action="close-modal">取消</button><button type="submit" class="button primary">${folder?'保存名称':'创建文件夹'}</button></div></form>`);$('#folder-form').addEventListener('submit',async e=>{e.preventDefault();const b=$('button[type=submit]',e.target);b.disabled=true;try{await api(folder?'/api/folders/'+folder.id:'/api/folders',folder?'PATCH':'POST',{name:new FormData(e.target).get('name'),...(folder?{}:{subject})});modal.close();await refreshLibrary();if(editor){const q=await api(`/api/questions/${editor.pid}/${editor.n}`);$('.folder-options').innerHTML=folderOptions(q)}else if(location.pathname.startsWith('/mistakes'))renderMistakes();toast(folder?'名称已更新':'错题夹已创建')}catch(err){$('#form-error').textContent=err.message}finally{b.disabled=false}});$('input',modal).focus()}
async function exportBackup(){if(!await flush())return;const response=await fetch('/api/backup',{cache:'no-store'});if(!response.ok)throw new Error('云端备份暂时无法导出，请重试');const url=URL.createObjectURL(await response.blob());const a=document.createElement('a');a.href=url;a.download=`拾题备份-${new Date().toLocaleDateString('sv-SE')}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('备份已导出，原卷请另行保留')}
async function importBackup(file){if(!file)return;if(file.size>100*1024*1024)throw new Error('备份文件不能超过 100 MB');let body;try{body=JSON.parse(await file.text())}catch{throw new Error('这不是有效的 JSON 备份文件')};const preview=await api('/api/backup/preview','POST',body);openModal('恢复备份',`<p class="modal-copy">相同题目的笔记、状态和收藏关系将以备份为准。其他题目的记录保留；已有文件夹按标识或名称合并。</p><div class="summary-box">${preview.questions} 道题目记录 · ${preview.folders} 个错题夹<br>${preview.images||0} 张笔记图片 · ${preview.memberships} 条收藏关系 · ${preview.overwrites} 道题将被覆盖<br>${preview.review_days||0} 天每日回顾记录（同科目、同日期覆盖）<br>${preview.activity_records||0} 条学习打卡记录（合并保留）<br>${preview.practice_rounds||0} 轮每日一练 · ${preview.practice_answers||0} 条作答（同轮次完整覆盖）<br>${preview.knowledge_cards||0} 张考点记录 · ${preview.knowledge_reviews||0} 条考点评分 · ${preview.knowledge_sessions||0} 组连续复习（保留完整进度）</div><p class="tip">恢复前会自动保存当前数据到 云端自动备份。</p><div class="modal-error" id="restore-error" role="alert"></div><div class="modal-actions"><button class="button" data-action="close-modal">取消</button><button class="button primary" id="restore-confirm">确认恢复</button></div>`);$('#restore-confirm').addEventListener('click',async e=>{e.target.disabled=true;try{if(!await flush())return;await api('/api/backup/restore','POST',body);modal.close();await render();toast('备份已恢复，旧数据已自动备份')}catch(err){$('#restore-error').textContent=err.message}finally{e.target.disabled=false}})}
const daily=createDailyReview({api:scopedAPI,subjectLabel,esc,app,flush,refreshLibrary,getLibrary:()=>lib,getEditor:()=>editor,toast,navigate});
const activity=createActivity({api,esc});
const knowledge=createKnowledge({api,app,esc,navigate,toast,onOverview:root=>activity.mount(root,'408','knowledge')});
const practice=createDailyPractice({api,app,esc,navigate,flush,refreshLibrary,getLibrary:()=>lib,getEditor:()=>editor,toast});
const actions={
 'date-ribbon':toggleDateRibbon,
 'subject':async b=>{if(subject===b.dataset.value||!await flush())return;setSubject(b.dataset.value);homeFilter={difficulty:'全部',year:'全部年份',search:''};reviewFilter='all';const path=location.pathname==='/daily-review'?'/daily-review':location.pathname.startsWith('/mistakes')?'/mistakes':'/';await navigate(path+'?subject='+subject)},
 'daily-answer':b=>daily.answer(b),
 'practice-start':b=>practice.start(b), 'practice-next-round':b=>practice.start(b,true), 'practice-answer':b=>practice.answer(b),
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
document.addEventListener('click',async event=>{const link=event.target.closest('a[data-nav]');if(link&&!event.ctrlKey&&!event.metaKey&&!event.shiftKey&&!event.altKey&&event.button===0){event.preventDefault();await navigate(link.getAttribute('href'));return}const button=event.target.closest('[data-action]');if(!button||button.disabled)return;try{await actions[button.dataset.action]?.(button)}catch(e){toast(e.message)}});
document.addEventListener('input',event=>{if(event.target.id==='paper-search'){homeFilter.search=event.target.value;homeCards()}if(event.target.id==='note'&&editor){const e=editor;e.value=event.target.value;draftWrite(e);saveStatus(e,e.draftUnavailable?'尚未保存，请保持页面打开':'尚未保存');clearTimeout(e.timer);e.timer=setTimeout(()=>saveEditor(e),600)}});
document.addEventListener('change',async event=>{try{if(event.target.id==='year-filter'){homeFilter.year=event.target.value;homeCards()}if(event.target.dataset.folder&&editor){const el=event.target,e=editor;el.disabled=true;try{const s=await api('/api/folders/'+el.dataset.folder+'/membership','PUT',{paper_id:e.pid,number:e.n,selected:el.checked});await refreshLibrary();if(editor===e){$$('.status-pills button').forEach(x=>x.classList.toggle('active',x.dataset.value===s.status));updateNumberMarkers()}}catch(err){el.checked=!el.checked;throw err}finally{el.disabled=false}}if(event.target.id==='backup-file'){await importBackup(event.target.files[0]);event.target.value=''}}catch(e){toast(e.message);if(event.target.id==='backup-file')event.target.value=''}});
render();
