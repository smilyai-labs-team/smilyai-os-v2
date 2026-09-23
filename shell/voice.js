(() => {
class Voice {
 constructor({api,config,state,amplitude,submit,notice}){
  Object.assign(this,{api,config,state,amplitude,submit,notice});this.active=false;this.generation=0;this.chunks=[];this.want=false;
 }
 async start(){
  if(this.active||this.want||this.starting)return;
  const config=this.config();
  if(!config?.privacy?.microphone||!config.voice?.stt_url){this.notice('Enable push-to-talk and set a local speech server in Voice settings.');return;}
  this.want=true;this.starting=true;const generation=++this.generation;
  try{
   const stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true}});
   if(!this.want||generation!==this.generation){stream.getTracks().forEach(t=>t.stop());return;}
   this.stream=stream;const context=new AudioContext();this.context=context;await context.audioWorklet.addModule('/pcm-worklet.js');
   if(!this.want||generation!==this.generation){this.cleanup();return;}
   this.chunks=[];this.samples=0;this.rate=this.context.sampleRate;
   const source=this.context.createMediaStreamSource(stream);this.node=new AudioWorkletNode(this.context,'smily-pcm');
   this.node.port.onmessage=e=>{
    if(!this.active)return;
    const samples=e.data;this.chunks.push(samples);this.samples+=samples.length;
    let sum=0;for(const v of samples)sum+=v*v;
    this.amplitude(Math.min(1,Math.sqrt(sum/samples.length)*8));
   };
   const mute=this.context.createGain();mute.gain.value=0;source.connect(this.node).connect(mute).connect(this.context.destination);
   await context.resume();if(!this.want||generation!==this.generation){this.cleanup();return;}this.active=true;this.state('listening','Listening…');
   this.timeout=setTimeout(()=>this.stop(),30000);
  }catch(e){this.cleanup();if(generation===this.generation){this.notice('Microphone unavailable or permission denied. You can still type.');this.state('idle');}}
  finally{this.starting=false;}
 }
 async stop(cancel=false){
  this.want=false;++this.generation;
  if(!this.active){this.cleanup();return;}
  this.active=false;const chunks=this.chunks,rate=this.rate;this.cleanup();this.chunks=[];
  if(cancel){this.state('idle');return;}
  this.state('transcribing','Turning speech into words…');
  try{
   const audio=this.wav(chunks,rate);let binary='';
   for(let i=0;i<audio.length;i+=8192)binary+=String.fromCharCode(...audio.subarray(i,i+8192));
   const generation=this.generation;
   const result=await this.api('/voice/transcribe',{audio:btoa(binary)},20000);
   if(generation!==this.generation)return;
   if(result.text)this.submit(result.text);else{this.notice('No speech detected.');this.state('idle');}
  }catch(e){this.notice(e.message);this.state('idle');}
 }
 cleanup(){clearTimeout(this.timeout);this.node?.disconnect();this.node=null;this.stream?.getTracks().forEach(t=>t.stop());this.stream=null;this.context?.close().catch(()=>{});this.context=null;this.amplitude(0);this.active=false;this.want=false;}
 wav(chunks,rate){
  const total=chunks.reduce((n,c)=>n+c.length,0);if(total<rate*.15)throw Error('Hold a little longer to speak.');
  const source=new Float32Array(total);let offset=0;for(const c of chunks){source.set(c,offset);offset+=c.length;}
  const count=Math.floor(total*16000/rate),bytes=new Uint8Array(44+count*2),view=new DataView(bytes.buffer);
  const str=(at,s)=>[...s].forEach((c,i)=>view.setUint8(at+i,c.charCodeAt(0)));
  str(0,'RIFF');view.setUint32(4,36+count*2,true);str(8,'WAVE');str(12,'fmt ');view.setUint32(16,16,true);
  view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,16000,true);view.setUint32(28,32000,true);
  view.setUint16(32,2,true);view.setUint16(34,16,true);str(36,'data');view.setUint32(40,count*2,true);
  for(let i=0;i<count;i++){const x=i*rate/16000,j=Math.floor(x),f=x-j;const v=source[j]*(1-f)+(source[j+1]||0)*f;view.setInt16(44+i*2,Math.max(-1,Math.min(1,v))*32767,true);}
  return bytes;
 }
 speak(text){
  const c=this.config();if(!c?.voice?.auto_speak||!window.speechSynthesis)return;
  const voices=speechSynthesis.getVoices().filter(v=>v.localService);
  const voice=voices.find(v=>v.name===c.voice.voice)||voices[0];if(!voice){this.notice('No local system voice is available.');return;}
  speechSynthesis.cancel();const u=new SpeechSynthesisUtterance(text);u.voice=voice;u.rate=c.voice.rate;
  u.onstart=()=>this.state('speaking','Speaking');u.onboundary=()=>{this.amplitude(.5);setTimeout(()=>this.amplitude(0),150);};
  u.onend=u.onerror=()=>this.state('idle');speechSynthesis.speak(u);
 }
 cancel(){this.stop(true);window.speechSynthesis?.cancel();}
}
window.SmilyVoice=Voice;
})();
