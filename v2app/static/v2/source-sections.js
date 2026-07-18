(() => {
  const list = document.querySelector('[data-source-section-list]');
  const addSection = document.querySelector('[data-add-source-section]');
  const template = document.querySelector('#source-section-template');
  if (!list || !addSection || !template) return;

  const sectionIndex = section => section.querySelector('input[name="source_section_indices"]').value;
  const root = section => `source_section_${sectionIndex(section)}_`;
  const nextIndex = (section, type) => Array.from(section.querySelectorAll(`input[name="${root(section)}${type}_indices"]`))
    .reduce((maximum, input) => Math.max(maximum, Number(input.value) || 0), -1) + 1;
  const renumber = (container, selector) => {
    Array.from(container.querySelectorAll(selector)).filter(item => {
      const removed = item.querySelector('[data-item-remove]');
      return !removed || removed.value !== '1';
    }).forEach((item, index) => {
      const number = item.querySelector('[data-item-number]');
      if (number) number.textContent = String(index + 1);
    });
  };
  const refresh = section => {
    const meaningList = section.querySelector('[data-section-meaning-list]');
    const exampleList = section.querySelector('[data-section-example-list]');
    if (meaningList) renumber(meaningList, '[data-section-meaning]');
    if (exampleList) renumber(exampleList, '[data-section-example]');
  };

  let nextSection = Array.from(list.querySelectorAll('input[name="source_section_indices"]'))
    .reduce((maximum, input) => Math.max(maximum, Number(input.value) || 0), -1) + 1;

  const addMeaning = section => {
    const index = nextIndex(section, 'meaning'); const prefix = `${root(section)}meaning_${index}_`;
    const card = document.createElement('article'); card.className = 'meaning-editor'; card.dataset.sectionMeaning = '';
    card.innerHTML = `<input type="hidden" name="${root(section)}meaning_indices" value="${index}"><input type="hidden" name="${prefix}remove" value="0" data-item-remove><div class="compact-row-heading"><h3>意味 <span data-item-number></span></h3><button type="button" class="remove-example" data-remove-section-item>この意味を削除</button></div><label>日本語の意味<textarea name="${prefix}ja" rows="2"></textarea></label><div class="field-grid"><label>英語訳<textarea name="${prefix}en" rows="2"></textarea></label><label>中国語訳（繁体字）<textarea name="${prefix}zh_tw" rows="2"></textarea></label></div>`;
    section.querySelector('[data-section-meaning-list]').appendChild(card); refresh(section); card.querySelector('textarea').focus();
  };
  const addExample = section => {
    const index = nextIndex(section, 'example'); const prefix = `${root(section)}example_${index}_`;
    const card = document.createElement('article'); card.className = 'example-editor'; card.dataset.sectionExample = '';
    card.innerHTML = `<input type="hidden" name="${root(section)}example_indices" value="${index}"><input type="hidden" name="${prefix}remove" value="0" data-item-remove><div class="example-editor-heading"><h3>例文 <span data-item-number></span></h3><button type="button" class="remove-example" data-remove-section-item>この例文を削除</button></div><label>原文（与那国語）<textarea name="${prefix}yonaguni" rows="3"></textarea></label><div class="example-translation-grid"><label>逐語訳（日本語）<textarea name="${prefix}ja_word_by_word" rows="3"></textarea></label><label>意訳（日本語）<textarea name="${prefix}ja_free_translation" rows="3"></textarea></label><label>英語訳<textarea name="${prefix}en_free_translation" rows="3"></textarea></label><label>中国語訳（繁体字）<textarea name="${prefix}zh_tw_free_translation" rows="3"></textarea></label></div>`;
    section.querySelector('[data-section-example-list]').appendChild(card); refresh(section); card.querySelector('textarea').focus();
  };
  const addConjugation = section => {
    const index = nextIndex(section, 'conjugation'); const prefix = `${root(section)}conjugation_${index}_`;
    const options = document.querySelector('[data-conjugation-options]');
    const row = document.createElement('tr'); row.dataset.sectionConjugation = '';
    row.innerHTML = `<td><input type="hidden" name="${root(section)}conjugation_indices" value="${index}"><input type="hidden" name="${prefix}remove" value="0" data-item-remove><select aria-label="活用形の種類" name="${prefix}name">${options ? options.innerHTML : '<option value="">選択</option>'}</select></td><td><input aria-label="語形" name="${prefix}form"></td><td><button type="button" class="compact-remove" data-remove-section-item>削除</button></td>`;
    section.querySelector('[data-section-conjugation-list]').appendChild(row); row.querySelector('select').focus();
  };

  addSection.addEventListener('click', () => {
    const wrapper = document.createElement('div');
    wrapper.innerHTML = template.innerHTML.replaceAll('__SECTION__', String(nextSection++));
    const section = wrapper.firstElementChild;
    const oldConjugationList = section.querySelector('[data-section-conjugation-list]');
    if (oldConjugationList && oldConjugationList.tagName !== 'TBODY') {
      const tableWrap = document.createElement('div'); tableWrap.className = 'conjugation-table-wrap';
      tableWrap.innerHTML = '<table class="conjugation-editor-table"><thead><tr><th>活用形の種類</th><th>語形</th><th><span class="sr-only">操作</span></th></tr></thead><tbody data-section-conjugation-list></tbody></table>';
      oldConjugationList.replaceWith(tableWrap);
    }
    const conjugationHeading = section.querySelector('[data-add-section-conjugation]')?.closest('.compact-title')?.querySelector('h3');
    if (conjugationHeading) conjugationHeading.textContent = '活用表';
    const noteField = section.querySelector(`[name="${root(section)}note"]`);
    if (noteField?.closest('label')?.firstChild) noteField.closest('label').firstChild.textContent = '自由記述';
    list.appendChild(section); addMeaning(section);
    section.querySelector('select').focus(); section.scrollIntoView({behavior: 'smooth', block: 'start'});
  });
  list.addEventListener('click', event => {
    const section = event.target.closest('[data-source-section]'); if (!section) return;
    if (event.target.closest('[data-add-section-meaning]')) return addMeaning(section);
    if (event.target.closest('[data-add-section-example]')) return addExample(section);
    if (event.target.closest('[data-add-section-conjugation]')) return addConjugation(section);
    const removeItem = event.target.closest('[data-remove-section-item]');
    if (removeItem) {
      const item = removeItem.closest('[data-section-meaning],[data-section-example],[data-section-conjugation]');
      if (Array.from(item.querySelectorAll('input,textarea')).some(input => input.type !== 'hidden' && input.value.trim()) && !confirm('この内容を取り除きますか？')) return;
      item.querySelector('[data-item-remove]').value = '1'; item.hidden = true; refresh(section); return;
    }
    if (event.target.closest('[data-remove-source-section]')) {
      if (!confirm('この辞典に属する意味・例文・補足情報をまとめて取り除きますか？')) return;
      section.querySelector('[data-source-section-remove]').value = '1'; section.hidden = true;
    }
  });
  document.addEventListener('structured-fields:restored', () => list.querySelectorAll('[data-source-section]').forEach(section => {
    section.hidden = section.querySelector('[data-source-section-remove]').value === '1'; refresh(section);
  }));
  list.querySelectorAll('[data-source-section]').forEach(refresh);
})();
