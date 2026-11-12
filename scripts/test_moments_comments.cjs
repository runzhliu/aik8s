/* Run after make build: NODE_PATH=.local/browser-check/node_modules node scripts/test_moments_comments.cjs */
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const {chromium} = require('playwright');
const site = path.resolve(__dirname, '../site');
const executablePath = process.env.CHROMIUM_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const issue = {number:4,created_at:'2026-11-12T00:00:00Z',user:{login:'runzhliu'},labels:[{name:'moments'}],comments:1,reactions:{heart:2,'+1':1},body:'<!-- moment-id:m-123 -->\n<!-- moment:zh -->\n中文动态 <script>bad()</script>\n<!-- moment:en -->\nEnglish moment\n<!-- moment:images -->\n![image](https://aik8s.run/test.png)\n<!-- moment:end -->'};
(async () => {
 const browser = await chromium.launch({executablePath,args:['--no-sandbox']});
 try {for(const lang of ['', 'en/']) {
  const page=await browser.newPage({viewport:{width:1280,height:900}});
  let limitApi = false;
  await page.route('**/*',async route=>{
   const url=new URL(route.request().url());
   if(url.hostname==='avatars.githubusercontent.com')return route.fulfill({contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAD0lEQVR4nGNgYPgPRmAKABf2A/1+6zfzAAAAAElFTkSuQmCC','base64')});
   if(url.hostname==='api.github.com') {
    if(limitApi)return route.fulfill({status:403,json:{message:'rate limited'},headers:{'access-control-allow-origin':'*'}});
    if(url.pathname.endsWith('/issues/4/comments'))return route.fulfill({json:[{user:{login:'octocat'},body:'A comment <img src=x onerror=alert(1)>'}],headers:{'access-control-allow-origin':'*'}});
    if(url.pathname.endsWith('/issues'))return route.fulfill({json:[issue,{...issue,number:5,user:{login:'stranger'}},{...issue,number:6,pull_request:{}}],headers:{'access-control-allow-origin':'*'}});
    return route.abort();
   }
   if(url.hostname!=='aik8s.run')return route.abort();
   if(url.pathname==='/assets/data/moments-issues.json')return route.fulfill({json:{issues:[issue],comments:{'4':[{user:{login:'octocat'},body:'Snapshot comment'}]}}});
   let file=path.resolve(site,'.'+decodeURIComponent(url.pathname));if(url.pathname.endsWith('/'))file=path.join(file,'index.html');
   if(!file.startsWith(site+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile())return route.abort();
   return route.fulfill({path:file});
  });
  await page.goto(`https://aik8s.run/${lang}moments/`);
  const card=page.locator('.moment'); await card.waitFor();
  assert.equal(await card.count(),1,'only owner issues, excluding pull requests');
  assert.equal(await card.getAttribute('id'),'issue-4');
  const avatar=card.locator('.moment__avatar-image');
  assert.equal(await avatar.getAttribute('src'),'https://avatars.githubusercontent.com/u/20874664?v=4');
  await avatar.evaluate(img=>img.dispatchEvent(new Event('error')));
  assert.equal(await card.locator('.moment__avatar-image').count(),0,'fallback letter remains if avatar fails');
  assert.equal(await card.locator('.moment__avatar').textContent(),'R');
  assert.equal(await card.locator('#m-123').count(),1,'legacy anchor');
  assert.equal(await card.locator('.moment__image').count(),1);
  assert.ok((await card.locator('.moment__text').textContent()).includes(lang?'English moment':'中文动态'));
  assert.equal(await card.locator('.moment__text script').count(),0,'untrusted text is not HTML');
  assert.equal(await card.locator('.moment__github-like').getAttribute('href'),'https://github.com/runzhliu/aik8s/issues/4');
  assert.match(await card.locator('.moment__github-like').textContent(),/3/);
  await card.locator('summary').click();
  await card.locator('.moment__comment-text').waitFor();
  assert.match(await card.locator('.moment__comment-text').textContent(),/A comment/);
  assert.equal(await card.locator('.moment__comment-text img').count(),0,'comments remain text');
  assert.equal(await card.locator('.moment__github-link').getAttribute('href'),'https://github.com/runzhliu/aik8s/issues/4');
  limitApi=true;
  await page.reload();
  await page.locator('.moment').waitFor();
  await page.locator('.moment summary').click();
  await page.getByText('Snapshot comment').waitFor();
  await page.close();
 }} finally {await browser.close();}
 console.log('Moments: owner filtering, bilingual content, GitHub likes/comments and HTML safety OK');
})().catch(err=>{console.error(err);process.exitCode=1;});
