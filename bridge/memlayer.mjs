/** Local adapter around the user-selected MemLayer SDK. Never accepts tenant identity from an LLM. */
import { createServer } from 'node:http';
import { DatabaseSync } from 'node:sqlite';
import { createHash } from 'node:crypto';
import { mkdirSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { pathToFileURL } from 'node:url';
const root=resolve(process.env.PROJECT_DIR||'.');
const {openMemoryService}=await import(pathToFileURL(resolve(root,'.memlayer-source/src/index.ts')).href);
const nativePath=resolve(root,'.adk/letslego-memlayer.sqlite');mkdirSync(dirname(nativePath),{recursive:true});
const memory=await openMemoryService({databasePath:nativePath,defaultTimeoutMs:15000,profileFactLimit:200});
const stopWorker=memory.startIndexingWorker();
// This index provides stable user keys, latest-version selection and durable working snapshots.
// Native profile facts/documents/episodes/audits/journal are written before publishing a snapshot here.
const index=new DatabaseSync(resolve(root,'.adk/memlayer-bridge-index.sqlite'));
index.exec('PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; CREATE TABLE IF NOT EXISTS memory_keys (app TEXT,user TEXT,kind TEXT,session TEXT,key TEXT,record TEXT,native_id TEXT,PRIMARY KEY(app,user,kind,session,key))');
const hash=value=>createHash('sha256').update(value).digest('hex');
const tenant=app=>'app_'+hash(app).slice(0,32);
const nativeSession=(user,session)=>'session_'+hash(JSON.stringify([user,session]));
const kinds=new Set(['working','profile','knowledge','episodic','operational']);
function validate(input){
 if(!input||typeof input.app!=='string'||!input.app.trim()||typeof input.user!=='string'||!input.user.trim())throw new Error('Application and user required');
 if(!kinds.has(input.kind))throw new Error('Unknown layer');
 if((input.kind==='working')!==Boolean(input.session_id))throw new Error('Working requires session; other layers are user scoped');
 if(input.app.length>200||input.user.length>200||(input.session_id||'').length>200)throw new Error('Scope too long');
}
const rows=scope=>index.prepare('SELECT record,native_id FROM memory_keys WHERE app=? AND user=? AND kind=? AND session=?').all(scope.app,scope.user,scope.kind,scope.session_id||'').map(r=>({...JSON.parse(r.record),native_id:r.native_id}));
async function store(body){
 const scope={app:body.app,user:body.user,kind:body.memory?.kind,session_id:body.memory?.session_id||''};validate(scope);
 const item=body.memory;
 if(!/^[a-zA-Z0-9_-]{1,100}$/.test(item.key)||typeof item.text!=='string'||!item.text.trim()||item.text.length>20000)throw new Error('Invalid memory key/text');
 if(JSON.stringify(item.metadata||{}).length>20000)throw new Error('Metadata too large');
 const appTenant=tenant(scope.app),sdkUser=scope.user;
 if(item.kind==='episodic'&&item.metadata?.source==='explicit_user_remember_request'){
  const prior=index.prepare('SELECT record FROM memory_keys WHERE app=? AND user=? AND kind=? AND session=? AND key=?').get(scope.app,sdkUser,item.kind,scope.session_id,item.key);
  if(prior){
   const saved=JSON.parse(prior.record);
   if(saved.text!==item.text||JSON.stringify(saved.metadata)!==JSON.stringify(item.metadata))throw new Error('Remember request ID reused with different content');
   return {memory:saved};
  }
 }

 const record={key:item.key,text:item.text,metadata:item.metadata||{},kind:item.kind,session_id:scope.session_id,updated_at:new Date().toISOString(),backend:'letslego/memlayer'};
 let nativeId;
 if(item.kind==='profile'){
  const fact=await memory.setProfileFact(appTenant,sdkUser,{key:item.key,type:'json',value:{text:item.text,metadata:record.metadata}});nativeId=fact.key;
 }else if(item.kind==='working'){
  const session=nativeSession(sdkUser,scope.session_id);
  const envelope={bridge:'agent-workshop',key:item.key,metadata:record.metadata};
  const payload={userId:sdkUser,sessionId:session,requestId:'memory_'+hash(JSON.stringify([item.key,item.text,record.metadata])),question:JSON.stringify(envelope),answer:item.text};
  const exchange=await memory.commitExchange(appTenant,payload);nativeId=exchange.id;
  await memory.appendTurn(appTenant,session,{role:record.metadata.author==='user'?'user':'assistant',content:item.text});
 }else if(item.kind==='knowledge'){
  const document=await memory.ingestDocument(appTenant,{title:item.key,text:item.text,source:'agent-workshop',acl:{visibility:'restricted',userIds:[sdkUser],roles:[]},metadata:{workshop_key:item.key,user:sdkUser}});nativeId=document.documentId;
 }else if(item.kind==='episodic'){
  const episode=await memory.recordEpisode(appTenant,{userId:sdkUser,type:'custom_memory',summary:item.text,payload:{key:item.key,metadata:record.metadata}});nativeId=episode.id;
 }else{
  const event=await memory.recordAudit(appTenant,{userId:sdkUser,action:'custom_memory',detail:{key:item.key,text:item.text,metadata:record.metadata},steps:0,costUnits:0});nativeId=event.id;
 }
 record.memory_id=nativeId;
 index.prepare('INSERT INTO memory_keys VALUES (?,?,?,?,?,?,?) ON CONFLICT(app,user,kind,session,key) DO UPDATE SET record=excluded.record,native_id=excluded.native_id').run(scope.app,sdkUser,item.kind,scope.session_id,item.key,JSON.stringify(record),nativeId);
 return {memory:record};
}
async function search(scope){
 scope.session_id||='';validate(scope);let results=rows(scope);
 const query=scope.query||'',limit=Math.max(1,Math.min(50,Number(scope.limit||10))),appTenant=tenant(scope.app);
 if(scope.kind==='profile'){
  const profile=await memory.getProfile(appTenant,scope.user);const facts=new Map(profile.facts.map(f=>[f.key,f]));
  results=results.filter(row=>facts.has(row.key)).map(row=>({...row,text:facts.get(row.key).value.text,metadata:facts.get(row.key).value.metadata||{},updated_at:new Date(facts.get(row.key).updatedAt).toISOString()}));
 }else if(scope.kind==='knowledge'&&query.trim()){
  const hits=await memory.searchKnowledge(appTenant,{query,userId:scope.user,topK:Math.min(limit,20),mode:'hybrid'});
  const ids=new Set(hits.map(hit=>hit.documentId));results=results.filter(row=>ids.has(row.native_id));
 }else if(scope.kind==='working'){
  // Touch native working cache for coherent shared-store semantics. Durable keyed journal snapshots
  // remain available after its TTL or process restart; no claim that appendTurn itself is durable.
  await memory.getWorkingMemory(appTenant,nativeSession(scope.user,scope.session_id));
 }
 if(query.trim()&&scope.kind!=='knowledge'){
  const terms=query.toLowerCase().match(/[\p{L}\p{N}_]+/gu)||[];
  results=results.filter(row=>terms.every(word=>(row.key+' '+row.text).toLowerCase().includes(word)));
 }
 return {memories:results.sort((a,b)=>b.updated_at.localeCompare(a.updated_at)).slice(0,limit).map(({native_id,...row})=>row)};
}
async function forget(body){validate(body);
 const found=rows(body).some(row=>row.key===body.key);if(!found)return {deleted:false};
 if(body.kind!=='profile'){const error=new Error('Native MemLayer exposes deletion for profile facts only. Journal, knowledge, episodes and audit records require a retention implementation.');error.status=409;throw error;}
 await memory.forgetFact(tenant(body.app),body.user,body.key);
 index.prepare('DELETE FROM memory_keys WHERE app=? AND user=? AND kind=? AND session=? AND key=?').run(body.app,body.user,body.kind,body.session_id||'',body.key);
 return {deleted:true};
}
async function readBody(request){let body='';for await(const chunk of request){body+=chunk;if(body.length>100000)throw new Error('Request too large');}return JSON.parse(body||'{}');}
const server=createServer(async(request,response)=>{
 try{
  const url=new URL(request.url,'http://127.0.0.1');let result;
  if(request.method==='GET'&&url.pathname==='/health')result={status:'ok',backend:'letslego/memlayer',layers:[...kinds]};
  else if(request.method==='POST'&&url.pathname==='/memory/store')result=await store(await readBody(request));
  else if(request.method==='GET'&&url.pathname==='/memory/search')result=await search(Object.fromEntries(url.searchParams));
  else if(request.method==='DELETE'&&url.pathname==='/memory')result=await forget(await readBody(request));
  else{response.writeHead(404);response.end();return;}
  response.writeHead(200,{'content-type':'application/json'});response.end(JSON.stringify(result));
 }catch(error){response.writeHead(error.status||422,{'content-type':'application/json'});response.end(JSON.stringify({error:error.message}));}
});
server.listen(Number(process.env.MEMLAYER_BRIDGE_PORT||61002),'127.0.0.1',()=>console.log('MemLayer SDK bridge on 127.0.0.1:61002'));
async function shutdown(){stopWorker();server.close();await memory.close();index.close();process.exit(0);}
process.on('SIGTERM',shutdown);process.on('SIGINT',shutdown);
