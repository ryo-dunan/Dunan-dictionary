(() => {
  const list = document.querySelector('[data-example-list]');
  const addButton = document.querySelector('[data-add-example]');
  if (!list || !addButton) return;
  const empty = document.querySelector('[data-empty-examples]');
  let nextIndex = Array.from(list.querySelectorAll('input[name="example_indices"]')).reduce((max, field) => Math.max(max, Number(field.value) || 0), -1) + 1;
  const renumber = () => {
    const visible = Array.from(list.querySelectorAll('[data-example-card]')).filter(card => card.querySelector('[data-remove-field]').value !== '1');
    visible.forEach((card, index) => { card.querySelector('[data-example-number]').textContent = String(index + 1); });
    if (empty) empty.hidden = visible.length !== 0;
  };
  const field = (index, suffix, label, placeholder = '') => `<label>${label}<textarea name="example_${index}_${suffix}" rows="3" placeholder="${placeholder}"></textarea></label>`;
  addButton.addEventListener('click', () => {
    const index = nextIndex++;
    const card = document.createElement('article');
    card.className = 'example-editor'; card.dataset.exampleCard = '';
    card.innerHTML = `<input type="hidden" name="example_indices" value="${index}"><input type="hidden" name="example_${index}_id" value=""><input type="hidden" name="example_${index}_remove" value="0" data-remove-field><div class="example-editor-heading"><h3>例文 <span data-example-number></span></h3><button type="button" class="remove-example" data-remove-example>この例文を削除</button></div>${field(index, 'yonaguni', '原文（与那国語）', '例文の原文を入力')}<div class="example-translation-grid">${field(index, 'ja_word_by_word', '逐語訳（日本語）', '語ごとの対応が分かる訳')}${field(index, 'ja_free_translation', '意訳（日本語）', '自然な日本語訳')}${field(index, 'en_free_translation', '英語訳')}${field(index, 'zh_tw_free_translation', '中国語訳（繁体字）')}</div><input type="hidden" name="example_${index}_en_word_by_word" value=""><input type="hidden" name="example_${index}_zh_tw_word_by_word" value="">`;
    list.appendChild(card); renumber(); card.querySelector('textarea').focus();
  });
  list.addEventListener('click', event => {
    const button = event.target.closest('[data-remove-example]'); if (!button) return;
    const card = button.closest('[data-example-card]');
    const hasContent = Array.from(card.querySelectorAll('textarea')).some(input => input.value.trim());
    if (hasContent && !window.confirm('この例文と翻訳を削除しますか？')) return;
    card.querySelector('[data-remove-field]').value = '1'; card.hidden = true; renumber();
  });
  document.addEventListener('examples:restored', () => {
    list.querySelectorAll('[data-example-card]').forEach(card => {
      card.hidden = card.querySelector('[data-remove-field]').value === '1';
    });
    renumber();
  });
  renumber();
})();
