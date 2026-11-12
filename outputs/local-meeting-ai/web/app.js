const $=s=>document.querySelector(s);let state=null,selected=null,current=null,activeTab='summary',uploading=false,detailVersion=0,refreshing=false,detailSignature='';
const labels={done:'Готово',needs_review:'Проверьте имена',held:'Отложено',queued:'В очереди',running:'Обрабатывается',error:'Нужна проверка',needs_speaker_setup:'Черновик готов'};
const stages={diarizing:'Разделяются голоса и определяются имена…',loading_asr:'Загружается модель речи…',transcribing:'Распознаётся речь…',auditing:'Проверяются решения по исходной расшифровке…',summarizing:'Составляется конспект…'};
const date=t=>new Date(t*1000).toLocaleString('ru-RU',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'});
const stamp=t=>{t=Math.floor(t);return [Math.floor(t/3600),Math.floor(t/60)%60,t%60].map(x=>String(x).padStart(2,'0')).join(':')};
function el(tag,cls,text){const x=document.createElement(tag);if(cls)x.className=cls;if(text!==undefined)x.textContent=text;return x}
async function api(path,method='GET',body){const r=await fetch(path,{method,headers:method==='POST'?{'X-Local-App':'meeting-ai','Content-Type':'application/json'}:{},body:body===undefined?undefined:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(d.error||'Не удалось выполнить действие');return d}
function toast(text){$('#toast').textContent=text;$('#toast').classList.remove('hidden');clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('#toast').classList.add('hidden'),6000)}
function view(name){for(const x of document.querySelectorAll('.view'))x.classList.toggle('hidden',x.id!==name+'-view');for(const x of document.querySelectorAll('.nav'))x.classList.toggle('active',x.dataset.view===name);$('#breadcrumb').textContent={records:'Записи',voices:'Голоса',system:'Система',help:'Помощь'}[name]}
document.querySelectorAll('[data-view]').forEach(x=>x.onclick=()=>view(x.dataset.view));
function renderState(){const jobs=state.jobs;$('#count-all').textContent=jobs.length;$('#list-count').textContent=jobs.length;$('#count-queue').textContent=jobs.filter(j=>j.status==='queued').length;$('#count-active').textContent=jobs.filter(j=>j.status==='running').length;$('#count-done').textContent=jobs.filter(j=>j.has_summary).length;
 $('#setup-title').textContent=state.models.ready?'Речь, голоса и конспектирование подключены':'Модели ещё не готовы к работе';
 $('#setup-description').textContent=state.models.ready?(state.profiles.length?'Сохранено голосов: '+state.profiles.length+'. Неуверенные совпадения будут отмечены в расшифровке.':'Сначала сохраните образцы голосов сотрудников, чтобы узнавать их по именам.'):'Записи уже можно добавить в очередь. Обработка станет доступна после завершения установки моделей.';
 $('#worker-label').textContent=state.worker?(state.stopping?'Остановится после текущей записи':'Очередь работает'):'Очередь остановлена';$('#worker-button').textContent=state.worker?(state.stopping?'Завершаем запись…':'Приостановить'):'Начать обработку';$('#worker-button').disabled=(!state.models.ready&&!state.worker)||(state.worker&&state.stopping);
 const list=$('#jobs');list.replaceChildren();if(!jobs.length)list.append(el('div','list-empty','Здесь появятся ваши записи'));
 for(const j of jobs){const button=el('button','job'+(j.id===selected?' selected':''));button.setAttribute('aria-label',j.name+' — '+(labels[j.status]||j.status));button.setAttribute('aria-pressed',String(j.id===selected));button.append(el('span','job-icon','≋'));const body=el('div','job-main');body.append(el('span','job-name',j.name),el('span','job-meta',date(j.created)+(j.status==='queued'||j.status==='held'?' · '+({'-10':'Низкий','0':'Обычный','10':'Высокий','20':'Срочный'}[j.priority]||'Обычный')+' приоритет':'')));button.append(body,el('span','badge '+j.status,labels[j.status]||j.status));button.onclick=()=>select(j.id);list.append(button)}
 const cards=$('#system-cards');cards.replaceChildren();for(const [name,ready,description] of [['Речь → текст',state.models.asr,'Whisper turbo · русский язык · процессор'],['Конспект и задачи',state.models.summary,(state.models.summary_name||'Локальная модель')+' · контекст '+state.models.summary_context+' токенов'],['Люди и имена',state.models.speakers,'Разделение голосов + сравнение с образцами сотрудников · процессор']]){const c=el('div','system-card');c.append(el('span','badge '+(ready?'needs_speaker_setup':''),ready?'Файлы установлены':name==='Люди и имена'?'Не подключено':'Установка не завершена'),el('h2','',name),el('p','',description));cards.append(c)}
 renderQueueControls();renderCapture();renderLifecycle();
 if(state.worker_error){$('#connection').textContent='Обработчик остановился: '+state.worker_error;$('#connection').classList.remove('hidden')}
}
// Poll metadata once at a time; large results are fetched only when their version changes.
async function refresh() {
 if (refreshing) return;
 refreshing = true;
 try {
  state = await api('/api/state');
  $('#connection').classList.add('hidden');
  renderState();
  const row = state.jobs.find(j => j.id === selected);
  if (row) {
   const signature = JSON.stringify([row.id,row.status,row.priority,row.error,row.result_version]);
   if (signature !== detailSignature) {
    await loadDetail(row.id);
    detailSignature = signature;
   }
  }
 } catch (error) {
  $('#connection').textContent='Не удалось обновить данные: '+error.message;
  $('#connection').classList.remove('hidden');
 } finally { refreshing=false; }
}
async function select(id){selected=id;current=null;detailSignature='';$('#audio-error').classList.add('hidden');$('#player').removeAttribute('src');$('#player').load();renderState();await loadDetail(id)}
async function loadDetail(id){const version=++detailVersion;const data=await api('/api/jobs/'+id);if(selected!==id||version!==detailVersion)return;const signature=JSON.stringify(data);if(current&&signature===JSON.stringify(current))return;current=data;const packaged=data.name.toLowerCase().endsWith('.meeting');$('#player').hidden=packaged;if(packaged){$('#audio-error').classList.add('hidden')}else if($('#player').getAttribute('src')!=='/api/jobs/'+id+'/audio'){$('#player').src='/api/jobs/'+id+'/audio'}$('#detail-empty').classList.add('hidden');$('#detail-content').classList.remove('hidden');$('#detail-title').textContent=data.name;$('#detail-meta').textContent=date(data.created)+(data.transcript?' · '+stamp(data.transcript.duration||0):'');$('#detail-status').className='badge '+data.status;$('#detail-status').textContent=labels[data.status]||data.status;let note=data.error||'';if(data.status==='running'){note=stages[data.progress.stage]||'Обрабатывается запись…';if(data.progress.total)note+=' · часть '+data.progress.part+' из '+data.progress.total;if(data.progress.seconds)note+=' '+stamp(data.progress.seconds)+' из '+stamp(data.progress.duration||0)}else if(data.status==='queued')note=state.worker?'Ожидает своей очереди.':'Запись добавлена. Нажмите «Начать обработку», когда модели будут готовы.';$('#detail-notice').textContent=note;$('#detail-notice').classList.toggle('hidden',!note);$('#retry').classList.toggle('hidden',data.status!=='error');renderResult();renderSources();renderQueueControls();renderLifecycle();$('#recognize-again').classList.toggle('hidden',!['done','needs_review','needs_speaker_setup'].includes(data.status))}
// Group short uncertain prefixes for reading; preserve their own attribution.
function transcriptDisplayRows(segments){
 const rows=[];
 for(let i=0;i<segments.length;i++){
  const fragment=segments[i],next=segments[i+1];
  const uncertain=fragment.speaker_id==null;
  const short=fragment.text.trim().split(/\s+/).length<=3 && fragment.end-fragment.start<=3;
  const adjacent=next && next.source===fragment.source && next.start>=fragment.end-.05 && next.start-fragment.end<=1.2;
  if(uncertain && short && adjacent && next.speaker_id!=null){
   rows.push({...next,start:fragment.start,prefix:fragment.text,prefixSpeaker:fragment.speaker});
   i++;
  }else{
   rows.push({...fragment});
  }
 }
 return rows;
}
function renderResult(){const body=$('#result-body');body.replaceChildren();if(!current)return;const link=$('#download-result');link.classList.toggle('hidden',activeTab==='summary'?!current.has_summary:activeTab==='minutes'?!current.has_minutes:!current.has_transcript);link.href='/api/jobs/'+current.id+'/'+activeTab;
 if(activeTab==='summary'||activeTab==='minutes'){const text=current[activeTab];body.append(el(text?'pre':'div',text?'summary-text':'result-empty',text||(activeTab==='minutes'?'Нажмите «Обновить сводку и конспект», чтобы создать подробный конспект.':'Сводка появится после обработки записи.')))}else if(current.transcript){if(!current.transcript.segments.length)body.append(el('div','result-empty','Речь не обнаружена. Проверьте запись.'));for(const s of transcriptDisplayRows(current.transcript.segments)){const row=el('div','segment'),time=el('button','time',stamp(s.start));time.disabled=current.name.toLowerCase().endsWith('.meeting');time.title=time.disabled?'Время реплики':'Прослушать с этого момента';time.onclick=()=>{$('#player').currentTime=s.start;$('#player').play().catch(()=>toast('Нажмите воспроизведение в плеере.'))};const text=el('div');const paragraph=el('p','');if(s.prefix){const prefix=el('span','uncertain-prefix',s.prefix.trim()+' ');prefix.title='Говорящий для этого фрагмента не определён уверенно';paragraph.append(prefix,document.createTextNode(s.text));}else paragraph.textContent=s.text;text.append(el('small','',(s.speaker||'Говорящий не определён')+(s.prefix?' · начало требует проверки':'')),paragraph);row.append(time,text);body.append(row)}}else body.append(el('div','result-empty','Расшифровка появится после распознавания речи.'))}
document.querySelectorAll('[data-tab]').forEach(x=>x.onclick=()=>{activeTab=x.dataset.tab;document.querySelectorAll('[data-tab]').forEach(t=>{t.classList.toggle('active',t===x);t.setAttribute('aria-selected',String(t===x))});renderResult()});
$('#player').onerror=()=>$('#audio-error').classList.remove('hidden');$('#refresh').onclick=refresh;
$('#worker-button').onclick=async()=>{try{$('#worker-button').disabled=true;await api(state.worker?'/api/pause':'/api/start','POST');await refresh()}catch(e){toast(e.message);await refresh()}};
$('#retry').onclick=async()=>{try{await api('/api/retry/'+selected,'POST');toast('Запись возвращена в очередь');await refresh()}catch(e){toast(e.message)}};
$('#upload-top').onclick=()=>$('#file-input').click();$('#dropzone').onclick=()=>$('#file-input').click();$('#dropzone').onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();$('#file-input').click()}};
function upload(file){return new Promise((resolve,reject)=>{const xhr=new XMLHttpRequest();xhr.open('POST','/api/upload');xhr.setRequestHeader('X-Local-App','meeting-ai');xhr.setRequestHeader('X-Filename',encodeURIComponent(file.name));xhr.setRequestHeader('Content-Type','application/octet-stream');xhr.upload.onprogress=e=>{if(e.lengthComputable)$('#upload-bar').value=e.loaded/e.total*100};xhr.onload=()=>{try{const d=JSON.parse(xhr.responseText);xhr.status===200?resolve(d):reject(Error(d.error))}catch(e){reject(Error('Не удалось загрузить запись'))}};xhr.onerror=()=>reject(Error('Загрузка прервалась. Проверьте, что программа запущена.'));xhr.send(file)})}
async function uploadFiles(files){if(uploading)return toast('Дождитесь завершения текущей загрузки');uploading=true;$('#upload-top').disabled=true;$('#upload-progress').classList.remove('hidden');let last=null;try{for(const file of files){if(!/\.(wav|mp3|m4a|mp4|flac|ogg|opus|webm)$/i.test(file.name))throw Error('Неподдерживаемый формат: '+file.name);if(!file.size)throw Error('Запись должна быть непустой');$('#upload-label').textContent='Добавляем: '+file.name;$('#upload-bar').value=0;last=(await upload(file)).id;await refresh()}toast('Запись добавлена в очередь');if(last)await select(last)}catch(e){toast(e.message)}finally{uploading=false;$('#upload-top').disabled=false;$('#upload-progress').classList.add('hidden');$('#file-input').value=''}}
$('#file-input').onchange=e=>uploadFiles([...e.target.files]);for(const event of ['dragenter','dragover'])$('#dropzone').addEventListener(event,e=>{e.preventDefault();$('#dropzone').classList.add('dragover')});for(const event of ['dragleave','drop'])$('#dropzone').addEventListener(event,e=>{e.preventDefault();$('#dropzone').classList.remove('dragover')});$('#dropzone').addEventListener('drop',e=>uploadFiles([...e.dataTransfer.files]));
// Initial polling starts after the queue controls script is loaded.
window.addEventListener('DOMContentLoaded',()=>{refresh();setInterval(()=>{if(!document.hidden)refresh()},3000)});

function renderSources(){
 const box=$('#source-downloads');box.replaceChildren();
 $('#source-folder').textContent=current?.capture?.folder?'Исходники: '+current.capture.folder:'';
 for(const kind of current?.capture?.sources||[]){const a=el('a','secondary',kind==='mic'?'Скачать микрофон':'Скачать звук компьютера');a.href='/api/jobs/'+current.id+'/'+kind;a.download=kind+'.wav';box.append(a)}
 if(current?.capture?.warning)box.append(el('p','muted',current.capture.warning));
}
