'use strict';
const $=s=>document.querySelector(s);
const escapeText=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let catalog,token='',step=0,identity=null,person=null,submissionID=sessionStorage.getItem('clinic-submission-id')||crypto.randomUUID(),busy=false;
sessionStorage.setItem('clinic-submission-id',submissionID);
const selected=new Set(); const followups={}; const warnings={};
async function api(path,body) {
  const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Clinic-Token':token},body:JSON.stringify(body),signal:AbortSignal.timeout(15000)});
  const data=await response.json(); if(!response.ok||!data.ok) throw new Error(data.message||'Unable to save. Please ask clinic staff.'); return data;
}
function showError(message) { $('#patient-error').textContent=message; $('#patient-error').scrollIntoView({block:'center',behavior:'smooth'}); }
function question(label,key,kind,value) { return `<label>${escapeText(label)}<select data-question="${escapeText(key)}" data-kind="${kind}"><option value="">Choose / unanswered</option>${['yes','no','unsure'].map(v=>`<option value="${v}" ${v===value?'selected':''}>${{yes:'Yes',no:'No',unsure:'I’m not sure'}[v]}</option>`).join('')}</select></label>`; }
function symptoms() {
  const search=$('#symptom-search').value.toLowerCase(),groups=new Map();
  for(const symptom of catalog.symptoms) {
    if(!`${symptom.label} ${symptom.category}`.toLowerCase().includes(search)) continue;
    if(!groups.has(symptom.category)) groups.set(symptom.category,[]);groups.get(symptom.category).push(symptom);
  }
  $('#symptom-list').innerHTML=[...groups].map(([category,items])=>`<section class="symptom-category"><h3>${escapeText(category)}</h3><div class="symptom-choices">${items.map(s=>`<label><input type="checkbox" data-symptom="${s.id}" ${selected.has(s.id)?'checked':''}>${escapeText(s.label)}</label>`).join('')}</div></section>`).join('')||'<p>No matching symptoms. Clear the search or choose “Something else”.</p>';
  $('#symptom-selection').textContent=`${selected.size} selected. Filtering does not clear your selections.`;
}
function moreDetails() {
  $('#warning-questions').innerHTML=catalog.warnings.map(w=>question(w.label,w.id,'warning',warnings[w.id])).join('');
  $('#followup-questions').innerHTML=catalog.symptoms.filter(s=>selected.has(s.id)&&s.followups.length).map(s=>`<div class="symptom-category"><h3>${escapeText(s.label)}</h3>${s.followups.map(f=>question(f.label,`${s.id}.${f.id}`,'followup',followups[`${s.id}.${f.id}`])).join('')}</div>`).join('');
}
function answers() {
  const unit=$('#duration-unit').value,value=$('#duration-value').value;
  return {symptoms:[...selected],followups:Object.fromEntries(Object.entries(followups).filter(([k])=>selected.has(k.split('.')[0]))),warnings:{...warnings},other_listed_absent:$('#other-absent').value==='yes'?true:$('#other-absent').value==='unsure'?false:null,
    duration:unit||value!==''?{unit:unit||null,value:value===''?null:Number(value)}:null,self_severity:$('#self-severity').value||null,additional:$('#additional-symptoms').value};
}
function emergencyNow() {
  let flag=Object.values(warnings).includes('yes');
  for(const s of catalog.symptoms) if(selected.has(s.id)) for(const f of s.followups) if(f.emergency_when&&followups[`${s.id}.${f.id}`]===f.emergency_when) flag=true;
  const firstWarning=flag&&$('#patient-emergency').hidden;
  $('#patient-emergency').hidden=!flag;
  $('#patient-emergency').innerHTML=`<strong>Get emergency help now.</strong>${escapeText(catalog.emergency_instruction)}`;
  if(firstWarning)$('#patient-emergency').scrollIntoView({block:'center',behavior:'auto'});
}
function drawStep() {
  for(let i=0;i<4;i++) { $(`#step-${i}`).hidden=i!==step;const li=$(`[data-step="${i}"]`);li.classList.toggle('active',i===step);li.classList.toggle('done',i<step);if(i===step) li.setAttribute('aria-current','step');else li.removeAttribute('aria-current'); }
  $('#patient-back').hidden=step===0;$('#patient-next').hidden=step===3;$('#patient-submit').hidden=step!==3;
  $('#patient-error').textContent=''; $('#patient-main').scrollIntoView({block:'start',behavior:'smooth'});
}
function reviewMarkup(a) {
  const rows=[['Patient',`${person.name} · ${person.age} years · ${person.id?`ID ${person.id}`:'New registration'}`],['Symptoms',catalog.symptoms.filter(s=>selected.has(s.id)).map(s=>s.label).join(', ')||'Not provided'],['Other listed symptoms',a.other_listed_absent===true?'Explicitly reported absent':'Not confirmed / unsure'],['Duration',a.duration?`${a.duration.value??'Unanswered'} ${a.duration.unit??'(unit unanswered)'}`:'Not provided / unsure'],['How you feel',a.self_severity||'Not provided'],['Additional symptoms',a.additional||'No additional text entered']];
  for(const w of catalog.warnings) rows.push([w.label,a.warnings[w.id]||'Unanswered']);
  for(const s of catalog.symptoms) if(selected.has(s.id)) for(const f of s.followups) rows.push([s.label+': '+f.label,a.followups[`${s.id}.${f.id}`]||'Unanswered']);
  return `<dl class="review-list">${rows.map(([k,v])=>`<div><dt>${escapeText(k)}</dt><dd>${escapeText(v)}</dd></div>`).join('')}</dl>`;
}
async function run(operation) {
  if(busy)return;busy=true;for(const b of document.querySelectorAll('button'))b.disabled=true;
  try{await operation();}catch(e){showError(e.name==='TimeoutError'?'Request timed out. Retry this same form; its submission reference prevents duplicates.':e.message);}
  finally{busy=false;for(const b of document.querySelectorAll('button'))b.disabled=false;}
}
$('#patient-next').addEventListener('click',()=>run(async()=>{
  if(step===0) {
    const kind=$('input[name="identity-kind"]:checked').value;
    identity=kind==='new'?{kind,name:$('#patient-name').value,age:$('#patient-age').value===''?null:Number($('#patient-age').value)}:{kind,id:$('#patient-id').value,code:$('#intake-code').value};
    person=(await api('/api/patient/identify',identity)).identity;
  }
  if(step===1)moreDetails();
  if(step===2) {
    const a=answers(),evaluation=(await api('/api/patient/preview',a)).evaluation;
    $('#patient-review').innerHTML=reviewMarkup(a);
    $('#suggestion-preview').innerHTML=`<strong>Demonstration suggestion: ${escapeText(evaluation.label)}</strong><p>${escapeText(evaluation.explanation)}</p><p>Only staff can confirm a final priority. This suggestion does not add you to the queue.</p>`;
  }
  step++;drawStep();
}));
$('#patient-back').addEventListener('click',()=>{if(step>0){step--;drawStep();}});
$('#patient-form').addEventListener('submit',e=>{e.preventDefault();run(async()=>{
  if(!$('#identity-confirmed').checked)throw new Error('Please confirm that the patient details and answers belong to you.');
  const receipt=await api('/api/patient/submit',{submission_id:submissionID,identity,identity_confirmed:true,answers:answers()});
  $('#patient-form').hidden=true;$('.progress-steps').hidden=true;$('#patient-receipt').hidden=false;
  $('#receipt-details').innerHTML=`<dt>Assessment reference</dt><dd>${escapeText(receipt.reference)}</dd><dt>Your patient ID</dt><dd>${escapeText(receipt.patient_id)}</dd><dt>Review status</dt><dd>${receipt.status==='reviewed'?'Reviewed by staff':'Awaiting staff review'}</dd>`;
  $('#receipt-summary').textContent=receipt.message;
  $('#receipt-warning').hidden=!receipt.evaluation.emergency;
  $('#receipt-warning').textContent=receipt.evaluation.emergency_instruction;
  $('#patient-receipt').focus();
});});
$('#symptom-search').addEventListener('input',symptoms);
$('#symptom-list').addEventListener('change',e=>{const id=e.target.dataset.symptom;if(!id)return;if(e.target.checked)selected.add(id);else selected.delete(id);$('#other-absent').value='';symptoms();emergencyNow();});
document.addEventListener('change',e=>{if(e.target.name==='identity-kind'){$('#existing-fields').hidden=e.target.value==='new';$('#new-fields').hidden=e.target.value!=='new';}if(e.target.dataset.question){const dest=e.target.dataset.kind==='warning'?warnings:followups;dest[e.target.dataset.question]=e.target.value||null;emergencyNow();}});
$('#another-assessment').addEventListener('click',()=>{sessionStorage.removeItem('clinic-submission-id');location.reload();});
function consumeInvitation() {
  const fragment=new URLSearchParams(location.hash.slice(1));
  if(!fragment.has('id')||!fragment.has('code'))return;
  if(step>0&&!$('#patient-form').hidden&&!window.confirm('Open a new assessment? Your current unsent answers will be cleared.')) { history.replaceState(null,'','/patient');return; }
  $('#patient-form').reset(); selected.clear();for(const k of Object.keys(followups))delete followups[k];for(const k of Object.keys(warnings))delete warnings[k];
  step=0;identity=null;person=null;submissionID=crypto.randomUUID();sessionStorage.setItem('clinic-submission-id',submissionID);
  $('#patient-form').hidden=false;$('.progress-steps').hidden=false;$('#patient-receipt').hidden=true;$('#receipt-details').textContent='';
  $('input[name="identity-kind"][value="existing"]').checked=true;$('#existing-fields').hidden=false;$('#new-fields').hidden=true;
  $('#patient-id').value=fragment.get('id');$('#intake-code').value=fragment.get('code');
  history.replaceState(null,'','/patient');symptoms();emergencyNow();drawStep();
}
window.addEventListener('hashchange',()=>{if(catalog)consumeInvitation();});
(async()=>{try{const session=await(await fetch('/api/session')).json();token=session.token;catalog=await(await fetch('/api/catalog')).json();symptoms();drawStep();consumeInvitation();}catch(e){showError('Cannot connect to the local clinic. Ask staff for help.');}})();
