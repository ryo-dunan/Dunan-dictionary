-- ui_translations.sql - 完整的多语言UI翻译数据
-- 运行此脚本以添加所有语言的UI翻译

-- 首先清空现有的UI翻译（避免重复）
DELETE FROM ui_translations;

-- 插入所有语言的UI翻译
INSERT INTO ui_translations (key, language, translation) VALUES
-- 词典名称
('dict_name', 'ja', '与那国語辞典'),
('dict_name', 'yonaguni', 'どぅなんむぬい辞典'),
('dict_name', 'zh-tw', '與那國語詞典'),
('dict_name', 'en', 'Yonaguni Dictionary'),

-- 语言选择
('language_selector', 'ja', '言語'),
('language_selector', 'yonaguni', 'くとぅば'),
('language_selector', 'zh-tw', '語言'),
('language_selector', 'en', 'Language'),

-- 导航菜单
('nav_home', 'ja', 'ホーム'),
('nav_home', 'yonaguni', 'ホーム'),
('nav_home', 'zh-tw', '首頁'),
('nav_home', 'en', 'Home'),

('nav_about_language', 'ja', '与那国語について'),
('nav_about_language', 'yonaguni', 'どぅなんくとぅば'),
('nav_about_language', 'zh-tw', '關於與那國語'),
('nav_about_language', 'en', 'About Yonaguni'),

('nav_grammar', 'ja', '文法'),
('nav_grammar', 'yonaguni', '文法'),
('nav_grammar', 'zh-tw', '文法'),
('nav_grammar', 'en', 'Grammar'),

('nav_dialect_materials', 'ja', '方言資料'),
('nav_dialect_materials', 'yonaguni', 'どぅなんくとぅばぬ資料'),
('nav_dialect_materials', 'zh-tw', '方言資料'),
('nav_dialect_materials', 'en', 'Dialect Materials'),

('nav_about_dict', 'ja', 'この辞典について'),
('nav_about_dict', 'yonaguni', 'うぬ辞典'),
('nav_about_dict', 'zh-tw', '關於本詞典'),
('nav_about_dict', 'en', 'About This Dictionary'),

-- 搜索选项
('search_direction_yo_to_ja', 'ja', '与那国語→日本語'),
('search_direction_yo_to_ja', 'yonaguni', 'どぅなん→だまとぅ'),
('search_direction_yo_to_ja', 'zh-tw', '與那國語→中文'),
('search_direction_yo_to_ja', 'en', 'Yonaguni→Englis'),

('search_direction_ja_to_yo', 'ja', '日本語→与那国語'),
('search_direction_ja_to_yo', 'yonaguni', 'だまとぅ→どぅなん'),
('search_direction_ja_to_yo', 'zh-tw', '中文→與那國語'),
('search_direction_ja_to_yo', 'en', 'English→Yonaguni'),

('search_placeholder', 'ja', '検索語を入力してください'),
('search_placeholder', 'yonaguni', 'ぬーば みき=ぶか゚？'),
('search_placeholder', 'zh-tw', '請輸入搜尋詞'),
('search_placeholder', 'en', 'Enter search term'),

('search_button', 'ja', '検索'),
('search_button', 'yonaguni', 'みきるん'),
('search_button', 'zh-tw', '搜尋'),
('search_button', 'en', 'Search'),

('search_type_headword', 'ja', '見出語のみ'),
('search_type_headword', 'yonaguni', '見出語ばがい'),
('search_type_headword', 'zh-tw', '僅詞條'),
('search_type_headword', 'en', 'Headword only'),

('search_type_conjugation', 'ja', '活用形'),
('search_type_conjugation', 'yonaguni', '動詞ぬ かたち'),
('search_type_conjugation', 'zh-tw', '動詞活用形'),
('search_type_conjugation', 'en', 'Verb conjugation'),

('search_type_fulltext', 'ja', '全文検索'),
('search_type_fulltext', 'yonaguni', 'ぶーる'),
('search_type_fulltext', 'zh-tw', '全文搜尋'),
('search_type_fulltext', 'en', 'Full text search'),

('match_type_prefix', 'ja', '前方一致'),
('match_type_prefix', 'yonaguni', 'まいがら'),
('match_type_prefix', 'zh-tw', '前方一致'),
('match_type_prefix', 'en', 'Prefix match'),

('match_type_suffix', 'ja', '後方一致'),
('match_type_suffix', 'yonaguni', 'つばらがら'),
('match_type_suffix', 'zh-tw', '後方一致'),
('match_type_suffix', 'en', 'Suffix match'),

-- 搜索结果
('search_results', 'ja', '検索結果'),
('search_results', 'yonaguni', 'みきゃるむぬ'),
('search_results', 'zh-tw', '搜尋結果'),
('search_results', 'en', 'Search Results'),

('no_results', 'ja', '該当する結果が見つかりませんでした。'),
('no_results', 'yonaguni', 'ぬーん みぬたん'),
('no_results', 'zh-tw', '找不到符合的結果。'),
('no_results', 'en', 'No matching results found.'),

('searching', 'ja', '検索中'),
('searching', 'yonaguni', 'みきどぅ ぶる'),
('searching', 'zh-tw', '搜尋中'),
('searching', 'en', 'Searching'),

('loading', 'ja', '読み込み中'),
('loading', 'yonaguni', 'どぅみどぅ ぶる'),
('loading', 'zh-tw', '載入中'),
('loading', 'en', 'Loading'),

-- 开发中提示
('under_development', 'ja', '開発中'),
('under_development', 'yonaguni', 'ないどぅ くい ぶる'),
('under_development', 'zh-tw', '開發中'),
('under_development', 'en', 'Under Development'),

-- 词条详情页标签
('label_kana', 'ja', 'かな表記'),
('label_kana', 'yonaguni', 'かな'),
('label_kana', 'zh-tw', '假名標記'),
('label_kana', 'en', 'Kana'),

('label_ipa', 'ja', 'IPA表記'),
('label_ipa', 'yonaguni', 'IPA'),
('label_ipa', 'zh-tw', 'IPA標記'),
('label_ipa', 'en', 'IPA'),

('label_pos', 'ja', '品詞'),
('label_pos', 'yonaguni', '品詞'),
('label_pos', 'zh-tw', '詞性'),
('label_pos', 'en', 'Part of Speech'),

('label_verb_class', 'ja', '動詞クラス'),
('label_verb_class', 'yonaguni', '動詞クラス'),
('label_verb_class', 'zh-tw', '動詞類別'),
('label_verb_class', 'en', 'Verb Class'),

('label_tone', 'ja', '音調'),
('label_tone', 'yonaguni', '音調'),
('label_tone', 'zh-tw', '音調'),
('label_tone', 'en', 'Tone'),

('label_meaning', 'ja', '意味'),
('label_meaning', 'yonaguni', '意味'),
('label_meaning', 'zh-tw', '意思'),
('label_meaning', 'en', 'Meaning'),

('label_synonyms', 'ja', '同義語'),
('label_synonyms', 'yonaguni', '同義語'),
('label_synonyms', 'zh-tw', '同義詞'),
('label_synonyms', 'en', 'Synonyms'),

('label_conjugation', 'ja', '活用形'),
('label_conjugation', 'yonaguni', 'かたち'),
('label_conjugation', 'zh-tw', '活用形'),
('label_conjugation', 'en', 'Conjugation'),

('label_etymology', 'ja', '語源'),
('label_etymology', 'yonaguni', '語源'),
('label_etymology', 'zh-tw', '語源'),
('label_etymology', 'en', 'Etymology'),

('label_historical_change', 'ja', '音変化'),
('label_historical_change', 'yonaguni', '音変化'),
('label_historical_change', 'zh-tw', '歷史音變'),
('label_historical_change', 'en', 'Historical Sound Change'),

('label_examples', 'ja', '例文'),
('label_examples', 'yonaguni', '例文'),
('label_examples', 'zh-tw', '例句'),
('label_examples', 'en', 'Examples'),

('label_word_by_word', 'ja', '逐語訳'),
('label_word_by_word', 'yonaguni', '逐語訳'),
('label_word_by_word', 'zh-tw', '逐字譯'),
('label_word_by_word', 'en', 'Word-by-word'),

('label_free_translation', 'ja', '意訳'),
('label_free_translation', 'yonaguni', '意訳'),
('label_free_translation', 'zh-tw', '意譯'),
('label_free_translation', 'en', 'Translation'),

-- 返回按钮
('back_to_results', 'ja', '検索結果に戻る'),
('back_to_results', 'yonaguni', 'もどぅる'),
('back_to_results', 'zh-tw', 'むどぅるん'),
('back_to_results', 'en', 'Back to Results'),

-- 错误信息
('error_occurred', 'ja', 'エラーが発生しました。'),
('error_occurred', 'yonaguni', 'エラーきゃん'),
('error_occurred', 'zh-tw', '發生錯誤。'),
('error_occurred', 'en', 'An error occurred.'),

('search_error', 'ja', '検索エラーが発生しました。'),
('search_error', 'yonaguni', 'エラーきゃん'),
('search_error', 'zh-tw', '搜尋錯誤。'),
('search_error', 'en', 'Search error occurred.'),

-- 动词活用表头
('conjugation_form', 'ja', '活用形'),
('conjugation_form', 'yonaguni', 'かたち'),
('conjugation_form', 'zh-tw', '活用形式'),
('conjugation_form', 'en', 'Form'),

('conjugated_result', 'ja', '形態'),
('conjugated_result', 'yonaguni', '形態'),
('conjugated_result', 'zh-tw', '形態'),
('conjugated_result', 'en', 'Result');

('label_verb_stem', 'ja', '語幹'),
('label_verb_stem', 'yonaguni', '語幹'), 
('label_verb_stem', 'zh-tw', '詞幹'),
('label_verb_stem', 'en', 'Verb Stem');