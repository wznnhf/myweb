import assetManifest from './assets-manifest.json';
import catalog from '../public/seed/catalog.json';
import cardsCatalog from './cards.json';
import book from './book.json';
import legacy from './legacy-ids.json';
import {readStore,commitStore} from './storage.mjs';
import {coreAPI,context,fail} from './model.mjs';
import {practiceAPI} from './practice.mjs';
import {knowledgeAPI} from './knowledge.mjs';
import {validateBackup,preview,restore} from './backup.mjs';
const assetByPath=new Map(assetManifest.files.map(f=>['/'+f.path,f]));
const assetByHash=new Map(assetManifest.files.map(f=>[f.sha256||f.target_sha256,f]));
const papers=Object.fromEntries(catalog.papers.map(p=>[p.id,p]));
const numericIds=new Map([...cardsCatalog.cards,...legacy.cards].map(c=>{const value=BigInt('0x'+c.id.split('-')[1]);return[Number(value),value.toString()]}));
function stringify(value){return JSON.stringify(value,(key,v)=>key==='card_id'&&typeof v==='number'&&numericIds.has(v)?'__shiti_integer_'+numericIds.get(v):v).replace(/"__shiti_integer_(\d+)"/g,'$1')}
const json=(value,status=200)=>new Response(stringify(value),{status,headers:{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}});
async function getImage(env,url,id){const object=await env.BUCKET?.get('note-images/'+id);if(object)return new Response(object.body,{headers:{'Content-Type':object.httpMetadata?.contentType||'image/png','Cache-Control':'private, max-age=3600','X-Content-Type-Options':'nosniff'}});const r=await assetResponse(new Request(new URL('/note-images/'+id,url)),env);if(!r.ok)fail(404,'笔记图片不存在');return new Response(r.body,{headers:{'Content-Type':'image/png','Cache-Control':'private, max-age=3600','X-Content-Type-Options':'nosniff'}})}
async function backupImages(data,env,url){const ids=[...new Set(data.states.flatMap(s=>[...s.note.matchAll(/\/api\/note-images\/([a-f0-9]{64})/g)].map(m=>m[1])))];const images=[];for(const id of ids){const response=await getImage(env,url,id),bytes=new Uint8Array(await response.arrayBuffer());let binary='';for(let offset=0;offset<bytes.length;offset+=8192)binary+=String.fromCharCode(...bytes.subarray(offset,offset+8192));images.push({id,data:btoa(binary)})}return images}

const digest=async bytes=>[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(v=>v.toString(16).padStart(2,'0')).join('');
function assetMime(path){const ext=path.split('.').at(-1).toLowerCase();return({webp:'image/webp',png:'image/png',jpg:'image/jpeg',jpeg:'image/jpeg',gif:'image/gif',pdf:'application/pdf',woff:'font/woff',woff2:'font/woff2',ttf:'font/ttf',otf:'font/otf'})[ext]||'image/png'}
export async function assetResponse(request,env){const path=new URL(request.url).pathname,entry=assetByPath.get(path);if(!entry)return null;if(!env.BUCKET)return new Response('云端文件存储尚未连接',{status:503});
 const headers=new Headers({'Content-Type':assetMime(path),'Cache-Control':'private, max-age=86400','X-Content-Type-Options':'nosniff','Accept-Ranges':'bytes','ETag':'"'+entry.sha256+'"'});if(request.headers.get('if-none-match')===headers.get('etag'))return new Response(null,{status:304,headers});
 let options={},status=200;const range=request.headers.get('range');if(range){const match=range.match(/^bytes=(\d+)-(\d*)$/);if(match){const offset=+match[1],end=match[2]?Math.min(+match[2],entry.size-1):entry.size-1;if(offset>=entry.size||end<offset)return new Response(null,{status:416,headers:{'Content-Range':'bytes */'+entry.size}});options.range={offset,length:end-offset+1};status=206;headers.set('Content-Range',`bytes ${offset}-${end}/${entry.size}`);headers.set('Content-Length',String(end-offset+1));}}
 const object=await env.BUCKET.get('assets/'+entry.sha256,options);if(!object)return new Response('题库资源正在迁移，请稍后重试。',{status:503,headers:{'Retry-After':'30','Cache-Control':'no-store'}});if(status===200)headers.set('Content-Length',String(entry.size));return new Response(request.method==='HEAD'?null:object.body,{status,headers});}
async function importAsset(env,sha,bytes){const entry=assetByHash.get(sha);if(!entry||entry.size!==bytes.byteLength||await digest(bytes)!==sha)fail(400,'资源校验失败');await env.BUCKET.put('assets/'+sha,bytes,{httpMetadata:{contentType:assetMime(entry.path)},customMetadata:{sha256:sha}});return sha;}
async function assetAdmin(request,env,path){if(!env.BUCKET)fail(503,'云端文件存储尚未连接');if(path==='/api/admin/assets/status'&&request.method==='GET'){const found=new Set();let cursor;do{const batch=await env.BUCKET.list({prefix:'assets/',limit:1000,...(cursor?{cursor}:{})});for(const o of batch.objects)found.add(o.key.slice(7));cursor=batch.truncated?batch.cursor:null;}while(cursor);const missing=[...assetByHash.keys()].filter(h=>!found.has(h));return json({total:assetByHash.size,uploaded:assetByHash.size-missing.length,missing});}
 if(path==='/api/admin/assets'&&request.method==='POST'){const size=+(request.headers.get('content-length')||0);if(size>25*1024*1024)fail(413,'单批资源过大');const sha=request.headers.get('x-shiti-asset-sha256');if(sha)return json({uploaded:[await importAsset(env,sha,await request.arrayBuffer())]});const body=await request.json();if(!Array.isArray(body.files)||body.files.length>128)fail(400,'资源批次无效');let total=0;const files=body.files.map(f=>{if(typeof f.sha256!=='string'||typeof f.data!=='string')fail(400,'资源字段无效');total+=f.data.length;if(total>4*1024*1024)fail(413,'资源批次过大');return{sha:f.sha256,bytes:Uint8Array.from(atob(f.data),v=>v.charCodeAt(0))}});const uploaded=[];for(let offset=0;offset<files.length;offset+=16)uploaded.push(...await Promise.all(files.slice(offset,offset+16).map(f=>importAsset(env,f.sha,f.bytes))));return json({uploaded});}fail(404,'资源迁移地址不存在');}

export async function apiHandler(request,env){const url=new URL(request.url),path=url.pathname,method=request.method;try{
 if(path.startsWith('/api/admin/assets')){const origin=request.headers.get('origin');if(request.method!=='GET'&&(request.headers.get('sec-fetch-site')==='cross-site'||origin&&origin!==url.origin))fail(403,'只接受本网站发起的修改');return await assetAdmin(request,env,path);}
 if(!env.DB)fail(503,'云端数据库尚未连接，请稍后重试');
 if(!['GET','HEAD'].includes(method)){const origin=request.headers.get('origin');if(request.headers.get('sec-fetch-site')==='cross-site'||origin&&origin!==url.origin)fail(403,'只接受本网站发起的修改');const length=Number(request.headers.get('content-length')||0);if(length>100*1024*1024)fail(413,'请求不能超过100 MB')}
 let match;
 if((match=path.match(/^\/api\/papers\/([^/]+)\/pdf$/))&&method==='GET'){const p=papers[match[1]];if(!p)fail(404,'试卷不存在');return assetResponse(new Request(new URL(p.pdf,url),request),env)}
 if((match=path.match(/^\/api\/knowledge\/source\/(ds|co|os|net)$/))&&method==='GET')return assetResponse(new Request(new URL('/knowledge-sources/'+match[1]+'.pdf',url),request),env);
 if(path==='/api/knowledge/outline'&&method==='GET')return assetResponse(new Request(new URL('/knowledge-sources/outline-2027.pdf',url),request),env);
 if((match=path.match(/^\/api\/note-images\/([a-f0-9]{64})$/))&&method==='GET')return getImage(env,url,match[1]);
 if((match=path.match(/^\/api\/questions\/([^/]+)\/(\d+)\/images$/))&&method==='POST'){
 if(!papers[match[1]]?.questions[+match[2]-1])fail(404,'题目不存在');if(!env.BUCKET)fail(503,'云端图片存储未连接');const bytes=new Uint8Array(await request.arrayBuffer());if(bytes.length>10*1024*1024)fail(413,'图片不能超过10 MB');let type;if(bytes[0]===137&&bytes[1]===80&&bytes[2]===78&&bytes[3]===71)type='image/png';else if(bytes[0]===255&&bytes[1]===216&&bytes[2]===255)type='image/jpeg';else if(String.fromCharCode(...bytes.slice(0,4))==='RIFF'&&String.fromCharCode(...bytes.slice(8,12))==='WEBP')type='image/webp';else if(String.fromCharCode(...bytes.slice(0,3))==='GIF')type='image/gif';else fail(400,'请上传 PNG、JPEG、WebP 或 GIF 图片');const id=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(v=>v.toString(16).padStart(2,'0')).join('');await env.BUCKET.put('note-images/'+id,bytes,{httpMetadata:{contentType:type}});return json({url:'/api/note-images/'+id});}
 if(path.startsWith('/api/knowledge/export/')&&method==='GET'){const quote=v=>'"'+String(v??'').replaceAll('"','""')+'"',rows=[['科目','章节','标题','源资料考频','卡片类型','结论','PDF页码'],...cardsCatalog.cards.map(c=>[cardsCatalog.subjects.find(s=>s.id===c.field)?.title,c.chapter,c.title,c.frequency,c.card_type,c.answer.join('\n'),c.pdf_pages.join(',')])];return new Response('\ufeff'+rows.map(r=>r.map(quote).join(',')).join('\r\n'),{headers:{'Content-Type':'text/csv; charset=utf-8','Content-Disposition':'attachment; filename="408-memory-cards.csv"'}})}
 let body={};if(!['GET','HEAD'].includes(method)){const raw=await request.text();if(raw.length>100*1024*1024)fail(413,'请求过大');if(raw)try{body=JSON.parse(raw)}catch{fail(400,'请求内容不是有效JSON')}}
 const mutating=!['GET','HEAD'].includes(method);
 if(path.startsWith('/api/backup/')&&method==='POST')validateBackup(body,papers,cardsCatalog);
 for(let attempt=0;attempt<5;attempt++){
 const before=await readStore(env.DB),d=before.data,c=context(d,papers);c.cardsCatalog=cardsCatalog;
 if(path==='/api/backup'&&method==='GET'){d.images=await backupImages(d,env,url);d.exported_at=c.now;d.last_read=d.last_reads?.math||null;return new Response(stringify(d),{headers:{'Content-Type':'application/json; charset=utf-8','Content-Disposition':'attachment; filename="shiti-cloud-backup.json"','Cache-Control':'no-store'}})}
 if(path==='/api/backup/preview'&&method==='POST'){const check=structuredClone(d);restore(body,check,context(check,papers));return json(preview(body,d));}
 let result;
 if(path==='/api/backup/restore'&&method==='POST'){if(!env.BUCKET)fail(503,'自动备份存储未连接');const snapshot={...d,exported_at:c.now,images:await backupImages(d,env,url)};await env.BUCKET.put('backups/before-restore-'+c.now+'-'+before.revision+'.json',stringify(snapshot),{httpMetadata:{contentType:'application/json'}});for(const image of body.images||[]){const bytes=Uint8Array.from(atob(image.data),v=>v.charCodeAt(0)),digest=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(v=>v.toString(16).padStart(2,'0')).join('');if(digest!==image.id)fail(400,'备份图片校验失败');const type=bytes[0]===137?'image/png':bytes[0]===255?'image/jpeg':bytes[0]===71?'image/gif':'image/webp';await env.BUCKET.put('note-images/'+image.id,bytes,{httpMetadata:{contentType:type}})}result=restore(body,d,c);}
 else result=coreAPI(path,method,body,url.searchParams,d,c,papers)??practiceAPI(path,method,body,url.searchParams,d,c,papers,book)??knowledgeAPI(path,method,body,url.searchParams,d,c);
 if(result===undefined)fail(404,'这个功能地址不存在');if(!mutating||await commitStore(env.DB,before,d))return json(result);
 }fail(409,'其他设备刚刚更新了记录，请重试。');
 }catch(e){return json({detail:e.status?e.message:'云端服务暂时无法完成请求，请稍后重试。'},e.status||500)}}
