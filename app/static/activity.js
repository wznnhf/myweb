const iso = d => d.toISOString().slice(0,10);
const utc = s => new Date(s+'T00:00:00Z');
const add = (d,n) => new Date(d.getTime()+n*86400000);
export function createActivity({api,esc}) {
 function mount(root,subject,area='all'){
  if(!root||root.querySelector('.activity-panel'))return;
  const panel=document.createElement('section');panel.className='activity-panel';panel.setAttribute('aria-label','学习打卡日历');
  panel.innerHTML='<div class="activity-loading">正在整理学习足迹…</div>';
  const heading=root.querySelector(':scope > .hero, :scope > .section-head, :scope > .daily-top');
  if(heading)heading.after(panel);else root.prepend(panel);
  let sequence=0;
  async function load(year=''){
   const seq=++sequence;
   try{
    const data=await api(`/api/activity?subject=${subject}&area=${area}${year?'&year='+year:''}`);
    if(seq!==sequence||!panel.isConnected)return;
    render(data);
   }catch(e){if(seq===sequence&&panel.isConnected){panel.innerHTML=`<p class="small">学习足迹暂时没有加载成功。${esc(e.message)} <button class="text-button activity-retry">重试</button></p>`;panel.querySelector('button').onclick=()=>load(year)}}
  }
  function render(data){
   const start=utc(data.start),end=utc(data.end),monday=add(start,-((start.getUTCDay()+6)%7));
   const count=Math.ceil(((end-monday)/86400000+1)/7),map=new Map(data.days.map(d=>[d.day,d]));
   const weeks=[],months=[];
   let previousMonth=-1;
   for(let w=0;w<count;w++){
    const cells=[];
    for(let row=0;row<7;row++){
     const d=add(monday,w*7+row),key=iso(d),item=map.get(key);
     if(item&&d.getUTCMonth()!==previousMonth){const label={week:w,label:(d.getUTCMonth()+1)+'月'};if(months.at(-1)?.week===w)months[months.length-1]=label;else months.push(label);previousMonth=d.getUTCMonth()}
     cells.push(item?`<button type="button" class="activity-cell level-${item.level}${key===data.today?' is-today':''}${item.future?' is-future':''}" data-day="${key}" tabindex="${key===(data.today<data.end?data.today:data.end)?0:-1}" aria-label="${key} ${item.future?'尚未到来':`完成 ${item.count} 道题或考点`}" ${item.future?'disabled':''}></button>`:'<span class="activity-cell outside" aria-hidden="true"></span>');
    }
    weeks.push(`<div class="activity-week">${cells.join('')}</div>`);
   }
   panel.innerHTML=`<div class="activity-heading"><div><span class="activity-kicker">一点点积累，看得见</span><h2>学习足迹 <span>${data.total} 次练习</span></h2></div><div class="activity-controls"><span class="activity-scope">${subject==='408'?'408':'数学'} · ${esc(data.label)}</span><select aria-label="学习足迹年份"><option value="" ${data.year===null?'selected':''}>最近一年</option>${data.years.map(y=>`<option value="${y}" ${data.year===y?'selected':''}>${y} 年</option>`).join('')}</select></div></div><div class="activity-chart"><div class="activity-weekdays" aria-hidden="true"><span>一</span><span></span><span>三</span><span></span><span>五</span><span></span><span>日</span></div><div class="activity-scroll" tabindex="0" aria-label="按周排列的学习日历，可左右滚动"><div class="activity-canvas" style="--weeks:${count}"><div class="activity-months" aria-hidden="true">${months.map(m=>`<span style="grid-column:${m.week+1}">${m.label}</span>`).join('')}</div><div class="activity-weeks">${weeks.join('')}</div></div></div></div><div class="activity-footer"><p>已打卡 <strong>${data.active_days}</strong> 天<span>·</span>连续 <strong>${data.current_streak}</strong> 天<span>·</span>最长连续 <strong>${data.longest_streak}</strong> 天</p><div class="activity-legend" aria-label="颜色由浅到深：0、1至4、5至9、10至19、20道以上"><span>少</span>${[0,1,2,3,4].map((l)=>`<span class="activity-cell level-${l}" title="${['未练习','1–4 道','5–9 道','10–19 道','20 道及以上'][l]}"></span>`).join('')}<span>多</span></div></div><div class="activity-detail" role="status" aria-live="polite">${data.today_count?`今天已完成 ${data.today_count} 道题或考点。`:'做一道题，点亮今天。'}<span>${data.area==='all'?'同一天，同一道题跨板块也只记一次。':'同一天同一板块，同一道题只记一次。'}</span></div>`;
   panel.querySelector('select').onchange=e=>load(e.target.value);
   const detail=panel.querySelector('.activity-detail');
   const show=cell=>{
    const item=map.get(cell.dataset.day);if(!item)return;
    panel.querySelector('.activity-cell.is-selected')?.classList.remove('is-selected');cell.classList.add('is-selected');
    detail.innerHTML=`<strong>${item.day}</strong> ${item.count?'完成 '+item.count+' 道题或考点':'尚未记录练习'}${item.areas.length?'<span>'+item.areas.map(a=>esc(a.label)+' '+a.count).join(' · ')+'</span>':''}`;
   };
   const scroll=panel.querySelector('.activity-scroll');
   scroll.addEventListener('pointerover',e=>{const c=e.target.closest('button.activity-cell');if(c)show(c)});
   scroll.addEventListener('focusin',e=>{const c=e.target.closest('button.activity-cell');if(c){scroll.querySelector('[tabindex="0"]')?.setAttribute('tabindex','-1');c.tabIndex=0;show(c)}});
   scroll.addEventListener('click',e=>{const c=e.target.closest('button.activity-cell');if(c)show(c)});
   scroll.addEventListener('keydown',e=>{
    if(!e.target.matches('button.activity-cell'))return;
    const offset={ArrowLeft:-7,ArrowRight:7,ArrowUp:-1,ArrowDown:1}[e.key];if(!offset)return;
    const key=iso(add(utc(e.target.dataset.day),offset)),next=scroll.querySelector(`[data-day="${key}"]:not(:disabled)`);
    if(next){e.preventDefault();next.focus()}
   });
   requestAnimationFrame(()=>{if(panel.isConnected)scroll.scrollLeft=scroll.scrollWidth});
  }
  load();return panel;
 }
 return {mount};
}
