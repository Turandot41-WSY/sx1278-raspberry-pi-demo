const $ = id => document.getElementById(id);
const clone = value => structuredClone(value);
const operational = location.pathname === '/monitor';
let disconnected = false;
let worldPaths = [];
let telemetry = null, dragging = false, renderedTelemetry = "";
let monitorMode = operational || new URLSearchParams(location.search).get('monitor') === '1';
let monitorSource = new URLSearchParams(location.search).get('source') || 'latest';
let scene, seed, revision = 0, selected = new Set(), undoStack = [], redoStack = [], zoom = .6;
let previewMode = new URLSearchParams(location.search).has('preview');
let dirty = false, saving = false, saveTimer, generation = 0;
const presets = {
  lunar: {preset:'lunar',background:'white',surface:'solid',accent:'#00766f',font:'-apple-system',dataFont:'Courier New',radius:10},
  research: {preset:'research',background:'silver',surface:'outline',accent:'#0f62d6',font:'Arial',dataFont:'Courier New',radius:2},
  polar: {preset:'polar',background:'ice',surface:'glass',accent:'#6240bb',font:'-apple-system',dataFont:'Courier New',radius:10},
  mission: {preset:'mission', background:'black',surface:'solid',accent:'#69d4e6',font:'Arial',dataFont:'Courier New'},
  observatory: {preset:'observatory',background:'stars',surface:'glass',accent:'#b2a0ff',font:'Helvetica Neue',dataFont:'Courier New'},
  console: {preset:'console',background:'navy',surface:'outline',accent:'#83dfbd',font:'Courier New',dataFont:'Courier New'}
};
function isLight(background){return ['white','silver','ice'].includes(background);}
function tokens() {
  const light=isLight(scene.theme.background),surface=scene.theme.surface;
  return {land:light?'#cfdee7':'#193b4d',coast:light?'#8fa8b9':'#41687f',ocean:light?'#f2f7fa':'#081722',mapGrid:light?'#bdceda':'#345267',ink:light?'#172939':'#edf2f6',muted:light?'#526477':'#a7b4c4',
    border:light?(surface==='outline'?'#aabacb':'#d6dfe7'):(surface==='outline'?'#3b6372':'#293441'),
    panel:light?(surface==='glass'?'#fffffff0':surface==='outline'?'#ffffff80':'#ffffff'):(surface==='glass'?'#0e1724d9':surface==='outline'?'#0a152280':'#0e141c'),...scene.theme};
}
function resolved(value) {return typeof value === 'string' && value.startsWith('$') ? tokens()[value.slice(1)] : value;}
function status(message,error=false){$('saveStatus').textContent=message;$('saveStatus').classList.toggle('error',error);}
function snapshot(){undoStack.push(clone(scene));if(undoStack.length>80)undoStack.shift();redoStack=[];}
function changed(){dirty=true;generation++;status(previewMode?'Preview only · click Apply preview to save':'Unsaved changes');clearTimeout(saveTimer);saveTimer=setTimeout(save,800);}
function change(action){if(operational)return;snapshot();action();changed();render();}
async function save(){
  clearTimeout(saveTimer);if(operational||previewMode||!dirty || saving)return;saving=true;const mark=generation;
  try{
    const response=await fetch('/api/scene',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision,scene})});
    const result=await response.json();if(!response.ok)throw new Error(result.error);
    revision=result.revision;dirty=generation!==mark;status(dirty?'Unsaved changes':`Saved to disk · revision ${revision}`);
  }catch(error){status(error.message,true);}finally{saving=false;if(dirty&&generation!==mark)saveTimer=setTimeout(save,500);}
}
function svgNode(tag,attributes={}){
  const node=document.createElementNS('http://www.w3.org/2000/svg',tag);
  for(const [key,value] of Object.entries(attributes))node.setAttribute(key,String(value));
  return node;
}
function shownSamples(){return monitorMode?(telemetry?.samples||[]):(scene.samples||[]);}
function region(){return telemetry?.region||scene.region;}
function shownTracks(){
  const tracks=new Map();
  for(const sample of shownSamples()){const key=sample.track||`pass-${sample.passId??'unknown'}`;if(!tracks.has(key))tracks.set(key,{key,label:sample.trackLabel||'Saved pass',samples:[]});tracks.get(key).samples.push(sample);}
  return [...tracks.values()];
}
function trackColor(index){
  const light=isLight(scene.theme.background),colors=[tokens().accent,light?'#2868b2':'#83b8ff',light?'#9a4d1b':'#f5b16f',light?'#8051b3':'#caa0ff',light?'#a33d6b':'#ef9bc3'];
  return colors[index%colors.length];
}
function chartBounds(o){
  const samples=shownSamples();if(!samples.length)return [0,20,o.chart==='range'?0:-10000,o.chart==='range'?2500:10000];
  const values=samples.map(sample=>sample[o.chart]),minimum=Math.min(...values),maximum=Math.max(...values),margin=Math.max((maximum-minimum)*.10,o.chart==='range'?1:10);
  const step=10**Math.floor(Math.log10(Math.max(maximum-minimum,1)));
  return [0,Math.max(20,Math.ceil(Math.max(...samples.map(sample=>sample.time))/20)*20),Math.floor((minimum-margin)/step)*step,Math.ceil((maximum+margin)/step)*step];
}
function project(lon,lat,o){const [west,east,south,north]=region().bounds;return [(lon-west)/(east-west)*o.w,(north-lat)/(north-south)*o.h];}
function dataGraphic(o){
  const palette=tokens(),svg=svgNode('svg',{viewBox:`0 0 ${o.w} ${o.h}`,width:'100%',height:'100%',role:'img','aria-label':o.map?'Regional map of received passes and the configured ground station':`${o.chart} for all retained received passes`});
  if(o.map){
    // Natural Earth 1:110m Admin 0 Countries. Regional bounds come from the archived station and passes.
    const [west,east,south,north]=region().bounds,sx=o.w/(east-west),sy=o.h/(north-south);
    const land=svgNode('g',{transform:`translate(${-sx*(west+180)} ${-sy*(90-north)}) scale(${sx} ${sy})`});
    for(const country of worldPaths){const path=svgNode('path',{d:country.path,fill:palette.land,stroke:palette.coast,'stroke-width':.7,'vector-effect':'non-scaling-stroke'});const title=svgNode('title');title.textContent=country.name;path.append(title);land.append(path);}svg.append(land);
  }
  const samples=shownSamples(),bounds=o.chart?chartBounds(o):null;
  const point=sample=>o.map?project(sample.longitude,sample.latitude,o):[(sample.time-bounds[0])/(bounds[1]-bounds[0])*o.w,(bounds[3]-sample[o.chart])/(bounds[3]-bounds[2])*o.h];
  const tracks=shownTracks();
  tracks.forEach((track,index)=>{
    const color=trackColor(index),active=track.key===tracks.at(-1)?.key;let pathData='',previous;
    for(const sample of track.samples){const [x,y]=point(sample);const continuous=previous&&sample.sample===previous.sample+1&&sample.time>=previous.time&&(!o.map||Math.abs(sample.longitude-previous.longitude)<180);pathData+=`${continuous?'L':'M'}${x.toFixed(3)},${y.toFixed(3)} `;previous=sample;}
    svg.append(svgNode('path',{d:pathData,fill:'none',stroke:color,'stroke-width':active?2.6:1.8,'data-track':track.key,opacity:active?1:.75}));
    for(const sample of track.samples){const [x,y]=point(sample),last=sample===samples.at(-1);const dot=svgNode('circle',{cx:x,cy:y,r:last?4.5:1.8,fill:color,stroke:last?palette.ink:'none','stroke-width':last?1:0,'data-sample':sample.sample,'data-track':track.key});const title=svgNode('title');title.textContent=`${track.label} · sample ${sample.sample} · ${sample.time} s`+(o.map?` · ${sample.latitude.toFixed(5)}°, ${sample.longitude.toFixed(5)}°`:` · ${sample[o.chart].toFixed(3)} ${o.chart==='range'?'km':'Hz'}`);dot.append(title);svg.append(dot);}
  });
  if(o.map){const station=region().station,[x,y]=project(station.longitude_deg,station.latitude_deg,o);const pin=svgNode('path',{d:`M${x},${y-7} L${x+7},${y} L${x},${y+7} L${x-7},${y} Z`,fill:palette.ink,stroke:isLight(scene.theme.background)?'#ffffff':'#070f1a','stroke-width':2,'data-station':'configured'});const title=svgNode('title');title.textContent=`Ground station · ${station.latitude_deg}°, ${station.longitude_deg}° · ${station.height_m} m`;pin.append(title);svg.append(pin);}
  return svg;
}
function displayText(o){
  if(o.chartTick){const plot=scene.objects.find(item=>item.id===o.chartTick.plot),bounds=chartBounds(plot);const value=o.chartTick.axis==='x'?bounds[0]+(bounds[1]-bounds[0])*o.chartTick.fraction:bounds[2]+(bounds[3]-bounds[2])*o.chartTick.fraction;return String(Math.round(value*100)/100);}
  if(o.legendIndex!==undefined){const track=shownTracks()[o.legendIndex];return track?`${track.label} · ${track.samples.length} points`:'';}
  if(!monitorMode)return o.text;
  const last=telemetry?.activeLatest, tracks=shownTracks();
  const values={
    'satellite-reference':`LOCAL REFERENCE  ${region().satellite} · NORAD ${region().norad}`,
    'source-label':`${region().satellite} · NORAD ${region().norad} · Local OMM epoch: ${region().epoch||'Unavailable'}`,
    'source-note':'Ground experiment · Model Doppler is not measured CFO',
    'ground-station-label':`GROUND STATION\n${region().station.latitude_deg.toFixed(5)}° N / ${region().station.longitude_deg.toFixed(5)}° E · ${region().station.height_m} m`,
    'track-subtitle':`Ground station mask: ${region().minimumElevationDeg}° · Regional margin: ${Math.round(region().marginFraction*100)}%`,
    'design-notice':telemetry?`${telemetry.dataOrigin==='software_test'?'SOFTWARE TEST LOG':'RECEIVER LOG'} · ${telemetry.state} · ${tracks.length} tracks retained${telemetry.activeLatest?.sourceMatched===false?' · SOURCE MISMATCH':''}`:'CONNECTING TO RECEIVER LOG',
    'sample-caption':telemetry?.source?`LOG: ${telemetry.source}`:'WAITING FOR RECEIVER LOG',
    'range-value':last?`${last.range.toFixed(3)} km`:'—','doppler-value':last?`${last.doppler>=0?'+':''}${last.doppler.toFixed(3)} Hz`:'—',
    'elapsed-value':last?`${last.time.toFixed(3)} s`:'—','sample-value':last?String(last.sample):'—',
    'height-value':last?`Derived altitude  ${last.altitude.toFixed(3)} km`:'Derived altitude  —',
    'validation-value':telemetry?`${telemetry.valid} valid · ${telemetry.invalid} rejected`:'No valid frames yet',
    'map-credit':telemetry?.warning||'Map: Natural Earth · earlier received passes retained',
    'position-label':last?`${last.trackLabel} · sample ${last.sample} · ${last.latitude.toFixed(3)}° N / ${last.longitude.toFixed(3)}° E`:'Waiting for first valid position'
  };
  for(const [index,axis] of ['X','Y','Z'].entries()){values['ecef-position-'+axis]=last?`${last.position[index].toFixed(3)} km`:'—';values['ecef-velocity-'+axis]=last?`${last.velocity[index]>=0?'+':''}${last.velocity[index].toFixed(6)} km/s`:'—';}
  return values[o.id]??o.text;
}
async function pollReceiver(){
  if(monitorMode){try{const response=await fetch('/api/telemetry?source='+encodeURIComponent(monitorSource),{signal:AbortSignal.timeout(5000)});if(!response.ok)throw Error('Receiver log service unavailable');telemetry=await response.json();const recovered=disconnected;disconnected=false;$('receiverStatus').textContent=telemetry.warning||telemetry.state;
    if(document.activeElement!==$('receiveSource')){const select=$('receiveSource');select.replaceChildren();for(const source of ['latest',...telemetry.sources]){const option=document.createElement('option');option.value=source;option.textContent=source==='latest'?'Newest receiver session':source;select.append(option);}select.value=monitorSource;}
    const fingerprint=JSON.stringify([telemetry.valid,telemetry.invalid,telemetry.source,telemetry.state,telemetry.warning,telemetry.tracks.length]);if((recovered||fingerprint!==renderedTelemetry)&&!dragging&&!/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)){render();renderedTelemetry=fingerprint;}updateDetails();
  }catch(error){disconnected=true;$('receiverStatus').textContent=error.message;updateDetails();const notice=document.querySelector('[data-id="design-notice"]');if(notice)notice.textContent='DISPLAY DISCONNECTED · LAST RECEIVED POINTS RETAINED';}}
  setTimeout(pollReceiver,750);
}
function geometry(o){
  if(o.type!=='line'||!o.from||!o.to)return o;
  const a=scene.objects.find(v=>v.id===o.from),b=scene.objects.find(v=>v.id===o.to);if(!a||!b)return o;
  const x=a.x+a.w+9,y=a.y+a.h/2,dx=b.x-9-x,dy=b.y+b.h/2-y;
  return {...o,x,y,w:Math.hypot(dx,dy),h:10,angle:Math.atan2(dy,dx)*180/Math.PI};
}
function selection(){return scene.objects.filter(o=>selected.has(o.id));}
function render(){
  if(document.activeElement!==$('notes'))$('notes').value=scene.notes||'';
  const theme=scene.theme;const stage=$('stage');if(operational&&$('runtimeControls'))document.body.append($('runtimeControls'));stage.replaceChildren();
  stage.style.backgroundColor=({navy:'#081523',white:'#f5f5f7',silver:'#edf1f5',ice:'#f3f6fc'})[theme.background]||'#05070b';
  stage.style.backgroundImage=theme.background==='stars'?'url("assets/deep-space.png")':theme.background==='ice'?'radial-gradient(ellipse at 88% 0%, #e1def8 0%, transparent 52%), radial-gradient(ellipse at 0% 100%, #dceff3 0%, transparent 48%)':'none';stage.style.backgroundSize='cover';
  for(const o of scene.objects){
    if(o.hidden)continue;
    const el=document.createElement('div');el.className=`obj ${o.type}${selected.has(o.id)?' selected':''}${o.locked?' locked':''}`;el.dataset.id=o.id;el.title=o.id;
    Object.assign(el.style,{left:o.x+'px',top:o.y+'px',width:o.w+'px',height:o.h+'px',color:resolved(o.color),fontFamily:resolved(o.font),fontSize:(o.size||20)+'px',fontWeight:o.weight||'400',textAlign:o.align||'left'});
    if(o.type==='text')el.textContent=displayText(o);
    if(o.legendIndex!==undefined)el.style.color=trackColor(o.legendIndex);
    if(o.type==='image'){const img=document.createElement('img');img.src=o.src;img.alt=o.id==='itu-logo'?'IT:U official logo':o.id==='spok-logo'?'SPOK Space Lab logo':'S³ Lab logo';if(!isLight(scene.theme.background))img.style.filter='brightness(0) invert(1)';el.append(img);}
    if(o.type==='panel')el.style.borderRadius=(theme.radius??10)+'px';
    if(o.type==='panel'||o.type==='dot'){el.style.background=resolved(o.fill);el.style.border=`${o.lineWidth||0}px solid ${resolved(o.stroke)||'transparent'}`;}
    if(o.map||o.chart){el.classList.add('data-graphic');el.append(dataGraphic(o));}
    if(o.type==='line'){
      let x=o.x,y=o.y,w=o.w,angle=o.angle||0;
      const a=scene.objects.find(v=>v.id===o.from),b=scene.objects.find(v=>v.id===o.to);
      if(a&&b){x=a.x+a.w+9;y=a.y+a.h/2;const dx=b.x-9-x,dy=b.y+b.h/2-y;w=Math.hypot(dx,dy);angle=Math.atan2(dy,dx)*180/Math.PI;}
      Object.assign(el.style,{left:x+'px',top:(y-6)+'px',width:w+'px',height:'12px',transform:`rotate(${angle}deg)`});el.style.setProperty('--line-color',resolved(o.stroke));el.style.setProperty('--line-width',(o.lineWidth||1)+'px');el.classList.toggle('no-arrow',o.arrow===false);
    }
    if(!operational)el.addEventListener('pointerdown',event=>startDrag(event,o,false));
    if(selected.has(o.id)&&!o.locked){const handle=document.createElement('span');handle.className='handle';handle.addEventListener('pointerdown',event=>startDrag(event,o,true));el.append(handle);}
    stage.append(el);
  }
  if(operational){stage.append($('runtimeControls'));return;}
  renderLayers();renderInspector();$('undo').disabled=!undoStack.length;$('redo').disabled=!redoStack.length;
  $('background').value=theme.background;$('surface').value=theme.surface;$('accent').value=theme.accent;$('themeFont').value=theme.font;
  document.querySelectorAll('[data-preset]').forEach(b=>b.classList.toggle('chosen',b.dataset.preset===theme.preset));
}
function renderLayers(){
  const box=$('objectList');box.replaceChildren();const query=$('search').value.toLowerCase();
  for(const o of scene.objects){if(!(o.id+' '+(o.text||'')).toLowerCase().includes(query))continue;const b=document.createElement('button');b.className='layer'+(selected.has(o.id)?' active':'')+(o.hidden?' dim':'');b.textContent=(o.locked?'🔒 ':'')+(o.text||o.id).replaceAll('\n',' ');b.title=o.id;b.onclick=e=>{if(!e.shiftKey)selected.clear();selected.add(o.id);render();};box.append(b);}
}
const fields=['text','font','size','color','weight','align','x','y','w','h','aspect','fill','stroke','lineWidth','hidden','locked','angle','from','to'];
function renderInspector(){
  const items=selection(),o=items[0];$('properties').disabled=!o;$('selectedName').textContent=o?(items.length>1?`${items.length} objects`:o.id):'Select an object';$('selectedMeta').textContent=o?`${o.group} · ${o.type}${o.locked?' · unlock to move':''}`:'Select any text, logo or panel.';
  for(const name of fields){const el=$(name);if(!el)continue;const value=o?resolved(geometry(o)[name]):'';if(el.type==='checkbox')el.checked=!!value;else if(el.type==='color')el.value=String(value||'#ffffff').slice(0,7);else el.value=value??'';}
}
function startDrag(event,o,resize){
  if(event.button!==0)return;event.preventDefault();event.stopPropagation();
  if(event.shiftKey){selected.has(o.id)?selected.delete(o.id):selected.add(o.id);render();return;}
  if(!selected.has(o.id)){selected.clear();selected.add(o.id);}render();if(o.locked)return;
  dragging=true;const initial=clone(scene),origin={x:event.clientX,y:event.clientY};let moved=false;
  const originals=initial.objects.filter(v=>selected.has(v.id)&&!v.locked).map(geometry);
  const move=e=>{
    const dx=(e.clientX-origin.x)/zoom,dy=(e.clientY-origin.y)/zoom;if(!moved&&Math.abs(dx)+Math.abs(dy)<2)return;
    if(!moved){snapshot();moved=true;}
    for(const old of originals){const obj=scene.objects.find(v=>v.id===old.id);
      if(resize){obj.w=Math.max(8,old.w+dx);obj.h=old.aspect?obj.w/(old.w/old.h):Math.max(8,old.h+dy);if(obj.type==='line'){delete obj.from;delete obj.to;}}
      else {obj.x=old.x+dx;obj.y=old.y+dy;if(obj.type==='line'){delete obj.from;delete obj.to;}}
    }render();
  };
  const end=()=>{dragging=false;window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',end);if(moved)changed();};
  window.addEventListener('pointermove',move);window.addEventListener('pointerup',end);
}
for(const name of fields){const el=$(name);if(!el)continue;el.addEventListener('change',()=>{
  let value=el.type==='checkbox'?el.checked:el.type==='number'?Number(el.value):el.value;
  if(el.type==='number'&&!Number.isFinite(value))return;
  if(['w','h','size'].includes(name))value=Math.max(1,value);
  change(()=>{for(const o of selection()){
    if(o.locked&&name!=='locked')continue;
    if(['from','to'].includes(name)&&value&&!scene.objects.some(item=>item.id===value)){status('Choose an existing object ID',true);continue;}
    if(o.aspect&&['w','h'].includes(name)){const ratio=o.w/o.h;if(name==='w')o.h=value/ratio;else o.w=value*ratio;}
    if(o.type==='line'&&['x','y','w','h','angle'].includes(name))Object.assign(o,geometry(o));
    o[name]=value;if(o.type==='line'&&['x','y','w','h','angle'].includes(name)){delete o.from;delete o.to;}
  }});
});}
$('undo').onclick=()=>{if(!undoStack.length)return;redoStack.push(clone(scene));scene=undoStack.pop();changed();render();};
$('redo').onclick=()=>{if(!redoStack.length)return;undoStack.push(clone(scene));scene=redoStack.pop();changed();render();};
$('save').onclick=()=>{previewMode=false;$('save').textContent='Save';history.replaceState(null,'',location.pathname+(document.body.classList.contains('presenting')?'?display=1':''));dirty=true;save();};$('search').oninput=renderLayers;
$('notes').onchange=()=>change(()=>scene.notes=$('notes').value);
$('restoreRatio').onclick=()=>change(()=>selection().filter(o=>o.type==='image'&&!o.locked).forEach(o=>{o.h=o.w/o.originalRatio;o.aspect=true;}));
$('selectGroup').onclick=()=>{const group=selection()[0]?.group;selected=new Set(scene.objects.filter(o=>o.group===group).map(o=>o.id));render();};
$('resetObject').onclick=()=>change(()=>{scene.objects=scene.objects.map(o=>selected.has(o.id)?clone(seed.objects.find(s=>s.id===o.id)||o):o);});
$('forward').onclick=()=>change(()=>{scene.objects.sort((a,b)=>Number(selected.has(a.id))-Number(selected.has(b.id)));});
$('backward').onclick=()=>change(()=>{scene.objects.sort((a,b)=>Number(selected.has(b.id))-Number(selected.has(a.id)));});
$('addText').onclick=()=>change(()=>{const id='text-'+crypto.randomUUID();scene.objects.push({id,type:'text',group:'Custom',x:80,y:200,w:500,h:50,size:28,text:'Your text',color:'$ink',font:'$font'});selected=new Set([id]);});
for(const button of document.querySelectorAll('[data-preset]'))button.onclick=()=>change(()=>scene.theme=clone(presets[button.dataset.preset]));
for(const [id,key] of [['background','background'],['surface','surface'],['accent','accent'],['themeFont','font']])$(id).onchange=()=>change(()=>{const previous=scene.theme.background;scene.theme[key]=$(id).value;if(key==='background'&&isLight(previous)!==isLight(scene.theme.background))scene.theme.accent=isLight(scene.theme.background)?'#00766f':'#69d4e6';scene.theme.preset='custom';});
function setZoom(value){zoom=value;$('stage').style.transform=`scale(${zoom})`;$('stageWrap').style.width=scene.width*zoom+'px';$('stageWrap').style.height=scene.height*zoom+'px';$('zoom').value=Math.round(zoom*100);$('zoomValue').textContent=Math.round(zoom*100)+'%';}
function fit(){const v=$('viewport'),padding=document.body.classList.contains('presenting')?0:44;setZoom(Math.min((v.clientWidth-padding)/1600,(v.clientHeight-padding)/1000));}
$('fit').onclick=fit;$('zoom').oninput=()=>setZoom(Number($('zoom').value)/100);window.addEventListener('resize',fit);
$('present').onclick=()=>{document.body.classList.add('presenting');$('exitPresent').hidden=false;fit();};$('exitPresent').onclick=()=>{if(operational)return;document.body.classList.remove('presenting');$('exitPresent').hidden=true;fit();};
$('monitor').onclick=()=>{monitorMode=!monitorMode;telemetry=null;renderedTelemetry="";$('monitor').textContent=monitorMode?'Design sample':'Watch receiver';render();};
$('receiveSource').onchange=()=>{monitorSource=$('receiveSource').value;monitorMode=true;renderedTelemetry='';$('monitor').textContent='Design sample';};
$('stage').onpointerdown=e=>{if(e.target===$('stage')){selected.clear();render();}};
window.addEventListener('keydown',e=>{
  if(operational)return;
  if(e.key==='Escape')$('exitPresent').click();if(/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName))return;
  if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='z'){e.preventDefault();$(e.shiftKey?'redo':'undo').click();return;}
  const direction={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]}[e.key];if(direction&&selected.size){e.preventDefault();change(()=>selection().filter(o=>!o.locked).forEach(o=>{o.x+=direction[0]*(e.shiftKey?10:1);o.y+=direction[1]*(e.shiftKey?10:1);}));}
});
$('export').onclick=()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(scene,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='communication-design.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
function validate(incoming){
  if(incoming.version!==1||incoming.width!==1600||incoming.height!==1000||!Array.isArray(incoming.objects)||incoming.objects.length<1||incoming.objects.length>400)throw Error('Unsupported design file');
  const ids=new Set();for(const o of incoming.objects){if(!o.id||ids.has(o.id)||!['text','panel','line','dot','image'].includes(o.type))throw Error('Invalid design object');ids.add(o.id);for(const k of ['x','y','w','h'])if(!Number.isFinite(o[k]))throw Error('Invalid object dimensions');if(o.w<=0||o.h<=0)throw Error('Invalid object size');if(o.type==='image'&&!['assets/itu-official.svg','assets/s3-lab-user.png','assets/s3-lab-transparent.png','assets/spok-space-lab-transparent.png'].includes(o.src))throw Error('Unsupported image asset');}if(!incoming.theme)throw Error('Missing design theme');return incoming;
}
$('import').onclick=()=>$('importFile').click();$('importFile').onchange=async e=>{try{const incoming=validate(JSON.parse(await e.target.files[0].text()));change(()=>{scene=incoming;selected.clear();$('notes').value=scene.notes||'';});}catch(error){status(error.message,true);}e.target.value='';};
$('restorePrevious').onclick=async()=>{try{const response=await fetch('/api/previous'),result=await response.json();if(!response.ok)throw Error(result.error);change(()=>{scene=validate(result.scene);selected.clear();$('notes').value=scene.notes||'';});}catch(error){status(error.message,true);}};
window.addEventListener('beforeunload',e=>{if(dirty&&!previewMode){e.preventDefault();e.returnValue='';}});
function alignRegion() {
  const map=scene.objects.find(o=>o.map),[west,east,south,north]=region().bounds;
  for(const o of scene.objects){
    if(o.id.startsWith('world-lon-')){const longitude=Number(o.id.split('world-lon-')[1].replace(/^(line|label)-/,''));const x=map.x+(longitude-west)/(east-west)*map.w;o.hidden=longitude<west||longitude>east;if(o.id.includes('-line-'))Object.assign(o,{x,y:map.y,w:map.h});else Object.assign(o,{x:x-25,y:map.y+map.h+5});}
    if(o.id.startsWith('world-lat-')){const latitude=Number(o.id.split('world-lat-')[1].replace(/^(line|label)-/,''));const y=map.y+(north-latitude)/(north-south)*map.h;o.hidden=latitude<south||latitude>north;if(o.id.includes('-line-'))Object.assign(o,{x:map.x,y,w:map.w});else Object.assign(o,{y:y-8});}
  }
  const station=region().station,[x,y]=project(station.longitude_deg,station.latitude_deg,map);
  Object.assign(scene.objects.find(o=>o.id==='ground-station-label'),{x:map.x+x+15,y:map.y+y+10});
}
function updateDetails(){
  if(!operational)return;
  const last=telemetry?.activeLatest,reference=telemetry?.reference;
  const age=last?.receivedUtcNs?Math.max(0,(Date.now()-last.receivedUtcNs/1e6)/1000):null;
  $('liveAge').textContent=disconnected?'Display disconnected':age===null?'No timed valid frame':`Last valid frame: ${Math.floor(age)} s ago`;
  $('detailsStatus').textContent=disconnected?'Display disconnected · Last received points retained':telemetry?.warning||telemetry?.state||'Connecting to receiver log';
  $('detailsReference').textContent=reference?`${region().satellite} / NORAD ${region().norad}\nDataset: ${reference.datasetId}\nOMM epoch: ${reference.epoch}\nLocal source: ${reference.directory}\nThese reference fields are local metadata, not transmitted OMM fields.`:'Waiting for local reference';
  $('detailsCounters').textContent=telemetry?`${telemetry.received} received · ${telemetry.valid} valid · ${telemetry.invalid} rejected · ${telemetry.malformed} malformed log lines`:'No receiver log';
  $('detailsMatch').textContent=last?(last.sourceMatched?'Latest frame matches the local reference dataset.':'Latest frame is valid but does not match the local reference dataset. Pass identity is unverified.'):'Waiting for a valid frame.';
  $('detailsRaw').textContent=last?last.frameHex.match(/.{1,2}/g).join(' '):'No valid frame received';
  $('detailsTime').textContent=last?.receivedUtcNs?`Host log timestamp: ${new Date(last.receivedUtcNs/1e6).toISOString()}. This is not an RF arrival timestamp.`:'Host log timestamp unavailable';
  $('detailsMetrics').textContent=last?`RSSI raw: ${last.rssiRaw??'unavailable'} · SNR raw: ${last.snrRaw??'unavailable'} · Range rate: ${last.rangeRate.toFixed(3)} m/s`:'Raw radio metrics unavailable';
}
if(operational){
  document.title='SPOK · Receiver Display';
  document.body.classList.add('operational','presenting');
  $('stage').setAttribute('aria-label','Received satellite telemetry dashboard');
  $('runtimeControls').hidden=false;
  $('detailsSource').append($('receiveSource'));
  $('showDetails').onclick=()=>{updateDetails();$('receiverDetails').showModal();};
  $('closeDetails').onclick=()=>$('receiverDetails').close();
  $('fullscreen').onclick=async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen();}catch(error){$('detailsStatus').textContent=error.message;}};
  setInterval(updateDetails,1000);
}
try{
  const world=await (await fetch('assets/world-countries.geojson')).json();
  worldPaths=world.features.map(feature=>({name:feature.properties.ADMIN,path:(feature.geometry.type==='Polygon'?[feature.geometry.coordinates]:feature.geometry.coordinates).map(polygon=>polygon.map(ring=>ring.map(([lon,lat],index)=>`${index?'L':'M'}${(lon+180).toFixed(4)},${(90-lat).toFixed(4)}`).join(' ')+'Z').join(' ')).join(' ')}));
  const saved=await (await fetch('/api/scene')).json();scene=validate(saved.scene);
  seed=operational?clone(scene):await (await fetch('scene.json')).json();
  scene.region=await (await fetch('/api/region')).json();revision=saved.revision;
  if(operational){previewMode=false;scene.samples=[];alignRegion();}
  const preview=new URLSearchParams(location.search).get('preview');
  if(!operational&&previewMode&&presets[preview]){scene.theme=clone(presets[preview]);$('save').textContent='Apply preview';dirty=true;}else previewMode=false;
  $('notes').value=scene.notes||'';render();fit();
  status(previewMode?'Preview only · current saved design is unchanged':`Loaded from disk · revision ${revision}`);
  if(!operational&&new URLSearchParams(location.search).get('display')==='1')$('present').click();
  $('monitor').textContent=monitorMode?'Design sample':'Watch receiver';pollReceiver();
}catch(error){status('Unable to load design: '+error.message,true);if(operational){$('fatalError').hidden=false;$('fatalError').textContent='Unable to load receiver display: '+error.message;}}
