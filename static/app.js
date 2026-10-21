const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="corner-token"]').content;
const empty = $('results').innerHTML;
const el = (tag, text, cls) => {const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
const clock = t => `${Math.floor(t/60)}:${String(Math.floor(t%60)).padStart(2,'0')}`;
const asset = (r, name) => '/outputs/'+r.folder.split('/').map(encodeURIComponent).join('/')+'/'+encodeURIComponent(name);
let previous = '', blocked = false;
async function post(path, data={}) {const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Corner-Token':token},body:JSON.stringify(data)});const result=await response.json();if(!response.ok)throw Error(result.error || 'Request failed');return result;}
function card(r){
  const node=el('article',undefined,'card');node.dataset.key=r.folder;
  const top=el('div',undefined,'card-top'),heading=el('div');heading.append(el('h3',r.title));const meta=el('div',`${r.author || 'YouTube'} · ${clock(r.duration)}`,'meta');if(r.demo)meta.append(el('span','Demo','demo-note'));heading.append(meta);top.append(heading);
  const source=el('a',r.url?'YouTube ↗':'Play video ↗','source');source.href=r.url || asset(r,r.video);source.target='_blank';source.rel='noopener noreferrer';top.append(source);node.append(top);
  const frames=el('div',undefined,'frames');r.frames.forEach((f,i)=>{const button=el('button',undefined,'frame');button.setAttribute('aria-label',`Open frame ${i+1} at ${clock(f.time)}`);const img=el('img');img.src=asset(r,f.file);img.alt=`${r.title}, frame at ${clock(f.time)}`;img.loading='lazy';button.append(img,el('span',clock(f.time)));button.onclick=()=>{$('large-image').src=img.src;$('image-caption').textContent=`${r.title} · ${clock(f.time)}`;$('lightbox').showModal();};frames.append(button);});node.append(frames);
  const text=el('details',undefined,'transcript');text.append(el('summary','Transcript'));text.append(el('p',r.transcription_error?`Transcription unavailable: ${r.transcription_error}`:r.transcript || 'No speech detected.',r.transcription_error?'warning':''));node.append(text);
  const reaction=el('div',undefined,'reaction');
  if(r.feedback){const f=r.feedback;const row=el('div',undefined,'feedback');const mood=['','Disliked it','Not keen','Mixed','Liked it','Loved it'][f.rating];row.append(el('span',`${f.rating}/5 · ${mood}`,'rating'),el('span',f.would_like?'♥ Would like':'♡ Would not like',f.would_like?'positive':''),el('span',f.would_comment?'Would comment':'Would not comment'));reaction.append(row);}
  if(r.reaction){reaction.append(el('small','AI reaction'),el('p',r.reaction));if(!r.feedback)reaction.append(el('small','No rating yet','unrated'));}else reaction.append(el('small','No AI reaction yet','unrated'));
  if(r.feedback?.would_comment){const comment=el('div',undefined,'suggested-comment');comment.append(el('small','Suggested comment'),el('p',r.feedback.comment));reaction.append(comment);}node.append(reaction);return node;
}
function renderLibrary(videos){const key=JSON.stringify(videos);if(key===previous)return;previous=key;const opened=new Set([...document.querySelectorAll('.card details[open]')].map(n=>n.closest('.card').dataset.key));$('result-count').textContent=videos.length;if(!videos.length){$('results').innerHTML=empty;return;}$('results').replaceChildren(...videos.map(r=>{const node=card(r);if(opened.has(r.folder))node.querySelector('details').open=true;return node;}));}
function renderState(state){$('status').textContent=state.status;$('start').disabled=state.running;$('stop').disabled=!state.running;const blocker=state.blocker;$('consent').hidden=!blocker;document.querySelector('main').inert=!!blocker;if(blocker){$('consent-title').textContent=blocker.title;$('consent-message').textContent=blocker.message;if(!blocked)$('retry').focus();}else if(blocked)$('start').focus();blocked=!!blocker;}
async function poll(){try{const responses=await Promise.all([fetch('/api/state'),fetch('/api/library')]);if(responses.some(r=>!r.ok))throw Error();const [state,videos]=await Promise.all(responses.map(r=>r.json()));renderState(state);renderLibrary(videos);}catch{$('status').textContent='Connection lost. Reopen Claude’s Corner.';}setTimeout(poll,1000);}
$('start').onclick=async()=>{try{await post('/api/start',{browser:$('browser').value,model:$('model').value});$('status').textContent='Opening YouTube…';}catch(e){$('status').textContent=e.message;}};
async function stop(){try{await post('/api/stop');$('status').textContent='Stopping…';}catch(e){$('status').textContent=e.message;}}
$('stop').onclick=stop;$('consent-stop').onclick=stop;$('retry').onclick=async()=>{try{await post('/api/retry');}catch(e){$('consent-message').textContent=e.message;}};
$('close-lightbox').onclick=()=>$('lightbox').close();$('lightbox').onclick=e=>{if(e.target===$('lightbox'))$('lightbox').close();};poll();
