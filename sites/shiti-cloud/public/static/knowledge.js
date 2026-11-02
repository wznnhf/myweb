const ratingNames=['忘记了','勉强想起','记得','很熟'];
const ratingHelp=['没想出，或关键结论有误','费力回忆，独立答对','独立、完整地答对','迅速答对，能解释条件'];
const stateNames={new:'尚未学习',due:'到期待复习',scheduled:'已安排复习'};
const time=value=>value?new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false}):'尚未安排';
const allowed=new Set(['p','ul','li','strong','em','table','tr','th','td','h3','h4','blockquote','code','sup','sub','span']);

export function createKnowledge({api,app,esc,navigate,toast,onOverview=()=>{}}){
 let active=false,epoch=0,data,session=null,busy=false,holes=new Set(),lastDraw='',filterSequence=0,searchTimer,startKey=null;
 let mode=localStorage.getItem('cuoti-memory-mode')||'core';if(!['core','question','read'].includes(mode))mode='core';
 const valid=e=>active&&e===epoch;
 const url=(view='',id='')=>'/knowledge-draw?subject=408'+(view?'&view='+view:'')+(id?'&session='+encodeURIComponent(id):'');
 const link=(label,href,cls='button')=>`<a class="${cls}" href="${href}" data-nav>${label}</a>`;
 const fieldName=field=>data.subjects.find(s=>s.id===field)?.title||'四科混合';
 const errorHTML=()=>'<div id="kd-error" class="kd-error" role="alert" hidden></div>';
 function reset(){active=false;epoch++;busy=false;session=null;clearTimeout(searchTimer);app.removeAttribute('aria-busy')}
 async function load(){return api('/api/knowledge/overview')}
 function source(card){return `<p class="mc-source">CodeBrick 导出记忆卡 · ${esc(card.chapter)} · <a href="/api/knowledge/source/${card.field}#page=${card.pdf_page}" target="_blank" rel="noopener">查看来源 PDF 第 ${card.pdf_pages.join('、')} 页 ↗</a><span title="沿用 PDF 的标注，本站未重新统计考频">考频：${esc(card.frequency)} · 源资料标注</span></p>`}
 function rich(nodes,mask=false){
  return (nodes||[]).map(node=>{
   if(node.tag==='blank'){
    if(mask&&!holes.has(node.key))return `<button class="mc-blank" data-k-action="hole" data-key="${esc(node.key)}" aria-label="揭示第 ${Number(node.key.slice(1))} 处关键词" style="--blank-width:${Math.min(14,Math.max(3,[...node.text].length))}ch"><span aria-hidden="true">···</span></button>`;
    return `<strong class="${mask?'mc-revealed':''}">${esc(node.text)}</strong>`;
   }
   const body=esc(node.text||'')+rich(node.children,mask);
   if(!node.tag||!allowed.has(node.tag))return body;
   const attrs=['td','th'].includes(node.tag)?`${node.rowspan?' rowspan="'+Math.min(100,Number(node.rowspan))+'"':''}${node.colspan?' colspan="'+Math.min(100,Number(node.colspan))+'"':''}`:'';
   const html=`<${node.tag}${attrs}>${body}</${node.tag}>`;
   return node.tag==='table'?`<div class="mc-table-scroll" tabindex="0" aria-label="可横向滚动的对照表">${html}</div>`:html;
  }).join('');
 }
 function explanation(card){return `<details class="mc-understanding"><summary><span>展开理解</span><small>为什么这样记 · 易混辨析 · 推导说明</small><i aria-hidden="true">＋</i></summary><div class="mc-prose">${rich(card.explanation)}</div></details>`}
 function history(card){return `<details class="mc-history"><summary>复习记录 · 正式复习 ${card.total} 次 · 成功回忆 ${card.remembered} 次</summary>${card.history.length?`<ol>${card.history.map(h=>`<li><time>${time(h.reviewed_at)}</time><span>${ratingNames[h.rating-1]}${h.mode==='practice'?' · 提前练习':''}${h.undone?' · 已撤销':''}</span></li>`).join('')}</ol>`:'<p>还没有评分记录。</p>'}</details>`}
 function overview(value){
  data=value;session=null;
  const completed=data.subjects.reduce((n,s)=>n+s.completed,0),due=data.subjects.reduce((n,s)=>n+s.due,0),fresh=data.subjects.reduce((n,s)=>n+s.new,0),resume=data.active_session;
  app.innerHTML=`<div class="page kd-page mc-overview"><section class="section-head kd-heading"><div><div class="eyebrow">408 · MEMORY STUDIO</div><h1>记住结论，也理解为什么。</h1><p class="lead">先回忆骨架，再核对细节。每天留一小段时间，让知识更清晰。</p></div>${link('浏览全部记忆卡 ↗',url('catalog'))}</section><div class="mc-overview-stats"><span><strong>${data.total}</strong> 张记忆卡</span><span><strong>${data.subjects.reduce((n,s)=>n+s.chapters.length,0)}</strong> 个章节</span><span><strong>${completed}</strong> 今日已复习</span><span><strong>${due}</strong> 到期 · <strong>${fresh}</strong> 未学</span></div>${errorHTML()}${resume?`<section class="mc-resume"><div><span class="eyebrow">接着上次的记忆</span><h2>${fieldName(resume.field)} · 已完成 ${resume.completed} / ${resume.total}</h2><p class="small">已记住的位置和评分会保留，随时回来继续。</p></div><div class="kd-actions">${link('继续这组复习 →',url('',resume.id),'button primary')}<button class="text-button" data-k-action="end-home" data-id="${resume.id}">结束这组</button></div></section>`:''}<section class="mc-setup panel"><div><div class="eyebrow">一次专注，一组记忆</div><h2>安排今天的复习</h2><p class="small">按记忆安排复习，或选一章完整梳理。</p></div><form id="mc-start-form"><label>科目<select name="field" aria-label="练习科目"><option value="">四科混合</option>${data.subjects.map(s=>`<option value="${s.id}">${s.title}</option>`).join('')}</select></label><label>章节<select name="chapter_id" aria-label="练习章节"><option value="">全部章节</option></select></label><label>练习方式<select name="mode" aria-label="练习方式"><option value="mixed">到期＋新卡</option><option value="due">只复习到期卡</option><option value="new">只学新卡</option><option value="chapter">整章练习</option></select></label><label>本组数量<select name="limit" aria-label="本组数量"><option value="10">10 张</option><option value="20" selected>20 张</option><option value="40">40 张</option><option value="100">最多 100 张</option></select></label><button class="button primary" type="submit" ${resume?'disabled':''}>开始连续复习 →</button></form><p class="tip">整章练习会覆盖所选章节；尚未到期的卡记为提前练习，保持原有复习安排。</p></section><div class="kd-machines">${data.subjects.map((s,i)=>`<section class="kd-machine"><div class="kd-machine-head"><span class="kd-number">0${i+1} / ${s.id.toUpperCase()}</span><span class="badge">${s.chapters.length} 章 · ${s.total} 张</span></div><h2>${s.title}</h2><p class="kd-chapters">${s.chapters.map(c=>esc(c.title)).join(' · ')}</p><div class="kd-metrics"><div><strong>${s.completed}<small> / ${s.target}</small></strong><span>今日不同考点</span></div><div><strong>${s.due}</strong><span>到期待复习</span></div><div><strong>${s.new}</strong><span>尚未学习</span></div></div><progress max="${s.target}" value="${Math.min(s.completed,s.target)}" aria-label="${s.title}今日进度"></progress><div class="kd-machine-footer"><button class="button primary" data-k-action="start-field" data-field="${s.id}" ${resume?'disabled':''}>复习这一科 →</button>${link('按章节查看',url('catalog')+'&field='+s.id,'text-button')}</div><form class="kd-goal" data-field="${s.id}"><label>每日目标 <input type="number" name="target" aria-label="${s.title}每日目标" min="1" max="100" required value="${s.target}"> 张</label><button class="text-button" type="submit">保存</button><span>${s.next_due?'下批到期 '+time(s.next_due):'从今天的第一张开始'}</span></form></section>`).join('')}</div><details class="kd-rules"><summary>这套记忆卡与复习安排</summary><p>四份用户提供的 CodeBrick PDF，共 140 张记忆卡。保留原文结论、表格、公式和理解说明，核心挖空根据重点词设置，来源 PDF 随时可核对。考频沿用源资料标注。</p><p>FSRS 安排下次复习时间。“忘记了”约 10 分钟后重学；“勉强想起”指费力但独立答对。先展开核对再评分，阅读和揭示单个关键词不会计为完成。</p><p>每组卡片不重复；本组评分前已到期或未学的卡参与记忆调度，提前练习只记录练习，不改变既定复习时间。源资料内容仅用于你的本地学习。</p></details></div>`;
  updateChapters(app.querySelector('#mc-start-form'));onOverview(app.querySelector('.page'));
 }
 function updateChapters(form){
  if(!form)return;const selected=form.elements.chapter_id?.value||form.elements.chapter?.value||'',f=form.elements.field.value,select=form.elements.chapter_id||form.elements.chapter;
  select.innerHTML='<option value="">全部章节</option>'+data.subjects.filter(s=>!f||s.id===f).map(s=>s.chapters.map(ch=>`<option value="${ch.id}">${esc((f?'':s.title+' · ')+ch.title)}</option>`).join('')).join('');
  if([...select.options].some(o=>o.value===selected))select.value=selected;
 }
 async function render(value){
  active=true;data=value;const e=epoch,p=new URLSearchParams(location.search);
  if(p.get('session')){
   const next=await api('/api/knowledge/sessions/'+encodeURIComponent(p.get('session')));if(!valid(e))return;session=next;
   if(next.status==='active'){
    const opened=await api('/api/knowledge/sessions/'+next.id+'/position','PUT',{position:next.cursor});if(!valid(e))return;session=opened;renderSession();
   }else renderSummary();
  }else if(p.get('view')==='catalog')await renderCatalog();else overview(value);
 }
 const holesKey=draw=>'cuoti-memory-holes:'+draw.id+':'+draw.card.content_revision;
 function loadHoles(draw){
  if(lastDraw===holesKey(draw))return;lastDraw=holesKey(draw);
  try{holes=new Set(JSON.parse(localStorage.getItem(holesKey(draw))||'[]'))}catch{holes=new Set()}
 }
 function renderSession(){
  const draw=session.current;if(!draw){renderSummary();return}loadHoles(draw);
  const card=draw.card,revealed=!!draw.revealed_at,scored=draw.status==='scored',item=session.items.find(i=>i.position===session.cursor);
  app.innerHTML=`<div class="page kd-page mc-study-page"><div class="mc-study-toolbar">${link('← 暂停并返回',url(),'text-button')}<span>${esc(fieldName(session.field))} · ${session.cursor} / ${session.total}</span><button class="text-button" data-k-action="directory" aria-expanded="false">本组目录 ☰</button></div><div class="mc-session-progress" role="progressbar" aria-label="本组完成进度" aria-valuemin="0" aria-valuemax="${session.total}" aria-valuenow="${session.completed}"><span style="width:${session.completed/session.total*100}%"></span></div><div class="mc-session-meta"><span>已完成 ${session.completed} · 剩余 ${session.remaining}</span><span>${draw.mode==='practice'?'提前练习 · 保持原调度':'正常复习 · 评分后安排下次复习'}</span></div>${errorHTML()}<nav class="mc-directory" aria-label="本组卡片目录" hidden>${session.items.map(i=>`<button data-k-action="position" data-position="${i.position}" class="${i.position===session.cursor?'active':''}"><span>${String(i.position).padStart(2,'0')}</span><strong>${esc(i.title)}</strong><small>${i.rating?ratingNames[i.rating-1]:'待复习'}</small></button>`).join('')}</nav><article class="mc-study"><header class="mc-card-head"><div class="eyebrow">${esc(fieldName(card.field))} / ${esc(card.chapter)}</div><span class="badge">${esc(card.card_type)}</span><h1 tabindex="-1">${esc(card.title)}</h1><p class="mc-card-hint">${revealed?'核对关键结论，按刚才独立回忆的情况评分。':'沿着结论骨架回忆，点击挖空处可逐个揭示。'}</p></header>${!revealed?`<div class="mc-mode" role="group" aria-label="记忆方式">${[['core','核心挖空'],['question','整卡回忆'],['read','阅读结论']].map(([v,label])=>`<button data-k-action="mode" data-value="${v}" class="${mode===v?'active':''}" aria-pressed="${mode===v}">${label}</button>`).join('')}</div>`:''}<section class="mc-core mc-prose" aria-label="核心结论">${!revealed&&mode==='question'?`<div class="mc-recall"><span class="eyebrow">先在脑中回答</span><p>你能完整回忆「${esc(card.title)}」的关键结论、适用条件和易混点吗？</p></div>`:rich(card.core,!revealed&&mode==='core')}</section>${!revealed?`<div class="mc-reveal-bar"><span id="mc-hole-count" class="small" role="status">${mode==='core'?`已揭示 ${Math.min(holes.size,card.blank_count)} / ${card.blank_count} 处关键词`:'先独立回忆，再展开核对。'}</span><button class="button primary" data-k-action="reveal">${mode==='read'?'已核对，开始评分':'翻开核对全部结论'} <kbd>空格</kbd></button></div>`:`${explanation(card)}${scored?`<div class="mc-scored">这张卡已记录：${ratingNames[(item.rating||3)-1]}。回看不会重复评分。</div>`:`<section class="mc-rating-area"><h2>刚才独立回忆得怎么样？</h2><p class="small">看了提示才想起、漏掉关键条件，请选“忘记了”。</p><div class="kd-ratings">${ratingNames.map((label,i)=>`<button class="kd-rating kd-rating-${i}" data-k-action="score" data-rating="${i+1}"><strong>${label}<kbd>${i+1}</kbd></strong><span>${ratingHelp[i]}</span><small>${draw.mode==='practice'?'提前练习，仅记录本次':time(draw.preview_due?.[i])+' 再见'}</small></button>`).join('')}</div></section>`}`}${source(card)}${history(card)}</article><footer class="mc-study-footer"><button class="button" data-k-action="position" data-position="${session.cursor-1}" ${session.cursor===1?'disabled':''}>← 上一张</button><span class="small">空格核对 · 1–4 评分 · ← → 切卡</span><button class="button" data-k-action="${session.cursor===session.total?'summary':'position'}" data-position="${session.cursor+1}">${session.cursor===session.total?'查看本组进度':'下一张 →'}</button></footer><div class="mc-session-bottom"><button class="text-button" data-k-action="end">结束本组</button>${data.last_review?'<button class="text-button" data-k-action="undo">撤销上次评分</button>':''}</div></div>`;
  app.querySelector('.mc-card-head h1')?.focus({preventScroll:true});
 }
 function renderSummary(){
  const complete=session.completed===session.total,next=session.items.find(i=>!i.rating);
  app.innerHTML=`<div class="page kd-page mc-summary-page">${link('← 返回记忆卡',url(),'text-button')}<section class="mc-summary-card"><div class="eyebrow">${complete?'A LITTLE BETTER, EVERY DAY':'YOUR STUDY SESSION'}</div><h1>${complete?'这一组，记得更清楚了。':'每一次回忆，都算数。'}</h1><p class="lead">${esc(fieldName(session.field))} · 已完成 ${session.completed} / ${session.total} 张${session.status==='ended'?' · 本组已结束':''}</p><div class="mc-summary-counts">${ratingNames.map((name,i)=>`<div><strong>${session.counts[i]}</strong><span>${name}</span></div>`).join('')}</div><p class="small">评分已保存，正常复习已安排下次时间。提前练习保持原有安排。</p><div class="kd-actions">${next&&session.status==='active'?`<button class="button primary" data-k-action="position" data-position="${next.position}">继续剩余 ${session.remaining} 张 →</button>`:link('返回记忆卡首页 →',url(),'button primary')}${data.last_review?'<button class="button" data-k-action="undo">撤销上次评分</button>':''}</div></section><div class="mc-summary-list">${session.items.map(i=>`<div><span>${String(i.position).padStart(2,'0')}</span><strong>${esc(i.title)}</strong><small>${i.rating?ratingNames[i.rating-1]:'未评分'}</small></div>`).join('')}</div>${errorHTML()}</div>`;
 }
 async function renderCatalog(){
  const e=epoch,field=new URLSearchParams(location.search).get('field')||'';
  app.innerHTML=`<div class="page kd-page"><div class="breadcrumb">${link('← 记忆卡首页',url(),'text-button')}</div><section class="section-head kd-heading"><div><div class="eyebrow">CODEBRICK · ${data.total} MEMORY CARDS</div><h1>按章节，搭起知识骨架。</h1><p class="lead">阅读结论、展开理解，或直接背这一章。浏览不会改变复习记录。</p></div><a class="button" href="/api/knowledge/export/cards">导出卡片清单</a></section><form id="kd-filter" class="kd-filter"><label>科目<select name="field" aria-label="考点科目"><option value="">四科全部</option>${data.subjects.map(s=>`<option value="${s.id}" ${s.id===field?'selected':''}>${s.title}</option>`).join('')}</select></label><label>章节<select name="chapter" aria-label="考点章节"><option value="">全部章节</option></select></label><label>状态<select name="status" aria-label="学习状态"><option value="">全部状态</option>${Object.entries(stateNames).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select></label><label class="kd-search">搜索<input type="search" name="q" aria-label="搜索考点" placeholder="标题或章节名称"></label></form>${errorHTML()}<div id="kd-results" aria-live="polite"></div><div id="kd-detail"></div></div>`;
  updateChapters(app.querySelector('#kd-filter'));if(valid(e))await filterCatalog();
 }
 async function filterCatalog(){
  const form=app.querySelector('#kd-filter');if(!form)return;const e=epoch,seq=++filterSequence,p=new URLSearchParams();for(const [k,v] of new FormData(form))if(v)p.set(k,v);
  const result=await api('/api/knowledge/catalog?'+p);if(!valid(e)||seq!==filterSequence||!app.querySelector('#kd-results'))return;
  const groups=new Map();for(const card of result.cards){if(!groups.has(card.chapter_id))groups.set(card.chapter_id,[]);groups.get(card.chapter_id).push(card)}
  app.querySelector('#kd-results').innerHTML=`<p class="kd-result-count">找到 ${result.cards.length} 张记忆卡 · ${groups.size} 个章节</p>${[...groups].map(([id,cards])=>`<section class="mc-catalog-chapter"><div class="section-head"><div><span class="eyebrow">${fieldName(cards[0].field)}</span><h2>${esc(cards[0].chapter)} <span class="small">${cards.length} 张 · 已学 ${cards.filter(c=>c.total>0).length}</span></h2></div><button class="button" data-k-action="chapter" data-field="${cards[0].field}" data-chapter="${id}">背这一章 →</button></div><div class="kd-catalog">${cards.map(c=>`<button class="kd-catalog-card" data-k-action="detail" data-id="${c.id}"><span class="small">${esc(c.card_type)} · ${esc(c.frequency)}（源资料）</span><strong>${esc(c.title)}</strong><span class="kd-catalog-bottom"><span class="badge">${stateNames[c.status]}</span><span>已复习 ${c.total} 次 · ${c.blank_count} 处挖空</span></span></button>`).join('')}</div></section>`).join('')||'<div class="empty">没有找到卡片，试试其他筛选条件。</div>'}`;
 }
 async function showDetail(id){
  const e=epoch,card=await api('/api/knowledge/cards/'+encodeURIComponent(id));if(!valid(e)||!app.querySelector('#kd-detail'))return;
  app.querySelector('#kd-detail').innerHTML=`<article class="mc-study"><div class="section-head"><span class="eyebrow">目录阅读 · 不计入复习</span><button class="text-button" data-k-action="close-detail">收起 ×</button></div><h2 tabindex="-1">${esc(card.title)}</h2><div class="mc-core mc-prose">${rich(card.core)}</div>${explanation(card)}${source(card)}${history(card)}<button class="button primary" data-k-action="chapter" data-field="${card.field}" data-chapter="${card.chapter_id}">开始这一章的练习 →</button></article>`;
  app.querySelector('#kd-detail').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'});app.querySelector('#kd-detail h2').focus({preventScroll:true});
 }
 function showError(error){const el=app.querySelector('#kd-error');if(el){el.hidden=false;el.textContent=error.message;el.scrollIntoView({block:'nearest'})}else toast(error.message)}
 function busyButtons(value){app.querySelectorAll('[data-k-action]').forEach(b=>{if(b instanceof HTMLButtonElement){if(value){b.dataset.wasDisabled=String(b.disabled);b.disabled=true}else if(b.dataset.wasDisabled){b.disabled=b.dataset.wasDisabled==='true';delete b.dataset.wasDisabled}}})}
 async function run(work){if(busy)return;busy=true;const e=epoch;app.setAttribute('aria-busy','true');busyButtons(true);try{await work()}catch(error){if(valid(e))showError(error)}finally{if(valid(e)){busy=false;app.removeAttribute('aria-busy');busyButtons(false)}}}
 async function start(options){
  const e=epoch;startKey??={id:crypto.randomUUID(),signature:JSON.stringify(options)};if(startKey.signature!==JSON.stringify(options))startKey={id:crypto.randomUUID(),signature:JSON.stringify(options)};
  const created=await api('/api/knowledge/sessions','POST',{...options,request_id:startKey.id});if(!valid(e))return;startKey=null;await navigate(url('',created.id));
 }
 async function position(pos){const e=epoch;const next=await api('/api/knowledge/sessions/'+session.id+'/position','PUT',{position:pos});if(valid(e)){session=next;renderSession();window.scrollTo({top:0,behavior:'instant'})}}
 async function action(name,b){
  const e=epoch;
  if(name==='start-field')await start({field:b.dataset.field,mode:'mixed',limit:20});
  else if(name==='chapter')await start({field:b.dataset.field,chapter_id:b.dataset.chapter,mode:'chapter',limit:100});
  else if(name==='position')await position(Number(b.dataset.position));
  else if(name==='reveal'){const draw=await api('/api/knowledge/draws/'+session.current.id+'/reveal','POST');if(valid(e)){session.current=draw;renderSession()}}
  else if(name==='score'){
   data=await api('/api/knowledge/draws/'+session.current.id+'/score','POST',{rating:Number(b.dataset.rating),revision:session.current.revision,request_id:'score:'+session.current.id});if(!valid(e))return;
   const next=await api('/api/knowledge/sessions/'+session.id);if(!valid(e))return;session=next;
   if(next.status==='completed')renderSummary();else{const remaining=next.items.filter(i=>!i.rating),target=remaining.find(i=>i.position>next.cursor)||remaining[0];if(target)await position(target.position);else renderSummary()}
  }else if(name==='end'||name==='end-home'){
   const next=await api('/api/knowledge/sessions/'+(b.dataset.id||session.id)+'/end','POST');if(!valid(e))return;if(name==='end-home'){data=await load();if(valid(e))overview(data)}else{session=next;renderSummary()}
  }else if(name==='undo'){
   const last=data.last_review;if(!last)return;data=await api('/api/knowledge/reviews/'+last.id+'/undo','POST',{revision:last.revision});if(!valid(e))return;
   if(session){session=await api('/api/knowledge/sessions/'+session.id);if(valid(e)){const next=session.items.find(i=>!i.rating);if(next&&session.status==='active')await position(next.position);else renderSummary()}}else overview(data);
   toast('已撤销上次评分，复习安排已恢复。');
  }else if(name==='detail')await showDetail(b.dataset.id);
 }
 app.addEventListener('click',event=>{
  if(!active)return;const b=event.target.closest('[data-k-action]');if(!b||b.disabled)return;const name=b.dataset.kAction;
  if(name==='hole'){
   const nodeKey=b.dataset.key;let answer='';function find(ns){for(const n of ns||[]){if(n.tag==='blank'&&n.key===nodeKey)answer=n.text;find(n.children)}}find(session.current.card.core);
   holes.add(nodeKey);try{localStorage.setItem(holesKey(session.current),JSON.stringify([...holes]))}catch{}
   b.outerHTML=`<strong class="mc-revealed">${esc(answer)}</strong>`;app.querySelector('#mc-hole-count').textContent=`已揭示 ${holes.size} / ${session.current.card.blank_count} 处关键词`;return;
  }
  if(name==='mode'){mode=b.dataset.value;localStorage.setItem('cuoti-memory-mode',mode);renderSession();return}
  if(name==='directory'){const nav=app.querySelector('.mc-directory');nav.hidden=!nav.hidden;b.setAttribute('aria-expanded',String(!nav.hidden));return}
  if(name==='summary'){renderSummary();return}
  if(name==='close-detail'){app.querySelector('#kd-detail').innerHTML='';return}
  run(()=>action(name,b));
 });
 app.addEventListener('submit',event=>{
  if(!active)return;const form=event.target;
  if(form.id==='kd-filter'){event.preventDefault();return}
  if(form.id==='mc-start-form'){event.preventDefault();const f=new FormData(form),field=f.get('field')||null,chapter_id=f.get('chapter_id')||null;run(()=>start({field,chapter_id,mode:f.get('mode'),limit:Number(f.get('limit'))}));return}
  if(form.matches('.kd-goal')){event.preventDefault();run(async()=>{const e=epoch,value=await api('/api/knowledge/goals/'+form.dataset.field,'PUT',{target:Number(new FormData(form).get('target'))});if(valid(e)){overview(value);toast('每日目标已保存。')}})}
 });
 app.addEventListener('change',event=>{
  if(!active)return;const form=event.target.form;
  if(form?.id==='mc-start-form'){if(event.target.name==='field')updateChapters(form);if(event.target.name==='chapter_id'&&event.target.value)form.elements.mode.value='chapter';return}
  if(form?.id==='kd-filter'){if(event.target.name==='field')updateChapters(form);filterCatalog().catch(showError)}
 });
 app.addEventListener('input',event=>{if(!active||event.target.form?.id!=='kd-filter'||event.target.name!=='q')return;clearTimeout(searchTimer);searchTimer=setTimeout(()=>filterCatalog().catch(showError),200)});
 document.addEventListener('keydown',event=>{
  if(!active||!session?.current||busy||event.repeat||event.ctrlKey||event.metaKey||event.altKey||document.querySelector('dialog[open]')||event.target.closest('input,textarea,select,[contenteditable="true"]'))return;
  let button;
  if(event.code==='Space'&&!session.current.revealed_at&&!event.target.closest('button,a'))button=app.querySelector('[data-k-action=reveal]');
  else if(/^[1-4]$/.test(event.key)&&session.current.revealed_at)button=app.querySelector(`[data-k-action=score][data-rating="${event.key}"]`);
  else if(['ArrowLeft','ArrowRight'].includes(event.key))button=app.querySelector(`.mc-study-footer [data-position="${session.cursor+(event.key==='ArrowLeft'?-1:1)}"]`);
  if(button&&!button.disabled){event.preventDefault();button.click()}
 });
 return {reset,load,render};
}
