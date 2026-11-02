"""Audit every source glyph against crop geometry, and create visual QA sheets."""
import json
from pathlib import Path
import pdfplumber
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parent
catalog=json.loads((ROOT/'data/catalog.json').read_text())['papers']
issues=[];continuations=[]
for p in catalog:
 with pdfplumber.open(ROOT.parent/p['source']) as doc:
  for i,page in enumerate(doc.pages):
   for col in range(2):
    margin=73.7 if col==0 else 615.1
    qs=[(q['number'],s['box']) for q in p['questions'] for s in q['segments'] if s['page']==i+1 and s['column']==col+1]
    if not qs:continue
    start=min(b[1] for _,b in qs)
    for ch in page.chars:
     if not ch['text'].strip() or ch['top']<start or ch['top']>=750 or not col*page.width/2 < ch['x0'] < (col+1)*page.width/2:continue
     if ch['x0']<margin-4-.5 or ch['x1']>margin+516+.5:
      issues.append([p['order'],i+1,col+1,'horizontal',ch['text'],round(ch['x0'],1),round(ch['x1'],1)])
    for n,b in qs:
     for boundary in [b[1],b[3]]:
      crossing=[ch['text'] for ch in page.chars if ch['text'].strip() and b[0]<ch['x0']<b[2] and ch['top']+.8<boundary<ch['bottom']-.8]
      if crossing:issues.append([p['order'],n,i+1,col+1,'vertical',round(boundary,1),''.join(crossing)])
 for q in p['questions']:
  if len(q['segments'])>1:continuations.append((p,q))
print('geometry_warnings',len(issues));print(json.dumps(issues[:100],ensure_ascii=False))
(ROOT/'output/crop-audit.json').write_text(json.dumps(issues,ensure_ascii=False,indent=2))
for batch in range(0,len(continuations),10):
 canvas=Image.new('RGB',(1400,1900),'#e8ece4');d=ImageDraw.Draw(canvas)
 for j,(p,q) in enumerate(continuations[batch:batch+10]):
  x=(j%2)*700;y=(j//2)*380
  d.text((x+15,y+10),f'Paper {p["order"]:03} / Q{q["number"]} / {len(q["segments"])} parts',fill='black')
  im=Image.open(ROOT/'data/questions'/p['id']/f'{q["number"]}.png');im.thumbnail((675,338))
  canvas.paste(im,(x+12,y+35))
 canvas.save(ROOT/f'output/continuations-{batch//10+1}.png')
print('contact_sheets', (len(continuations)+9)//10)
