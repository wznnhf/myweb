import {createParchmentBackdrop} from './parchment.js?v=1';
// Shared study environment. Animation pauses off-screen or on request.
export function createCyber(){
 const reduced=matchMedia('(prefers-reduced-motion: reduce)');
 let mode='',enabled=true,frame=0,last=0,drops=[],width=0,height=0;
 const initial=new URL(location.href),path=initial.pathname,params=initial.searchParams;
 let subject=document.body.dataset.subject||'math';
 createParchmentBackdrop();
 try{enabled=localStorage.getItem('cuoti-cyber-motion')!=='off'}catch{}
 const backdrop=document.createElement('div');backdrop.className='cyber-backdrop';backdrop.setAttribute('aria-hidden','true');
 const canvas=document.createElement('canvas');canvas.className='cyber-matrix';backdrop.append(canvas);document.body.prepend(backdrop);
 const hud=document.createElement('div');hud.className='cyber-hud';hud.innerHTML='<span class="cyber-hud-label"><i></i> NEURAL LINK / 专注空间</span><button type="button" aria-pressed="true" class="cyber-motion-toggle"></button>';
 document.body.append(hud);
 const header=document.querySelector('.topbar'),subjects=document.querySelector('.subject-bar');
 header.insertBefore(subjects,header.querySelector('.sidebar-bottom'));
 const button=hud.querySelector('button'),ctx=canvas.getContext('2d');
 function resize(){
  width=innerWidth;height=innerHeight;const scale=Math.min(devicePixelRatio||1,1.5);canvas.width=width*scale;canvas.height=height*scale;ctx.setTransform(scale,0,0,scale,0,0);ctx.clearRect(0,0,width,height);
  const rail=width<700?18:width<1100?36:64,step=14;drops=[];
  for(const start of [4,width-rail])for(let x=start;x<start+rail;x+=step)drops.push({x,y:Math.random()*height,speed:12+Math.random()*25,length:9+Math.floor(Math.random()*19)});
 }
 const chars='01ABCDEF<>/{}[]アイウエオカキクケコ';
 function draw(t){
  if(subject==='math'||!mode||!enabled||reduced.matches||document.hidden){frame=0;return}
  frame=requestAnimationFrame(draw);if(t-last<45)return;last=t;ctx.clearRect(0,0,width,height);ctx.font='12px monospace';
  for(const d of drops){
   d.y+=d.speed*.65;if(d.y-d.length*16>height)d.y=-20;
   for(let j=0;j<d.length;j++){const y=d.y-j*16;if(y<0||y>height)continue;ctx.fillStyle=j===0?'#d8ffb2':`rgba(134,255,37,${Math.max(.04,.6-j/d.length*.6)})`;ctx.fillText(chars[Math.floor(Math.random()*chars.length)],d.x,y)}
  }
 }
 function sync(){
  cancelAnimationFrame(frame);frame=0;
  const moving=enabled&&!reduced.matches;document.body.classList.toggle('cyber-still',!moving);document.body.classList.toggle('page-hidden',document.hidden);button.textContent=moving?(subject==='math'?'Ⅱ 暂歇笔墨':'Ⅱ 暂停动效'):(subject==='math'?'▷ 续写笔墨':'▷ 开启动效');button.setAttribute('aria-pressed',String(moving));
  if(subject!=='math'&&mode&&moving&&!document.hidden)frame=requestAnimationFrame(draw);else ctx.clearRect(0,0,width,height);
 }
 button.addEventListener('click',()=>{enabled=!enabled;try{localStorage.setItem('cuoti-cyber-motion',enabled?'on':'off')}catch{}sync()});
 reduced.addEventListener('change',sync);document.addEventListener('visibilitychange',sync);window.addEventListener('resize',resize);resize();
 function setMode(next){
  next=next||'library';const changed=mode!==next;mode=next;document.body.classList.add('cyber-mode');document.body.dataset.focus=mode;
  const labels=subject==='math'?{library:'案头札记 / 数学二',reader:'静心推演 / 解题手稿',mistakes:'拾遗集 / 错题重读',review:'温故知新 / 每日回顾'}:{library:'STUDY FIELD / 自习主场',reader:'DEEP WORK / 解题现场',mistakes:'ERROR ARCHIVE / 错题档案',review:'RECALL LOOP / 每日回顾',practice:'DAILY PROTOCOL / 每日一练',knowledge:'MEMORY DRIVE / 考点抽奖机'};
  hud.querySelector('.cyber-hud-label').innerHTML='<i></i>'+(labels[mode]||labels.library);
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content',subject==='math'?'#ede3cd':'#070b0c');
  if(changed){sync();if(mode&&enabled&&!reduced.matches){document.body.classList.remove('cyber-boot');void document.body.offsetWidth;document.body.classList.add('cyber-boot');setTimeout(()=>document.body.classList.remove('cyber-boot'),850)}}
 }
 setMode(path==='/knowledge-draw'?'knowledge':path==='/daily-practice'||params.has('practice')?'practice':path==='/daily-review'||params.has('daily')?'review':path.startsWith('/mistakes')||params.has('folder')?'mistakes':path.startsWith('/papers/')?'reader':'library');
 return {setMode,setSubject(next){if(subject===next)return;subject=next;document.body.classList.toggle('parchment-mode',subject==='math');setMode(mode);sync()}};
}
