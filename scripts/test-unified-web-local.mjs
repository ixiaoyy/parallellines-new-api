// 仅用合成 HTTP/iframe 状态检查本地最终 dist；所有外部域名均拦截，不代表真实 OIDC/线上验收。
import assert from 'node:assert/strict';
import { createReadStream, existsSync, mkdirSync, statSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { createRequire } from 'node:module';
import { extname, resolve, sep } from 'node:path';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.PLAYWRIGHT_PATH);
const root=resolve(process.env.UNIFIED_WORKSPACE || '.build/unified-web-login-pkce10-20261114');
const dist=resolve(root,'source/web/dist'); const evidence=resolve(root,'evidence');mkdirSync(evidence,{recursive:true});
const types={'.html':'text/html; charset=utf-8','.js':'text/javascript','.css':'text/css','.png':'image/png','.svg':'image/svg+xml','.woff2':'font/woff2','.ico':'image/x-icon'};
const server=createServer((req,res)=>{let pathname=new URL(req.url,'http://localhost').pathname;let file=resolve(dist,'.'+pathname);if(!file.startsWith(dist+sep)&&file!==dist){res.writeHead(403).end();return;}if(!existsSync(file)||!statSync(file).isFile())file=extname(pathname)?'':resolve(dist,'index.html');if(!file){res.writeHead(404).end();return;}res.writeHead(200,{'Content-Type':types[extname(file)]||'application/octet-stream'});createReadStream(file).pipe(res);});
await new Promise(done=>server.listen(0,'127.0.0.1',done));const base=`http://127.0.0.1:${server.address().port}`;
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE});
const results=[];
const status={setup:true,main_unified_web_login_enabled:true,password_login_enabled:true,HeaderNavModules:JSON.stringify({pricing:{enabled:true,requireAuth:true}}),system_name:'New API · Local verification',logo:'/logo.png',custom_oauth_providers:[],announcements:[]};
async function fixture({auth=false,available=true,subject='53',user=null,rp=false,width=1440,enabled=true}={}){
 const context=await browser.newContext({viewport:{width,height:960},locale:'zh-CN'});const calls=[],errors=[];
 await context.addInitScript(user=>{localStorage.setItem('i18nextLng','zh-CN');if(user){localStorage.setItem('user',JSON.stringify(user));localStorage.setItem('playground_messages','synthetic-private-history');}},user);
 await context.route('**/*',async route=>{const url=new URL(route.request().url());
  if(url.origin==='https://pingxingxian.space'&&url.pathname==='/auth/unified/state'){
   const nonce=url.searchParams.get('request_id');await route.fulfill({contentType:'text/html',body:`<script>const state=${JSON.stringify({type:'pl:unified-session',version:1,request_id:nonce,available,authenticated:auth,subject:auth?subject:null,auth_epoch:auth?'a'.repeat(64):null})};function emit(){parent.postMessage(state,${JSON.stringify(base)})};addEventListener('message',emit);emit();<\/script>`});return;
  }
  if(url.origin==='https://pingxingxian.space'&&url.pathname==='/auth/oidc/auth'){await route.fulfill({contentType:'text/html',body:'<h1>Synthetic OIDC continuation</h1>'});return;}
  if(url.origin!==base){calls.push('blocked:'+url.origin);await route.abort();return;}
  if(url.pathname.startsWith('/api/')){
   calls.push(route.request().method()+':'+url.pathname);let data=[];
   if(url.pathname==='/api/status')data={...status,main_unified_web_login_enabled:enabled};
   else if(url.pathname==='/api/pricing'){await route.fulfill({json:{success:true,data:[],vendors:[],group_ratio:{},usable_group:{},supported_endpoint:{},auto_groups:[]}});return;}
   else if(url.pathname==='/api/setup')data={status:true};
   else if(url.pathname==='/api/user/unified/state')data={authenticated:rp,subject:rp?'53':null};
   else if(url.pathname==='/api/oauth/pingxingxian/start')data={authorization_url:'https://pingxingxian.space/auth/oidc/auth?client_id=parallellines-newapi&state=synthetic'};
   else if(['/api/notice','/api/home_page_content','/api/about','/api/user-agreement','/api/privacy-policy'].includes(url.pathname))data='';
   else if(route.request().method()!=='GET'&&url.pathname!=='/api/user/unified/local-clear'){await route.abort();return;}
   await route.fulfill({json:{success:true,data}});return;
  }
  await route.continue();
 });
 const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));return{context,page,calls,errors};
}
try{
 for(const [name,path,width] of [['guest-home','/',1440],['guest-pricing','/pricing',1440],['guest-login','/login',1440],['guest-login-mobile','/login',390]]){
  const f=await fixture({width});await f.page.goto(base+path);if(path==='/login')await f.page.getByRole('heading',{name:'登录',exact:true}).waitFor();await f.page.waitForTimeout(path==='/pricing'?1200:300);
  assert.equal(await f.page.locator('input[type=password]').count(),0);assert.equal(new URL(f.page.url()).origin,base);assert.ok(!f.calls.includes('POST:/api/oauth/pingxingxian/start'));assert.equal(await f.page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);assert.deepEqual(f.errors,[]);await f.page.screenshot({path:resolve(evidence,name+'.png'),fullPage:true});results.push({case:name,passed:true});await f.context.close();
 }
 const legacy=await fixture({enabled:false});await legacy.page.goto(base+'/login');await legacy.page.locator('input[name="username"]').waitFor();assert.equal(await legacy.page.locator('iframe[title="主站登录状态"]').count(),0);results.push({case:'default-off native login preserved',passed:true});await legacy.context.close();
 const forged=await fixture();await forged.page.goto(base+'/');await forged.page.locator('iframe[title="主站登录状态"]').waitFor({state:'attached'});await forged.page.waitForTimeout(200);const frameURL=await forged.page.locator('iframe[title="主站登录状态"]').getAttribute('src');const requestId=new URL(frameURL).searchParams.get('request_id');await forged.page.evaluate(id=>window.dispatchEvent(new MessageEvent('message',{origin:'https://pingxingxian.space',source:window,data:{type:'pl:unified-session',version:1,request_id:id,available:true,authenticated:true,subject:'53',auth_epoch:'a'.repeat(64)}})),requestId);const issuerFrame=forged.page.frames().find(f=>f.url().startsWith('https://pingxingxian.space/auth/unified/state'));await issuerFrame.evaluate(target=>parent.postMessage({type:'pl:unified-session',version:1,request_id:'b'.repeat(32),available:true,authenticated:true,subject:'53',auth_epoch:'a'.repeat(64)},target),base);await forged.page.waitForTimeout(100);assert.ok(!forged.calls.includes('POST:/api/oauth/pingxingxian/start'));results.push({case:'forged window source and wrong iframe nonce ignored',passed:true});await forged.context.close();
 const guest=await fixture();await guest.page.goto(base+'/console/token');await guest.page.waitForURL(base+'/login');await guest.page.getByRole('heading',{name:'登录',exact:true}).waitFor();assert.ok(!guest.calls.includes('GET:/api/token/'));results.push({case:'guest protected route to unified entry without password form',passed:true});await guest.context.close();
 const active=await fixture({auth:true});await active.page.goto(base+'/');await active.page.waitForURL('https://pingxingxian.space/auth/oidc/auth?**');assert.equal(active.calls.filter(x=>x==='POST:/api/oauth/pingxingxian/start').length,1);results.push({case:'existing Main auth uses original PKCE once',passed:true});await active.context.close();
 const old={id:7,username:'synthetic-old-user',role:1,setting:'{}'};
 const switched=await fixture({auth:true,subject:'54',user:old,rp:true});await switched.page.goto(base+'/console/token');await switched.page.waitForURL('https://pingxingxian.space/auth/oidc/auth?**');const stored=await switched.context.storageState();const oldOrigin=stored.origins.find(x=>x.origin===base);assert.ok(!oldOrigin?.localStorage.some(x=>['user','playground_messages'].includes(x.name)));results.push({case:'subject mismatch discards old cache before new PKCE',passed:true});await switched.context.close();
 const unavailable=await fixture({available:false,user:old,rp:true});await unavailable.page.goto(base+'/console/token');await unavailable.page.getByText('暂时无法确认登录状态，请稍后重试。').waitFor();assert.ok(!unavailable.calls.includes('POST:/api/user/unified/local-clear'));assert.equal(await unavailable.page.evaluate(()=>JSON.parse(localStorage.getItem('user')).id),7);assert.ok(!unavailable.calls.includes('GET:/api/token/'));results.push({case:'unavailable preserves identity and blocks private render',passed:true});await unavailable.context.close();
 const recovery=await fixture();await recovery.page.goto(base+'/root-recovery');await recovery.page.getByRole('heading',{name:'管理员登录'}).waitFor();await recovery.page.getByLabel('密码',{exact:true}).waitFor();assert.ok(!recovery.calls.includes('POST:/api/oauth/pingxingxian/start'));await recovery.page.waitForTimeout(300);await recovery.page.screenshot({path:resolve(evidence,'root-recovery.png'),fullPage:true});results.push({case:'dedicated private recovery form without Main auto login',passed:true});await recovery.context.close();
 writeFileSync(resolve(evidence,'browser-smoke.json'),JSON.stringify({realApiOrModelCalls:false,results},null,2));console.log(JSON.stringify(results,null,2));
}finally{await browser.close();await new Promise(done=>server.close(done));}

