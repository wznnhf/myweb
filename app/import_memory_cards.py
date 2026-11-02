"""Import the four user-provided, tagged CodeBrick print PDFs without flattening tables.

Run with app/.venv/bin/python app/import_memory_cards.py. Source bytes are copied
into data/knowledge/sources; no page scripts or PDF text are executed.
"""
from collections import defaultdict, Counter
import hashlib
import json
import logging
from pathlib import Path
import re
import shutil
import unicodedata
import pdfplumber
import pdfplumber.page
from pdfplumber.utils import decode_text

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'data/knowledge'
logging.getLogger('pdfminer').setLevel(logging.ERROR)

# pdfplumber clears MCIDs at nested ActualText spans. Preserve their parent tag,
# otherwise CJK compatibility radicals disappear from both titles and body text.
def begin_tag(self,tag,props=None):
    if not hasattr(self,'marked_stack'):self.marked_stack=[]
    self.marked_stack.append((self.cur_mcid,self.cur_tag,getattr(self,'cur_actual',None)))
    self.cur_tag=str(tag.name)
    if isinstance(props,dict):
        if 'MCID' in props:self.cur_mcid=props['MCID']
        if 'ActualText' in props:self.cur_actual={'text':decode_text(props['ActualText']),'emitted':False}
def end_tag(self):
    self.cur_mcid,self.cur_tag,self.cur_actual=self.marked_stack.pop() if self.marked_stack else (None,None,None)
original_render_char=pdfplumber.page.PDFPageAggregatorWithMarkedContent.render_char
def render_char(self,*args,**kwargs):
    adv=original_render_char(self,*args,**kwargs)
    actual=getattr(self,'cur_actual',None)
    if actual is not None and self.cur_item._objs:
        self.cur_item._objs[-1]._text=actual['text'] if not actual['emitted'] else ''
        actual['emitted']=True
    return adv
pdfplumber.page.PDFPageAggregatorWithMarkedContent.render_char=render_char
pdfplumber.page.PDFPageAggregatorWithMarkedContent.begin_tag=begin_tag
pdfplumber.page.PDFPageAggregatorWithMarkedContent.end_tag=end_tag

def normalize(text):
    return ''.join(unicodedata.normalize('NFKC',c) if 0x2e80<=ord(c)<=0x2fff else c for c in text if c not in '\u200b\ufeff')

OVERRIDES=json.loads((OUT/'cloze-overrides.json').read_text())

TAGS={'P':'p','L':'ul','LI':'li','Strong':'strong','Em':'em','Table':'table','TR':'tr','TH':'th','TD':'td','H1':'h3','H2':'h3','H3':'h3','H4':'h4','BlockQuote':'blockquote','Code':'code','Sup':'sup','Sub':'sub'}

def import_pdf(path,field,title,expected):
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    with pdfplumber.open(path) as pdf:
        chars=defaultdict(list)
        for page in pdf.pages:
            for ch in page.chars:
                if ch.get('mcid') is not None:chars[page.page_number,ch['mcid']].append(ch)
        def own(n):
            return normalize(''.join(ch['text'] for i in n.get('mcids',[]) for ch in chars[n.get('page_number'),i]))
        def text(n):return own(n)+''.join(text(k) for k in n.get('children',[]))
        def ast(n):
            if n['type']=='Lbl':return []
            children=[]
            if own(n):children.append({'text':own(n)})
            for k in n.get('children',[]):children.extend(ast(k))
            tag=TAGS.get(n['type'])
            if tag and children:
                node={'tag':tag,'children':children}
                if tag in ('td','th'):
                    for attr in ('RowSpan','ColSpan'):
                        value=n.get('attributes',{}).get(attr,1)
                        if value>1:node[attr.lower()]=value
                return [node]
            return children
        def pages(n):
            result={n['page_number']} if n.get('mcids') and own(n) else set()
            for k in n.get('children',[]):result.update(pages(k))
            return result
        cards=[];chapters=[];chapter=None
        def walk(nodes):
            nonlocal chapter
            for n in nodes:
                if n['type']=='H2':
                    label=text(n);match=re.fullmatch(r'(.+?)\s*(\d+)\s*张',label)
                    if match:
                        chapter={'id':'cb-'+field+'-'+hashlib.sha256(match[1].encode()).hexdigest()[:10],'title':match[1].strip(),'expected':int(match[2])};chapters.append(chapter)
                elif n['type']=='Art':
                    assert chapter and len(n['children'])==5
                    a,b,c,core,explanation=n['children']
                    name=text(a).strip();assert name
                    nodes=ast(core)
                    candidates=[]
                    def scan(ns):
                        for item in ns:
                            if item.get('tag')=='strong':
                                value=flat(item).strip()
                                if 1<len(value)<=30 and not re.search(r'[：:。；\n]$',value) and re.search(r'[\w\u4e00-\u9fff]',value):candidates.append((item,value))
                            scan(item.get('children',[]))
                    scan(nodes)
                    seen=set()
                    for item,value in candidates:
                        if value in seen or len(seen)>=12:continue
                        seen.add(value);item['tag']='blank';item['key']='b'+str(len(seen));item['text']=value;item.pop('children',None)
                    if not seen:
                        # Prefer a complete table value or short definition, never
                        # remove arbitrary character positions from a formula.
                        def fallback(ns):
                            for item in ns:
                                if item.get('text') and len(item['text'].strip())>=2:return item
                                found=fallback(item.get('children',[]))
                                if found:return found
                        target=fallback(nodes)
                        assert target, name
                        raw=target['text'];match=re.search(r'[\u4e00-\u9fff]{2,8}|[A-Za-z][A-Za-z0-9_]{1,15}',raw);assert match,name
                        value=match[0];target.clear();target.update(tag='span',children=[{'text':raw[:match.start()]},{'tag':'blank','key':'b1','text':value},{'text':raw[match.end():]}]);seen.add(value)
                    # Mask every occurrence, including repeats in comparison
                    # tables, so a nearby cell cannot give away the missing term.
                    terms=OVERRIDES.get(name,list(seen))
                    terms=sorted(set(terms),key=lambda value:(-len(value),value))
                    patterns=[]
                    for term in terms:
                        escaped=re.escape(term)
                        patterns.append(r'(?<![A-Za-z0-9_])'+escaped+r'(?![A-Za-z0-9_])' if re.fullmatch(r'[A-Za-z0-9_]+',term) else escaped)
                    matcher=re.compile('|'.join(patterns));count=[0]
                    def apply(ns):
                        result=[]
                        for item in ns:
                            if item.get('text'):
                                raw=item['text'];offset=0
                                for match in matcher.finditer(raw):
                                    result.append({'text':raw[offset:match.start()]});count[0]+=1
                                    result.append({'tag':'blank','key':'b'+str(count[0]),'text':match[0]});offset=match.end()
                                result.append({'text':raw[offset:]})
                            else:
                                if 'children' in item:item['children']=apply(item['children'])
                                result.append(item)
                        return result
                    baseline=''.join(flat(x) for x in ast(core))
                    nodes=apply(ast(core));assert count[0]>0,name
                    assert ''.join(flat(x) for x in nodes)==baseline,('结论文本不一致',name)
                    seen=set(range(count[0]))
                    cid='mc-'+hashlib.sha256((field+'\0'+chapter['title']+'\0'+name).encode()).hexdigest()[:16]
                    cards.append(dict(id=cid,field=field,title=name,chapter=chapter['title'],chapter_id=chapter['id'],source='CodeBrick 导出记忆卡',source_kind='codebrick_pdf',source_sha256=digest,source_file=field+'.pdf',pdf_page=min(pages(n)),pdf_pages=sorted(pages(n)),frequency=text(b),card_type=text(c),prompt='先回忆「'+name+'」的结论，再翻开核对。',core=nodes,explanation=ast(explanation),blank_count=len(seen),content_revision=hashlib.sha256(json.dumps(nodes,ensure_ascii=False).encode()).hexdigest()[:12],answer=[flat(x) for x in nodes],pitfall='',provenance='来自用户提供的 CodeBrick 打印 PDF；考频为源资料标注，未在本站重新统计。'))
                else:walk(n.get('children',[]))
        walk(pdf.structure_tree)
        assert len(cards)==expected,(field,len(cards),expected)
        for ch in chapters:assert sum(c['chapter_id']==ch['id'] for c in cards)==ch.pop('expected'),ch
        return dict(id=field,title=title,chapters=chapters),cards,dict(field=field,filename=path.name,sha256=digest,pages=len(pdf.pages),cards=len(cards))

def flat(node):
    return node.get('text','')+''.join(flat(n) for n in node.get('children',[]))

if __name__=='__main__':
    records=[];subjects=[];sources=[]
    for suffix,field,title,count in [('3','ds','数据结构',32),('4','co','计算机组成原理',20),('2','os','操作系统',43),('','net','计算机网络',45)]:
        s,c,m=import_pdf(Path('/Users/fenglang/Downloads')/f'CodeBrick 刷题{suffix}.pdf',field,title,count);subjects.append(s);records.extend(c);sources.append(m)
    version=hashlib.sha256(json.dumps(sources,sort_keys=True).encode()).hexdigest()
    data=dict(version=2,source_sha256=version,subjects=subjects,cards=records,sources=sources)
    (OUT/'sources').mkdir(parents=True,exist_ok=True)
    for source in sources:shutil.copy2(Path('/Users/fenglang/Downloads')/source['filename'],OUT/'sources'/(source['field']+'.pdf'))
    (OUT/'memory-cards.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    report=dict(total=len(records),subjects=dict(Counter(c['field'] for c in records)),chapters=len([ch for s in subjects for ch in s['chapters']]),blanks=dict(Counter(c['blank_count'] for c in records)),cards=[{k:c[k] for k in ['id','field','chapter','title','blank_count','pdf_pages']} for c in records])
    (ROOT/'output/knowledge-reference/import-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!='cards'},ensure_ascii=False))
