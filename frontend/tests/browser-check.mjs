/* --conversation UUID / --real-conversation UUID: inspect an existing demo without inference.
   --round6 CID PORT DIR JOB SHA256 LOCATION: only view and download the already committed job.
   --submit-real-esmfold2 / --submit-real-protenix: submit ubiquitin once on a configured backend.
   --offline-protenix PORT DIR: temporary test server with a CLI double, never a prediction.
   --faults: fresh chat on the isolated test stack at 5174, local scripted upstream. */
import { chromium } from 'playwright-core'
import { createHash } from 'node:crypto'
import { readFile, mkdir, writeFile, rename } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import assert from 'node:assert/strict'

const [action, argument, third, proofDir, expectedJob, expectedHash, location] = process.argv.slice(2)
const round6 = action === '--round6'
const tempDir = round6 ? proofDir : third
const offline = action === '--offline-protenix'
if (round6) {
  assert(/^\d+$/.test(third) && Number(third)>1023 && Number(third)<=65535 && proofDir)
  assert(/^[a-f0-9-]{36}$/.test(expectedJob) && /^[a-f0-9]{64}$/.test(expectedHash))
  assert(['colab_backend','mac_archive','offline_backend'].includes(location))
}
if (offline) assert(/^\d+$/.test(argument) && Number(argument) > 1023 && Number(argument) <= 65535 && tempDir)
const faults = action === '--faults', submitReal = offline || ['--submit-real-esmfold2', '--submit-real-protenix'].includes(action)
let realModel = action === '--submit-real-esmfold2' ? 'ESMFold2' : 'Protenix'
const real = submitReal || action === '--real-conversation' || round6
let cid = offline ? undefined : argument
if (faults || submitReal) {
  assert.equal(cid, undefined, 'Submission and fault checks take no conversation ID')
} else {
  assert(['--conversation', '--real-conversation', '--round6'].includes(action) && /^[0-9a-f-]{36}$/i.test(cid || ''),
    'Use --conversation UUID, --real-conversation UUID, --submit-real-esmfold2, --submit-real-protenix or --faults')
}
const base='http://127.0.0.1:' + (round6 ? third : offline ? argument : '5173')
const shots=offline || round6 ? tempDir+'/' : fileURLToPath(new URL('../../examples/screenshots/',import.meta.url))
const outputs=offline || round6 ? tempDir+'/' : fileURLToPath(new URL('../../examples/outputs/',import.meta.url))
const sha=bytes=>createHash('sha256').update(bytes).digest('hex')
const UBQ='MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG'
const browser=await chromium.launch({...(round6 && process.env.PLAYWRIGHT_BROWSERS_PATH ? {} : {channel:'chrome'}),
  ...(process.env.CHROME_PATH ? {executablePath:process.env.CHROME_PATH} : {}),
  args:['--use-angle=swiftshader','--enable-unsafe-swiftshader'], headless:true})
const page=await browser.newPage({viewport:{width:1210,height:900},acceptDownloads:true, reducedMotion:'reduce'})
const errors = [], httpErrors = []
const receipt={conversation_id:cid, job_id:expectedJob, browser:browser.version(), location}
const saveReceipt=async facts=>{
  if (!round6) return
  Object.assign(receipt,facts)
  await writeFile(shots+'browser.json.part',JSON.stringify(receipt,null,2))
  await rename(shots+'browser.json.part',shots+'browser.json')
}
try {
  if (round6) await page.route('**/api/chat', route=>route.abort())
  page.on('pageerror',e=>errors.push(e.message))
  page.on('response',r=>{if(r.status()>=400)httpErrors.push(r.status()+' '+new URL(r.url()).pathname)})
  const calls=[], poll={}
  page.on('request',r=>{
    const url=new URL(r.url())
    if (url.pathname==='/api/chat') calls.push(r.method())
    if (/^\/api\/jobs\/[0-9a-f-]{36}$/.test(url.pathname)) (poll[url.pathname]??=[]).push(Date.now())
  })
  await mkdir(shots,{recursive:true})
  if (faults) {
    await page.goto('http://127.0.0.1:5174')
    for (const [model,err] of [['ESMFold2','execution_error'],['Protenix','invalid_output']]) {
      await page.getByRole('textbox').fill(`Use ${model}. Sequence: ${UBQ}`)
      await page.getByRole('button',{name:'发送消息'}).click()
      const card=page.getByRole('article').filter({has:page.getByRole('heading',{name:model,exact:true})})
      await card.getByText('运行中',{exact:true}).waitFor({timeout:12000})
      await card.getByText(err,{exact:true}).waitFor({timeout:12000})
      assert.equal(await card.getByText('失败',{exact:true}).count(),1)
      assert.equal(await card.getByText('已完成',{exact:true}).count(),0)
      assert.equal(await card.getByRole('button').count(),0)
      assert.equal(await card.locator('canvas').count(),0)
      const id=await card.getAttribute('data-job-id'), times=poll['/api/jobs/'+id]
      assert(times.length>=2 && times.slice(1).some((t,i)=>t-times[i]>=1850 && t-times[i]<4000))
      console.log('PASS browser: running → failed,',model,err,'· poll intervals (ms)',times.slice(1).map((t,i)=>t-times[i]))
    }
    assert.equal(calls.length,2)
    await page.reload()
    await page.getByText('invalid_output',{exact:true}).waitFor()
    await page.getByText('execution_error',{exact:true}).waitFor()
    await page.getByRole('region',{name:'本会话的任务'}).screenshot({path:shots+'round-3-failures.png'})
  } else {
    let submittedJob
    if (submitReal) {
      const health = await (await page.request.get(base+'/api/health')).json()
      const route = realModel.toLowerCase()
      assert(health.llm_configured && health.prediction_configured?.[route] && health.prediction_modes[route] === 'real',
        'A configured Real '+realModel+' route is required before sending chat')
      await page.goto(base)
      await page.getByRole('textbox').fill('请用 '+realModel+' 预测这条序列：\n'+UBQ)
      const response = page.waitForResponse(r => new URL(r.url()).pathname === '/api/chat', {timeout:75000})
      await page.getByRole('button',{name:'发送消息'}).click()
      const reply = await (await response).json()
      assert.equal(reply.outcome, 'job_submitted', reply.error?.code || reply.outcome)
      assert.equal(reply.job_ids.length, 1)
      cid = reply.conversation_id
      submittedJob = reply.job_ids[0]
      console.log(offline ? 'Offline test chat:' : 'Real chat committed:',cid,'job',submittedJob)
    } else {
      await page.goto(base+'/?conversation='+encodeURIComponent(cid))
      if (real) {
        const history = await (await page.request.get(base+'/api/conversations/'+cid)).json()
        assert.equal(history.job_ids.length, 1, 'This check expects a single-job demonstration conversation')
        if (round6) assert.deepEqual(history.job_ids,[expectedJob])
        const saved = await (await page.request.get(base+'/api/jobs/'+history.job_ids[0]+'?conversation_id='+cid)).json()
        assert(['esmfold2','protenix'].includes(saved.model) && saved.mode === 'real')
        realModel = saved.model === 'protenix' ? 'Protenix' : 'ESMFold2'
      }
    }
    let terminalLabel = '已完成'
    let round = realModel === 'Protenix' ? 'round-5' : 'round-4'
    for (const model of (real ? [realModel] : ['ESMFold2','Protenix'])) {
      const card=page.getByRole('article').filter({has:page.getByRole('heading',{name:model,exact:true})})
      const waitMs = real && !offline ? 3660000 : 140000
      await card.getByRole('status').filter({hasText:/^(已完成|失败)$/}).waitFor({timeout:waitMs})
      assert.equal(await card.getByText(real ? 'Real' : 'Mock · 示例',{exact:true}).count(),1)
      const id=await card.getAttribute('data-job-id')
      if (submittedJob) assert.equal(id, submittedJob)
      const jobUrl=base+'/api/jobs/'+id+'?conversation_id='+cid
      const job=await (await page.request.get(jobUrl)).json()
      if (round6) {
        assert.equal(id,expectedJob);assert.equal(job.sha256,expectedHash);assert.equal(job.model,'protenix')
        assert.equal(job.status,'succeeded')
      }
      assert.equal(job.id,id); assert.equal(job.conversation_id,cid)
      assert.equal(job.mode,real?'real':'mock'); assert.equal(job.model,model.toLowerCase())
      assert.equal(job.length,76)
      if (real) {
        const openprotein = model === 'ESMFold2' && job.parameters?.provider === 'openprotein'
        if (openprotein) {
          round = 'openprotein'
          assert.equal(job.seed,0)
        }
        assert.equal(job.model_version, model === 'Protenix' ? 'protenix_mini_default_v0.5.0' :
          openprotein ? 'esmfold2' : 'esmfold2-fast-2026-05')
        if (model === 'Protenix') assert.equal(job.seed,101)
        assert.equal(job.fixture_source,null)
        await page.getByRole('log',{name:'聊天记录'}).screenshot({path:shots+(round6?'chat.png':round+'-chat-'+id+'.png')})
      }
      if (real && job.status === 'failed') {
        terminalLabel = '失败'
        assert.equal(job.result_available,false); assert.equal(job.sha256,null); assert.equal(job.download_name,null)
        await card.getByText(job.error,{exact:true}).waitFor()
        assert.equal(await card.getByRole('button').count(),0); assert.equal(await card.locator('canvas').count(),0)
        const structure = base+'/api/jobs/'+id+'/structure?conversation_id='+cid
        for (const url of [structure, structure+'&download=true']) assert.equal((await page.request.get(url)).status(),409)
        await card.screenshot({path:shots+round+'-'+model.toLowerCase()+'-'+id+'.png'})
        console.log('Recorded Real failure:',id,job.error,job.error_message)
        process.exitCode = 2
        continue
      }
      assert.equal(job.status,'succeeded'); assert.equal(job.result_available,true)
      const viewed = page.waitForResponse(r => {
        const url = new URL(r.url())
        return url.pathname === '/api/jobs/'+id+'/structure' && url.searchParams.get('conversation_id') === cid && !url.searchParams.has('download')
      })
      await card.getByRole('button',{name:'查看三维结构'}).click()
      const shown = await viewed
      assert.equal(shown.status(),200)
      await card.getByRole('button',{name:'复位视角'}).waitFor({timeout:35000})
      const canvas=card.locator('canvas')
      await canvas.scrollIntoViewIfNeeded()
      const box=await canvas.boundingBox()
      assert(box && box.width>200 && box.height>200)
      // Wait for a visible, non-uniform protein drawing; a blank WebGL canvas is not a pass.
      const picture=()=>canvas.evaluate(el=>{
        const c=document.createElement('canvas'); c.width=96;c.height=64
        const ctx=c.getContext('2d');ctx.drawImage(el,0,0,c.width,c.height)
        const data=ctx.getImageData(0,0,c.width,c.height).data
        let area=0,cx=0,cy=0,xx=0,yy=0,xy=0
        for(let i=0;i<data.length;i+=4){
          if(Math.abs(data[i]-data[0])+Math.abs(data[i+1]-data[1])+Math.abs(data[i+2]-data[2])<65)continue
          const x=(i/4)%96,y=Math.floor(i/4/96);area++;cx+=x;cy+=y;xx+=x*x;yy+=y*y;xy+=x*y
        }
        return {area,shape:[xx/area-(cx/area)**2,yy/area-(cy/area)**2,xy/area-cx*cy/area**2]}
      })
      async function changed(predicate){
        for(let i=0;i<65;i++){const s=await picture();if(predicate(s))return s;await new Promise(r=>setTimeout(r,70))}
        throw new Error('WebGL canvas did not show the expected camera change')
      }
      const before=await changed(s=>s.area>100 && s.area<5300)
      const x=box.x+box.width*.48,y=box.y+box.height*.51
      await page.mouse.move(x,y);await page.mouse.down();await page.mouse.move(x+85,y+50,{steps:18});await page.mouse.up()
      const rotated=await changed(s=>s.shape.some((n,i)=>Math.abs(n-before.shape[i])>4))
      await page.mouse.move(x,y);await page.mouse.wheel(0,-420)
      const zoomed=await changed(s=>Math.abs(s.area-rotated.area)>rotated.area*.10)
      if (round6) {
        assert.equal(sha(await shown.body()),expectedHash)
        assert.equal(calls.length,0)
        await card.screenshot({path:shots+'molstar.png'})
        const url=new URL(shown.url())
        await saveReceipt({view_path:url.pathname+url.search, view_sha256:expectedHash, before, rotated, zoomed, chat_requests:calls.length})
      }
      await card.getByRole('button',{name:'复位视角'}).click()
      const downloadPath='/api/jobs/'+id+'/structure?conversation_id='+cid+'&download=true'
      const [file,received]=await Promise.all([
        page.waitForEvent('download'),
        round6 ? page.waitForResponse(r=>r.url()===base+downloadPath) : null,
        card.getByRole('button',{name:real?'下载 Real PDB':'下载 Mock PDB'}).click()
      ])
      const name=file.suggestedFilename(), bytes=await readFile(await file.path())
      assert.equal(name,`${model.toLowerCase()}-${job.mode}-${id}.pdb`)
      assert.deepEqual(bytes,await shown.body())
      assert.equal(job.sha256,sha(bytes));assert(bytes.includes(Buffer.from(id)))
      assert.equal(await page.locator('canvas').count(),1)
      if (real) {
        await mkdir(outputs,{recursive:true})
        await file.saveAs(outputs+name)
        if (round6) {
          assert.equal(received.status(),200);assert.deepEqual(await received.body(),bytes)
          await saveReceipt({download_path:downloadPath, download_name:name, download_sha256:sha(bytes)})
        }
      }
      const shot=real ? round+'-'+model.toLowerCase()+'-'+id : 'round-3-'+model.toLowerCase()
      if (!round6) await card.screenshot({path:shots+shot+'.png'})
      console.log('PASS browser:',model,'· colored pixels',before.area,'→',rotated.area,'→',zoomed.area,'· download',name)
    }
    await page.reload()
    await page.getByText(terminalLabel,{exact:true}).nth(real?0:1).waitFor()
    assert.equal(calls.length,submitReal ? 1 : 0,'Viewing / recovery / downloads must not send chat')
    assert.deepEqual(errors,[])
    if (round6) await saveReceipt({refresh:true, chat_requests:calls.length})
  }
  assert.deepEqual(errors,[])
} catch (e) {
  console.error('Browser diagnostics:',{errors,httpErrors,title:await page.title(),visible:(await page.locator('body').innerText()).slice(-1200)})
  throw e
} finally {await browser.close()}
