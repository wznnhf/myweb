"""Import 408 papers with locally recognized, visually checked layout coordinates.
Source PDFs remain untouched; math paper IDs and all study records are preserved.
Run from any directory: .venv/bin/python import_408.py
"""
from pathlib import Path
import hashlib,json
import pypdfium2 as pdfium
from PIL import Image
ROOT=Path(__file__).resolve().parent
DATA=ROOT/'data'
SCALE=220/72

def cut_before(image,y):
    """Find blank scanlines immediately above the recognized question heading."""
    end=round(y*image.height)-2
    gray=image.convert('L')
    for row in range(end,max(0,end-22),-1):
        # Ignore isolated scanning speckles, but not real text or diagram strokes.
        hist=gray.crop((int(image.width*.025),row,int(image.width*.975),row+1)).histogram()
        if sum(hist[:180])<=2:return row
    return max(0,end-4)

def run():
    layouts=json.loads((DATA/'408-layout.json').read_text())
    catalog=json.loads((DATA/'catalog.json').read_text())
    for p in catalog['papers']:p.setdefault('subject','math');p['question_count']=len(p['questions'])
    papers=[p for p in catalog['papers'] if p['subject']!='408']
    for order,f in enumerate(sorted((ROOT.parent/'408试卷').glob('*.pdf')),1):
        year=f.stem[:4];layout=layouts[year];anchors=layout['anchors']
        assert [a[0] for a in anchors]==list(range(1,48)),f.name
        digest=hashlib.sha256(f.read_bytes()).hexdigest();pid=digest[:16]
        assert layout['sha256']==digest,'Source changed; recheck layout: '+f.name
        out=DATA/'questions'/pid;out.mkdir(parents=True,exist_ok=True)
        doc=pdfium.PdfDocument(f)
        images={i:doc[i-1].render(scale=SCALE).to_pil().convert('RGB') for i in range(anchors[0][1],layout['last_page']+1)}
        cuts={n:cut_before(images[page],y) for n,page,x,y,text in anchors}
        questions=[]
        for index,(n,page,x,y,text) in enumerate(anchors):
            next_anchor=anchors[index+1] if index+1<len(anchors) else None
            end_page=next_anchor[1] if next_anchor else layout['last_page']
            parts=[];segments=[]
            for page_number in range(page,end_page+1):
                im=images[page_number]
                top=cuts[n] if page_number==page else round(im.height*layout['top'])
                bottom=cuts[n+1] if next_anchor and page_number==end_page else round(im.height*layout.get('page_bottoms',{}).get(str(page_number),layout['bottom']))
                # Keep section headings out of the preceding choice question.
                if n==40 and next_anchor and page_number==end_page:
                    heading=layout.get('section_heading')
                    if heading and heading[0]==page_number:bottom=cut_before(im,heading[1])
                if bottom<=top:continue
                left=round(im.width*.025);right=round(im.width*.975)
                piece=im.crop((left,top,right,bottom))
                mask=piece.convert('L').point(lambda p:255 if p<190 else 0)
                box=mask.getbbox()
                if not box:continue
                # Use a common horizontal extent for every continuation in this paper.
                piece=piece.crop((0,max(0,box[1]-12),piece.width,min(piece.height,box[3]+12)))
                parts.append(piece)
                segments.append(dict(page=page_number,column=1,box=[round(left/SCALE,2),round(top/SCALE,2),round(right/SCALE,2),round(bottom/SCALE,2)]))
            assert parts,(f.name,n)
            width=max(part.width for part in parts)
            height=sum(part.height for part in parts)+24*(len(parts)-1)+32
            canvas=Image.new('RGB',(width+32,height),'white');offset=16
            for part in parts:canvas.paste(part,(16,offset));offset+=part.height+24
            canvas.save(out/f'{n}.png',optimize=True)
            questions.append(dict(number=n,type='选择题' if n<=40 else '综合应用题',image=f'/assets/questions/{pid}/{n}.png',width=canvas.width,height=canvas.height,segments=segments,warning=None))
        papers.append(dict(id=pid,title=f'{year} 年 408 统考真题',order=order,year=int(year),subject='408',difficulty='真题',source=str(f.relative_to(ROOT.parent)),sha256=digest,question_count=47,questions=questions))
        doc.close();print(year,47,'questions',flush=True)
    catalog.update(version=2,papers=papers)
    target=DATA/'catalog.json';temp=target.with_suffix('.tmp');temp.write_text(json.dumps(catalog,ensure_ascii=False,indent=2));temp.replace(target)
    print('Imported',len(papers),'papers',sum(p['question_count'] for p in papers),'questions')
if __name__=='__main__':run()
