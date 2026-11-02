"""Check real rendered ink omitted between book question crops, including equations.

PDF text bounding boxes can overlap the next question even where the rendered
formula does not. Pixel checks complement the chapter/number checks in the importer.
"""
from collections import defaultdict
import json
from pathlib import Path

import pypdfium2 as pdfium

ROOT = Path(__file__).resolve().parent


def run():
    catalog = json.loads((ROOT / 'data/relax-catalog.json').read_text())
    report = json.loads((ROOT / 'output/relax-import/report.json').read_text())
    covered, starts, labels = defaultdict(list), {}, {}
    for p in catalog['papers']:
        for q in p['questions']:
            for segment in q['segments']:
                covered[segment['page']].append(segment['box'])
                labels[segment['page']] = p['id']
    for chapter in report['chapters']:
        first = chapter['anchors'][0]
        starts[first[1]] = first[2]
    source = ROOT.parent / catalog['papers'][0]['source']
    doc = pdfium.PdfDocument(source)
    issues = []
    for page, boxes in sorted(covered.items()):
        im = doc[page-1].render(scale=2).to_pil().convert('RGB')
        gray = im.convert('L')
        for y in range(round(starts.get(page, 70) * 2), 790 * 2):
            # The one-pixel tolerance accounts for rounding at crop boundaries.
            if any(round(b[1] * 2) - 1 <= y <= round(b[3] * 2) + 1 for b in boxes):
                continue
            ink = gray.crop((100, y, 1100, y+1)).histogram()
            if sum(ink[:150]) > 4:
                issues.append(dict(page=page, row=y / 2, ink_pixels=sum(ink[:150])))
    doc.close()
    result = dict(sha256=catalog['sha256'], pages_checked=len(covered),
                  questions_checked=sum(p['question_count'] for p in catalog['papers']),
                  missing_ink_rows=issues)
    (ROOT / 'output/relax-import/pixel-audit.json').write_text(json.dumps(result, indent=2))
    print(json.dumps({**result, 'missing_ink_rows': len(issues)}, ensure_ascii=False))
    if issues:
        raise SystemExit('Uncovered source ink requires visual review')


if __name__ == '__main__':
    run()
