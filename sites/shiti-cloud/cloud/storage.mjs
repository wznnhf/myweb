import initial from './initial-study.json';
const groups=['states','folders','memberships','daily_reviews','daily_practice','activity'];
const kgroups=['states','draws','reviews','goals','sessions'];
const id=(group,v)=>group==='states'?v.paper_id+':'+v.number:group==='memberships'?v.folder_id+':'+v.paper_id+':'+v.number:group==='daily_reviews'?v.subject+':'+v.day:group==='activity'?[v.subject,v.area,v.day,v.item_id].join(':'):v.id;
export function documents(data){
 const m=new Map();
 m.set('header',JSON.stringify(Object.fromEntries(Object.entries(data).filter(([k])=>!groups.includes(k)&&k!=='knowledge'&&k!=='images'))));
 for(const g of groups) for(const v of data[g]||[])m.set(g+'/'+id(g,v),JSON.stringify(v));
 m.set('knowledge/header',JSON.stringify(Object.fromEntries(Object.entries(data.knowledge||{}).filter(([k])=>!kgroups.includes(k)))));
 for(const g of kgroups)for(const v of data.knowledge?.[g]||[])m.set('knowledge/'+g+'/'+(g==='states'?v.card_id:g==='goals'?v.field:v.id),JSON.stringify(v));
 return m;
}
function decode(rows){const d=JSON.parse(rows.get('header')||'{}');for(const g of groups)d[g]=[];d.images=[];d.knowledge=JSON.parse(rows.get('knowledge/header')||'{}');for(const g of kgroups)d.knowledge[g]=[];
 for(const [key,value]of rows){const parts=key.split('/');if(groups.includes(parts[0]))d[parts[0]].push(JSON.parse(value));else if(parts[0]==='knowledge'&&kgroups.includes(parts[1]))d.knowledge[parts[1]].push(JSON.parse(value));}return d;}
export async function readStore(db){
 await db.prepare('INSERT OR IGNORE INTO study_revision(id,revision,initialized) VALUES(1,0,0)').run();
 let header=await db.prepare('SELECT revision,initialized FROM study_revision WHERE id=1').first();
 if(!header.initialized){const stmts=[...documents(initial)].map(([key,payload])=>db.prepare('INSERT OR IGNORE INTO study_documents(key,payload) SELECT ?,? WHERE (SELECT initialized FROM study_revision WHERE id=1)=0').bind(key,payload));stmts.push(db.prepare('UPDATE study_revision SET initialized=1,revision=revision+1 WHERE id=1 AND initialized=0'));await db.batch(stmts);}
 // A single query snapshots both the revision and the documents.
 const result=await db.prepare('SELECT d.key,d.payload,r.revision FROM study_revision r LEFT JOIN study_documents d ON 1=1 WHERE r.id=1').all();
 const rows=new Map(result.results.filter(r=>r.key).map(r=>[r.key,r.payload]));return {revision:result.results[0]?.revision||0,rows,data:decode(rows)};
}
export async function commitStore(db,before,data){const after=documents(data),statements=[];
 for(const [key,payload]of after)if(before.rows.get(key)!==payload)statements.push(db.prepare('INSERT INTO study_documents(key,payload) SELECT ?,? WHERE (SELECT revision FROM study_revision WHERE id=1)=? ON CONFLICT(key) DO UPDATE SET payload=excluded.payload').bind(key,payload,before.revision));
 for(const key of before.rows.keys())if(!after.has(key))statements.push(db.prepare('DELETE FROM study_documents WHERE key=? AND (SELECT revision FROM study_revision WHERE id=1)=?').bind(key,before.revision));
 if(!statements.length)return true;
 statements.push(db.prepare('UPDATE study_revision SET revision=revision+1 WHERE id=1 AND revision=?').bind(before.revision));
 const r=await db.batch(statements);return r.at(-1).meta.changes===1;
}
