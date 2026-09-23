const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const shell=path.join(__dirname,'../shell');
function boot(reduced=false){
 const timers=[],listeners={},classes=new Set();
 const c={window:{addEventListener:(n,fn)=>listeners[n]=fn},document:{querySelector:()=>({classList:{add:x=>classes.add(x)}})},setTimeout:(fn,ms)=>timers.push([fn,ms]),matchMedia:()=>({matches:reduced})};
 vm.runInNewContext(fs.readFileSync(path.join(shell,'boot.js'),'utf8'),c);
 return {c,timers,listeners,classes};
}
test('boot has independent bounded fallback',()=>{const x=boot();assert.equal(x.timers[0][1],2200);x.timers[0][0]();assert(x.classes.has('revealed'));});
test('shader/application failure immediately releases splash',()=>{const x=boot();x.listeners.error();assert(x.classes.has('revealed'));});
test('reduced motion releases splash immediately',()=>{assert(boot(true).classes.has('revealed'));});
test('WebGL unavailable does not throw or schedule animation',()=>{
 const classes=new Set(),canvas={parentElement:{classList:{add:x=>classes.add(x),remove:x=>classes.delete(x)}},getContext:()=>null,addEventListener(){}};
 const c={window:{addEventListener(){}},document:{hidden:false,addEventListener(){}},console:{warn(){}},performance:{now:()=>0},matchMedia:()=>({matches:false}),IntersectionObserver:class{observe(){}},setTimeout(){throw Error('must not animate')},requestAnimationFrame(){throw Error('must not animate')}};
 vm.runInNewContext(fs.readFileSync(path.join(shell,'orb.js'),'utf8'),c);
 new c.window.SmilyOrb(canvas);assert.equal(canvas.hidden,true);
});
function voice(config={privacy:{microphone:false},voice:{stt_url:''}},media={}){
 const notices=[],states=[];let requests=0;
 const c={window:{},navigator:{mediaDevices:media},setTimeout,clearTimeout,Float32Array,Uint8Array,DataView,console};
 vm.runInNewContext(fs.readFileSync(path.join(shell,'voice.js'),'utf8'),c);
 const v=new c.window.SmilyVoice({api:async()=>{requests++;return{text:''}},config:()=>config,state:x=>states.push(x),amplitude(){},submit(){},notice:x=>notices.push(x)});
 return {v,notices,states,get requests(){return requests}};
}
test('voice is opt-in; no ambient capture',async()=>{
 let calls=0;const x=voice(undefined,{getUserMedia:async()=>calls++});await x.v.start();assert.equal(calls,0);assert.equal(x.requests,0);assert(x.notices.length);
});
test('denied microphone gracefully returns idle',async()=>{
 const x=voice({privacy:{microphone:true},voice:{stt_url:'http://127.0.0.1:8080/inference'}},{getUserMedia:async()=>{throw Error('denied')}});
 await x.v.start();assert.equal(x.v.active,false);assert.equal(x.states.at(-1),'idle');assert.equal(x.requests,0);
});
test('release while microphone permission is pending stops the eventual stream',async()=>{
 let resolve,stopped=0;
 const x=voice({privacy:{microphone:true},voice:{stt_url:'local'}},{getUserMedia:()=>new Promise(r=>resolve=r)});
 const pending=x.v.start();await x.v.stop(true);resolve({getTracks:()=>[{stop:()=>stopped++}]});await pending;
 assert.equal(stopped,1);assert.equal(x.v.active,false);assert.equal(x.requests,0);
});
test('voice creates a bounded 16kHz PCM WAV',()=>{
 const x=voice(),wav=x.v.wav([new Float32Array(48000)],48000);
 assert.equal(wav.length,32044);assert.equal(Buffer.from(wav.slice(0,4)).toString(),'RIFF');assert.equal(new DataView(wav.buffer).getUint32(24,true),16000);
});
test('shell renders untrusted content as text, not markup',()=>{
 const app=fs.readFileSync(path.join(shell,'app.js'),'utf8');
 assert(!app.includes('innerHTML'));assert(!app.includes('eval('));assert(!app.includes('localStorage'));
});
