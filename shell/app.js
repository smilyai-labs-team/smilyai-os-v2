(() => {
'use strict';
const $=s=>document.querySelector(s);
const state={config:null,token:'',online:false,job:null,seq:0,pending:null,section:'ai',retry:1000,attached:'',filePath:'~'};
const node=(tag,attrs={},...children)=>{
 const el=document.createElement(tag);
 for(const [k,v] of Object.entries(attrs)){if(k.startsWith('on'))el.addEventListener(k.slice(2),v);else if(k==='class')el.className=v;else if(k in el)el[k]=v;else el.setAttribute(k,v);}
 for(const c of children.flat())if(c!==null&&c!==undefined)el.append(c instanceof Node?c:document.createTextNode(String(c)));
 return el;
};
const notice=message=>{const el=node('div',{class:'toast'},message);$('#toasts').append(el);setTimeout(()=>el.remove(),5500);};
const fallback={setState(){},setReduced(){},setAmplitude(){},setPointer(){},destroy(){}};
let orb=fallback;
try{if(window.SmilyOrb)orb=new SmilyOrb($('#orbCanvas'));}catch(e){console.warn('Orb fallback',e.name);}
let feedbackTimer, retryTimer, polling=false;
const setState=(next,message)=>{
 clearTimeout(feedbackTimer);document.body.dataset.state=next;orb.setState(next);
 $('#stateLabel').textContent=({idle:'YOUR COMPUTER, UNDERSTOOD',thinking:'THINKING',tool:'WORKING',listening:'MICROPHONE ON',transcribing:'TRANSCRIBING',permission:'YOUR PERMISSION',success:'COMPLETE',error:'NEEDS ATTENTION',offline:'LOCAL CONTROLS',speaking:'SPEAKING',stopping:'STOPPING'})[next]||next.toUpperCase();
 if(message)$('#responseText').textContent=message;
};
async function api(path,body,timeout=6000){
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeout);
 try{
  const res=await fetch('/api'+path,{method:body===undefined?'GET':'POST',signal:controller.signal,headers:{'Content-Type':'application/json','X-SmilyAI-Session':state.token},body:body===undefined?undefined:JSON.stringify(body)});
  const data=await res.json();if(!res.ok){if(res.status===503)offline();throw Error(data.error||'Request failed');}return data;
 }catch(e){if(e.name==='AbortError')throw Error('Request timed out. You can retry.');throw e;}
 finally{clearTimeout(timer);}
}
const reducedMedia=matchMedia('(prefers-reduced-motion: reduce)');
function preferences(){
 const reduced=reducedMedia.matches||!!state.config?.appearance?.reduced_effects;
 document.body.classList.toggle('reduced-effects',reduced);orb.setReduced(reduced);
 $('#muteButton').hidden=!state.config?.voice?.auto_speak;
}
reducedMedia.addEventListener('change',preferences);
const voice=window.SmilyVoice?new SmilyVoice({api,config:()=>state.config,state:setState,amplitude:x=>orb.setAmplitude(x),submit:text=>submit(text),notice}):{start(){notice('Voice module unavailable');},stop(){},cancel(){},speak(){}};
function sweep(){const el=$('#spectral');el.classList.remove('sweep');requestAnimationFrame(()=>el.classList.add('sweep'));}
function revealPrompt(){ $('#promptForm').hidden=false;$('#suggestions').hidden=false;$('#promptInput').focus(); }
function closeSurface(){ $('#surface').hidden=true;document.body.classList.remove('panel-open'); }
function surface(title,subtitle,...content){
 $('#surfaceTitle').textContent=title;$('#surfaceSubtitle').textContent=subtitle;$('#surfaceBody').replaceChildren(...content.flat());$('#surface').hidden=false;document.body.classList.add('panel-open');
}
function offline(){
 state.online=false;$('#connection').textContent='Harness unavailable';$('#recovery').hidden=false;
 $('#recoveryText').textContent='The AI harness is reconnecting. Native apps remain available.';
 setState('offline','Your computer is still here.');
 clearTimeout(retryTimer);retryTimer=setTimeout(connect,state.retry);state.retry=Math.min(30000,state.retry*2);
}
async function connect(){
 clearTimeout(retryTimer);
 try{
  const b=await api('/bootstrap',undefined,4000);state.token=b.session_token;state.config=b.config;state.hardware=b.hardware;state.online=true;state.retry=1000;
  $('#recovery').hidden=true;$('#connection').textContent=b.config.provider.kind==='mock'?'Local tools':'AI configured';preferences();window.smilyReveal?.();
  if(!b.config.setup_complete&&!$('#settingsDialog').open&&!$('#setupDialog').open)$('#setupDialog').showModal();
  if(b.active_job||state.job){if(b.active_job&&b.active_job!==state.job)state.seq=0;state.job=b.active_job||state.job;$('#stopButton').hidden=false;poll();}
  else setState('idle');
 }catch(e){window.smilyReveal?.();offline();}
}
async function submit(text,direct){
 if(state.job){notice('Stop the current task before starting another.');return;}
 if(!state.online){notice('Harness unavailable. Use native shortcuts or Retry.');return;}
 text=(text??$('#promptInput').value).trim();if(!text&&!direct)return;
 const body=direct||{text:text+state.attached};state.attached='';
 $('#promptInput').value='';$('#promptInput').placeholder='Ask your computer…';$('#promptForm').hidden=true;$('#suggestions').hidden=true;
 closeSurface();setState('thinking','Understanding…');$('#stopButton').hidden=false;
 try{
  const result=await api(direct?'/tool':'/jobs',body);state.job=result.job_id;state.seq=0;poll();
 }catch(e){notice(e.message);setState('error','That request did not start.');$('#stopButton').hidden=true;}
}
const tool=(name,args={})=>submit('',{name,arguments:args});
async function stop(){
 voice.cancel();
 if(state.job){try{await api('/cancel',{job_id:state.job});setState('stopping','Stopping after the current action…');if($('#confirmDialog').open)$('#confirmDialog').close('cancel');}catch(e){notice(e.message);}}
 else setState('idle');
}
async function poll(){
 if(polling||!state.job)return;polling=true;
 try{
  while(state.job){
   if(document.hidden){await new Promise(r=>setTimeout(r,1500));continue;}
   const response=await api('/job?id='+encodeURIComponent(state.job)+'&after='+state.seq);
   for(const event of response.events){
    state.seq=event.seq;
    if(event.state==='permission'){await showPermission(event.confirmation);}
    else if(event.state==='observation'){if(event.action?.data)render(event.action.data);}
    else setState(event.state,event.message);
   }
   if(response.result){
    const result=response.result;state.job=null;$('#stopButton').hidden=true;
    if(result.action?.data)render(result.action.data);
    const ok=result.status==='success';setState(ok?'success':result.status==='provider_unavailable'?'offline':'error',result.message||'Done.');
    if(ok){sweep();voice.speak(result.message||'Done.');}
    if(!state.config?.voice?.auto_speak)feedbackTimer=setTimeout(()=>setState('idle'),1800);
    break;
   }
   await new Promise(r=>setTimeout(r,500));
  }
 }catch(e){if(e.message==='Invalid request or shell session'){state.job=null;state.seq=0;$('#stopButton').hidden=true;}notice('Connection interrupted. Reconnecting; an action already started may have completed.');offline();}
 finally{polling=false;}
}
function showPermission(info){
 if(!info.local&&state.pending?.token===info.token)return;
 state.pending=info;setState('permission','May I do this?');
 $('#confirmTitle').textContent=info.title;$('#confirmDescription').textContent=info.description;
 $('#confirmDetails').textContent=Object.entries(info.arguments||{}).filter(([k])=>!['password','api_key'].includes(k)).map(([k,v])=>k+': '+String(v)).join('\n');
 $('#phraseLabel').hidden=!info.strong_phrase;$('#confirmPhrase').value='';
 if(!$('#confirmDialog').open)$('#confirmDialog').showModal();
}
$('#confirmDialog').addEventListener('close',async()=>{
 const approved=$('#confirmDialog').returnValue==='approve';
 if(state.pending?.local){const cb=state.pending.local;state.pending=null;setState('idle');cb(approved);return;}
 if(!state.pending||!state.job)return;
 const info=state.pending;state.pending=null;
 try{await api('/confirm',{job_id:state.job,token:info.token,approved,phrase:$('#confirmPhrase').value});}catch(e){notice(e.message);}
});
const fmt=n=>{if(!Number.isFinite(n))return'—';const units=['B','KiB','MiB','GiB'];let i=0;while(n>=1024&&i<3){n/=1024;i++;}return n.toFixed(i?1:0)+' '+units[i];};
function render(data){
 if(data.surface==='memory'){
  const content=[node('div',{class:'metric'},String(data.percent)+'%'),node('p',{class:'fine'},fmt(data.used)+' of '+fmt(data.total)),
   node('progress',{value:data.percent,max:100,'aria-label':'Memory usage'}),node('h3',{},'Largest processes')];
  for(const p of data.processes||[])content.push(node('div',{class:'row'},node('span',{},p.name),node('small',{},fmt(p.bytes))));
  surface('Memory','LIVE SYSTEM VIEW',content);
 }else if(data.surface==='files')filesPanel(data);
 else if(data.surface==='apps')surface('Applications','INSTALLED ON THIS COMPUTER',(data.items||[]).map(a=>node('button',{class:'row',onclick:()=>tool('open_app',{app:a.name})},a.name,' ↗')));
 else if(data.surface==='app_missing')surface('Not installed','APPLICATION',node('p',{class:'fine'},data.app+' is not installed.'),node('button',{class:'primary',onclick:()=>tool('install_package',{name:data.app.toLowerCase()})},'Request installation'));
 else if(['system','cpu','disk','battery','network','wifi','windows'].includes(data.surface)){
  surface(data.surface[0].toUpperCase()+data.surface.slice(1),'THIS COMPUTER',Object.entries(data).filter(([k])=>k!=='surface').map(([k,v])=>node('div',{class:'row'},node('span',{},k.replaceAll('_',' ')),node('small',{},typeof v==='object'?JSON.stringify(v):String(v)))));
 }else if(data.content!==undefined)surface('Text preview',data.path,node('pre',{class:'fine'},data.content));
}
function filesPanel(data){
 state.filePath=data.path||state.filePath;
 const input=node('input',{placeholder:'Folder name',required:true,'aria-label':'New folder name'});
 const form=node('form',{class:'inline-form',onsubmit:e=>{e.preventDefault();if(input.value.includes('/')||input.value.startsWith('.'))return notice('Use a simple folder name.');tool('create_folder',{path:state.filePath+'/'+input.value});}},input,node('button',{type:'submit'},'Create'));
 const path=node('input',{value:state.filePath,'aria-label':'Folder path'});
 const browse=node('form',{class:'inline-form',onsubmit:e=>{e.preventDefault();tool('list_files',{path:path.value});}},path,node('button',{type:'submit'},'Go'));
 const rows=(data.items||data.matches||[]).map(f=>{
  const open=node('button',{class:'item-name',onclick:()=>f.kind==='folder'?tool('list_files',{path:f.path}):fileActions(f)},(f.kind==='folder'?'▱ ':'· ')+f.name);
  return node('div',{class:'row'},open,node('small',{},f.kind==='folder'?'Folder':fmt(f.size)));
 });
 surface('Files',data.query?'SEARCH RESULTS':state.filePath,browse,form,...rows);
}
function fileActions(f){
 const destination=node('input',{value:f.path, 'aria-label':'Destination path'});
 surface(f.name,'FILE ACTIONS',node('p',{class:'fine'},f.path),destination,node('div',{class:'panel-actions'},
  node('button',{onclick:()=>tool('read_file',{path:f.path})},'Read with permission'),
  node('button',{onclick:()=>tool('copy_file',{source:f.path,destination:destination.value})},'Copy to path'),
  node('button',{onclick:()=>tool('move_file',{source:f.path,destination:destination.value})},'Move / rename'),
  node('button',{onclick:()=>tool('delete_file',{path:f.path})},'Move to Trash')));
}
async function panel(name){
 if(name==='settings')return settings('ai');
 if(name==='files')return tool('list_files');
 if(name==='apps')return tool('list_applications');
 if(name==='network')return tool('open_network_settings');
 if(name==='activity'){
  try{const r=await api('/activity');surface('Activity','ACTIONS, NOT PRIVATE REASONING',r.items.reverse().map(x=>node('div',{class:'row'},node('span',{},x.event.replaceAll('_',' ')),node('small',{},x.tool||new Date(x.time).toLocaleTimeString()))));}catch(e){notice(e.message);}
 }
}
const providers=[
 ['smilyai','SmilyAI API','https://apismilyai.pythonanywhere.com/v1'],
 ['mock','Local tools · no account',''],['custom','OpenAI-compatible endpoint',''],
 ['openai','OpenAI','https://api.openai.com/v1'],['openrouter','OpenRouter','https://openrouter.ai/api/v1'],
 ['ollama','Ollama','http://127.0.0.1:11434/v1'],['llama.cpp','llama.cpp','http://127.0.0.1:8080/v1'],
 ['anthropic','Anthropic-compatible gateway',''],['gemini','Gemini-compatible gateway','']
];
const field=(label,id,value,type='text')=>node('label',{},label,node('input',{id,value:value??'',type,autocomplete:'off'}));
function settings(section='ai'){
 state.section=section;const c=state.config||{};$('#settingsStatus').textContent='';
 document.querySelectorAll('[data-settings]').forEach(b=>b.classList.toggle('active',b.dataset.settings===section));
 let content=[];
 if(section==='ai'){
  const select=node('select',{id:'providerKind'},providers.map(([value,label])=>node('option',{value},label)));select.value=c.provider?.kind||'mock';
  select.onchange=()=>{const p=providers.find(p=>p[0]===select.value);$('#providerEndpoint').value=p[2];$('#providerModel').value=p[0]==='mock'?'smily-simulator':'';$('#providerKey').value='';};
  content=[node('h3',{},'Choose your intelligence'),node('p',{},'Your computer works without an account. Keys stay with the endpoint you configure.'),
   node('label',{},'Provider',select),field('Base URL','providerEndpoint',c.provider?.endpoint||providers.find(p=>p[0]===select.value)?.[2]),
   field('API key · leave blank to keep saved key','providerKey','','password'),
   node('label',{},'Model ID',node('input',{id:'providerModel',value:c.provider?.model||'',list:'modelOptions',placeholder:'Fetch models or enter an ID'}),node('datalist',{id:'modelOptions'})),
   node('label',{class:'toggle'},node('input',{type:'checkbox',id:'streaming',checked:c.provider?.streaming!==false}),'Stream provider responses'),
   node('div',{class:'controls'},node('button',{type:'button',onclick:models},'Test & fetch models'),
    node('button',{type:'button',onclick:()=>saveAI(true)},'Delete saved key')),
   node('p',{class:'fine'},'Tests use the values above without saving. Model-list failure does not block manual entry. Changing the endpoint never transfers a saved key.')];
 }else if(section==='voice'){
  const voices=window.speechSynthesis?.getVoices().filter(v=>v.localService)||[];
  const select=node('select',{id:'ttsVoice'},node('option',{value:''},'System default'),voices.map(v=>node('option',{value:v.name},v.name)));select.value=c.voice?.voice||'';
  content=[node('h3',{},'Speak to your computer'),node('p',{},'Hold Space while the shell is focused, or hold the orb. Audio goes only to your local speech service. Release to send; Escape cancels.'),
   node('label',{class:'toggle'},node('input',{id:'allowMic',type:'checkbox',checked:!!c.privacy?.microphone}),'Enable push-to-talk'),
   field('Local whisper.cpp endpoint','sttURL',c.voice?.stt_url||'','url'),
   node('p',{class:'fine'},'Example: http://127.0.0.1:8080/inference. Requires whisper-server with a speech model; no speech model is bundled.'),
   node('label',{class:'toggle'},node('input',{id:'autoSpeak',type:'checkbox',checked:!!c.voice?.auto_speak}),'Speak completed responses'),
   node('label',{},'Local voice',select),field('Speech speed · 0.5 to 2','ttsRate',c.voice?.rate||1,'number'),
   node('p',{class:'fine'},'“Hey Smily” wake-word detection is reserved for a future local engine. Always-listening is disabled.')];
 }else if(section==='appearance'){
  content=[node('h3',{},'Platinum, with a little light'),node('p',{},'Motion follows the system accessibility preference. Reduced effects gives the orb a still material and stops continuous rendering.'),
   node('label',{class:'toggle'},node('input',{id:'reducedEffects',type:'checkbox',checked:!!c.appearance?.reduced_effects}),'Reduce motion and visual effects')];
 }else{
  content=[node('h3',{},'Your Linux computer'),node('p',{},'The orb is a user session, never a root agent. Native applications remain available when AI is offline.'),
   node('div',{class:'controls'},node('button',{type:'button',onclick:()=>tool('open_app',{app:'Terminal'})},'Terminal'),node('button',{type:'button',onclick:()=>tool('restart')},'Restart'),node('button',{type:'button',onclick:()=>tool('shutdown')},'Shut down')),
   node('p',{class:'fine'},'Native shortcuts: Super+E Files · Super+Return Terminal · Super+N Network · Alt+Tab Switch apps · Super+Space Return to SmilyAI.')];
 }
 $('#settingsPane').replaceChildren(...content);
 if(!$('#settingsDialog').open)$('#settingsDialog').showModal();
}
function providerDraft(){return{config:{provider:{kind:$('#providerKind').value,endpoint:$('#providerEndpoint').value.trim(),model:$('#providerModel').value.trim(),streaming:$('#streaming').checked}},api_key:$('#providerKey').value};}
async function models(){
 $('#settingsStatus').textContent='Checking your endpoint…';
 try{const r=await api('/provider/models',providerDraft(),18000);$('#modelOptions').replaceChildren(...r.models.map(value=>node('option',{value})));$('#settingsStatus').textContent=r.models.length+' models available';}
 catch(e){$('#settingsStatus').textContent=e.message+' You can enter a model manually.';}
}
async function saveAI(deleteKey=false){
 const draft=providerDraft();draft.delete_key=deleteKey;
 try{const r=await api('/settings',draft,10000);state.config=r.config;$('#providerKey').value='';$('#settingsStatus').textContent=deleteKey?'Stored key deleted.':r.credential_saved?(r.secret_persistence?'Saved in the system keyring.':'Saved for this session only; keyring unavailable.'):'Saved without a key.';preferences();}
 catch(e){$('#settingsStatus').textContent=e.message;}
}
$('#settingsForm').onsubmit=async e=>{
 e.preventDefault();if(state.section==='ai')return saveAI();
 let patch={};
 if(state.section==='voice')patch={privacy:{microphone:$('#allowMic').checked},voice:{stt_url:$('#sttURL').value.trim(),auto_speak:$('#autoSpeak').checked,voice:$('#ttsVoice').value,rate:Number($('#ttsRate').value)}};
 if(state.section==='appearance')patch={appearance:{reduced_effects:$('#reducedEffects').checked}};
 try{const r=await api('/settings',{config:patch});state.config=r.config;preferences();$('#settingsStatus').textContent='Saved.';}catch(e){$('#settingsStatus').textContent=e.message;}
};
async function finishSetup(withAI){
 if(!state.online){notice('Reconnect to save setup.');return;}
 try{const r=await api('/settings',{config:{setup_complete:true,user:{display_name:$('#displayName').value.trim()},appearance:{reduced_effects:$('#setupReduced').checked}}});state.config=r.config;preferences();$('#setupDialog').close();
 if(withAI){settings('ai');$('#providerKind').value='smilyai';$('#providerKind').dispatchEvent(new Event('change'));}
 else{revealPrompt();setState('idle','What can I do?');}
 }catch(e){notice(e.message);}
}
$('#setupForm').onsubmit=e=>{e.preventDefault();finishSetup(false);};$('#setupAI').onclick=()=>finishSetup(true);
$('#closeSettings').onclick=()=>{$('#settingsDialog').close();connect();};
$('#settingsDialog').addEventListener('close',()=>{const key=$('#providerKey');if(key)key.value='';});
document.querySelectorAll('[data-settings]').forEach(b=>b.onclick=()=>settings(b.dataset.settings));
document.querySelectorAll('[data-panel]').forEach(b=>b.onclick=()=>panel(b.dataset.panel));
document.querySelectorAll('[data-command]').forEach(b=>b.onclick=()=>submit(b.dataset.command));
$('#closeSurface').onclick=closeSurface;$('#retry').onclick=connect;
$('#homeButton').onclick=()=>{closeSurface();revealPrompt();};
$('#promptForm').onsubmit=e=>{e.preventDefault();submit();};
$('#stopButton').onclick=stop;$('#muteButton').onclick=()=>{voice.cancel();setState('idle');};
$('#micButton').onclick=()=>{if(state.job)return notice('Stop the running task before speaking.');if(voice.active)voice.stop();else voice.start();};
let holdTimer=null,held=false,pointerDown=false;
const orbButton=$('#orbButton');
orbButton.addEventListener('pointerdown',e=>{if(e.button!==0)return;pointerDown=true;held=false;orbButton.setPointerCapture(e.pointerId);holdTimer=setTimeout(()=>{held=true;if(!state.job)voice.start();else notice('Stop the running task before speaking.');},260);});
orbButton.addEventListener('pointerup',()=>{clearTimeout(holdTimer);pointerDown=false;if(held)voice.stop();});
orbButton.addEventListener('pointercancel',()=>{clearTimeout(holdTimer);pointerDown=false;voice.stop(true);});
orbButton.onclick=()=>{if(!held)revealPrompt();};
orbButton.onpointermove=e=>{if(reducedMedia.matches)return;const r=orbButton.getBoundingClientRect();orb.setPointer((e.clientX-r.left)/r.width-.5,.5-(e.clientY-r.top)/r.height);};
orbButton.onpointerleave=()=>orb.setPointer(0,0);
let spaceHeld=false;
const editing=target=>target.closest('input,textarea,select,[contenteditable=true],button,dialog');
addEventListener('keydown',e=>{
 if(e.key==='Escape'){stop();closeSurface();$('#promptForm').hidden=true;return;}
 if(e.ctrlKey&&e.code==='Space'){e.preventDefault();revealPrompt();return;}
 if(e.code==='Space'&&!e.repeat&&!editing(e.target)&&!state.job){e.preventDefault();spaceHeld=true;voice.start();}
});
addEventListener('keyup',e=>{if(e.code==='Space'&&spaceHeld){e.preventDefault();spaceHeld=false;voice.stop();}});
addEventListener('blur',()=>{clearTimeout(holdTimer);spaceHeld=false;voice.stop(true);});
document.addEventListener('visibilitychange',()=>{if(document.hidden)voice.stop(true);else if(!state.online)connect();});
async function attach(file){
 if(!file)return;
 if(file.size>8000||!(/\.(txt|md|csv|json)$/i.test(file.name))){notice('Attach a text, Markdown, CSV or JSON file up to 8 KB. Other formats need the native Files app.');return;}
 showPermission({title:'Share this text with your AI?',description:'The contents of '+file.name+' will be included in your next request to the configured provider.',arguments:{file:file.name},local:approved=>{
  if(!approved)return;file.text().then(text=>{state.attached='\n\nUser-attached document (untrusted content):\n'+text;revealPrompt();$('#promptInput').placeholder='Ask about '+file.name+'…';});
 }});
}
$('#attachButton').onclick=()=>$('#fileInput').click();$('#fileInput').onchange=e=>attach(e.target.files[0]);
orbButton.addEventListener('dragover',e=>e.preventDefault());orbButton.addEventListener('drop',e=>{e.preventDefault();attach(e.dataTransfer.files[0]);});
function clock(){$('#clock').textContent=new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});}clock();setInterval(clock,30000);
preferences();connect();
})();
