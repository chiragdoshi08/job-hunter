'use strict';
// A single view of separate role stores. Group only exact question/context keys.
let questionFilter={q:'',status:'all',category:'all',role:'all'},questionRows=[],questionGroups=[],questionVisible=[],questionSelected=new Set(),questionDrafts=new Map(),questionActive=null,questionLoad=0;
const questionStatuses={unanswered:'Needs an answer',needs_review:'Needs review',ready:'Ready to reuse',expired:'Review overdue',application_review:'Review per application',different:'Different answers'};
const questionNeedsReview=g=>g.entries.some(x=>['unanswered','needs_review','expired'].includes(x.status));
function groupQuestions(rows){
 const groups=new Map();for(const row of rows){const key=row.question_key||row.role+':'+row.id;if(!groups.has(key))groups.set(key,{key,question:row.question,category:row.category,entries:[]});groups.get(key).entries.push(row);}
 return [...groups.values()].map(g=>{const values=new Set(g.entries.map(x=>JSON.stringify([x.value,x.answer_mode||'single'])));g.different=values.size>1;g.value=g.entries[0].value;g.status=g.different?'different':['unanswered','expired','needs_review','application_review','ready'].find(s=>g.entries.some(x=>x.status===s));g.selectable=!g.different&&!!g.value.trim()&&g.entries.every(x=>!x.review_note&&x.status!=='expired')&&g.entries.some(x=>!x.confirmed);return g;}).sort((a,b)=>a.question.localeCompare(b.question));
}
async function loadQuestionBank(){
 const roles=Object.keys(boot.identities),catalogs=await Promise.all(roles.map(i=>api(`/api/${i}/questions`)));
 questionRows=catalogs.flatMap((d,n)=>d.questions.map(q=>({...q,role:roles[n]})));questionGroups=groupQuestions(questionRows);
}
function bankRoleLabel(entries){return entries.length===Object.keys(boot.identities).length?'All roles':entries.map(x=>boot.identities[x.role]).join(', ');}
function bankScopeLabel(g){return g.entries.every(x=>x.sharing?.mode==='all')?'All roles':g.entries.length>1?`${g.entries.length} roles`:(boot.identities[g.entries[0].role]||'');}
function bankDraftKey(row){return row.role+':'+row.id;}
function stashQuestionEditor(){if(!questionActive)return;const form=$('#question-inline #question-editor');if(!form||!form.dataset.dirty)return;questionDrafts.set(questionActive,{values:[...new FormData(form)],confirmed:form.elements.confirmed.checked,version:Number(form.dataset.version)});}
async function questionBankView(){
 stashQuestionEditor();await loadQuestionBank();
 return `<section class="question-bank"><div class="bank-heading"><div><h1>Question bank</h1><p>Keep answers you can reuse across applications. Employer and vacancy questions appear in Applications.</p></div><div class="actions"><button id="review-next" class="primary">Review next</button><button id="new-question">+ Add question</button><details class="bank-more"><summary>More</summary><div><button id="import-simplify">Import from Simplify ↗</button><small>For ${esc(boot.identities[identity])}</small></div></details></div></div>
 <div class="bank-filters"><input id="bank-search" type="search" aria-label="Search question bank" placeholder="Search questions or answers" value="${esc(questionFilter.q)}"><select id="bank-role" aria-label="Show questions for role"><option value="all">All roles</option>${Object.entries(boot.identities).map(([id,name])=>`<option value="${id}" ${questionFilter.role===id?'selected':''}>${esc(name)}</option>`).join('')}</select><select id="bank-category" aria-label="Question category"><option value="all">All categories</option>${['contact','availability','work_authorisation','compensation','experience','education','motivation','sensitive','search_preferences','general'].map(x=>`<option value="${x}" ${questionFilter.category===x?'selected':''}>${esc(human(x))}</option>`).join('')}</select></div>
 <div id="bank-tabs" class="bank-tabs"></div><div id="bank-feedback" role="status" hidden></div>
 <div class="bank-bulk" id="bank-bulk" hidden><strong id="bank-selected-count"></strong><button id="bank-confirm" class="primary">Mark as reviewed</button><button id="bank-clear">Clear selection</button><small>Roles and reuse settings stay unchanged.</small></div>
 <div id="bank-results"></div><p class="bank-footnote">Open a row to edit its answer or choose its roles. Mark as reviewed means you have checked the answer for accuracy.</p></section>`;
}
function bankFiltered(){const groups=questionFilter.role==='all'?questionGroups:groupQuestions(questionRows.filter(x=>x.role===questionFilter.role));return groups.filter(g=>(questionFilter.category==='all'||g.category===questionFilter.category)&&(!questionFilter.q||[g.question,...g.entries.flatMap(x=>[x.value,boot.identities[x.role]])].join(' ').toLowerCase().includes(questionFilter.q.toLowerCase())));}
function drawBank(){
 if(!$('#bank-results'))return;stashQuestionEditor();questionActive=null;questionLoad++;if($('#bank-feedback')?.classList.contains('error'))$('#bank-feedback').hidden=true;
 const base=bankFiltered(),tabs=[['all','All questions',base.length],['attention','Needs attention',base.filter(questionNeedsReview).length],['ready','Ready to reuse',base.filter(g=>g.status==='ready').length],['different','Different answers',base.filter(g=>g.different).length]];
 $('#bank-tabs').innerHTML=tabs.map(([key,label,count])=>`<button data-bank-status="${key}" aria-pressed="${questionFilter.status===key}">${label} <b>${count}</b></button>`).join('');
 questionVisible=base.filter(g=>questionFilter.status==='all'||(questionFilter.status==='attention'?questionNeedsReview(g):g.status===questionFilter.status));
 // A filter cannot leave hidden answers selected for a bulk write.
 questionSelected=new Set([...questionSelected].filter(key=>questionVisible.some(g=>g.key===key&&g.selectable)));
 $('#bank-results').innerHTML=`<div class="bank-result-count">${questionVisible.length} of ${questionGroups.length} questions${questionDrafts.size?` · ${questionDrafts.size} unsaved draft${questionDrafts.size===1?'':'s'} kept in this tab`:''}</div>`+(questionVisible.length?`<div class="bank-table-wrap"><table class="bank-table"><thead><tr><th class="bank-check"><input id="bank-select-all" type="checkbox" aria-label="Select answers to review"></th><th>Question</th><th>Answer</th><th>Status / roles</th><th><span class="sr-only">Edit</span></th></tr></thead><tbody>${questionVisible.map(g=>{
 const draft=g.entries.some(x=>questionDrafts.has(bankDraftKey(x))),context=parse(g.entries[0].context,{}),contextText=Object.entries(context).map(([k,v])=>`${human(k)}: ${typeof v==='string'?v:JSON.stringify(v)}`).join(' · ');
 return `<tr data-bank-row="${g.key}"><td class="bank-check"><input type="checkbox" data-select-bank="${g.key}" aria-label="Select ${esc(g.question)}" ${questionSelected.has(g.key)?'checked':''} ${g.selectable?'':'disabled'} title="${g.selectable?'Select to mark this answer as reviewed':!questionNeedsReview(g)?'Already reviewed':'Open to review differences, expiry or missing information'}"></td><td class="bank-question"><button data-edit-bank="${g.key}" aria-expanded="false"><span class="bank-row-chevron" aria-hidden="true">›</span>${esc(g.question)}</button>${contextText?`<small>${esc(contextText)}</small>`:''}${draft?'<small class="bank-draft">Unsaved draft</small>':''}<small class="bank-mobile-meta">${esc(questionStatuses[g.status])} · ${esc(bankScopeLabel(g))}</small></td><td class="bank-answer">${g.different?g.entries.map(x=>`<div class="bank-variant"><small>${esc(boot.identities[x.role])}</small><span>${esc(x.value||'No answer yet')}</span></div>`).join(''):`<span>${esc(g.entries[0].answer_mode==='jd_choice'?g.entries[0].alternatives.join(' / '):g.value||'Add an answer')}</span>${g.entries[0].answer_mode==='jd_choice'?`<small>${g.entries[0].alternatives.length} options · choose one for each job</small>`:''}`}</td><td class="bank-state">${tag(questionStatuses[g.status],g.status==='ready'?'green':g.different?'purple':g.status==='application_review'?'':'amber')}<small title="${esc(bankRoleLabel(g.entries))}">${esc(bankScopeLabel(g))}</small>${g.entries.some(x=>x.reuse_scope==='application')&&g.status==='needs_review'?'<small>Review per application</small>':''}</td><td class="bank-action"><button data-edit-bank="${g.key}" aria-expanded="false" aria-label="Edit ${esc(g.question)}">${draft?'Continue':'Edit'}</button></td></tr>`;
 }).join('')}</tbody></table></div>`:empty('No questions match','Change the filters or add a question.'));
 document.querySelectorAll('[data-bank-status]').forEach(b=>b.onclick=()=>{questionFilter.status=b.dataset.bankStatus;drawBank()});
 document.querySelectorAll('[data-bank-row]').forEach(row=>row.onclick=e=>{
  // Selection and interactive controls are independent of the row disclosure.
  if(e.target.closest('.bank-check,input,select,textarea,label,a')||window.getSelection()?.toString())return;
  const control=e.target.closest('button');if(control&&!control.matches('[data-edit-bank]'))return;
  safe(()=>toggleBankQuestion(row.dataset.bankRow,control));
 });
 document.querySelectorAll('[data-select-bank]').forEach(b=>b.onchange=()=>{b.checked?questionSelected.add(b.dataset.selectBank):questionSelected.delete(b.dataset.selectBank);updateBankSelection()});
 if($('#bank-select-all'))$('#bank-select-all').onchange=e=>{questionVisible.filter(g=>g.selectable).forEach(g=>e.target.checked?questionSelected.add(g.key):questionSelected.delete(g.key));document.querySelectorAll('[data-select-bank]:not(:disabled)').forEach(x=>x.checked=e.target.checked);updateBankSelection()};
 updateBankSelection();$('#review-next').disabled=!questionVisible.some(questionNeedsReview);
}
function updateBankSelection(){const count=questionSelected.size;$('#bank-bulk').hidden=!count;$('#bank-selected-count').textContent=`${count} selected`;
 const eligible=questionVisible.filter(g=>g.selectable).length,all=$('#bank-select-all');if(all){all.checked=!!eligible&&count===eligible;all.indeterminate=count>0&&count<eligible;}
}
function closeBankQuestion(key,restoreFocus=false){
 stashQuestionEditor();questionActive=null;drawBank();
 if(restoreFocus)document.querySelector(`[data-bank-row="${key}"] .bank-question button`)?.focus();
}
function toggleBankQuestion(key,control){
 if($('#question-inline-row')?.previousElementSibling?.dataset.bankRow===key){closeBankQuestion(key,!!control);return;}
 return openBankQuestion(key);
}
function markExpandedBankRow(key){
 document.querySelectorAll('[data-bank-row]').forEach(row=>{
  const expanded=row.dataset.bankRow===key;row.classList.toggle('bank-row-open',expanded);
  row.querySelectorAll('[data-edit-bank]').forEach(button=>{button.setAttribute('aria-expanded',String(expanded));if(expanded)button.setAttribute('aria-controls','question-inline');else button.removeAttribute('aria-controls');});
  const action=row.querySelector('.bank-action button'),group=questionGroups.find(g=>g.key===row.dataset.bankRow);
  action.textContent=expanded?'Close':group?.entries.some(x=>questionDrafts.has(bankDraftKey(x)))?'Continue':'Edit';action.setAttribute('aria-label',(expanded?'Close editor for ':'Edit ')+group.question);
 });
}
async function openBankQuestion(key,role){
 stashQuestionEditor();const request=++questionLoad,g=questionGroups.find(x=>x.key===key);if(!g)return;
 const row=g.entries.find(x=>x.role===role)||g.entries.find(x=>x.role===questionFilter.role)||g.entries.find(x=>questionDrafts.has(bankDraftKey(x)))||g.entries.find(x=>['unanswered','needs_review','expired'].includes(x.status))||g.entries[0];
 $('#question-inline-row')?.remove();if($('#handoff').open)$('#handoff').close();$('#handoff-content').innerHTML='';
 const anchor=document.querySelector(`[data-bank-row="${key}"]`);if(!anchor)return;
 const tr=document.createElement('tr');tr.id='question-inline-row';tr.innerHTML=`<td colspan="5"><div id="question-inline" class="question-inline"><p>Loading answer…</p></div></td>`;anchor.after(tr);questionActive=bankDraftKey(row);markExpandedBankRow(key);
 const nextKeys=questionVisible.map(x=>x.key),nextIndex=nextKeys.indexOf(key);
 await editQuestion(row.id,{role:row.role,host:$('#question-inline'),group:g,request,draft:questionDrafts.get(questionActive),onSaved:async(result,next)=>{
  questionDrafts.delete(bankDraftKey(row));questionActive=null;questionSelected.delete(key);await loadQuestionBank();drawBank();
  if(next){const current=questionGroups.find(x=>x.key===key),other=current?.entries.find(x=>x.role!==row.role&&['unanswered','needs_review','expired'].includes(x.status));const nextKey=nextKeys.slice(nextIndex+1).concat(nextKeys.slice(0,nextIndex)).find(k=>questionVisible.some(x=>x.key===k&&questionNeedsReview(x)));if(other&&questionVisible.some(x=>x.key===key))await openBankQuestion(key,other.role);else if(nextKey)await openBankQuestion(nextKey);else toast(questionVisible.some(questionNeedsReview)?'Saved. Unconfirmed drafts still need your review.':'Saved. No more questions need attention in this view.');}
 }});
 if(request!==questionLoad)return;$('#question-inline')?.scrollIntoView({block:'nearest',behavior:'smooth'});
}
async function reviewBankSelection(){
 stashQuestionEditor();const button=$('#bank-confirm');if(button.disabled)return;button.disabled=true;const chosen=questionVisible.filter(g=>questionSelected.has(g.key)),items=[];
 try{
  for(const g of chosen){if(g.entries.some(x=>questionDrafts.has(bankDraftKey(x))))throw Error(`Save or discard your draft for “${g.question}” before marking it as reviewed.`);
   items.push({entries:g.entries.map(x=>({identity:x.role,id:x.id,version:x.version}))});
  }
  const result=await api('/api/question-bank/review',{items});questionSelected.clear();await loadQuestionBank();drawBank();
  const box=$('#bank-feedback');box.hidden=false;box.textContent=`${result.saved.length} question${result.saved.length===1?'':'s'} marked as reviewed. ${result.failed.length?result.failed.map(x=>x.error).join(' '):'Roles and reuse settings unchanged.'}`;box.className=result.failed.length?'bank-feedback error':'bank-feedback';
 }catch(e){const box=$('#bank-feedback');box.hidden=false;box.className='bank-feedback error';box.textContent=e.message;}finally{button.disabled=false;}
}
async function editQuestion(id,options={}){
 const i=options.role||identity,d=id?await api(`/api/${i}/questions/${id}`):{question:{question:'',value:'',reuse_scope:'application'},history:[],encounters:[],imports:[]};if(options.host?options.request!==questionLoad||!options.host.isConnected:i!==identity)return;const q=d.question;let share=d.sharing||{mode:'this',identities:[i]};

 const dateQuestion=['birthday','date of birth','dob'].includes(q.question.trim().toLowerCase());
 const validDate=!q.value||(/^\d{4}-\d{2}-\d{2}$/.test(q.value)&&!Number.isNaN(Date.parse(q.value))&&new Date(q.value).toISOString().slice(0,10)===q.value);
 const answerInput=dateQuestion&&validDate?`<input type="date" name="value" value="${esc(q.value)}">`:['contact','sensitive','availability'].includes(q.category)&&q.value.length<140&&!q.value.includes('\n')?`<input type="text" name="value" value="${esc(q.value)}">`:`<textarea name="value" rows="2">${esc(q.value)}</textarea>`;
 const host=options.host||$('#handoff-content');host.innerHTML=`
 <div class="answer-heading"><div class="eyebrow">${esc(boot.identities[i])} · Question bank</div><h1 id="answer-title">${id?esc(q.question):'Add an answer'}</h1>${options.group&&options.group.different?`<label class="bank-edit-role">Editing answer for <select id="bank-edit-role" aria-label="Edit answer for role">${options.group.entries.map(x=>`<option value="${x.role}" ${x.role===i?'selected':''}>${esc(boot.identities[x.role])}</option>`).join('')}</select></label>`:''}</div>
 <form id="question-editor" aria-labelledby="answer-title">
  <div class="answer-body">
   ${id?`<input type="hidden" name="question" value="${esc(q.question)}">`:`<label class="field answer-question">Question<input name="question" value="${esc(q.question)}" required placeholder="For example: Notice period"></label>`}
   ${!q.category||['experience','general','motivation'].includes(q.category)?`<label class="answer-format">Answer format <select name="answer_mode" aria-label="Answer format"><option value="single" ${q.answer_mode!=='jd_choice'?'selected':''}>One answer</option><option value="jd_choice" ${q.answer_mode==='jd_choice'?'selected':''}>Choose one based on the job</option></select></label>`:'<input type="hidden" name="answer_mode" value="single">'}
   <label class="field answer-value"><span id="answer-value-label">Answer</span>${answerInput}</label><p id="answer-format-help" class="answer-hint" hidden></p>
   ${q.review_note?`<div class="banner">${esc(q.review_note)}</div>`:''}<div id="address-parts" class="banner info" hidden></div>
   <div class="answer-settings">
    <div><label class="field">Save this answer for<select name="availability" aria-label="Save this answer for"><option value="all" ${share.mode==='all'?'selected':''}>All roles</option>${Object.entries(boot.identities).map(([key,label])=>`<option value="role:${key}" ${share.mode==='this'&&key===i?'selected':''}>${esc(label)}</option>`).join('')}<option value="selected" ${share.mode==='selected'?'selected':''}>Choose multiple roles…</option></select></label>
     <div id="answer-identities">${Object.entries(boot.identities).map(([key,label])=>`<label class="checkbox"><input type="checkbox" name="identities" value="${key}" ${share.identities.includes(key)?'checked':''}> ${esc(label)}</label>`).join('')}</div><p id="availability-explanation" class="answer-hint"></p>
    </div>
    <div><label class="field">Reuse<select name="reuse_scope" aria-label="How should this answer be used?"><option value="identity" ${q.reuse_scope==='identity'?'selected':''}>Confirm once, reuse automatically</option><option value="application" ${q.reuse_scope==='application'?'selected':''}>Ask me to review every application</option></select></label><p id="reuse-explanation" class="answer-hint"></p></div>
   </div>
   <div id="sharing-conflicts" hidden></div>
   <details class="answer-more"><summary>${q.expires_at?'Review by '+date(q.expires_at)+' · details':'Review date, history & details'}</summary><div class="answer-more-content">${q.value?'<button type="button" id="copy-answer-clipboard">Copy to clipboard</button>':''}
    ${q.source_url?`<p><a href="${esc(q.source_url)}" target="_blank" rel="noopener">Open answer source ↗</a></p>`:''}<label class="field answer-review-date">Review by (optional)<input type="date" name="expires_at" value="${esc(q.expires_at||'')}"></label>
    <p class="answer-hint">Reuse fills matching questions with your confirmed answer. Each application still requires approval. Editing the bank keeps previously used application versions fixed.</p>
    ${d.imports.length?`<details><summary>Imported values & source</summary>${d.imports.map(x=>`<p>${esc(x.value)}</p><p class="sub">${esc(x.provenance)}</p>`).join('')}</details>`:''}
    ${d.encounters.length?`<details><summary>Where this question appeared</summary>${d.encounters.map(x=>`<p>${esc(x.company)} · ${esc(x.title)}<br>${esc(x.question)} · ${x.required?'Required':'Optional'}</p>`).join('')}</details>`:''}
    ${d.history.length?`<details><summary>Answer history · ${d.history.length} versions</summary>${d.history.map(x=>`<p><strong>Version ${x.version} · ${x.confirmed?'Confirmed':'Draft/import'}</strong> · ${date(x.created_at)}</p><p>${esc(x.value)}</p>`).join('')}</details>`:''}
   </div></details>
  </div>
  <div class="answer-footer">
   <div id="question-save-error" class="banner" role="alert" hidden></div>
   <div class="answer-footer-row"><label class="checkbox"><input name="confirmed" type="checkbox" ${q.confirmed&&!q.review_note&&(!q.expires_at||q.expires_at>=new Date().toISOString().slice(0,10))?'checked':''}> <span id="answer-confirm-label">I confirm this answer is accurate</span></label><div class="answer-save-actions">${options.host?'<button type="button" id="bank-discard-draft" hidden>Discard draft</button><button type="button" id="bank-close-editor">Close</button><button id="save-question">Save</button><button id="save-next-question" class="primary" value="next">Save & next</button>':'<button id="save-question" class="primary">Save answer</button>'}</div></div>
  </div>
 </form>`;
 const editor=$('#question-editor'),reuseHelp=$('#reuse-explanation');editor.dataset.version=q.version||0;
 if(options.draft){for(const [name,value] of options.draft.values){const el=editor.elements[name];if(el&&name!=='identities'&&name!=='confirmed')el.value=value;}editor.elements.confirmed.checked=options.draft.confirmed;editor.querySelectorAll('[name="identities"]').forEach(el=>el.checked=options.draft.values.some(([name,value])=>name==='identities'&&value===el.value));editor.dataset.dirty='true';editor.dataset.version=options.draft.version;}
 const markDirty=()=>{editor.dataset.dirty='true';if($('#bank-discard-draft'))$('#bank-discard-draft').hidden=false;};editor.addEventListener('input',markDirty);editor.addEventListener('change',markDirty);
 if(options.host){$('#bank-discard-draft').hidden=!options.draft;$('#bank-discard-draft').onclick=()=>{delete editor.dataset.dirty;questionDrafts.delete(questionActive);questionActive=null;drawBank()};$('#bank-close-editor').onclick=()=>closeBankQuestion(options.group.key,true);if($('#bank-edit-role'))$('#bank-edit-role').onchange=e=>safe(()=>openBankQuestion(options.group.key,e.target.value));}

 const fitAnswer=()=>{const input=editor.elements.value;if(input.tagName==='TEXTAREA'){input.style.height='auto';input.style.height=Math.min(144,Math.max(66,input.scrollHeight))+'px';}};
 if($('#copy-answer-clipboard'))$('#copy-answer-clipboard').onclick=()=>safe(async()=>{await navigator.clipboard.writeText(editor.elements.value.value);toast('Answer copied to clipboard. Paste it where you need it.');});
 let policy=q.reuse_policy||{automatic_allowed:true,default_scope:'application',reason:''},reuseChosen=false,policyRequest=0,policyTimer;
 const explainReuse=()=>{reuseHelp.textContent=(editor.elements.answer_mode.value==='jd_choice'?(editor.elements.reuse_scope.value==='identity'?'Choose from your approved options; show the choice in application review.':'Suggest one option; ask you to review it for each application.'):policy.reason)||(editor.elements.reuse_scope.value==='identity'?'Confirm once below. Reuse for matching questions.':policy.personal_disclosure?'Personal disclosure: review each time, or choose automatic reuse.':'Keep a reference answer; confirm it for each application.');};
 const applyPolicy=()=>{const select=editor.elements.reuse_scope;select.options[0].disabled=!policy.automatic_allowed;if(!policy.automatic_allowed)select.value='application';else if(!id&&!reuseChosen)select.value=policy.default_scope;explainReuse();};
 const refreshPolicy=async()=>{if(id)return;const request=++policyRequest,result=await api(`/api/${i}/question-policy`,{question:editor.elements.question.value});if(request!==policyRequest||!editor.isConnected)return;policy=result;applyPolicy();};
 const explainFormat=()=>{const alternative=editor.elements.answer_mode.value==='jd_choice';$('#answer-value-label').textContent=alternative?'Alternatives · one per line':'Answer';$('#answer-format-help').hidden=!alternative;$('#answer-format-help').textContent='The agent selects one option using the JD and records why. All options must be accurate; official employment titles stay as recorded in your master profile.';$('#answer-confirm-label').textContent=alternative?'These alternatives are accurate; choose one for each job':'I confirm this answer is accurate';explainReuse();fitAnswer();};
 editor.elements.answer_mode.onchange=()=>{editor.elements.confirmed.checked=false;explainFormat();};explainFormat();
 editor.elements.reuse_scope.onchange=()=>{reuseChosen=true;explainReuse();};applyPolicy();
 const explainAvailability=()=>{$('#answer-identities').hidden=editor.elements.availability.value!=='selected';$('#availability-explanation').textContent=editor.elements.availability.value==='all'?'Includes roles you add later.':editor.elements.availability.value==='selected'?'Choose the roles to update. Other saved versions stay unchanged.':'Updates this role’s answer. Other saved versions stay unchanged.';};
 editor.elements.availability.onchange=()=>{explainAvailability();$('#sharing-conflicts').hidden=true;};explainAvailability();
 let conflictSignature=null;

 let addressRequest=0,addressTimer;
 const previewAddress=async()=>{const request=++addressRequest,box=$('#address-parts'),label=editor.elements.question.value.trim().toLowerCase();
  if(!['address','full address','home address','residential address','current address'].includes(label)){box.hidden=true;return;}
  const result=await api(`/api/${i}/address-preview`,{value:editor.elements.value.value});if(request!==addressRequest||!editor.isConnected)return;
  const parts=Object.entries(result.parts);box.hidden=false;
  box.innerHTML=parts.length?'<strong>From this address</strong><p>'+parts.map(([k,v])=>esc(k==='Province'?'State / province':k)+': <strong>'+esc(v)+'</strong>').join(' · ')+'</p><p>Saved with this address. Separately entered differences stay for review.</p>':'Use “Street, City, State – 123456” to extract city, state and PIN. Missing parts stay blank.';
 };
 const scheduleAddress=()=>{clearTimeout(addressTimer);addressRequest++;addressTimer=setTimeout(()=>safe(previewAddress),350);};
 editor.elements.value.oninput=()=>{editor.elements.confirmed.checked=false;fitAnswer();scheduleAddress();};editor.elements.question.oninput=()=>{editor.elements.confirmed.checked=false;scheduleAddress();clearTimeout(policyTimer);policyRequest++;policyTimer=setTimeout(()=>safe(refreshPolicy),250);};await previewAddress();
 if(options.host&&(options.request!==questionLoad||!host.isConnected))return;if(!options.host&&!$('#handoff').open)$('#handoff').showModal();fitAnswer();editor.onsubmit=async e=>{e.preventDefault();const button=$('#save-question'),error=$('#question-save-error');if(button.disabled)return;const next=e.submitter?.value==='next',originalLabel=button.textContent;button.disabled=true;if($('#save-next-question'))$('#save-next-question').disabled=true;button.textContent='Saving…';error.hidden=true;try{clearTimeout(policyTimer);await refreshPolicy();const f=Object.fromEntries(new FormData(e.target));f.confirmed=f.confirmed==='on';if(id){f.id=id;f.expected_version=Number(editor.dataset.version);}f.identities=f.availability==='selected'?Array.from(editor.querySelectorAll('[name="identities"]:checked')).map(x=>x.value):f.availability.startsWith('role:')?[f.availability.slice(5)]:Object.keys(boot.identities);if(f.availability.startsWith('role:'))f.availability=f.identities[0]===i?'this':'selected';if(!f.identities.length)throw Error('Choose at least one role for this answer.');
 const plan=await api(`/api/${i}/sharing-preview`,f);f.target_versions=Object.fromEntries(plan.targets.map(x=>[x.identity,x.version]));
 const conflicts=plan.targets.filter(x=>x.conflict),signature=JSON.stringify([f.value,f.answer_mode,f.availability,plan.targets]);
 if(conflicts.length&&(signature!==conflictSignature||!$('#replace-shared-answer')?.checked)){
  conflictSignature=signature;const box=$('#sharing-conflicts');box.hidden=false;box.innerHTML='<div class="banner"><strong>Different answers are already saved</strong>'+conflicts.map(x=>'<p><strong>'+esc(boot.identities[x.identity])+'</strong><br>'+esc(x.value)+'</p>').join('')+'<label class="checkbox"><input id="replace-shared-answer" type="checkbox"> Replace these saved answers with the answer above</label><p>Review the difference, then save again. Existing application versions remain unchanged.</p></div>';box.scrollIntoView({block:'nearest'});return;
 }
 f.replace_conflicts=conflicts.length>0;const result=await api(`/api/${i}/question`,f);delete editor.dataset.dirty;if(!options.host)$('#handoff').close();toast('Saved in '+result.saved_in.map(x=>boot.identities[x]).join(' and ')+(result.confirmed?(result.reuse_scope==='identity'?(f.answer_mode==='jd_choice'?' · One option will be chosen for each job.':' · Automatic reuse on.'):' · Review for each application.'):' · Draft; confirmation needed.'));if(options.onSaved)await options.onSaved(result,next);else await render();
 }catch(e){error.textContent=e.message;error.hidden=false;error.scrollIntoView({block:'nearest'});}finally{button.disabled=false;button.textContent=originalLabel;if($('#save-next-question'))$('#save-next-question').disabled=false;}};
}
async function showBatchPrompt(){const i=identity,d=await api(`/api/${i}/batch-prompt`);if(i!==identity)return;$('#handoff-content').innerHTML=`<div class="eyebrow">${esc(boot.identities[i])}</div><h1>Continue queued work in one Codex session</h1><p>Copy these instructions into Codex. Each task keeps its own role, approval and checkpoint. Tasks are waiting until the agent claims them.</p><textarea id="batch-prompt" class="prompt-box" readonly>${esc(d.prompt)}</textarea><button class="primary" id="copy-batch">Copy queued instructions</button>`;$('#handoff').showModal();$('#copy-batch').onclick=()=>safe(async()=>{await navigator.clipboard.writeText(d.prompt);toast('Copied. Paste into Codex to start queued work.')});}
function bindQuestions(){
 const on=(sel,event,fn)=>{if($(sel))$(sel)[event]=fn};
 if($('#bank-results')){
  $('#identity-badge').textContent='Question bank · All role profiles';drawBank();
  on('#bank-search','oninput',e=>{questionFilter.q=e.target.value;drawBank()});on('#bank-role','onchange',e=>{questionSelected.clear();questionFilter.role=e.target.value;drawBank()});on('#bank-category','onchange',e=>{questionFilter.category=e.target.value;drawBank()});
  on('#review-next','onclick',()=>safe(()=>openBankQuestion(questionVisible.find(questionNeedsReview)?.key)));
  on('#bank-confirm','onclick',()=>safe(reviewBankSelection));on('#bank-clear','onclick',()=>{questionSelected.clear();drawBank()});
 }
 on('#new-question','onclick',()=>safe(()=>{stashQuestionEditor();questionActive=null;$('#question-inline-row')?.remove();return editQuestion(null)}));
 on('#import-simplify','onclick',()=>safe(async()=>launchDesktop((await api(`/api/${identity}/task`,{kind:'import_answers'})).id)));
 on('#batch-desktop','onclick',()=>safe(showBatchPrompt));on('#prepare-batch','onclick',()=>safe(async()=>{const result=await api(`/api/${identity}/prepare-batch`,{});if(!result.tasks.length)return toast('No unprepared shortlisted applications are waiting.');await showBatchPrompt()}));
}
window.addEventListener('beforeunload',e=>{stashQuestionEditor();if(questionDrafts.size){e.preventDefault();e.returnValue='';}});
