'use strict';
const byId = id => document.getElementById(id);
const mode = byId('mode'), start = byId('start'), stop = byId('stop');
const say = message => { byId('status').textContent = message; };
const params = new URLSearchParams(location.search), voice = params.has('voice');
let db, current, streams = [], recorders = [], writes = [], timer, stopping = false, storageError;
const uploading = new Set();
const micDevice=byId('mic-device'), micList=byId('mic-list');
let checkingDevices=false, meterContext, meterTimer;
function lockInputs(locked){
  micDevice.disabled=locked;micList.disabled=locked;
}
async function listMicrophones(){
  const selected=micDevice.value;
  const devices=await navigator.mediaDevices.enumerateDevices();
  const microphones=devices.filter(d=>d.kind==='audioinput' && d.deviceId);
  micDevice.replaceChildren(new Option('По умолчанию в браузере',''));
  microphones.forEach((d,i)=>micDevice.add(new Option(d.label || 'Микрофон '+(i+1),d.deviceId)));
  if(microphones.some(d=>d.deviceId===selected))micDevice.value=selected;
}
micList.onclick=async()=>{
  if(current || checkingDevices)return;
  checkingDevices=true;lockInputs(true);start.disabled=true;
  let permission;
  try{
    permission=await navigator.mediaDevices.getUserMedia({audio:true});
    await listMicrophones();
    byId('mic-note').textContent='Выберите микрофон для следующей записи.';
  }catch(e){byId('mic-note').textContent='Список микрофонов недоступен: '+e.message;}
  finally{
    permission?.getTracks().forEach(t=>t.stop());
    checkingDevices=false;lockInputs(false);start.disabled=!db;hint();
  }
};
micDevice.onchange=()=>hint();
function deliveryStatus(text){
  const label=byId('delivery');label.textContent=text;label.hidden=!text;
}
function closeMeters(){
  clearInterval(meterTimer);
  if(meterContext)meterContext.close().catch(()=>{});
  meterContext=null;
  for(const k of ['microphone','computer'])byId(k+'-level').value=0;
}
function monitorLevels(inputs){
  for(const [key,track] of Object.entries(inputs)){
    byId(key+'-source').textContent=track.label || (key==='microphone'?'Микрофон браузера':'Выбранный источник звонка');
  }
  try{
    meterContext=new AudioContext();
    const context=meterContext;
    const meters=Object.entries(inputs).map(([key,track])=>{
      const source=context.createMediaStreamSource(new MediaStream([track]));
      const analyser=context.createAnalyser();
      analyser.fftSize=1024;source.connect(analyser);
      return {source,analyser,data:new Float32Array(analyser.fftSize),bar:byId(key+'-level')};
    });
    const unavailable=()=>{if(meterContext===context)byId('mic-note').textContent='Индикатор уровня недоступен в браузере.';};
    context.resume().catch(unavailable);
    meterTimer=setInterval(()=>{
      for(const {analyser,data,bar} of meters){
        analyser.getFloatTimeDomainData(data);
        let peak=0;
        for(const value of data)peak=Math.max(peak,Math.abs(value));
        bar.value=Math.max(0,100+100*Math.log10(Math.max(.001,peak))/3);
      }
    },100);
  }catch{closeMeters();byId('mic-note').textContent='Индикатор уровня недоступен в браузере.';}
}
let unlockSession;
async function lockDraft(id) {
  if (!navigator.locks) return;
  await new Promise((resolve,reject)=>{
    navigator.locks.request('protocol-record-'+id,()=>new Promise(unlock=>{
      unlockSession=unlock;resolve();
    })).catch(reject);
  });
}
function result(request) {
  return new Promise((resolve,reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}
function save(store, operation) {
  return new Promise((resolve,reject) => {
    const tx = db.transaction(store,'readwrite');
    operation(tx.objectStore(store));
    tx.oncomplete = resolve;
    tx.onabort = () => reject(tx.error || Error('Браузер прервал сохранение.'));
  });
}
function partsRange(id, source) {
  return IDBKeyRange.bound([id,source,0],[id,source,Number.MAX_SAFE_INTEGER]);
}
async function deliver(draft) {
  if (uploading.has(draft.id)) return;
  uploading.add(draft.id);
  try {
    deliveryStatus('Отправляется · '+draft.title);
    const bodies = [], tracks = [];
    for (const track of draft.tracks) {
      const chunks = await result(db.transaction('parts').objectStore('parts').getAll(partsRange(draft.id,track.source)));
      const audio = new Blob(chunks);
      if (!audio.size) throw Error('Источник не передал звук: '+track.source);
      bodies.push(audio);
      tracks.push({...track,size:audio.size});
    }
    const headers = {'X-Local-App':'meeting-ai'};
    if (draft.voice) {
      headers['X-Filename'] = 'voice.'+tracks[0].ext;
      headers['X-Person-Name'] = encodeURIComponent(draft.title);
    } else {
      headers['X-Meeting'] = encodeURIComponent(JSON.stringify({title:draft.title,seconds:draft.seconds,interrupted:draft.interrupted,tracks}));
    }
    const response = await fetch(draft.voice?'/api/voices/upload':'/api/browser-meeting',{method:'POST',headers,body:new Blob(bodies)});
    const reply = await response.json();
    if (!response.ok || (!draft.voice && !reply.id)) throw Error(reply.error || 'Сервер не подтвердил приём.');
    deliveryStatus('Принято сервером · '+draft.title+(draft.voice?'':' · № '+reply.id.slice(0,8)));
    try{
    await save('sessions',s=>s.delete(draft.id));
    for (const track of tracks) await save('parts',s=>s.delete(partsRange(draft.id,track.source)));
    }catch{say('Сервер подтвердил приём. Не удалось очистить локальную копию.');return;}
    if(draft.voice)byId('voice-profiles-link').hidden=false;
    say(draft.voice?'Сервер принял образец на проверку. После успешной проверки имя и число образцов появятся в разделе «Голоса».':'Сервер принял встречу в очередь. Откройте «Встречи» для просмотра результата.');
  } catch(e) { deliveryStatus('Приём не подтверждён · '+draft.title);say('Отправка не завершена. '+e.message+' Запись сохранена в этом браузере.'); }
  finally { uploading.delete(draft.id); await listDrafts(); }
}
async function listDrafts() {
  const rows = await result(db.transaction('sessions').objectStore('sessions').getAll());
  const box = byId('drafts'); box.replaceChildren();
  const locks=navigator.locks ? await navigator.locks.query() : {held:[]};
  for (const draft of rows.filter(r=>r.seconds && r.id!==current?.id)) {
    if (draft.open && (!navigator.locks || locks.held.some(l=>l.name==='protocol-record-'+draft.id))) continue;
    if(draft.open) draft.interrupted='Вкладка была закрыта во время записи';
    const button = document.createElement('button'); button.className='secondary';
    button.textContent = 'Отправить · '+draft.title; button.disabled=uploading.has(draft.id);
    button.onclick = ()=>{button.disabled=true; deliver(draft);}; box.append(button);
  }
  byId('pending').hidden = !box.childElementCount;
}
function release() {
  closeMeters();
  for (const stream of streams) for (const track of stream.getTracks()) track.stop();
  streams=[];
}
async function finish(reason='') {
  if (!current || stopping) return;
  stopping=true; stop.disabled=true; clearInterval(timer);
  const draft=current;
  try {
    await Promise.all(recorders.map(r=>new Promise(resolve=>{
      if(r.state==='inactive') return resolve();
      r.addEventListener('stop',resolve,{once:true});r.stop();
    })));
    release(); await Promise.all(writes);
    draft.seconds=Math.max(.001,(Date.now()-draft.started)/1000);
    draft.open=false;draft.interrupted=storageError||reason;
    await save('sessions',s=>s.put(draft));
    if(storageError){deliveryStatus('Ожидает отправки');say('Запись прервалась: '+storageError+'. Сохранённую часть можно отправить.');}
    else await deliver(draft);
  } catch(e) {say('Ошибка сохранения: '+e.message);}
  finally {release(); unlockSession?.();unlockSession=null;current=null; stopping=false; start.disabled=false; mode.disabled=voice;lockInputs(false); await listDrafts();}
}
function hint(){
  byId('mic-options').hidden=byId('microphone-row').hidden=mode.value==='call';
  byId('computer-row').hidden=mode.value==='mic';
  byId('microphone-source').textContent=micDevice.selectedOptions[0].textContent;
  byId('computer-source').textContent='Источник выбирается при запуске';
  byId('hint').textContent=mode.value==='mic'?'Разрешите доступ к микрофону этого устройства.':
    'Выберите вкладку звонка или экран и включите передачу звука. Сохраняется только аудио.';
}
start.onclick=async()=>{
  start.disabled=true; mode.disabled=true;lockInputs(true);byId('mic-note').textContent='';
  const name=byId('title').value.trim();
  let stage='Микрофон комнаты';
  try {
    if(voice && name.length<2)throw Error('Введите имя сотрудника.');
    const inputs={};
    if(mode.value!=='mic'){
      stage='Звук звонка';
      const display=await navigator.mediaDevices.getDisplayMedia({video:true,audio:true,systemAudio:'include'});
      streams.push(display); inputs.computer=display.getAudioTracks()[0];
      if(!inputs.computer)throw Error('У выбранного источника нет дорожки звука. Выберите вкладку со звуком или режим «Только комната».');
    }
    if(mode.value!=='call'){
      stage='Микрофон комнаты';
      const mic=await navigator.mediaDevices.getUserMedia({audio:micDevice.value?{deviceId:{exact:micDevice.value}}:true});
      streams.push(mic); inputs.microphone=mic.getAudioTracks()[0];
    }
    stage='Запуск записи';
    const names=['microphone','computer'].filter(k=>inputs[k]);
    const mimeType=['audio/webm;codecs=opus','audio/mp4','audio/ogg;codecs=opus'].find(type=>MediaRecorder.isTypeSupported(type));
    if(!mimeType)throw Error('Браузер не поддерживает доступные форматы записи.');
    recorders=names.map(k=>new MediaRecorder(new MediaStream([inputs[k]]),{mimeType}));
    const tracks=recorders.map((r,i)=>{
      const ext=['webm','mp4','ogg'].find(type=>r.mimeType.includes(type));
      if(!ext)throw Error('Браузер выбрал неподдерживаемый формат '+r.mimeType);
      return {source:names[i],ext};
    });
    const draft={id:crypto.randomUUID(),started:Date.now(),title:name||new Date().toLocaleString('ru'),voice,tracks,seconds:0,open:true};
    await lockDraft(draft.id);
    await save('sessions',s=>s.put(draft));
    current=draft;writes=[];storageError='';
    recorders.forEach((r,i)=>{
      let sequence=0;
      r.ondataavailable=e=>{
        if(!e.data.size)return;
        const index=sequence++;
        const pending=save('parts',s=>s.put(e.data,[draft.id,names[i],index])).then(()=>{
          if (!stopping && i===0) {
            draft.seconds=Math.max(.001,(Date.now()-draft.started)/1000);
            return save('sessions',s=>s.put(draft));
          }
        }).catch(err=>{
          storageError=err.message;finish(storageError);
        });
        writes.push(pending);
        pending.then(()=>{writes=writes.filter(w=>w!==pending);});
      };
      r.onerror=e=>finish(e.error?.message||'Браузер прервал запись');
      inputs[names[i]].onended=()=>finish('Источник отключился');
      r.start(4000);
    });
    monitorLevels(inputs);deliveryStatus('Записывается на этом устройстве');
    timer=setInterval(()=>{
      const seconds=Math.floor((Date.now()-draft.started)/1000);
      byId('timer').textContent=Math.floor(seconds/60)+':'+String(seconds%60).padStart(2,'0');
      if(voice && seconds>=120)finish();
    },500);
    say('Идёт запись. Оставьте вкладку открытой до завершения.');stop.disabled=false;
  }catch(e){
    if(current){await finish(e.message);return;}
    release();unlockSession?.();unlockSession=null;start.disabled=false;mode.disabled=voice;lockInputs(false);
    say(stage+' — '+(e.name==='NotAllowedError'?'доступ не предоставлен или выбор отменён':e.message));
  }
};
stop.onclick=()=>finish();
mode.onchange=hint;
window.addEventListener('beforeunload',e=>{if(current){e.preventDefault();e.returnValue='';}});
async function setup(){
  if(!isSecureContext){location.replace('https://'+location.host+location.pathname+location.search);return;}
  if(!window.MediaRecorder||!navigator.mediaDevices?.getUserMedia)throw Error('Этот браузер не поддерживает запись микрофона.');
  if(voice || !navigator.mediaDevices.getDisplayMedia){
    mode.value='mic';
    for(const option of mode.options)option.disabled=option.value!=='mic';
  }
  if(voice){byId('voice-script').hidden=false;byId('heading').textContent='Образец голоса';byId('label').firstChild.textContent='Имя и фамилия';byId('title').value=params.get('name')||'';}
  const request=indexedDB.open('protocol-audio',1);
  request.onupgradeneeded=()=>{
    request.result.createObjectStore('sessions',{keyPath:'id'});
    request.result.createObjectStore('parts');
  };
  db=await result(request);micList.disabled=false;listMicrophones().catch(()=>{});hint();start.disabled=false;mode.disabled=voice;await listDrafts();
}
setup().catch(e=>say(e.message));
