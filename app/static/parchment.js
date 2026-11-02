// Native vector ink: no remote fonts, images, timers, or animation loops.
export function manuscriptArt(id='manuscript'){
 return `<svg class="manuscript-art" viewBox="0 0 540 390" fill="none" aria-hidden="true">
 <defs><clipPath id="${id}-ink"><rect class="ink-reveal" x="35" y="157" width="420" height="85"/></clipPath><pattern id="${id}-hatch" width="8" height="8" patternUnits="userSpaceOnUse"><path d="M0 8 8 0" stroke="currentColor" stroke-width=".6" opacity=".35"/></pattern></defs>
 <g class="manuscript-diagram" stroke="currentColor" stroke-width=".9"><path d="M85 143H425M117 158V25" opacity=".35"/><path d="m419 140 6 3-6 3m-305-115 3-6 3 6" opacity=".4"/><path d="M142 143C180 127 206 53 267 53S346 126 384 143Z" fill="url(#${id}-hatch)" stroke="none"/><path class="ink-curve" pathLength="1" d="M126 148C174 148 203 53 267 53S352 148 403 148" stroke-width="1.6"/><path d="M185 143V108M345 143V108" stroke-dasharray="3 5" opacity=".5"/><path d="M267 43V152" opacity=".2"/></g>
 <g fill="currentColor" font-family="Georgia, 'Times New Roman', serif" font-style="italic"><text x="431" y="149" font-size="15">x</text><text x="100" y="29" font-size="15">y</text><text x="178" y="162" font-size="14">a</text><text x="340" y="162" font-size="14">b</text><text x="304" y="60" font-size="19">y = f(x)</text>
 <g clip-path="url(#${id}-ink)"><text x="42" y="223" font-size="47">∫</text><text x="62" y="185" font-size="18">b</text><text x="56" y="239" font-size="18">a</text><text x="80" y="218" font-size="32">f(x) dx = F(b) − F(a)</text></g>
 <g class="manuscript-notes" opacity=".6"><text x="108" y="282" font-size="23">d</text><path d="M100 290h29" stroke="currentColor"/><text x="99" y="314" font-size="22">dx</text><text x="143" y="300" font-size="26">F(x) = f(x)</text><text x="358" y="330" font-size="16">Q.E.D.</text></g></g>
 <path class="ink-flourish" pathLength="1" d="M82 251c110-10 210-10 352-5m-111 67c26-8 61-9 98-3" stroke="currentColor" stroke-width="1" opacity=".45"/>
 <g class="writing-quill"><g class="quill-nib"><path d="M0 0C16-44 32-88 88-155 77-94 71-49 21-22Z" fill="#e7dbc1" stroke="#806e4c" stroke-width="1.1"/><path d="M0 0 88-155M20-35l-4-24m14 1-4-26m16 2-2-25m13 3 0-20m-21 72 29-13m-19-7 25-14m-16-8 21-12" stroke="#9b8660" stroke-width=".9"/><path d="m0 0 11-10-5-4Z" fill="#493a29"/><path d="M6-5 54-98" stroke="#655039" stroke-width="1.4"/></g></g>
 <circle class="ink-drop" cx="443" cy="230" r="2" fill="currentColor"/>
 </svg>`;
}

export function createParchmentBackdrop(){
 const backdrop=document.createElement('div');
 backdrop.className='parchment-backdrop';backdrop.setAttribute('aria-hidden','true');
 backdrop.innerHTML=`<div class="paper-fibres"></div><div class="margin-manuscript">${manuscriptArt('margin')}</div><span class="margin-equation equation-one">e<sup>iπ</sup> + 1 = 0</span><span class="margin-equation equation-two">lim<small>x→0</small> sin x / x = 1</span><div class="paper-dust"><i></i><i></i><i></i><i></i><i></i></div>`;
 document.body.prepend(backdrop);
}

export function mathHomeHTML({lib,collected,drafts,resume,paper,last,filter,esc,questionURL}){
 const count=lib.papers.reduce((sum,p)=>sum+p.question_count,0);
 return `<div class="page home-page math-manuscript"><div class="manuscript-masthead"><span>拾题 · 数学手稿</span><span>MATHEMATICA / VOL. II</span><span>一笔一划，皆有所得</span></div>
 <section class="manuscript-hero"><div class="manuscript-copy"><div class="eyebrow">一方纸，一支笔，一点新的思路</div><h1>在纸上，<br>慢慢<em>想明白。</em></h1><p class="lead">不必急着抵达答案。<br>让每一次推演，都成为下一次的灵光。</p><a class="manuscript-start" href="#math-archive">翻开今日习题 <span>↓</span></a><div class="stats"><div class="stat"><strong>${lib.papers.length}</strong><span>卷精选习题</span></div><div class="stat"><strong>${count.toLocaleString()}</strong><span>道待解之问</span></div><div class="stat"><strong>${collected}</strong><span>道珍藏错题</span></div></div></div>
 <div class="manuscript-aside"><span class="folio-note">关于积累，也关于豁然开朗。</span>${manuscriptArt('hero')}<span class="manuscript-caption">微小的变化，终会积成答案。<i>— ∫ —</i></span><span class="scholar-seal" aria-hidden="true">日拱<br>一卒</span></div></section>
 <div class="manuscript-bookmarks">${resume?`<a class="manuscript-resume" data-nav href="${questionURL(resume.id,paper?last.number:1)}"><span class="bookmark-number">Ⅰ</span><div><div class="eyebrow">${paper?'折页处 · 接上一次的思路':'启卷 · 从第一笔开始'}</div><h2>${esc(resume.title)}</h2><p>${paper?'上次读到第 '+last.number+' 题':'数学二 · 第一套练习'}</p></div><span class="bookmark-arrow">↗</span></a>`:''}<a class="manuscript-recall" data-nav href="/daily-review" aria-label="进入每日回顾"><span class="bookmark-number">Ⅱ</span><div><div class="eyebrow">温故 · 每日回顾</div><h2>旧题重读，另有新知。</h2><p>每天 5 道错题，把遗漏的思路拾回来。</p></div><span class="bookmark-arrow">↗</span></a></div>
 ${drafts.length?`<div class="pending-banner">有 ${drafts.length} 道题的笔记草稿等待保存。<a class="text-button" data-nav href="${questionURL(drafts[0].ref[0],drafts[0].ref[1])}">打开草稿 →</a></div>`:''}
 <section class="library-section" id="math-archive"><div class="section-head library-heading"><div><div class="eyebrow">THE COLLECTED PAPERS / 习题典藏</div><h2>翻一页，<em>落一笔。</em></h2><p>循序而行，或随心挑一卷。今天的思考，从这里开始。</p></div><span class="archive-years">${Math.min(...lib.papers.map(p=>p.year))}<span>—</span>${Math.max(...lib.papers.map(p=>p.year))}</span></div>
 <div class="toolbar"><div class="tabs" aria-label="难度筛选">${['全部',...new Set(lib.papers.map(p=>p.difficulty))].map(d=>`<button data-action="difficulty" data-value="${d}" class="${filter.difficulty===d?'active':''}">${d}${d==='全部'?'试卷':''}</button>`).join('')}</div><div class="filters"><input id="paper-search" type="search" placeholder="寻一卷：年份、老师、试卷名称" aria-label="搜索试卷" value="${esc(filter.search)}"><select id="year-filter" aria-label="年份筛选">${['全部年份',...new Set(lib.papers.map(p=>p.year).sort((a,b)=>b-a))].map(y=>`<option ${String(y)===filter.year?'selected':''}>${y}</option>`).join('')}</select></div></div><div class="library-index-head"><span id="result-count" class="small"></span><span>依建议顺序编目 · 每一卷都值得认真</span></div><div id="paper-grid" class="paper-grid"></div><div class="manuscript-endnote" aria-hidden="true">❦<span>纸短，思长。</span></div></section></div>`;
}
