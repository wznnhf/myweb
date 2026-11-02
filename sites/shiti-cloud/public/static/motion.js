// Keep route loading separate from presentation: the previous page stays in place
// until its replacement is ready, and only the latest navigation may commit.
export function transitionBetween(from, to) {
 const a=new URL(from||to,location.origin),b=new URL(to,location.origin);
 const reader=/^\/papers\/([^/]+)\/questions\/(\d+)$/;
 const x=a.pathname.match(reader),y=b.pathname.match(reader);
 if(x&&y){
  const sameSession=['practice','daily'].some(k=>a.searchParams.has(k)&&a.searchParams.get(k)===b.searchParams.get(k)&&a.searchParams.get('day')===b.searchParams.get('day'));
  const delta=sameSession?Number(b.searchParams.get('position'))-Number(a.searchParams.get('position')):x[1]===y[1]?Number(y[2])-Number(x[2]):0;
  return {kind:'question',direction:Math.sign(delta)||1};
 }
 return {kind:a.searchParams.get('subject')!==b.searchParams.get('subject')?'subject':'page',direction:1};
}

export function createMotion(app) {
 const reduced=matchMedia('(prefers-reduced-motion: reduce)'),ease='cubic-bezier(.22, 1, .36, 1)';
 const animations=new Set(),entered=new WeakSet(),revealed=new WeakSet();
 let cycle=0,timer,observer;
 const progress=document.createElement('div');progress.className='route-progress';progress.setAttribute('aria-hidden','true');document.body.append(progress);
 function animate(el,frames,options={}){
  if(!el||reduced.matches||!el.animate)return null;
  const animation=el.animate(frames,{duration:380,easing:ease,fill:'backwards',...options});animations.add(animation);
  animation.finished.catch(()=>{}).finally(()=>{animations.delete(animation);animation.cancel()});
  return animation;
 }
 function cancel(){for(const a of animations)a.cancel();animations.clear()}
 reduced.addEventListener('change',()=>{cancel();if(reduced.matches)observer?.disconnect()});
 const cards='.paper-card,.mistake-card,.daily-card,.practice-subject,.kd-machine,.kd-catalog-card,.daily-banner,.continue-card,.daily-progress,.practice-welcome';
 function reveal(el,index=0){
  if(revealed.has(el))return;revealed.add(el);
  animate(el,[{opacity:0,transform:'translateY(14px)'},{opacity:1,transform:'translateY(0)'}],{duration:460,delay:Math.min(index*35,175)});
 }
 function watchCards(root){
  let index=0;
  for(const el of root.querySelectorAll(cards)){
   if(revealed.has(el))continue;
   const rect=el.getBoundingClientRect();
   if(rect.top<innerHeight+30&&rect.bottom>0)reveal(el,index++);
   else if(observer)observer.observe(el);
  }
 }
 function enter(root,transition={kind:'page',direction:1}){
  if(!root||entered.has(root))return;entered.add(root);observer?.disconnect();
  if(reduced.matches)return;
  observer=typeof IntersectionObserver==='function'?new IntersectionObserver(entries=>{
   let index=0;for(const entry of entries)if(entry.isIntersecting){reveal(entry.target,index++);observer.unobserve(entry.target)}
  },{threshold:.06}):null;
  const offset=transition.kind==='question'?`translateX(${transition.direction*18}px)`:'translateY(12px)';
  animate(root,[{opacity:0,transform:offset},{opacity:1,transform:'translate(0,0)'}],{duration:transition.kind==='question'?280:360});
  // Reader panels move as one surface, keeping question text stable and legible.
  if(!root.classList.contains('reader-page'))watchCards(root);
 }
 new MutationObserver(records=>{
  let changed=false;
  for(const record of records)for(const node of record.addedNodes){
   if(node.nodeType!==1)continue;
   if(node.parentElement===app){enter(node);changed=true}
   else if(node.matches('.activity-chart,.kd-study'))animate(node,[{opacity:0,transform:'translateY(6px)'},{opacity:1,transform:'translateY(0)'}]);
   else if(node.matches(cards)||node.querySelector(cards))changed=true;
  }
  if(changed){const root=app.firstElementChild;if(root&&!root.classList.contains('reader-page'))watchCards(root)}
 }).observe(app,{childList:true,subtree:true});

 // A shared highlight travels between destinations instead of blinking on/off.
 const nav=document.querySelector('.topbar nav'),indicator=document.createElement('span');
 indicator.className='nav-indicator';indicator.setAttribute('aria-hidden','true');nav.prepend(indicator);
 let navReady=false;
 function placeIndicator(){
  const link=nav.querySelector('a.active');if(!link){if(!indicator.hidden)indicator.hidden=true;return}
  if(indicator.hidden)indicator.hidden=false;
  Object.assign(indicator.style,{width:link.offsetWidth+'px',height:link.offsetHeight+'px',transform:`translate(${link.offsetLeft}px,${link.offsetTop}px)`});
  if(!navReady){navReady=true;requestAnimationFrame(()=>nav.classList.add('motion-nav'))}
 }
 new MutationObserver(placeIndicator).observe(nav,{subtree:true,attributes:true,attributeFilter:['class','hidden']});
 new ResizeObserver(placeIndicator).observe(nav);window.addEventListener('resize',placeIndicator);
 placeIndicator();

 return {
  begin(transition){
   const id=++cycle;cancel();clearTimeout(timer);progress.classList.remove('visible');
   const restoreFocus=app.contains(document.activeElement);
   app.inert=true;app.setAttribute('aria-busy','true');
   timer=setTimeout(()=>{if(id===cycle)progress.classList.add('visible')},180);
   return {id,transition,restoreFocus};
  },
  async commit(ticket,draw,{scrollTop=false}={}){
   if(ticket.id!==cycle)return;
   const old=app.firstElementChild;
   if(old?.classList.contains('page')||old?.classList.contains('page-error')){
    const offset=ticket.transition.kind==='question'?`translateX(${-ticket.transition.direction*10}px)`:'translateY(-5px)';
    const leave=animate(old,[{opacity:1,transform:'translate(0,0)'},{opacity:0,transform:offset}],{duration:100,fill:'forwards'});
    if(leave)await leave.finished.catch(()=>{});
   }
   if(ticket.id!==cycle)return;
   try{
    const pending=draw();
    if(scrollTop)window.scrollTo({top:0,behavior:'instant'});
    enter(app.firstElementChild,ticket.transition);
    await pending;
   }finally{
    if(ticket.id===cycle){
     app.inert=false;app.removeAttribute('aria-busy');clearTimeout(timer);progress.classList.remove('visible');
     if(ticket.restoreFocus)app.focus({preventScroll:true});
    }
   }
  }
 };
}
