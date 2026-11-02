"""Build the reviewed, local 2027 outline card catalog and auditable CSV exports.

Run with app/.venv/bin/python app/build_knowledge.py after editing source cards.
IDs depend on subject/chapter/source/title, never the question order or answer.
"""
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data/knowledge'
FIELDS = [('ds', '数据结构'), ('co', '计算机组成原理'),
          ('os', '操作系统'), ('net', '计算机网络')]


def build():
    cards, subjects, coverage = [], [], {}
    for field, label in FIELDS:
        chapters = []
        for line in (DATA / f'{field}.txt').read_text().splitlines():
            if not line or line.startswith('#'):
                continue
            if line.startswith('@'):
                chapter = line[1:]
                chapter_id = f'{field}-{len(chapters)+1:02d}'
                chapters.append(dict(id=chapter_id, title=chapter))
                continue
            page, source, title, prompt, answer, pitfall = line.split('|')
            assert all([source, title, prompt, answer, pitfall]) and 1 <= int(page) <= 20
            identity = f'{field}/{chapter}/{source}/{title}'
            card_id = field + '-' + hashlib.sha256(identity.encode()).hexdigest()[:12]
            card = dict(id=card_id, field=field, chapter_id=chapter_id, chapter=chapter,
                        title=title, prompt=prompt, answer=answer.split('；'), pitfall=pitfall,
                        source=source, pdf_page=int(page), printed_page=int(page)+3,
                        provenance='学习整理：自测问题与答案由大纲条目展开，并非大纲原文答案。')
            cards.append(card)
            coverage.setdefault((label, chapter, source, page), []).append(card)
        subjects.append(dict(id=field, title=label, chapters=chapters))
    assert len({c['id'] for c in cards}) == len(cards)
    assert sum(len(s['chapters']) for s in subjects) == 24
    catalog = dict(version=1, edition='2027', source='27考研408大纲-原文.pdf',
                   source_sha256=hashlib.sha256((DATA/'outline-2027.pdf').read_bytes()).hexdigest(),
                   subjects=subjects, cards=cards)
    (DATA/'catalog.json').write_text(json.dumps(catalog, ensure_ascii=False, indent=2)+'\n')
    output = ROOT/'output/knowledge'
    output.mkdir(parents=True, exist_ok=True)
    with (output/'408全部考点.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['编号', '科目', '章节', '大纲条目', 'PDF页', '印刷页', '标题', '自测问题', '答案要点', '易错点'])
        names = dict(FIELDS)
        for c in cards:
            writer.writerow([c['id'], names[c['field']], c['chapter'], c['source'], c['pdf_page'],
                             c['printed_page'], c['title'], c['prompt'], '；'.join(c['answer']), c['pitfall']])
    with (output/'408大纲覆盖表.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['科目', '章节', '大纲条目', 'PDF页', '卡片数', '对应卡片编号', '对应卡片标题'])
        for (field, chapter, source, page), rows in coverage.items():
            writer.writerow([field, chapter, source, page, len(rows),
                             ' / '.join(c['id'] for c in rows), ' / '.join(c['title'] for c in rows)])
    print(json.dumps({s['title']: sum(c['field']==s['id'] for c in cards) for s in subjects}, ensure_ascii=False))


if __name__ == '__main__':
    build()
