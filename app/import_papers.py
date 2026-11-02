"""Read-only PDF import; generated assets may be rebuilt without touching user data."""
from pathlib import Path
import hashlib, json, re
import pdfplumber
import pypdfium2 as pdfium
from PIL import Image, ImageChops, ImageOps

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / '独立试卷'
DATA = ROOT / 'data'
SCALE = 220 / 72
WARNINGS = {
 ('2025 欧几里得三套卷第1套', 21): '原有整理说明提示：齐次条件与 f(0,0)=1 可能冲突，请查原卷勘误。此提示未经本应用重新求解核实。',
 ('2024 超越十套卷第1套', 17): '原有整理说明提示：奇函数条件与 ln cos(x/2) 的奇偶性可能冲突，请查原卷勘误。此提示未经本应用重新求解核实。',
}

def ink_bbox(im):
    gray = im.convert('L').point(lambda p: 255 if p < 235 else 0)
    return gray.getbbox()

BOUNDARY_WARNINGS=[]
def boundary(im, anchor_y, floor_y, objects):
    """Prefer whitespace outside full glyph bounds, not gaps within a fraction."""
    end=int(anchor_y*SCALE)
    floor=max(int(floor_y*SCALE),end-int(65*SCALE))
    gray=im.convert('L');runs=[];run=None
    for y in range(floor,end):
        empty=gray.crop((0,y,gray.width,y+1)).getextrema()[0]>242
        if empty and run is None:run=y
        if not empty and run is not None:
            if y-run>=2:runs.append((run,y))
            run=None
    if run is not None and end-run>=2:runs.append((run,end))
    if not runs:raise ValueError(f'No pixel whitespace near {anchor_y}')
    choices=[]
    for a,b in runs:
        for y in range(a,b):
            crossing=sum(lo-.2<=y/SCALE<=hi+.2 for lo,hi in objects)
            choices.append((crossing,-y,(y+.5)/SCALE))
    score,_,cut=min(choices)
    if score:BOUNDARY_WARNINGS.append(dict(anchor=anchor_y,cut=cut,crossing=score))
    # Give both neighboring rows half the usable whitespace around the cut.
    for a,b in runs:
        if a<=cut*SCALE<=b:
            safe=[y for y in range(a,b) if sum(lo-.2<=y/SCALE<=hi+.2 for lo,hi in objects)==score]
            if safe:cut=(min(safe)+max(safe))/2/SCALE
            break
    return cut

def import_all():
    DATA.mkdir(exist_ok=True)
    ordering = {}
    for line in (SOURCE / '00 做题顺序与难度说明.txt').read_text().splitlines():
        m = re.match(r'^(\d{3})\s+(.+)$', line)
        if m: ordering[m[2]] = int(m[1])
    catalog, report = [], []
    for f in sorted(SOURCE.rglob('*.pdf'), key=lambda f: ordering[f.stem]):
        digest = hashlib.sha256(f.read_bytes()).hexdigest()
        pid = digest[:16]
        out = DATA / 'questions' / pid
        out.mkdir(parents=True, exist_ok=True)
        paper = dict(id=pid, title=f.stem, order=ordering[f.stem], year=int(f.stem[:4]),
                     subject='math',question_count=22,difficulty=f.parent.name[3:], source=str(f.relative_to(ROOT.parent)), sha256=digest, questions=[])
        chunks = {n: [] for n in range(1,23)}
        segments = {n: [] for n in range(1,23)}
        anchors_found=[]; current=None; warning_start=len(BOUNDARY_WARNINGS)
        renderer=pdfium.PdfDocument(f)
        with pdfplumber.open(f) as doc:
            for page_index,p in enumerate(doc.pages):
                page_bitmap=renderer[page_index].render(scale=SCALE).to_pil().convert('RGB')
                for col in range(2):
                    margin = 73.7 if col==0 else 615.1
                    x0=margin-4; x1=margin+516
                    column=page_bitmap.crop((round(x0*SCALE),0,round(x1*SCALE),page_bitmap.height))
                    words=p.crop((col*p.width/2,0,(col+1)*p.width/2,p.height)).extract_words()
                    objects=[(ch['top'],ch['bottom']) for ch in p.chars if ch['text'].strip() and x0 <= ch['x0'] < x1]
                    objects += [(o['top'],o['bottom']) for o in [*p.lines,*p.rects,*p.curves,*p.images] if o['x0'] >= x0 and o['x1'] <= x1 and o['bottom']-o['top']<100]
                    anchors=[]; headings=[]
                    for w in words:
                        if abs(w['x0']-margin)>2 or w['top']>=750: continue
                        m=re.match(r'^(\d{1,2})[.．]',w['text'])
                        if m and 1 <= int(m[1]) <= 22: anchors.append((int(m[1]),w['top']))
                        if re.match(r'^[一二三]、',w['text']): headings.append(w['top'])
                    anchors.sort(key=lambda a:a[1])
                    start=28.0; previous_anchor=None
                    def append_part(number,top,bottom):
                        if number is None or bottom<=top: return
                        piece=column.crop((0,round(top*SCALE),column.width,round(bottom*SCALE)))
                        box=ink_bbox(piece)
                        if box:
                            # Preserve column width, trim only empty vertical margins.
                            piece=piece.crop((0,max(0,box[1]-8),piece.width,min(piece.height,box[3]+8)))
                            chunks[number].append(piece)
                            segments[number].append(dict(page=page_index+1,column=col+1,box=[round(x0,2),round(top,2),round(x1,2),round(bottom,2)]))
                    for number,y in anchors:
                        cut=boundary(column,y,previous_anchor+12 if previous_anchor is not None else 28,objects)
                        stops=[h for h in headings if start < h < y]
                        end=boundary(column,stops[0],start,objects) if stops else cut
                        append_part(current,start,end)
                        current=number; start=cut; previous_anchor=y; anchors_found.append(number)
                    append_part(current,start,750)
        renderer.close()
        if anchors_found!=list(range(1,23)):
            raise ValueError(f'{f.name}: bad anchors {anchors_found}')
        for n,parts in chunks.items():
            if not parts: raise ValueError(f'{f.name}: missing image {n}')
            width=max(p.width for p in parts)
            height=sum(p.height for p in parts)+24*(len(parts)-1)+36
            canvas=Image.new('RGB',(width+36,height),'white'); y=18
            for part in parts:
                canvas.paste(part,(18,y)); y+=part.height+24
            canvas.save(out/f'{n}.png',optimize=True)
            q=dict(number=n, type='选择题' if n<=10 else '填空题' if n<=16 else '解答题',
                   image=f'/assets/questions/{pid}/{n}.png',width=canvas.width,height=canvas.height,
                   segments=segments[n],warning=WARNINGS.get((f.stem,n)))
            paper['questions'].append(q)
            if len(parts)>1: report.append(dict(paper=f.stem,number=n,parts=len(parts)))
        for warning in BOUNDARY_WARNINGS[warning_start:]:warning['paper']=paper['order']
        catalog.append(paper)
        print(f'{paper["order"]:03} {f.stem}: 22 questions',flush=True)
    existing=json.loads((DATA/'catalog.json').read_text()) if (DATA/'catalog.json').exists() else {'papers':[]}
    catalog += [p for p in existing['papers'] if p.get('subject','math')!='math']
    result=dict(version=2,papers=catalog)
    (DATA/'catalog.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    (DATA/'import-report.json').write_text(json.dumps(dict(papers=len(catalog),questions=sum(len(p['questions']) for p in catalog),cross_column=report,boundary_warnings=BOUNDARY_WARNINGS),ensure_ascii=False,indent=2))
    print(f'Done: {len(catalog)} papers, {sum(len(p['questions']) for p in catalog)} questions, {len(report)} continued questions')

if __name__=='__main__': import_all()
