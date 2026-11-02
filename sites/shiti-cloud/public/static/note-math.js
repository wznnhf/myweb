import katex from './vendor/katex/katex.mjs';

const escapeHTML = value => value.replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));

function readMath(source, block = false) {
  const input = block ? source.replace(/^ {0,3}/, '') : source;
  let match = input.match(/^\\\[([\s\S]*?)\\\]/) || input.match(/^\$\$([\s\S]*?)\$\$/);
  const display = !!match;
  if (!match && !block) {
    match = input.match(/^\\\(([\s\S]*?)\\\)/)
      || input.match(/^\$(?!\s|\$)((?:\\[\s\S]|[^\\$\n])+?)(?<!\s)\$(?![\d$])/);
  }
  if (!match) return;
  const length = source.length - input.length + match[0].length;
  // A block must end on its own line; inline display math handles other cases.
  const ending = block ? source.slice(length).match(/^[ \t]*(?:\n|$)/) : null;
  if (block && !ending) return;
  return {raw: source.slice(0, length + (ending?.[0].length || 0)), text:match[1], display};
}

function renderMath(token, block) {
  let rendered;
  try {
    rendered = katex.renderToString(token.text, {
      displayMode:token.display, throwOnError:false, trust:false,
      strict:'ignore', maxExpand:1000, maxSize:20, macros:{},
    });
  } catch {
    rendered = `<span class="note-math-error" title="公式未能解析，请检查 LaTeX 写法">${escapeHTML(token.raw)}</span>`;
  }
  const tag = block ? 'div' : 'span';
  return `<${tag} class="${token.display ? 'note-math-block' : 'note-math-inline'}"${token.display ? ' tabindex="0" role="region" aria-label="数学公式，可横向滚动"' : ''}>${rendered}</${tag}>`;
}

// Tokenize before Markdown consumes backslashes, underscores, or asterisks.
// Code spans and fenced code blocks remain code, without formula rendering.
export const mathExtensions = {
  extensions:[{
    name:'noteMathBlock', level:'block',
    start(source) { return source.match(/^ {0,3}(?:\\\[|\$\$)/m)?.index; },
    tokenizer(source) {
      const math = readMath(source, true);
      if (math) return {type:'noteMathBlock', ...math};
    },
    renderer(token) { return renderMath(token, true) + '\n'; },
  }, {
    name:'noteMathInline', level:'inline',
    start(source) { return source.match(/\\[\[(]|\$/)?.index; },
    tokenizer(source) {
      const math = readMath(source);
      if (math) return {type:'noteMathInline', ...math};
    },
    renderer(token) { return renderMath(token, false); },
  }],
};
