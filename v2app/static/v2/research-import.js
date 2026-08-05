document.addEventListener("DOMContentLoaded", () => {
  const form = document.querySelector("[data-manual-search-url]");
  if (!form) return;

  const searchUrl = form.dataset.manualSearchUrl;

  const resultLine = (text, className = "") => {
    const line = document.createElement("p");
    line.className = className;
    line.textContent = text;
    return line;
  };

  const chooseTarget = (index, item, resultBox) => {
    const select = form.querySelector(`[data-target-select="${index}"]`);
    const selectLabel = form.querySelector(`[data-target-label="${index}"]`);
    const mergeRadio = form.querySelector(`[data-merge-radio="${index}"]`);
    const mergeLabel = form.querySelector(`[data-merge-label="${index}"]`);
    if (!select || !selectLabel || !mergeRadio) return;

    let option = Array.from(select.options).find((candidate) => candidate.value === String(item.id));
    if (!option) {
      option = document.createElement("option");
      option.value = item.id;
      select.append(option);
    }
    option.disabled = false;
    option.textContent = `${item.headword}${item.kana ? `（${item.kana}）` : ""} — 手動検索で選択`;
    select.value = String(item.id);
    selectLabel.classList.remove("is-hidden");
    mergeRadio.disabled = false;
    mergeRadio.checked = true;
    mergeLabel?.classList.remove("unavailable");
    resultBox.replaceChildren(resultLine(`「${item.headword}」を追加先に選びました。`, "manual-target-chosen"));
  };

  const renderResults = (index, results, resultBox) => {
    resultBox.replaceChildren();
    if (!results.length) {
      resultBox.append(resultLine("該当する見出し語がありません。表記や意味を変えて検索してください。", "muted"));
      return;
    }
    const list = document.createElement("div");
    list.className = "manual-target-list";
    results.forEach((item) => {
      const card = document.createElement("article");
      card.className = "manual-target-item";
      const body = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = item.headword;
      body.append(title);
      if (item.kana) body.append(resultLine(item.kana, "manual-target-kana"));
      if (item.meanings?.length) body.append(resultLine(item.meanings.join("／"), "manual-target-meanings"));
      body.append(resultLine(
        `${item.pos || "品詞未確認"}・${item.matched_fields.join("・")}で一致・${item.publication_status === "published" ? "公開中" : "非公開"}`,
        "manual-target-meta",
      ));
      const button = document.createElement("button");
      button.type = "button";
      button.className = "quiet";
      button.textContent = item.merge_blocked ? "作業中のため選択不可" : "この語へ追加";
      button.disabled = item.merge_blocked;
      button.addEventListener("click", () => chooseTarget(index, item, resultBox));
      card.append(body, button);
      list.append(card);
    });
    resultBox.append(list);
  };

  const runSearch = async (index) => {
    const input = form.querySelector(`[data-manual-query="${index}"]`);
    const button = form.querySelector(`[data-manual-search="${index}"]`);
    const resultBox = form.querySelector(`[data-manual-results="${index}"]`);
    const query = input?.value.trim() || "";
    if (!query) {
      resultBox.replaceChildren(resultLine("検索する見出し語・意味を入力してください。", "muted"));
      input?.focus();
      return;
    }
    button.disabled = true;
    resultBox.replaceChildren(resultLine("辞書内を検索しています…", "muted"));
    try {
      const response = await fetch(`${searchUrl}?q=${encodeURIComponent(query)}`, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) throw new Error("search failed");
      const payload = await response.json();
      renderResults(index, payload.results || [], resultBox);
    } catch (_error) {
      resultBox.replaceChildren(resultLine("検索できませんでした。少し待ってから、もう一度お試しください。", "manual-target-error"));
    } finally {
      button.disabled = false;
    }
  };

  form.querySelectorAll("[data-manual-search]").forEach((button) => {
    const index = button.dataset.manualSearch;
    button.addEventListener("click", () => runSearch(index));
    form.querySelector(`[data-manual-query="${index}"]`)?.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        runSearch(index);
      }
    });
  });
});
