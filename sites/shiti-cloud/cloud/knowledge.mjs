// Knowledge API port of app/knowledge.py and knowledge_sessions.py.
// Scheduling follows python-fsrs 6.3.2, with one 10-minute (re)learning step,
// retention 0.9 and fuzzing disabled. Python state values are kept unchanged.
export const PARAMETERS = [0.212,1.2931,2.3065,8.2956,6.4133,0.8334,3.0194,0.001,1.8722,0.1666,0.796,1.4835,0.0614,0.2629,1.6483,0.6014,1.8729,0.5425,0.0912,0.0658,0.1542];
export const CONFIG = {algorithm:'FSRS-6',package:'fsrs==6.3.2',selection_version:1,scheduler:{parameters:PARAMETERS,desired_retention:0.9,learning_steps:[600],relearning_steps:[600],maximum_interval:36500,enable_fuzzing:false}};
const DECAY = -PARAMETERS[20], FACTOR = 0.9 ** (1 / DECAY) - 1;
const copy = value => value == null ? null : structuredClone(value);
const decode = value => typeof value === 'string' ? JSON.parse(value) : value;
const numericID = cardID => parseInt(cardID.split('-')[1],16);
const clamp = (v,min,max=Infinity) => Math.min(Math.max(v,min),max);
// datetime.isoformat() uses six fractional digits when microseconds are nonzero.
function micros(value) {
  const match = String(value).match(/\.(\d+)/);
  return BigInt(new Date(value).getTime()) * 1000n + BigInt((match?.[1] || '').padEnd(6,'0').slice(3,6) || '0');
}
function stamp(value,seconds=0) {
  const us = micros(value) + BigInt(seconds) * 1000000n;
  const whole = us / 1000000n;
  const fraction = Number(us % 1000000n);
  return new Date(Number(whole)*1000).toISOString().slice(0,19) + (fraction ? '.'+String(fraction).padStart(6,'0') : '') + '+00:00';
}
function elapsedDays(at,last) {
  const elapsed = micros(at)-micros(last), day = 86400000000n;
  return Number(elapsed >= 0n ? elapsed/day : (elapsed-day+1n)/day);
}
function pyRound(value) {
  const low=Math.floor(value), remainder=value-low;
  return remainder===0.5 ? low+(low%2) : Math.round(value);
}
function initialDifficulty(rating,shouldClamp=true) {
  const value=PARAMETERS[4] - Math.E ** (PARAMETERS[5]*(rating-1)) + 1;
  return shouldClamp ? clamp(value,1,10) : value;
}
export function retrievability(card,at) {
  if (!card?.last_review || card.stability==null) return 0;
  return (1+FACTOR*Math.max(0,elapsedDays(at,card.last_review))/card.stability) ** DECAY;
}
export function scheduleFSRS(saved,cardID,rating,at) {
  const card = saved ? copy(decode(saved)) : {card_id:numericID(cardID),state:1,step:0,stability:null,difficulty:null,due:stamp(at),last_review:null};
  const s=card.stability,d=card.difficulty,days=card.last_review ? elapsedDays(at,card.last_review) : null;
  if (s==null || d==null) {
    card.stability=Math.max(PARAMETERS[rating-1],0.001);
    card.difficulty=initialDifficulty(rating);
  } else {
    let next;
    if (days!=null && days<1) {
      let increase=Math.E ** (PARAMETERS[17]*(rating-3+PARAMETERS[18])) * s ** -PARAMETERS[19];
      if (rating>=2) increase=Math.max(increase,1);
      next=s*increase;
    } else {
      const r=retrievability(card,at);
      if(rating===1) {
        next=Math.min(PARAMETERS[11]*d ** -PARAMETERS[12]*((s+1) ** PARAMETERS[13]-1)*Math.E ** ((1-r)*PARAMETERS[14]),s/(Math.E ** (PARAMETERS[17]*PARAMETERS[18])));
      } else {
        next=s*(1+Math.E ** PARAMETERS[8]*(11-d)*s ** -PARAMETERS[9]*(Math.E ** ((1-r)*PARAMETERS[10])-1)*(rating===2?PARAMETERS[15]:1)*(rating===4?PARAMETERS[16]:1));
      }
    }
    card.stability=Math.max(next,0.001);
    card.difficulty=clamp(PARAMETERS[7]*initialDifficulty(4,false)+(1-PARAMETERS[7])*(d+(10-d)*(-PARAMETERS[6]*(rating-3))/9),1,10);
  }
  const interval=()=>clamp(pyRound((card.stability/FACTOR)*(0.9 ** (1/DECAY)-1)),1,36500)*86400;
  let seconds;
  if(card.state===2) {
    if(rating===1) {card.state=3;card.step=0;seconds=600;}
    else seconds=interval();
  } else if(card.state===1 || card.state===3) {
    if(rating===1) {card.step=0;seconds=600;}
    else if(rating===2 && card.step===0) seconds=900;
    else {card.state=2;card.step=null;seconds=interval();}
  } else throw new Error('记忆阶段无效。');
  card.due=stamp(at,seconds);card.last_review=stamp(at);
  return {card,log:{card_id:card.card_id,rating,review_datetime:stamp(at),review_duration:null}};
}

export function knowledgeAPI(path,method,body,params,data,context) {
  if(!path.startsWith('/api/knowledge/')) return undefined;
  const catalog=context.cardsCatalog, cards=catalog.cards, byID=new Map(cards.map(c=>[c.id,c])), subjects=catalog.subjects;
  const at=stamp(context.now), today=context.today || new Date(new Date(at).getTime()+8*3600000).toISOString().slice(0,10);
  const fail=context.fail, id=context.id;
  const k=data.knowledge ||= {catalog_version:catalog.version,source_sha256:catalog.source_sha256,config:copy(CONFIG),states:[],draws:[],reviews:[],goals:[],sessions:[]};
  for(const key of ['states','draws','reviews','goals','sessions']) k[key] ||= [];
  // Backups expose decoded FSRS JSON, while historical database rows used text.
  for(const row of k.states) row.fsrs=decode(row.fsrs);
  for(const row of k.reviews) for(const key of ['before_state','after_state','fsrs_log']) row[key]=decode(row[key]);
  const value = key => typeof params?.get==='function' ? params.get(key) : params?.[key];
  const validField = field => subjects.some(s=>s.id===field) || fail(422,'科目无效。');
  const integer = (n,min,max=Number.MAX_SAFE_INTEGER) => Number.isInteger(n)&&n>=min&&n<=max || fail(422,'数值超出允许范围。');
  function requestID(v) {if(typeof v!=='string'||!v.length||v.length>100)fail(422,'请求标识无效。');}
  function strict(fields) {if(!body || typeof body!=='object' || Array.isArray(body) || Object.keys(body).some(key=>!fields.includes(key)))fail(422,'请求字段无效。');}
  function cardCheck(cardID) {return byID.get(cardID)||fail(404,'考点不存在');}
  function state(cardID,create=false) {
    let row=k.states.find(s=>s.card_id===cardID);
    if(!row) {row={card_id:cardID,fsrs:null,revision:0,seen_at:create?at:null};if(create)k.states.push(row);}
    return row;
  }
  function memory(row) {
    if(!row?.fsrs) return {status:'new',due:null,retention:null};
    const card=row.fsrs;
    return {status:micros(card.due)<=micros(at)?'due':'scheduled',due:stamp(card.due),retention:Number(retrievability(card,at).toFixed(4)),phase:card.state,stability:card.stability,difficulty:card.difficulty};
  }
  function counts(cardID) {
    const ratings=[0,0,0,0];
    for(const r of k.reviews) if(r.card_id===cardID&&r.mode==='review'&&!r.undone) ratings[r.rating-1]++;
    return {ratings,total:ratings.reduce((a,b)=>a+b,0),remembered:ratings.slice(1).reduce((a,b)=>a+b,0)};
  }
  const newest = rows => rows.map((r,i)=>({r,i})).sort((a,b)=>Number(micros(b.r.reviewed_at)-micros(a.r.reviewed_at))||b.i-a.i).map(v=>v.r);
  function detail(cardID,answer=true) {
    const card=copy(cardCheck(cardID)),saved=state(cardID);
    const out={...card,...memory(saved),...counts(cardID),revision:saved.revision,history:newest(k.reviews.filter(r=>r.card_id===cardID)).slice(0,100).map(r=>({id:r.id,rating:r.rating,mode:r.mode,reviewed_at:r.reviewed_at,undone:r.undone}))};
    if(!answer) {delete out.answer;delete out.pitfall;delete out.explanation;}
    return out;
  }
  function drawPayload(draw) {
    const result={...copy(draw),card:detail(draw.card_id,Boolean(draw.revealed_at)),revision:draw.expected_revision};
    if(draw.revealed_at&&draw.status==='pending'&&draw.mode==='review')result.preview_due=[1,2,3,4].map(r=>scheduleFSRS(state(draw.card_id).fsrs,draw.card_id,r,at).card.due);
    return result;
  }
  function sessionGet(sid) {
    const session=k.sessions.find(s=>s.id===sid)||fail(404,'这组复习不存在。');
    let current=null;
    const items=session.items.map(item=>{
      const card=cardCheck(item.card_id),draw=k.draws.find(d=>d.id===item.draw_id),review=k.reviews.find(r=>r.id===item.draw_id);
      const done=draw?.status==='scored' && review?.rating!=null && !review.undone;
      if(item.position===session.cursor&&draw&&['pending','scored'].includes(draw.status))current=drawPayload(draw);
      return {position:item.position,card_id:card.id,title:card.title,field:card.field,chapter:card.chapter,chapter_id:card.chapter_id,rating:done?review.rating:null,mode:draw?.mode||null};
    });
    const completed=items.filter(i=>i.rating!=null).length;
    return {...copy(session),items,total:items.length,completed,remaining:items.length-completed,current,counts:[1,2,3,4].map(r=>items.filter(i=>i.rating===r).length)};
  }
  function activeSummary() {
    const session=k.sessions.find(s=>s.status==='active');if(!session)return null;
    const full=sessionGet(session.id);
    return Object.fromEntries(['id','field','chapter_id','mode','cursor','total','completed','remaining'].map(key=>[key,full[key]]));
  }
  function overview() {
    const result=subjects.map(subject=>{
      const members=cards.filter(c=>c.field===subject.id), memories=members.map(c=>memory(state(c.id))), pending=k.draws.find(d=>d.field===subject.id&&d.status==='pending');
      const completed=new Set(k.reviews.filter(r=>!r.undone&&r.mode==='review'&&r.field===subject.id&&byID.has(r.card_id)&&new Date(new Date(r.reviewed_at).getTime()+8*3600000).toISOString().slice(0,10)===today).map(r=>r.card_id));
      const future=memories.filter(m=>m.status==='scheduled').map(m=>m.due).sort();
      return {...copy(subject),total:members.length,target:k.goals.find(g=>g.field===subject.id)?.target||5,completed:completed.size,due:memories.filter(m=>m.status==='due').length,new:memories.filter(m=>m.status==='new').length,unseen:members.filter(c=>!k.states.some(s=>s.card_id===c.id)).length,next_due:future[0]||null,pending:pending?drawPayload(pending):null};
    });
    const last=newest(k.reviews.filter(r=>!r.undone))[0];let last_review=null;
    if(last&&byID.has(last.card_id))last_review={id:last.id,field:last.field,rating:last.rating,title:byID.get(last.card_id).title,mode:last.mode,due:memory(state(last.card_id)).due,revision:state(last.card_id).revision};
    return {day:today,subjects:result,last_review,config:copy(CONFIG),catalog_version:catalog.version,total:cards.length,active_session:activeSummary()};
  }
  function pendingDraw(drawID) {
    const draw=k.draws.find(d=>d.id===drawID)||fail(404,'这次抽取不存在。');
    if(draw.status!=='pending'||state(draw.card_id).revision!==draw.expected_revision)fail(409,'此卡片已在其他页面处理，请刷新继续。');
    return draw;
  }
  function makeDraw(card,kind,request_id) {
    const saved=state(card.id,true), draw={id:id(),request_id,card_id:card.id,field:card.field,mode:kind==='practice'?'practice':'review',kind,expected_revision:saved.revision,created_at:at,revealed_at:null,status:'pending'};
    k.draws.push(draw);return draw;
  }
  function updateSessions(drawID) {
    for(const session of k.sessions.filter(s=>s.items.some(i=>i.draw_id===drawID))) {
      const complete=sessionGet(session.id).remaining===0;
      if(session.status==='active'&&complete)session.status='completed';
      else if(session.status==='completed'&&!complete)session.status=k.sessions.some(s=>s.status==='active')?'ended':'active';
    }
  }
  const pick = choices => choices[Math.floor(Math.random()*choices.length)];
  function choose(field,practice) {
    const all=cards.filter(c=>c.field===field),fresh=[],due=[],relearn=[],future=[];
    for(const card of all) {
      const saved=state(card.id);
      if(!saved.fsrs)fresh.push(card);
      else if(memory(saved).status==='due')(saved.fsrs.state===1||saved.fsrs.state===3?relearn:due).push(card);
      else future.push(card);
    }
    if(practice) {
      if(fresh.length||due.length||relearn.length)fail(409,'还有新卡或到期考点，请先使用正常抽取。');
      return future.length ? [pick(future),'practice'] : null;
    }
    if(relearn.length)return [relearn.sort((a,b)=>Number(micros(state(a.id).fsrs.due)-micros(state(b.id).fsrs.due)))[0],'relearn'];
    const ordinary=k.draws.filter(d=>d.field===field&&['new','due'].includes(d.kind)&&d.status==='scored').length;
    if(fresh.length&&(!due.length||ordinary%5===4)) {
      const coverage=new Map();
      for(const card of fresh) {
        const chapter=all.filter(c=>c.chapter_id===card.chapter_id);
        coverage.set(card.chapter_id,chapter.filter(c=>state(c.id).seen_at).length/chapter.length);
      }
      const lowest=Math.min(...coverage.values());return [pick(fresh.filter(c=>coverage.get(c.chapter_id)===lowest)),'new'];
    }
    if(due.length) {
      const weights=due.map(card=>{
        const m=state(card.id).fsrs,interval=Math.max(Number(micros(m.due)-micros(m.last_review))/1000000,1),overdue=Math.max(Number(micros(at)-micros(m.due))/1000000,0)/interval;
        const failures=newest(k.reviews.filter(r=>r.card_id===card.id&&r.mode==='review'&&!r.undone)).slice(0,10).filter(r=>r.rating===1).length;
        return (1+4*(1-retrievability(m,at)))*(1+Math.min(overdue,3))*(1+Math.min(failures,3));
      });
      let ticket=Math.random()*weights.reduce((a,b)=>a+b,0);
      for(let i=0;i<due.length;i++){ticket-=weights[i];if(ticket<=0)return [due[i],'due'];}
      return [due.at(-1),'due'];
    }
    return null;
  }
  if(path==='/api/knowledge/overview'&&method==='GET')return overview();
  if(path==='/api/knowledge/catalog'&&method==='GET') {
    const field=value('field'),chapter=value('chapter'),query=(value('q')||'').toLocaleLowerCase(),status=value('status');
    if(field)validField(field);if(status&&!['new','due','scheduled'].includes(status))fail(422,'学习状态无效。');
    const selected=[];
    for(const card of cards) {
      if(field&&card.field!==field||chapter&&card.chapter_id!==chapter||query&&![card.title,card.prompt,card.source,card.chapter].join(' ').toLocaleLowerCase().includes(query))continue;
      const m=memory(state(card.id));if(status&&m.status!==status)continue;
      const item=copy(card);for(const key of ['answer','pitfall','core','explanation'])delete item[key];
      selected.push({...item,...m,...counts(card.id)});
    }
    return {subjects:copy(subjects),cards:selected};
  }
  let match=path.match(/^\/api\/knowledge\/cards\/([^/]+)$/);
  if(match&&method==='GET')return detail(decodeURIComponent(match[1]));
  if(path==='/api/knowledge/draw'&&method==='POST') {
    strict(['field','request_id','practice']);validField(body.field);requestID(body.request_id);
    if(body.practice!==undefined&&typeof body.practice!=='boolean')fail(422,'练习模式无效。');
    const existing=k.draws.find(d=>d.request_id===body.request_id);
    if(existing) {
      if(existing.field!==body.field||(existing.mode==='practice')!==Boolean(body.practice))fail(409,'抽取标识已被另一请求使用。');
      return {draw:drawPayload(existing)};
    }
    const pending=k.draws.find(d=>d.field===body.field&&d.status==='pending');if(pending)return {draw:drawPayload(pending)};
    const chosen=choose(body.field,body.practice);if(!chosen)return {draw:null,overview:overview()};
    return {draw:drawPayload(makeDraw(chosen[0],chosen[1],body.request_id))};
  }
  match=path.match(/^\/api\/knowledge\/draws\/([^/]+)\/(reveal|score)$/);
  if(match&&method==='POST') {
    const drawID=decodeURIComponent(match[1]);
    if(match[2]==='reveal') {const draw=pendingDraw(drawID);draw.revealed_at ||= at;return drawPayload(draw);}
    strict(['rating','revision','request_id']);integer(body.rating,1,4);integer(body.revision,0);requestID(body.request_id);
    const existing=k.reviews.find(r=>r.id===drawID||r.request_id===body.request_id);
    if(existing) {
      if(existing.id===drawID&&existing.request_id===body.request_id&&existing.rating===body.rating&&!existing.undone) {context.record?.('408','knowledge','k:'+existing.card_id,existing.reviewed_at);return overview();}
      fail(409,'这次抽取已评分或请求标识冲突，请刷新查看。');
    }
    const draw=pendingDraw(drawID);
    if(!draw.revealed_at)fail(409,'请先展开答案并核对，再评分。');
    if(body.revision!==draw.expected_revision)fail(409,'卡片版本已变化，请刷新。');
    const saved=state(draw.card_id),before=copy(saved.fsrs);let after=copy(before),log=null;
    if(draw.mode==='review') {const result=scheduleFSRS(before,draw.card_id,body.rating,at);after=result.card;log=result.log;}
    k.reviews.push({id:drawID,request_id:body.request_id,card_id:draw.card_id,field:draw.field,mode:draw.mode,rating:body.rating,reviewed_at:at,before_state:before,after_state:copy(after),fsrs_log:log,undone:0});
    saved.fsrs=after;saved.revision++;draw.status='scored';updateSessions(drawID);context.record?.('408','knowledge','k:'+draw.card_id,at);
    return overview();
  }
  match=path.match(/^\/api\/knowledge\/reviews\/([^/]+)\/undo$/);
  if(match&&method==='POST') {
    strict(['revision']);integer(body.revision,0);const reviewID=decodeURIComponent(match[1]),review=k.reviews.find(r=>r.id===reviewID)||fail(404,'评分记录不存在。');
    if(review.undone)return overview();
    const latest=newest(k.reviews.filter(r=>!r.undone))[0],saved=state(review.card_id);
    if(latest.id!==reviewID||saved.revision!==body.revision)fail(409,'只能撤销最近一次评分，请刷新查看最新记录。');
    review.undone=1;
    for(const draw of k.draws) {if(draw.id===reviewID)draw.status='undone';else if(draw.card_id===review.card_id&&draw.status==='pending')draw.status='invalidated';}
    saved.fsrs=copy(review.before_state);saved.revision++;updateSessions(reviewID);return overview();
  }
  match=path.match(/^\/api\/knowledge\/goals\/([^/]+)$/);
  if(match&&method==='PUT') {
    strict(['target']);const field=decodeURIComponent(match[1]);validField(field);integer(body.target,1,100);
    const goal=k.goals.find(g=>g.field===field);if(goal)goal.target=body.target;else k.goals.push({field,target:body.target});return overview();
  }
  if(path==='/api/knowledge/sessions'&&method==='POST') {
    strict(['request_id','field','chapter_id','mode','limit']);requestID(body.request_id);
    const field=body.field??null,chapter=body.chapter_id??null,mode=body.mode??'mixed',limit=body.limit??20;
    if(field!==null)validField(field);integer(limit,1,100);
    if(!['mixed','due','new','chapter'].includes(mode))fail(422,'复习模式无效。');
    if(chapter!==null&&(typeof chapter!=='string'||chapter.length>100))fail(422,'章节标识无效。');
    if(chapter&&!subjects.some(s=>(!field||s.id===field)&&s.chapters.some(ch=>ch.id===chapter)))fail(400,'章节与科目不匹配。');
    if(mode==='chapter'&&!chapter)fail(400,'请选择要练习的章节。');
    const existing=k.sessions.find(s=>s.request_id===body.request_id);
    if(existing) {if(existing.field!==field||existing.chapter_id!==chapter||existing.mode!==mode||existing.limit_count!==limit)fail(409,'这次开始标识已用于另一组练习。');return sessionGet(existing.id);}
    if(activeSummary())fail(409,'还有一组未结束的复习，请继续该组，或先结束后再选择新范围。');
    let candidates=cards.filter(card=>(!field||card.field===field)&&(!chapter||card.chapter_id===chapter)).map(card=>({card,m:memory(state(card.id))})).filter(({m})=>mode==='due'?m.status==='due':mode==='new'?m.status==='new':mode==='mixed'?m.status!=='scheduled':true);
    if(!candidates.length)fail(409,'这个范围目前没有可复习的卡片，可选择其他范围或按章节练习。');
    for(let i=candidates.length-1;i>0;i--){const j=Math.floor(Math.random()*(i+1));[candidates[i],candidates[j]]=[candidates[j],candidates[i]];}
    const rank=m=>m.status==='due'?0:m.status==='new'?1:2;
    candidates.sort((a,b)=>rank(a.m)-rank(b.m)||String(a.m.due||'').localeCompare(String(b.m.due||'')));
    function spread(items) {
      const groups=new Map();for(const item of items){const key=item.card.field+':'+item.card.chapter_id;if(!groups.has(key))groups.set(key,[]);groups.get(key).push(item);}
      const result=[];while([...groups.values()].some(g=>g.length))for(const group of groups.values())if(group.length)result.push(group.shift());return result;
    }
    if(mode==='new')candidates=spread(candidates);
    else if(mode==='mixed') {const due=candidates.filter(p=>p.m.status==='due'),fresh=spread(candidates.filter(p=>p.m.status==='new'));candidates=[];while(due.length||fresh.length){candidates.push(...due.splice(0,4));if(fresh.length)candidates.push(fresh.shift());}}
    const sid=id();k.sessions.push({id:sid,request_id:body.request_id,field,chapter_id:chapter,mode,limit_count:limit,created_at:at,status:'active',cursor:1,items:candidates.slice(0,limit).map(({card},i)=>({position:i+1,card_id:card.id,draw_id:null}))});
    return sessionGet(sid);
  }
  match=path.match(/^\/api\/knowledge\/sessions\/([^/]+)(?:\/(position|end))?$/);
  if(match) {
    const sid=decodeURIComponent(match[1]),action=match[2];
    if(!action&&method==='GET')return sessionGet(sid);
    if(action==='end'&&method==='POST') {sessionGet(sid);const session=k.sessions.find(s=>s.id===sid);if(session.status==='active')session.status='ended';return sessionGet(sid);}
    if(action==='position'&&method==='PUT') {
      strict(['position']);integer(body.position,1,100);sessionGet(sid);const session=k.sessions.find(s=>s.id===sid),item=session.items.find(i=>i.position===body.position)||fail(404,'该位置不在这组复习内。');
      let draw=k.draws.find(d=>d.id===item.draw_id);
      if(!draw||!['pending','scored'].includes(draw.status)) {
        if(session.status!=='active')fail(409,'本组已结束，请从首页开始新一组。');
        draw=k.draws.find(d=>d.card_id===item.card_id&&d.status==='pending');
        if(!draw) {const card=cardCheck(item.card_id),saved=state(card.id),m=memory(saved),kind=m.status==='scheduled'?'practice':m.status==='new'?'new':'due';draw=makeDraw(card,kind,'session:'+sid+':'+body.position+':'+saved.revision);}
        item.draw_id=draw.id;
      }
      session.cursor=body.position;return sessionGet(sid);
    }
  }
  return undefined;
}
