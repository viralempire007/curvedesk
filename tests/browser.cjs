// End-to-end test against an isolated offline fixture, never a broker account.
const {chromium}=require('playwright'),{spawn}=require('node:child_process'),assert=require('node:assert/strict'),path=require('node:path');
(async()=>{
 const root=path.resolve(__dirname,'..'),port=18877;
 const server=spawn(process.env.PYTHON||'python',['tests/fixture.py',String(port)],{cwd:root,stdio:['ignore','pipe','pipe']});
 let stderr='';server.stderr.on('data',x=>stderr+=x);
 await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('Fixture startup timed out: '+stderr)),20000);server.stdout.on('data',x=>{if(x.toString().includes('FIXTURE_READY')){clearTimeout(timer);resolve();}});server.on('exit',code=>{clearTimeout(timer);reject(Error('Fixture exited '+code+': '+stderr));});});
 let browser;
 try{
  browser=await chromium.launch({headless:true,executablePath:process.env.CURVEDESK_CHROMIUM||undefined,args:['--no-sandbox','--disable-dev-shm-usage','--no-zygote','--single-process']});const page=await browser.newPage({viewport:{width:1440,height:1050}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:'+port);await page.waitForFunction(()=>document.getElementById('contract-count').textContent==='2');
  await page.waitForFunction(()=>!document.getElementById('analysis').hidden);
  assert.match(await page.locator('#measurements').textContent(),/ATR14/);assert.match(await page.locator('#live-ratios').textContent(),/1:2/);
  await page.click('[data-page="builder"]');await page.selectOption('#far-contract','2');await page.fill('#far-lots','2');await page.click('#pair-form button');
  await page.waitForFunction(()=>document.getElementById('basket-count').textContent==='2');
  await page.click('[data-page="ratios"]');for(const [id,value]of Object.entries({'scenario-ne':'100','scenario-fe':'120','scenario-nx':'110','scenario-fx':'125'}))await page.fill('#'+id,value);
  await page.click('#scenario-form button');await page.waitForFunction(()=>document.getElementById('scenario-output').textContent.includes('50'));
  const margin=page.locator('#margin-fields input').first();await margin.fill('5000');await page.waitForTimeout(3200);assert.equal(await margin.inputValue(),'5000');
  await page.click('[data-page="settings"]');await page.fill('#cost-min','250');await page.click('#cost-form button');await page.waitForFunction(()=>document.getElementById('message').textContent.includes('filters saved'));
  await page.reload();await page.click('[data-page="builder"]');assert.equal(await page.locator('#far-lots').inputValue(),'2');
  await page.click('[data-page="settings"]');assert.equal(await page.locator('#cost-min').inputValue(),'250');
  for(const name of ['journal','history','terminal'])await page.click(`[data-page="${name}"]`);
  await page.setViewportSize({width:390,height:844});await page.waitForTimeout(100);assert.equal(await page.locator('#terminal').isVisible(),true);
  assert.deepEqual(errors,[]);console.log('Browser checks passed: terminal, charts, depth, ratio scenario, persistent drafts/settings, margin focus, navigation and mobile layout.');
 }finally{if(browser)await browser.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
