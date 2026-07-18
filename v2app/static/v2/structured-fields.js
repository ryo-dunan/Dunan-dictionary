(() => {
  const setupMeanings = () => {
    const list = document.querySelector('[data-meaning-list]'); const add = document.querySelector('[data-add-meaning]');
    if (!list || !add) return;
    const empty = document.querySelector('[data-empty-meanings]');
    let next = Array.from(list.querySelectorAll('input[name="meaning_indices"]')).reduce((max, input) => Math.max(max, Number(input.value) || 0), -1) + 1;
    const renumber = () => { const visible = Array.from(list.querySelectorAll('[data-meaning-card]')).filter(card => card.querySelector('[data-meaning-remove-field]').value !== '1'); visible.forEach((card, i) => card.querySelector('[data-meaning-number]').textContent = String(i + 1)); if (empty) empty.hidden = visible.length > 0; };
    add.addEventListener('click', () => { const index = next++; const card = document.createElement('article'); card.className='meaning-editor'; card.dataset.meaningCard=''; card.innerHTML=`<input type="hidden" name="meaning_indices" value="${index}"><input type="hidden" name="meaning_${index}_remove" value="0" data-meaning-remove-field><div class="compact-row-heading"><h3>意味 <span data-meaning-number></span></h3><button type="button" class="remove-example" data-remove-meaning>この意味を削除</button></div><label>日本語の意味<textarea name="meaning_${index}_ja" rows="2"></textarea></label><div class="field-grid"><label>英語訳<textarea name="meaning_${index}_en" rows="2"></textarea></label><label>中国語訳（繁体字）<textarea name="meaning_${index}_zh_tw" rows="2"></textarea></label></div>`; list.appendChild(card); renumber(); card.querySelector('textarea').focus(); });
    list.addEventListener('click', event => { const button=event.target.closest('[data-remove-meaning]'); if(!button)return; const card=button.closest('[data-meaning-card]'); if(Array.from(card.querySelectorAll('textarea')).some(input=>input.value.trim())&&!confirm('この意味と翻訳を削除しますか？'))return; card.querySelector('[data-meaning-remove-field]').value='1'; card.hidden=true; renumber(); });
    document.addEventListener('structured-fields:restored',()=>{list.querySelectorAll('[data-meaning-card]').forEach(card=>card.hidden=card.querySelector('[data-meaning-remove-field]').value==='1');renumber();}); renumber();
  };
  const setupConjugations = () => {
    const list=document.querySelector('[data-conjugation-list]'); const add=document.querySelector('[data-add-conjugation]'); const options=document.querySelector('[data-conjugation-options]');
    if(!list||!add||!options)return; const empty=document.querySelector('[data-empty-conjugations]'); let next=Array.from(list.querySelectorAll('input[name="conjugation_indices"]')).reduce((max,input)=>Math.max(max,Number(input.value)||0),-1)+1;
    const refresh=()=>{const visible=Array.from(list.querySelectorAll('[data-conjugation-card]')).filter(card=>card.querySelector('[data-conjugation-remove-field]').value!=='1');if(empty)empty.hidden=visible.length>0;};
    add.addEventListener('click',()=>{const index=next++;const row=document.createElement('tr');row.dataset.conjugationCard='';row.innerHTML=`<td><input type="hidden" name="conjugation_indices" value="${index}"><input type="hidden" name="conjugation_${index}_remove" value="0" data-conjugation-remove-field><select aria-label="活用形の種類" name="conjugation_${index}_name">${options.innerHTML}</select></td><td><input aria-label="語形" name="conjugation_${index}_form"></td><td><button type="button" class="compact-remove" data-remove-conjugation>削除</button></td>`;list.appendChild(row);refresh();row.querySelector('select').focus();});
    list.addEventListener('click',event=>{const button=event.target.closest('[data-remove-conjugation]');if(!button)return;const row=button.closest('[data-conjugation-card]');row.querySelector('[data-conjugation-remove-field]').value='1';row.hidden=true;refresh();});
    document.addEventListener('structured-fields:restored',()=>{list.querySelectorAll('[data-conjugation-card]').forEach(row=>row.hidden=row.querySelector('[data-conjugation-remove-field]').value==='1');refresh();});refresh();
  };
  setupMeanings(); setupConjugations();
})();
