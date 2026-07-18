(() => {
  const form = document.querySelector('.editor-layout');
  if (!form) return;
  const key = `yonaguni-draft:${location.pathname}`;
  const savable = field => field.name && field.name !== 'csrf_token' && field.type !== 'file' && !field.matches('button');
  const capture = () => Array.from(form.elements).filter(savable).map(field => ({
    name: field.name,
    type: field.type,
    value: field.value,
    checked: Boolean(field.checked),
  }));
  const restore = savedFields => {
    const sourceSectionCount = savedFields.filter(item => item.name === 'source_section_indices').length;
    const addSourceSection = document.querySelector('[data-add-source-section]');
    while (addSourceSection && form.querySelectorAll('input[name="source_section_indices"]').length < sourceSectionCount) addSourceSection.click();
    const savedSectionIndices = savedFields.filter(item => item.name === 'source_section_indices').map(item => item.value);
    savedSectionIndices.forEach(sectionIndex => {
      const section = Array.from(form.querySelectorAll('[data-source-section]')).find(item => item.querySelector('input[name="source_section_indices"]')?.value === sectionIndex);
      if (!section) return;
      [['meaning', '[data-add-section-meaning]'], ['example', '[data-add-section-example]'], ['conjugation', '[data-add-section-conjugation]']].forEach(([type, selector]) => {
        const name = `source_section_${sectionIndex}_${type}_indices`;
        const count = savedFields.filter(item => item.name === name).length;
        const button = section.querySelector(selector);
        while (button && section.querySelectorAll(`input[name="${name}"]`).length < count) button.click();
      });
    });
    const dynamicGroups = [
      ['example_indices', '[data-add-example]'],
      ['meaning_indices', '[data-add-meaning]'],
      ['conjugation_indices', '[data-add-conjugation]'],
    ];
    dynamicGroups.forEach(([name, selector]) => {
      const count = savedFields.filter(item => item.name === name).length;
      const button = document.querySelector(selector);
      while (button && form.querySelectorAll(`input[name="${name}"]`).length < count) button.click();
    });
    const positions = new Map();
    savedFields.forEach(item => {
      const fields = Array.from(form.elements).filter(field => field.name === item.name);
      const position = positions.get(item.name) || 0;
      const field = fields[position];
      positions.set(item.name, position + 1);
      if (!field) return;
      if (field.type === 'checkbox' || field.type === 'radio') field.checked = item.checked;
      else field.value = item.value;
    });
    document.dispatchEvent(new CustomEvent('examples:restored'));
    document.dispatchEvent(new CustomEvent('structured-fields:restored'));
  };
  try {
    const saved = JSON.parse(localStorage.getItem(key) || 'null');
    if (saved && confirm('この端末に保存された入力途中の内容があります。復元しますか？')) {
      if (Array.isArray(saved.fields)) restore(saved.fields);
      else Object.entries(saved).forEach(([name, value]) => {
        const field = form.elements.namedItem(name); if (field && 'value' in field) field.value = value;
      });
    }
  } catch (_) { localStorage.removeItem(key); }
  let timer;
  const save = () => {
    clearTimeout(timer);
    timer = setTimeout(() => localStorage.setItem(key, JSON.stringify({version: 2, fields: capture()})), 350);
  };
  form.addEventListener('input', save);
  form.addEventListener('change', save);
  form.addEventListener('submit', () => localStorage.removeItem(key));
})();
