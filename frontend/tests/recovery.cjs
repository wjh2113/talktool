/* 在隔离 Mock 服务运行；会创建测试问计，不用于生产账号。 */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'chromium',args:['--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream']});
 const context=await browser.newContext({viewport:{width:390,height:844},permissions:['microphone','notifications']});
 await context.grantPermissions(['microphone','notifications'],{origin:process.env.TALKTOOL_QA_BASE || 'http://127.0.0.1:15173'});
 const page=await context.newPage(); const errors=[]; page.on('pageerror',e=>errors.push(e.message));
 const base=process.env.TALKTOOL_QA_BASE || 'http://127.0.0.1:15173';
 await page.goto(base+'/#/pages/login/login');await page.locator('input').nth(0).fill(process.env.TALKTOOL_QA_USER || 'qa_admin');await page.locator('input').nth(1).fill(process.env.TALKTOOL_QA_PASSWORD || 'TalktoolQA2026');await page.locator('.submit').click();await page.getByText('沟通表达演练场',{exact:true}).waitFor();
 await page.getByText('智囊',{exact:true}).last().click();await page.locator('textarea').fill('王总总在会上否定我的方案，我想争取下季度项目负责人');await page.getByText('问智囊',{exact:true}).click();
 await page.getByText('锦囊 v1',{exact:true}).waitFor({timeout:20000});
 const cid=new URL(page.url()).hash.match(/id=(\d+)/)[1];
 const token=await page.evaluate(()=>uni.getStorageSync('tt_token'));
 const headers={Authorization:'Bearer '+token};
 const api=async(method,path,data)=>{const r=await context.request.fetch((process.env.TALKTOOL_QA_API || 'http://127.0.0.1:18000')+path,{method,headers,data});assert.ok(r.ok(),await r.text());return r.json()};
 console.log('PASS queued create and automatic plan',cid);
 // 跨设备新版本到达时保留本地草稿。
 await page.locator('textarea').fill('这段尚未发送的草稿要保留');
 const job=await api('POST','/api/advisor/jobs',{request_key:'cross-device-'+Date.now(),kind:'message',consult_id:Number(cid),payload:{text:'如果他当场拒绝我，帮我改一下',kind:'ask'}});
 await page.getByText('锦囊 v2',{exact:true}).waitFor({timeout:15000});
 assert.equal(await page.locator('textarea').inputValue(),'这段尚未发送的草稿要保留');
 console.log('PASS cross-device updates preserve draft');
 // 后端收到提交，但客户端丢失响应。
 let dropped=false;let submittedKey='';
 await page.route('**/api/advisor/jobs',async route=>{
   if(!dropped&&route.request().method()==='POST'){
     dropped=true;submittedKey=route.request().postDataJSON().request_key;
     await route.fetch();await route.abort('connectionreset');
   }else await route.continue();
 });
 await page.locator('textarea').fill('如果他继续反对，再帮我改一下');await page.locator('textarea').press('Enter');
 await page.waitForFunction(()=>Object.keys(localStorage).some(k=>k.startsWith('tt_generation_')));
 await page.waitForTimeout(300);await context.setOffline(true);await page.waitForTimeout(3500);await context.setOffline(false);
 await page.reload();await page.getByText('锦囊 v3',{exact:true}).waitFor({timeout:20000});
 const detail=await api('GET','/api/consults/'+cid);
 assert.equal(detail.plan.version,3);assert.equal(detail.messages.filter(m=>m.role==='user'&&m.text==='如果他继续反对，再帮我改一下').length,1);
 const same=await api('GET','/api/advisor/jobs/find?request_key='+submittedKey);assert.equal(same.status,'done');
 console.log('PASS lost response, offline/online and reload without duplicate message or plan');
 // 返回页面后刷新私人谋士列席信息。
 await api('PUT','/api/consults/'+cid+'/advisors',{codes:[]});
 await page.locator('textarea').fill('Shift+Enter 保留换行');await page.locator('textarea').press('Shift+Enter');await page.waitForTimeout(250);assert.ok((await page.locator('textarea').inputValue()).includes('\n'));
 const inputBox=await page.locator('.input-bar').boundingBox();assert.ok(inputBox.y+inputBox.height<=846);
 console.log('PASS keyboard and mobile input visibility');
 // 实际浏览器麦克风（虚拟音频设备），离页后轨道必须停止。
 await page.addInitScript(()=>{window.__tracks=[];const original=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);navigator.mediaDevices.getUserMedia=async(...a)=>{const s=await original(...a);window.__tracks.push(...s.getTracks());return s}});
 await page.goto(base+'/#/pages/advisor/advisor');await page.reload();await page.locator('.vi').first().click();
 await page.waitForFunction(()=>window.__tracks&&window.__tracks.some(t=>t.readyState==='live'));
 await page.getByText('我的',{exact:true}).last().click();await page.waitForTimeout(600);
 assert.ok(await page.evaluate(()=>window.__tracks.every(t=>t.readyState==='ended')));
 console.log('PASS microphone released on navigation');
 // 已注册真实 Service Worker 并验证系统通知显示。
 const worker=await context.waitForEvent('serviceworker',{timeout:2000}).catch(()=>context.serviceWorkers()[0]);
 assert.ok(worker);
 await context.grantPermissions(['notifications'],{origin:process.env.TALKTOOL_QA_BASE || 'http://127.0.0.1:15173'});
 await worker.evaluate(async()=>{await self.registration.showNotification('智囊验收',{body:'通知链路验证',tag:'talktool-test',data:{url:'/#/pages/advisor/advisor'}})});
 const notifications=await worker.evaluate(async()=> (await self.registration.getNotifications()).map(n=>({title:n.title,tag:n.tag})));
 assert.ok(notifications.some(n=>n.title==='智囊验收'));
 console.log('PASS service worker and browser notification');
 await page.setViewportSize({width:1440,height:1000});await page.goto(base+'/#/pages/advisor/advisor');await page.screenshot({path:process.env.TALKTOOL_QA_SCREENSHOT || '/tmp/talktool-advisor-desktop.png',fullPage:true});
 const box=await page.locator('uni-page-body > .page').boundingBox();assert.ok(box.width<=1121);
 assert.deepEqual(errors,[]);console.log('ALL RECOVERY BROWSER TESTS PASSED');await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
