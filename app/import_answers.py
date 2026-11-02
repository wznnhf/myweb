"""Rebuild complete, comfortably spaced answer images from local source PDFs.

Writes only generated assets; question images and study records are independent.
Run: app/.venv/bin/python app/import_answers.py
"""
from __future__ import annotations
import argparse
import hashlib
import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent
SCALE = 3
ASSET_VERSION = 'v2'


def ink_groups(image, left=0, right=None):
    """Keep fractions and matrices together by bridging small internal gaps."""
    pixels = np.asarray(image.convert('L'))[:, left:right]
    occupied = np.flatnonzero((pixels < 205).sum(axis=1) > 1)
    if not len(occupied):
        return []
    breaks = np.flatnonzero(np.diff(occupied) > round(SCALE*2.2))
    starts = np.r_[occupied[0], occupied[breaks+1]]
    ends = np.r_[occupied[breaks]+1, occupied[-1]+1]
    return list(zip(starts.tolist(), ends.tolist()))


def marker_group(groups, marker, height):
    center = (marker[0]+min(marker[1], .026)/2)*height
    return min(groups, key=lambda pair: max(pair[0]-center, center-pair[1], 0))


def preserve_boundary(groups, boundary, side):
    for a, b in groups:
        if a < boundary < b:
            return a if side == 'top' else b
    return boundary


def spacious_piece(piece):
    """Add vertical space between complete printed lines, never inside formulas."""
    ink = piece.convert('L').point(lambda p: 255 if p < 205 else 0).getbbox()
    if not ink:
        return None
    a, b, c, d = ink
    piece = piece.crop((max(0, a-12), max(0, b-12), min(piece.width, c+12), min(piece.height, d+12)))
    groups = ink_groups(piece)
    # Increase only genuine paragraph/line gaps. Very small gaps belong to math.
    cuts = [(groups[i][1]+groups[i+1][0])//2 for i in range(len(groups)-1)
            if groups[i+1][0]-groups[i][1] >= SCALE*3.5]
    extra = round(SCALE*4)
    canvas = Image.new('RGB', (piece.width, piece.height+extra*len(cuts)), 'white')
    top = y = 0
    for cut in cuts+[piece.height]:
        band = piece.crop((0, top, piece.width, cut))
        canvas.paste(band, (0, y))
        y += band.height+extra
        top = cut
    return ImageOps.expand(canvas, border=round(SCALE*12), fill='white')


def import_answers(keys=None):
    manifest = json.loads((ROOT/'data/answer-sources.json').read_text())
    catalog = json.loads((ROOT/'data/catalog.json').read_text())
    papers = {p['title']:p for p in catalog['papers'] if p.get('subject','math') == 'math'}
    output = ROOT/'static/answers'
    output.mkdir(parents=True, exist_ok=True)
    result = json.loads((output/'index.json').read_text()) if keys else {'version':2,'papers':{}}
    result['version'] = 2
    sources = {}
    for entry in manifest:
        if not keys or entry['key'] in keys:
            sources.setdefault(entry['source'], []).append(entry)
    for source, entries in sources.items():
        path = ROOT.parent/source
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        document = pdfium.PdfDocument(path)
        original_dir = output/'pages-v2'/digest[:12]
        original_dir.mkdir(parents=True, exist_ok=True)

        @lru_cache(maxsize=4)
        def page_image(number):
            page = document[number-1]
            bitmap = page.render(scale=SCALE)
            image = bitmap.to_pil().convert('RGB')
            bitmap.close();page.close()
            return image

        @lru_cache(maxsize=12)
        def page_groups(number, left, right):
            return ink_groups(page_image(number), left, right)

        def original_asset(number):
            image = page_image(number)
            target = original_dir/f'{number}.webp'
            if not target.exists():
                image.save(target, format='WEBP', quality=92, method=3)
            return {'url':f'/static/answers/pages-v2/{digest[:12]}/{number}.webp',
                    'page':number,'width':image.width,'height':image.height}

        for entry in entries:
            paper = papers[entry['title']]
            target = output/ASSET_VERSION/paper['id']
            target.mkdir(parents=True, exist_ok=True)
            answers = {}
            for number, question in entry['questions'].items():
                assets = [];used_pages = []
                for segment in question['segments']:
                    image = page_image(segment['page'])
                    x0,y0,x1,y1 = segment['box']
                    left,right = round(x0*image.width),round(x1*image.width)
                    top,bottom = round(y0*image.height),round(y1*image.height)
                    groups = page_groups(segment['page'],left,right)
                    if not groups:
                        continue
                    if segment.get('top_marker'):
                        group = marker_group(groups,segment['top_marker'],image.height)
                        top = group[0]-round(SCALE*2)
                        if segment.get('single_line'):
                            bottom = group[1]+round(SCALE*2)
                    else:
                        top = preserve_boundary(groups,top,'top')-round(SCALE*1.5)
                    if segment.get('bottom_marker') and not segment.get('single_line'):
                        bottom = marker_group(groups,segment['bottom_marker'],image.height)[0]-round(SCALE*2)
                    elif not segment.get('single_line'):
                        bottom = preserve_boundary(groups,bottom,'bottom')+round(SCALE*1.5)
                    if bottom <= top:
                        # Adjacent OCR labels can share a line group. Retain the
                        # complete group instead of producing a truncated answer.
                        bottom = preserve_boundary(groups,round(y1*image.height),'bottom')+round(SCALE*2)
                    piece = spacious_piece(image.crop((max(0,left),max(0,top),min(image.width,right),min(image.height,bottom))))
                    if piece is None:
                        continue
                    filename = f'{number}-{len(assets)+1}.webp'
                    temporary = target/(filename+'.tmp')
                    piece.save(temporary,format='WEBP',quality=94,method=3)
                    temporary.replace(target/filename)
                    assets.append({'url':f'/static/answers/{ASSET_VERSION}/{paper["id"]}/{filename}',
                                   'width':piece.width,'height':piece.height,'page':segment['page'],
                                   'display_width':round(piece.width/SCALE*1.65)})
                    used_pages.append(segment['page'])
                if not assets:
                    raise ValueError(f'Empty answer: {entry["title"]} #{number}')
                pages = list(dict.fromkeys(used_pages))
                answers[number] = {'images':assets,'pages':pages,
                                   'originals':[original_asset(p) for p in pages]}
            result['papers'][paper['id']] = {'title':paper['title'],'source':path.name,
                                            'source_sha256':digest,'questions':answers}
            print(f'{paper["title"]}: {len(answers)} answers',flush=True)
        page_groups.cache_clear();page_image.cache_clear();document.close()
    temporary = output/'index.json.tmp'
    temporary.write_text(json.dumps(result,ensure_ascii=False,separators=(',',':')))
    temporary.replace(output/'index.json')
    print(f'Imported {len(result["papers"])} papers, '
          f'{sum(len(p["questions"]) for p in result["papers"].values())} answers.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--keys',nargs='+',help='Rebuild selected source/set keys.')
    import_answers(parser.parse_args().keys)
