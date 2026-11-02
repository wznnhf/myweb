// Selection feedback is independent of grading. A bloom confirms a saved choice.
export function createChoiceBloom() {
 const reduced=matchMedia('(prefers-reduced-motion: reduce)'),effects=new Set();
 let field;
 const moving=()=>!reduced.matches&&!document.body.classList.contains('cyber-still');
 function destroy(effect){
  for(const animation of effect.animations)animation.cancel();
  clearTimeout(effect.timer);effect.root?.remove();
  effect.button.classList.remove('is-choosing');effects.delete(effect);
  if(!effects.size){field?.remove();field=null}
 }
 function clear(){for(const effect of [...effects])destroy(effect)}
 function animate(effect,node,frames,options){
  const animation=node.animate(frames,{duration:950,easing:'cubic-bezier(.16,1,.3,1)',fill:'both',...options});
  effect.animations.push(animation);return animation;
 }
 function press(button,event){
  for(const old of [...effects])if(old.button===button)destroy(old);
  while(effects.size>=4)destroy(effects.values().next().value);
  const rect=button.getBoundingClientRect();
  const pointer=event?.detail>0&&event.clientX>=rect.left&&event.clientX<=rect.right&&event.clientY>=rect.top&&event.clientY<=rect.bottom;
  const effect={button,animations:[],x:pointer?event.clientX:rect.left+rect.width/2,
   y:pointer?event.clientY:rect.top+rect.height/2,rect,root:null,timer:null};
  effects.add(effect);button.classList.add('is-choosing');
  if(moving())animate(effect,button,[{scale:'1'},{scale:'.93',offset:.16},{scale:'1.045',offset:.55},{scale:'1'}],{duration:430});
  // A stalled or aborted request must not leave a charging effect behind.
  effect.timer=setTimeout(()=>destroy(effect),15000);
  return effect;
 }
 function confirm(effect){
  if(!effects.has(effect)||!effect.button.isConnected)return;
  effect.button.classList.remove('is-choosing');clearTimeout(effect.timer);
  if(!moving()){destroy(effect);return}
  field??=Object.assign(document.createElement('div'),{className:'choice-bloom-field'});
  field.setAttribute('aria-hidden','true');if(!field.isConnected)document.body.append(field);
  const root=document.createElement('div');root.className='choice-bloom';
  root.style.left=effect.x+'px';root.style.top=effect.y+'px';field.append(root);effect.root=root;
  const add=(className,text='')=>{const node=document.createElement('span');node.className=className;node.textContent=text;root.append(node);return node};
  const radius=innerWidth<700?68:106;
  const core=add('choice-bloom-core');
  animate(effect,core,[{opacity:.85,transform:'translate(-50%,-50%) scale(.3)'},{opacity:.45,offset:.25,transform:'translate(-50%,-50%) scale(2.4)'},{opacity:0,transform:'translate(-50%,-50%) scale(4)'}],{duration:520});
  for(let i=0;i<3;i++){
   const ring=add('choice-bloom-ring'+(i===2?' is-orbit':''));
   animate(effect,ring,[{opacity:.95,transform:'translate(-50%,-50%) rotate(0deg) scale(.08)'},
    {opacity:.6,offset:.32,transform:`translate(-50%,-50%) rotate(${i*35}deg) scale(.65)`},
    {opacity:0,transform:`translate(-50%,-50%) rotate(${100+i*80}deg) scale(1.65)`}],{duration:950+i*100,delay:i*65});
  }
  for(let i=0;i<10;i++){
   const petal=add('choice-bloom-petal'),angle=i*36+18;
   animate(effect,petal,[{opacity:0,transform:`translate(-50%,-50%) rotate(${angle}deg) translateY(-4px) scale(.1)`},
    {opacity:.95,offset:.16,transform:`translate(-50%,-50%) rotate(${angle}deg) translateY(-${radius*.35}px) scale(.8)`},
    {opacity:.75,offset:.54,transform:`translate(-50%,-50%) rotate(${angle+12}deg) translateY(-${radius*.75}px) scale(1)`},
    {opacity:0,transform:`translate(-50%,-50%) rotate(${angle+22}deg) translateY(-${radius}px) scale(.2)`}],{duration:1050+i%3*80,delay:i%2*35,easing:'cubic-bezier(.2,.7,.35,1)'});
  }
  for(let i=0;i<14;i++){
   const spark=add('choice-bloom-spark',i%4===0?'+' : i%4===1?'✦':''),angle=(i*137.5+Math.random()*18)*Math.PI/180;
   const distance=radius*(.7+Math.random()*.65),x=Math.cos(angle)*distance,y=Math.sin(angle)*distance;
   animate(effect,spark,[{opacity:0,transform:'translate(-50%,-50%) scale(.1)'},
    {opacity:1,offset:.12,transform:`translate(calc(-50% + ${x*.2}px),calc(-50% + ${y*.2}px)) scale(1)`},
    {opacity:0,transform:`translate(calc(-50% + ${x}px),calc(-50% + ${y}px)) rotate(${i*23}deg) scale(.25)`}],{duration:850+Math.random()*350,delay:20+i%3*35,easing:'cubic-bezier(.2,.7,.35,1)'});
  }
  const label=add('choice-bloom-label',effect.button.dataset.value+' / 已选中');
  label.style.left=(effect.rect.left+effect.rect.width/2-effect.x)+'px';
  label.style.top=(effect.rect.top-effect.y-12)+'px';
  animate(effect,label,[{opacity:0,transform:'translate(-50%,8px) scale(.85)'},{opacity:1,offset:.16,transform:'translate(-50%,-8px) scale(1)'},
   {opacity:1,offset:.6,transform:'translate(-50%,-14px) scale(1)'},{opacity:0,transform:'translate(-50%,-23px) scale(.98)'}],{duration:1150});
  animate(effect,effect.button.querySelector('strong'),[{scale:'.85',rotate:'-9deg'},{scale:'1.25',rotate:'3deg',offset:.4},{scale:'1',rotate:'0deg'}],{duration:650});
  effect.timer=setTimeout(()=>destroy(effect),1400);
 }
 function fail(effect){
  const button=effect.button;destroy(effect);
  if(moving()&&button.isConnected){const shake=button.animate([{translate:'0'},{translate:'-4px'},{translate:'4px'},{translate:'-2px'},{translate:'0'}],{duration:240});shake.finished.then(()=>shake.cancel(),()=>{})}
 }
 reduced.addEventListener('change',()=>{if(reduced.matches)clear()});
 new MutationObserver(()=>{if(!moving())clear()}).observe(document.body,{attributes:true,attributeFilter:['class']});
 document.addEventListener('visibilitychange',()=>{if(document.hidden)clear()});
 return {press,confirm,fail,clear};
}
