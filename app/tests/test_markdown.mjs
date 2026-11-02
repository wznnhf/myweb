import test from 'node:test';
import assert from 'node:assert/strict';
import {renderMarkdown} from '../static/notes.js';

test('renders common Markdown and preserves plain-text line breaks', () => {
  const html = renderMarkdown('## 复盘\n\n**重点**\n下一行\n\n- [ ] 重做\n\n| 步骤 | 提醒 |\n| --- | --- |\n| 1 | 检查 |\n\n```js\nconst x = 1;\n```');
  for (const expected of ['<h2>复盘</h2>', '<strong>重点</strong>', '<br>', 'type="checkbox"', '<table>', '<pre><code']) {
    assert.ok(html.includes(expected), expected);
  }
});

test('renders local and remote images while rejecting executable URLs and raw HTML', () => {
  const safe = renderMarkdown('![草稿](/api/note-images/abc)\n\n![图片](https://example.com/image.png)');
  assert.ok(safe.includes('src="/api/note-images/abc"'));
  assert.ok(safe.includes('src="https://example.com/image.png"'));
  for (const url of ['javascript:alert%281%29', 'java&#x73;cript:alert%281%29', 'data:text/html;base64,PHNjcmlwdD4=', 'file:///etc/passwd', '//example.com/image']) {
    const html = renderMarkdown(`[链接](${url})\n\n![图片](${url})`);
    assert.ok(!html.includes('<a ') && !html.includes('<img '), url);
  }
  const html = renderMarkdown('<img src=x onerror=alert(1)>\n<script>alert(1)</script>\n<iframe srcdoc="bad"></iframe>');
  assert.ok(!/<(?:img|script|iframe)\b/i.test(html));
  assert.ok(html.includes('&lt;'));
});

test('image captions and link destinations cannot inject attributes', () => {
  const html = renderMarkdown('![" onerror="alert(1)](https://example.com/image.png)\n\n[链接](https://example.com/?x="onclick="bad)');
  assert.ok(html.includes('&quot;'));
  assert.ok(!/\sonerror="|\sonclick="/.test(html));
  assert.ok(html.includes('rel="noopener noreferrer"'));
});

test('renders the reported boxed matrix identities without losing backslashes', () => {
  const source = String.raw`特别记住这三个公式：
\[
\boxed{
A^TA=E,\qquad
A^{-1}=A^T,\qquad
|A|=\pm1
}
\]`;
  const html = renderMarkdown(source);
  assert.ok(html.includes('特别记住这三个公式：'));
  assert.equal((html.match(/class="katex"/g) || []).length, 1);
  assert.ok(html.includes('class="katex-display"'));
  assert.ok(!html.includes('katex-error'));
  for (const tex of [String.raw`\boxed`, String.raw`\qquad`, String.raw`\pm1`, 'A^{-1}']) assert.ok(html.includes(tex));
});

test('supports all four delimiters, multiline environments and mixed Markdown', () => {
  const source = String.raw`行内 $a_1^2$ 和 \(A^{-1}\)，**重点**。

$$\frac{1}{2}$$

\[
\begin{aligned}
a &= b \\
c &= d
\end{aligned}
\]

- 行内公式 $x+1$
> 引用公式 \(y=2\)`;
  const html = renderMarkdown(source);
  assert.equal((html.match(/class="katex"/g) || []).length, 6);
  assert.equal((html.match(/class="katex-display"/g) || []).length, 2);
  assert.ok(html.includes('<strong>重点</strong>'));
  assert.ok(!html.includes('katex-error'));
});

test('leaves code examples, escaped dollars and currency alone', () => {
  const html = renderMarkdown('`$a$` 和 `\\[b\\]`\n\n```latex\n$$c$$\n\\[d\\]\n```\n\n价格 $5 和 $10，字面量 \\$x\\$');
  assert.ok(!html.includes('class="katex"'));
  assert.ok(html.includes('<code>$a$</code>'));
});

test('invalid or untrusted TeX does not break the rest of the note or inject HTML', () => {
  const html = renderMarkdown(String.raw`\[\frac{\]

**其余笔记仍可读**

$\href{javascript:alert(1)}{点击}$

$\includegraphics{https://example.com/image}$

$\htmlStyle{background:red}{x}$`);
  assert.ok(html.includes('katex-error'));
  assert.ok(html.includes('<strong>其余笔记仍可读</strong>'));
  assert.ok(!/<a\s|<img\s|<script\b|background:red/.test(html.replace(/<annotation[\s\S]*?<\/annotation>/g, '')));
});
