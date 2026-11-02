"""Import the October answer book, checking every chapter against detailed answers."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import shutil

import pypdfium2 as pdfium

ROOT = Path(__file__).resolve().parent
STARTS = [6, 14, 19, 31, 45, 56, 70, 83, 90, 107, 123, 127, 146,
          156, 170, 207, 228, 244, 260, 266, 271, 283, 296, 305, 313]
PATTERN = re.compile(r'(?<!\d)(\d{1,3})．\s*([①②③]?\s*[ABCD](?:[、,，\s]*[①②③]?\s*[ABCD])*)')


def run(source):
    book = json.loads((ROOT / 'data/relax-catalog.json').read_text())
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    doc = pdfium.PdfDocument(source)
    assert len(doc) == 312, '解析册页数与十月版本不符'
    pages = [p.get_textpage().get_text_range().replace('\r\n', '\n') for p in doc]
    papers, conflicts, report = {}, [], []
    for paper, start, stop in zip(book['papers'], STARTS, STARTS[1:]):
        quick = re.split('【(?:答案速对|速对答案)】', pages[start - 1])[1]
        quick = re.split(r'1[．.]\s*[ABCD]', quick)[0]
        tokens = re.findall(r'[（(]([ABCD]+)[）)]|([ABCD])', re.sub(r'\s', '', quick))
        keys = [a or b for a, b in tokens]
        assert len(keys) == paper['question_count'], (paper['id'], len(keys))
        details = {}
        for page_no in range(start, stop):
            for m in PATTERN.finditer(pages[page_no - 1]):
                n = int(m[1])
                if 1 <= n <= paper['question_count']:
                    assert n not in details, (paper['id'], n, 'duplicate')
                    details[n] = (''.join(re.findall('[ABCD]', m[2])), page_no)
        # The final OS overview explanation omits its question number in the PDF.
        if paper['field'] == 'os' and paper['chapter_order'] == 1:
            assert 'A。【解析】A 错误：这是微内核与外核' in pages[168]
            details[52] = ('A', 169)
        assert set(details) == set(range(1, len(keys) + 1)), (paper['id'], set(range(1, len(keys) + 1)) - set(details))
        answers = {}
        for n, quick_answer in enumerate(keys, 1):
            answer, page = details[n]
            assert 1 <= len(answer) <= 3
            if answer != quick_answer:
                conflicts.append(dict(paper_id=paper['id'], number=n, quick=quick_answer,
                                      detailed=answer, page=page, resolution='采用逐题解析'))
            next_page = details[n + 1][1] if n < len(keys) else stop - 1
            answers[str(n)] = dict(answer=answer, slots=len(answer), page=page,
                                   end_page=max(page, next_page))
        papers[paper['id']] = answers
        report.append(dict(paper_id=paper['id'], chapter=paper['chapter'], count=len(answers)))
    assert len(conflicts) == 3, conflicts
    dest = ROOT / 'data/sources' / f'relax-answers-{digest[:16]}.pdf'
    if not dest.exists():
        shutil.copyfile(source, dest)
    data = dict(title='27 Relax 1000题解析册 · 10月勘误版', sha256=digest,
                question_book_sha256=book['sha256'], source=str(dest.relative_to(ROOT)),
                total=sum(len(p) for p in papers.values()), papers=papers, conflicts=conflicts)
    (ROOT / 'data/relax-answers.json').write_text(json.dumps(data, ensure_ascii=False, indent=2))
    output = ROOT / 'output/relax-answers'
    output.mkdir(exist_ok=True)
    (output / 'import-report.json').write_text(json.dumps(dict(total=data['total'], chapters=report,
        conflicts=conflicts, multi_blank=[dict(paper_id=pid, number=int(n), answer=a['answer'])
            for pid, qs in papers.items() for n, a in qs.items() if a['slots'] > 1]), ensure_ascii=False, indent=2))
    print(json.dumps(dict(total=data['total'], conflicts=conflicts), ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    run(parser.parse_args().source)
