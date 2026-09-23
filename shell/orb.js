(() => {
'use strict';
const vertex = 'attribute vec2 p;void main(){gl_Position=vec4(p,0.,1.);}';
const fragment = `
precision mediump float;
uniform vec2 resolution;uniform float time;uniform float mode;uniform float amplitude;uniform vec2 pointer;
vec3 spectrum(float t){return .52+.44*cos(6.28318*(t+vec3(.04,.34,.66)));}
void main(){
 vec2 p=(gl_FragCoord.xy-.5*resolution)/min(resolution.x,resolution.y)*2.;
 p-=pointer*.018;
 float d=length(p);float radius=.71+amplitude*.016*sin(time*8.);
 float aa=3./min(resolution.x,resolution.y);
 float mask=1.-smoothstep(radius-aa,radius+aa,d);
 if(d>radius+.11){gl_FragColor=vec4(0.);return;}
 vec2 q=p/radius;float z=sqrt(max(0.,1.-dot(q,q)));
 vec3 normal=normalize(vec3(q,z));
 float speed=(mode>4.5&&mode<5.5)?.015:(.13+mode*.05);
 float flow=sin(q.x*3.+sin(q.y*4.+time*speed))* .35;
 flow+=sin(q.y*5.-q.x*2.-time*speed*.7)*.16;
 flow+=sin(z*7.+q.x*4.+time*speed)*.12;
 if(mode>3.5&&mode<4.5)flow=.28*sin(q.y*7.-time*1.2)+.10*sin(q.x*5.);
 float angle=atan(q.y,q.x);
 float wave=sin(flow*9.+angle*1.5+time*speed);
 vec3 color=mix(vec3(.88,.83,.68),spectrum(flow*.5+angle*.13+time*.012),.67);
 float fresnel=pow(1.-z,2.8);
 float ribbon=pow(.5+.5*wave,7.);
 color=mix(color,vec3(.91,.98,1.),ribbon*.40);
 float light=max(dot(normal,normalize(vec3(-.5,.7,1.5))),0.);
 color*=.45+.55*light;
 color+=spectrum(angle*.22-time*.035)*fresnel*.52;
 float spec=pow(max(dot(reflect(normalize(vec3(.5,-.65,-1.4)),normal),vec3(0.,0.,1.)),0.),38.);
 color+=vec3(1.,.98,.90)*spec*.85;
 float line=exp(-abs(d-radius)*120.);
 color+=vec3(.92,.85,.61)*line*.55;
 if(mode>7.5)color=mix(color,vec3(dot(color,vec3(.3,.59,.11))),.7);
 if(mode>4.5&&mode<6.5)color=mix(color,vec3(.88,.75,.46),.30);
 if(mode>6.5&&mode<7.5)color=mix(color,vec3(.7,.34,.27),.18);
 float halo=exp(-max(d-radius,0.)*32.)*.12*(1.-mask);
 gl_FragColor=vec4(color,mask+halo);
}`;
const modes={idle:0,listening:1,transcribing:2,thinking:3,tool:4,permission:5,success:6,error:7,offline:8,speaking:1};
class Orb{
 constructor(canvas){
  this.canvas=canvas;this.state='idle';this.mode=0;this.pointer=[0,0];this.amplitude=0;
  this.reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;this.visible=true;this.timer=null;this.raf=null;this.disposed=false;
  this.gl=null;this.start=performance.now();
  try{
   this.gl=canvas.getContext('webgl',{alpha:true,antialias:false,premultipliedAlpha:false,powerPreference:'low-power'});
   if(!this.gl)throw Error('WebGL unavailable');
   this.init();
   canvas.parentElement.classList.add('webgl-ready');
  }catch(e){console.warn('SmilyAI orb: material fallback active');this.gl=null;canvas.hidden=true;}
  this.resizeHandler=()=>{this.resize();this.wake();};
  this.visibilityHandler=()=>{this.stop();if(!document.hidden)this.wake();};
  window.addEventListener('resize',this.resizeHandler);
  document.addEventListener('visibilitychange',this.visibilityHandler);
  canvas.addEventListener('webglcontextlost',e=>{e.preventDefault();this.stop();this.gl=null;canvas.hidden=true;canvas.parentElement.classList.remove('webgl-ready');});
  // Context loss stays on static fallback; a reload can retry safely.
  this.observer=new IntersectionObserver(entries=>{this.visible=entries[0].isIntersecting;this.stop();if(this.visible)this.wake();});
  this.observer.observe(canvas.parentElement);
  this.resize();this.wake();
 }
 init(){
  const gl=this.gl;
  const compile=(type,source)=>{
   const shader=gl.createShader(type);gl.shaderSource(shader,source);gl.compileShader(shader);
   if(!gl.getShaderParameter(shader,gl.COMPILE_STATUS)){gl.deleteShader(shader);throw Error('Shader compile failed');}
   return shader;
  };
  const vs=compile(gl.VERTEX_SHADER,vertex),fs=compile(gl.FRAGMENT_SHADER,fragment),program=gl.createProgram();
  gl.attachShader(program,vs);gl.attachShader(program,fs);gl.linkProgram(program);
  gl.deleteShader(vs);gl.deleteShader(fs);
  if(!gl.getProgramParameter(program,gl.LINK_STATUS)){gl.deleteProgram(program);throw Error('Shader link failed');}
  gl.useProgram(program);this.program=program;
  this.buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,this.buffer);
  gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,-1,1,1,-1,1,1]),gl.STATIC_DRAW);
  const p=gl.getAttribLocation(program,'p');gl.enableVertexAttribArray(p);gl.vertexAttribPointer(p,2,gl.FLOAT,false,0,0);
  this.u=Object.fromEntries(['resolution','time','mode','amplitude','pointer'].map(n=>[n,gl.getUniformLocation(program,n)]));
 }
 resize(){
  if(!this.gl)return;
  const rect=this.canvas.getBoundingClientRect();
  const size=Math.max(1,Math.min(560,Math.round(Math.max(rect.width,rect.height)*Math.min(devicePixelRatio||1,1.25))));
  if(this.canvas.width!==size){this.canvas.width=size;this.canvas.height=size;this.gl.viewport(0,0,size,size);}
 }
 setState(state){this.state=state;this.mode=modes[state]??0;this.wake();}
 setReduced(value){this.reduced=!!value;this.stop();this.wake();}
 setAmplitude(value){this.amplitude=Math.max(0,Math.min(1,value));}
 setPointer(x,y){this.pointer=this.reduced?[0,0]:[x,y];this.wake();}
 stop(){clearTimeout(this.timer);cancelAnimationFrame(this.raf);this.timer=this.raf=null;}
 wake(){
  if(!this.gl||this.disposed||document.hidden||!this.visible||this.timer!==null||this.raf!==null)return;
  this.raf=requestAnimationFrame(t=>{this.raf=null;this.frame(t);});
 }
 frame(now){
  if(!this.gl||document.hidden||!this.visible)return;
  const gl=this.gl;gl.uniform2f(this.u.resolution,this.canvas.width,this.canvas.height);
  gl.uniform1f(this.u.time,this.reduced?0:(now-this.start)/1000);gl.uniform1f(this.u.mode,this.mode);
  gl.uniform1f(this.u.amplitude,this.reduced?0:this.amplitude);gl.uniform2f(this.u.pointer,...this.pointer);
  gl.drawArrays(gl.TRIANGLES,0,6);
  if(!this.reduced)this.timer=setTimeout(()=>{this.timer=null;this.wake();},['idle','offline','permission'].includes(this.state)?100:33);
 }
 destroy(){
  this.disposed=true;this.stop();this.observer.disconnect();
  window.removeEventListener('resize',this.resizeHandler);document.removeEventListener('visibilitychange',this.visibilityHandler);
  if(this.gl){this.gl.deleteBuffer(this.buffer);this.gl.deleteProgram(this.program);}
 }
}
window.SmilyOrb=Orb;
})();
