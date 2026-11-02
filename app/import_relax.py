"""Import the versioned Relax book without retyping formulas or changing paper catalogs."""
from __future__ import annotations

import argparse
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import shutil

import pdfplumber
import pypdfium2 as pdfium
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
SCALE = 220 / 72
FIELDS = [
    ('ds', '数据结构', [6, 11, 16, 24, 34, 46, 55, 65],
     ['绪论', '线性表', '栈、队列、数组、字符串', '树', '图', '查找', '排序'],
     ['1', '2', '3、4', '5', '6', '7', '8'], [26, 31, 64, 82, 65, 65, 78]),
    ('co', '计算机组成原理', [66, 71, 81, 95, 101, 114, 121],
     ['计算机系统概述', '数据的表示和运算', '存储器层次结构', '指令系统', '中央处理器（CPU）', '总线和输入/输出系统'],
     ['1', '2', '3', '4', '5', '6'], [35, 89, 79, 43, 86, 41]),
    ('os', '操作系统', [122, 131, 156, 171, 186, 199],
     ['计算机系统概述', '进程管理', '内存管理', '文件管理', '输入/输出管理'],
     ['1', '2', '3', '4', '5'], [52, 131, 79, 81, 74]),
    ('cn', '计算机网络', [200, 205, 211, 225, 240, 246, 253],
     ['绪论', '物理层', '数据链路层', '网络层', '传输层', '应用层'],
     ['1', '2', '3', '4', '5', '6'], [37, 45, 96, 101, 49, 47]),
]


def run(source: Path, anchors_only=False):
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    dest = ROOT / 'data/sources' / f'relax-{digest[:16]}.pdf'
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        shutil.copyfile(source, dest)
    output = ROOT / 'output/relax-import'
    output.mkdir(parents=True, exist_ok=True)
    renderer = pdfium.PdfDocument(dest)
    papers, report = [], dict(sha256=digest, chapters=[], boundary_warnings=[])

    @lru_cache(maxsize=3)
    def bitmap(page):
        return renderer[page - 1].render(scale=SCALE).to_pil().convert('RGB')

    with pdfplumber.open(dest) as doc:
        for field, field_label, bounds, names, chapter_numbers, counts in FIELDS:
            for index, (start, stop) in enumerate(zip(bounds, bounds[1:])):
                pid = f'relax-{digest[:16]}-{field}-{index + 1}'
                chapter = f'第 {chapter_numbers[index]} 章 {names[index]}'
                anchors, page_objects = [], {}
                for page_no in range(start, stop):
                    page = doc.pages[page_no - 1]
                    # The large diagonal watermark is separate from the real text.
                    clean = page.filter(lambda o: o.get('object_type') != 'char' or
                                        (o.get('upright', True) and o.get('size', 0) < 30))
                    objects = [(c['top'], c['bottom']) for c in clean.chars
                               if c['text'].strip() and 50 < c['x0'] < 550 and 70 < c['top'] < 790]
                    objects += [(max(70, o['top']), min(790, o['bottom'])) for o in [*page.images, *page.lines, *page.rects, *page.curves]
                                if 50 < o['x0'] < 550 and o['top'] < 790 and o['bottom'] > 70 and o['bottom'] - o['top'] > 1]
                    page_objects[page_no] = objects
                    for word in clean.extract_words():
                        match = re.match(r'^(\d{1,3})[．.]', word['text'])
                        if not match or not 70 < word['x0'] < 96 or not 70 < word['top'] < 790:
                            continue
                        number = int(match[1])
                        if number != len(anchors) + 1:
                            # Numbered statements inside a question are not new questions.
                            continue
                        candidates = [word['top'] - d / 2 for d in range(4, 31)]
                        safe = [y for y in candidates if not any(a - .4 <= y <= b + .4 for a, b in objects)]
                        cut = max(safe) if safe else word['top'] - 2
                        if not safe:
                            report['boundary_warnings'].append(dict(paper_id=pid, number=number, page=page_no))
                        anchors.append((number, page_no, cut))
                if len(anchors) != counts[index]:
                    raise ValueError(f'{field} {chapter}: {len(anchors)} != {counts[index]}')
                report['chapters'].append(dict(id=pid, chapter=chapter, field=field, count=len(anchors), anchors=anchors))
                print(field, chapter, len(anchors), 'anchors OK', flush=True)
                if anchors_only:
                    continue
                directory = ROOT / 'data/questions' / pid
                directory.mkdir(parents=True, exist_ok=True)
                questions = []
                for j, (number, first_page, top) in enumerate(anchors):
                    next_anchor = anchors[j + 1] if j + 1 < len(anchors) else None
                    last_page = next_anchor[1] if next_anchor else stop - 1
                    pieces, segments = [], []
                    for page_no in range(first_page, last_page + 1):
                        y0 = top if page_no == first_page else 70
                        y1 = next_anchor[2] if next_anchor and page_no == last_page else 790
                        if y1 <= y0 + 1:
                            continue
                        # Ignore empty end pages; retain everything around dark source ink.
                        occupied = [(a, b) for a, b in page_objects[page_no] if a >= y0 and b <= y1]
                        if not occupied:
                            continue
                        y0 = max(y0, min(a for a, _ in occupied) - 4)
                        y1 = min(y1, max(b for _, b in occupied) + 5)
                        box = [50, round(y0, 2), 550, round(y1, 2)]
                        image = bitmap(page_no)
                        piece = image.crop(tuple(round(v * SCALE) for v in box))
                        pieces.append(piece)
                        segments.append(dict(page=page_no, book_page=page_no - 4, column=1, box=box))
                    if not pieces:
                        raise ValueError(f'Empty question {pid}/{number}')
                    canvas = Image.new('RGB', (max(p.width for p in pieces) + 32,
                                              sum(p.height for p in pieces) + 20 * (len(pieces) - 1) + 32), 'white')
                    offset = 16
                    for piece in pieces:
                        canvas.paste(piece, (16, offset))
                        offset += piece.height + 20
                    canvas.save(directory / f'{number}.png')
                    questions.append(dict(number=number, type='选择题', image=f'/assets/questions/{pid}/{number}.png',
                                          width=canvas.width, height=canvas.height, segments=segments, warning=None))
                papers.append(dict(id=pid, title=f'Relax 1000题 · {field_label} · {chapter}', subject='408',
                                   source_kind='exercise_book', book_version=digest, field=field, field_label=field_label,
                                   chapter=chapter, chapter_order=index + 1, order=1000 + len(papers), year=2027,
                                   difficulty='专项练习', source=str(dest.relative_to(ROOT.parent)), sha256=digest,
                                   question_count=len(questions), questions=questions))
                # One contact sheet per chapter: first, last, and every cross-page question.
                samples = [q for q in questions if q['number'] in (1, len(questions)) or len(q['segments']) > 1]
                width, cell = 1050, 260
                sheet = Image.new('RGB', (width, ((len(samples) + 2) // 3) * cell), '#eeeeee')
                draw = ImageDraw.Draw(sheet)
                for k, q in enumerate(samples):
                    image = Image.open(directory / f'{q["number"]}.png')
                    image.thumbnail((340, 225))
                    x, y = k % 3 * 350 + 5, k // 3 * cell
                    draw.text((x, y + 3), f'{field} ch{index+1} Q{q["number"]} pages {[s["page"] for s in q["segments"]]}', fill='black')
                    sheet.paste(image, (x, y + 25))
                sheet.save(output / f'{field}-{index+1}.jpg')
                print('  rendered', len(questions), 'questions', flush=True)
    renderer.close()
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    if not anchors_only:
        catalog = dict(version=1, title='27 Relax 1000题 · 7.29勘误版', sha256=digest, papers=papers)
        assert sum(p['question_count'] for p in papers) == 1576
        target = ROOT / 'data/relax-catalog.json'
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(catalog, ensure_ascii=False, indent=2))
        temporary.replace(target)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('--anchors-only', action='store_true')
    args = parser.parse_args()
    run(args.source, args.anchors_only)
