let catalogPromise;

async function loadCatalog() {
  if (!catalogPromise) {
    catalogPromise = fetch('/static/answers/index.json?v=2', {cache: 'no-cache'})
      .then(response => {
        if (!response.ok) throw new Error('答案资料加载失败，请重试。');
        return response.json();
      })
      .catch(error => { catalogPromise = null; throw error; });
  }
  return catalogPromise;
}

function answerImage(asset, number) {
  const img = document.createElement('img');
  img.className = 'answer-image';
  img.src = asset.url;
  img.alt = `第 ${number} 题参考答案`;
  img.width = asset.width;
  img.height = asset.height;
  img.style.width = `${asset.display_width || Math.round(asset.width / 2)}px`;
  img.style.setProperty('--answer-width', img.style.width);
  return img;
}

function openReader(paper, answer, number, originals, trigger) {
  const dialog = document.createElement('dialog');
  dialog.className = 'answer-reader';
  dialog.setAttribute('aria-label', originals ? '答案原页' : '答案放大阅读');
  const header = document.createElement('header');
  header.className = 'answer-reader-header';
  const title = document.createElement('div');
  const heading = document.createElement('h2');
  heading.textContent = `第 ${number} 题 · ${originals ? '答案原页' : '参考答案'}`;
  const subtitle = document.createElement('p');
  subtitle.textContent = paper.title;
  title.append(heading, subtitle);
  const controls = document.createElement('div');
  controls.className = 'answer-reader-controls';
  const zoom = document.createElement('button');
  zoom.type = 'button';
  zoom.className = 'button';
  zoom.textContent = '继续放大';
  zoom.setAttribute('aria-pressed', 'false');
  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'button';
  close.textContent = '关闭';
  close.addEventListener('click', () => dialog.close());
  controls.append(zoom, close);
  header.append(title, controls);
  const scroll = document.createElement('div');
  scroll.className = 'answer-reader-scroll';
  zoom.addEventListener('click', () => {
    const enlarged = scroll.classList.toggle('is-enlarged');
    zoom.textContent = enlarged ? '适应宽度' : '继续放大';
    zoom.setAttribute('aria-pressed', String(enlarged));
  });
  for (const asset of (originals ? answer.originals : answer.images) || []) {
    const figure = document.createElement('figure');
    figure.className = 'answer-reader-sheet';
    const label = document.createElement('figcaption');
    label.textContent = `${originals ? '原资料' : '参考答案'} · 第 ${asset.page || answer.pages[0]} 页`;
    const img = answerImage(asset, number);
    figure.append(label, img);
    scroll.append(figure);
  }
  dialog.append(header, scroll);
  dialog.addEventListener('close', () => {
    dialog.remove();
    if (trigger.isConnected) trigger.focus();
  }, {once: true});
  document.body.append(dialog);
  dialog.showModal();
  close.focus();
}

export function mountAnswer(container, paperId, number) {
  const details = document.createElement('details');
  details.className = 'question-answer';
  details.innerHTML = '<summary><span>答案</span><span class="answer-hint">做完后展开核对</span></summary><div class="answer-content" aria-live="polite"></div>';
  container.before(details);
  const content = details.querySelector('.answer-content');
  let loaded = false, loading = false;

  async function showAnswer() {
    if (loaded || loading) return;
    loading = true;
    content.textContent = '正在加载答案…';
    try {
      const catalog = await loadCatalog();
      if (!details.isConnected) return;
      const paper = catalog.papers[paperId];
      const answer = paper?.questions[String(number)];
      content.replaceChildren();
      if (!answer) {
        content.textContent = '暂未收录这道题的答案。';
        loaded = true;
        return;
      }
      const toolbar = document.createElement('div');
      toolbar.className = 'answer-toolbar';
      const label = document.createElement('span');
      label.className = 'answer-label';
      label.textContent = '参考答案';
      const tools = document.createElement('div');
      tools.className = 'answer-tools';
      for (const [caption, originals] of [['放大阅读', false], ['查看原页', true]]) {
        if (originals && !answer.originals?.length) continue;
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'answer-tool';
        button.textContent = caption;
        button.addEventListener('click', () => openReader(paper, answer, number, originals, button));
        tools.append(button);
      }
      toolbar.append(label, tools);
      content.append(toolbar);
      if (answer.text) {
        const text = document.createElement('p');
        text.className = 'answer-text';
        text.textContent = answer.text;
        content.append(text);
      }
      const pages = document.createElement('div');
      pages.className = 'answer-pages';
      for (const [index, asset] of (answer.images || []).entries()) {
        const figure = document.createElement('figure');
        figure.className = 'answer-sheet';
        if (answer.images.length > 1) {
          const caption = document.createElement('figcaption');
          caption.textContent = `${index ? '续页' : '答案'} · 原资料第 ${asset.page || answer.pages[index]} 页`;
          figure.append(caption);
        }
        const img = answerImage(asset, number);
        img.addEventListener('error', () => {
          loaded = false;
          img.replaceWith(document.createTextNode('答案图片加载失败，请收起后重新展开重试。'));
        });
        figure.append(img);
        pages.append(figure);
      }
      content.append(pages);
      const source = document.createElement('p');
      source.className = 'answer-source';
      source.textContent = `来源：${paper.source} · 第 ${answer.pages.join('、')} 页`;
      content.append(source);
      loaded = true;
    } catch (error) {
      content.textContent = error.message || '答案加载失败，请重试。';
      const retry = document.createElement('button');
      retry.type = 'button';
      retry.className = 'text-button';
      retry.textContent = '重新加载';
      retry.addEventListener('click', showAnswer);
      content.append(retry);
    } finally {
      loading = false;
    }
  }
  details.addEventListener('toggle', () => { if (details.open) showAnswer(); });
}
