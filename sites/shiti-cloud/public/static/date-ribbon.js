export function dateRibbon(day,esc) {
 const label=esc(day)+' · 北京时间';
 const item=`<span class="date-ribbon-item"><i aria-hidden="true"></i><time datetime="${esc(day)}">${label}</time></span>`;
 const group=`<span class="date-ribbon-group">${item}${item}</span>`;
 return `<div class="daily-date date-ribbon"><span class="date-ribbon-window" role="img" aria-label="${label}"><span class="date-ribbon-track" aria-hidden="true">${group}${group}</span></span><button class="date-ribbon-toggle" type="button" data-action="date-ribbon" aria-label="暂停日期滚动" aria-pressed="false" title="暂停日期滚动"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true"><path class="ribbon-pause" d="M5.5 4v8m5-8v8"/><path class="ribbon-play" d="m6 4 6 4-6 4z"/></svg></button></div>`;
}

export function toggleDateRibbon(button) {
 const paused=button.closest('.date-ribbon').classList.toggle('is-paused');
 const label=paused?'继续日期滚动':'暂停日期滚动';
 button.setAttribute('aria-pressed',String(paused));button.setAttribute('aria-label',label);button.title=label;
}
