import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source=fs.readFileSync(new URL('../static/app.js',import.meta.url),'utf8');
const functions=source.slice(source.indexOf('async function api('),source.indexOf('async function refreshLibrary('))+
 source.slice(source.indexOf('async function exportBackup('),source.indexOf('const daily=createDailyReview('));
const text='{"knowledge":{"states":[{"card_id":"mc-526bcb2be4602b06","fsrs":{"card_id":5939063922993670918}}]}}';

function browser(fetch){
 const state={requests:[],blob:null,confirm:null};
 const context=vm.createContext({fetch,AbortController,Blob,Date,setTimeout:()=>0,clearTimeout(){},
  URL:{createObjectURL(blob){state.blob=blob;return 'blob:backup'},revokeObjectURL(){}},
  document:{createElement:()=>({click(){}})},flush:async()=>true,toast(){},openModal(){},
  $:()=>({addEventListener(type,callback){state.confirm=callback}}),modal:{close(){}},render:async()=>{}});
 vm.runInContext(functions,context);
 return {state,context};
}

test('browser export preserves full server JSON integers',async()=>{
 const {state,context}=browser(async()=>({ok:true,text:async()=>text,json:async()=>JSON.parse(text)}));
 await context.exportBackup();
 assert.equal(await state.blob.text(),text);
});

test('browser import sends original file text for both preview and restore',async()=>{
 const requests=[];
 const {state,context}=browser(async(url,options)=>{
  requests.push({url,...options});return {ok:true,json:async()=>({})};
 });
 await context.importBackup({size:text.length,text:async()=>text});
 assert.equal(requests.length,1);
 await state.confirm({target:{disabled:false}});
 assert.deepEqual(requests.map(r=>r.url),['/api/backup/preview','/api/backup/restore']);
 for(const request of requests){assert.equal(request.body,text);assert.equal(request.headers['Content-Type'],'application/json')}
});

test('invalid JSON is rejected before sending a restore request',async()=>{
 let calls=0;
 const {context}=browser(async()=>{calls++;throw new Error('unexpected request')});
 await assert.rejects(context.importBackup({size:5,text:async()=>'{oops'}),/有效的 JSON/);
 assert.equal(calls,0);
});
