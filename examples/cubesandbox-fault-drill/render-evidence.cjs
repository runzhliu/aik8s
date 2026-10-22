// Capture the custom evidence viewer. This does not create product screenshots.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('fs');
const base=process.argv[2]||'http://127.0.0.1:18975/';
const output=process.argv[3]||'.local/cube-drill/images';
fs.mkdirSync(output,{recursive:true});
(async()=>{
  const browser=await chromium.launch(process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE}:{});
  try{
    const page=await browser.newPage({viewport:{width:1200,height:675},deviceScaleFactor:1});
    for(const group of ['control','runtime','dependencies']){
      await page.goto(base+'?group='+group,{waitUntil:'networkidle'});
      await page.locator('tbody tr').first().waitFor();
      if(await page.locator('main').evaluate(el=>el.scrollHeight>665))throw Error('Viewer would be clipped: '+group);
      await page.screenshot({path:output+'/'+group+'-results.png'});
    }
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
