-- 与那国語辞典データベース設計
-- このSQLファイルはデータベーステーブル構造を作成するために使用される

-- 1. 見出し語主テーブル
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,  -- 自動増加の主キー
    headword TEXT NOT NULL,                -- 見出し語（与那国語原文）
    kana TEXT,                             -- かな表記
    ipa TEXT,                              -- IPA（ローマ字）表記
    pos TEXT,                              -- 品詞（名詞、動詞など）
    verb_class TEXT,                       -- 動詞クラス（動詞のみ必要）
    verb_stem TEXT,                        -- 動詞の語幹（動詞のみ必要）。複数はコンマ区切りで保存。
    tone TEXT,                             -- 音調
    etymology TEXT,                        -- 語源
    historical_change TEXT,                -- 歴史的音変化
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. 意味テーブル（多言語と多義語対応）
CREATE TABLE IF NOT EXISTS meanings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id INTEGER NOT NULL,             -- entriesテーブルへの関連
    language TEXT NOT NULL,                -- 言語コード：ja, zh-tw, en
    meaning_number INTEGER DEFAULT 1,      -- 義項番号（多義語対応）
    definition TEXT NOT NULL,              -- 意味の説明
    FOREIGN KEY (entry_id) REFERENCES entries(id) ON DELETE CASCADE
);

-- 3. 同義語テーブル
CREATE TABLE IF NOT EXISTS synonyms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id INTEGER NOT NULL,
    synonym TEXT NOT NULL,                 -- 同義語
    FOREIGN KEY (entry_id) REFERENCES entries(id) ON DELETE CASCADE
);

-- 4. 動詞活用テーブル
CREATE TABLE IF NOT EXISTS conjugations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id INTEGER NOT NULL,
    form_name TEXT NOT NULL,               -- 活用形式名（例：過去形、否定形など）
    conjugated_form TEXT NOT NULL,         -- 活用後の形式
    FOREIGN KEY (entry_id) REFERENCES entries(id) ON DELETE CASCADE
);

-- 5. 例文テーブル
CREATE TABLE IF NOT EXISTS examples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id INTEGER NOT NULL,
    yonaguni_sentence TEXT NOT NULL,       -- 与那国語例文
    FOREIGN KEY (entry_id) REFERENCES entries(id) ON DELETE CASCADE
);

-- 6. 例文翻訳テーブル（多言語対応）
CREATE TABLE IF NOT EXISTS example_translations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    example_id INTEGER NOT NULL,
    language TEXT NOT NULL,                -- 言語コード
    word_by_word TEXT,                     -- 逐語訳
    free_translation TEXT,                 -- 意訳
    FOREIGN KEY (example_id) REFERENCES examples(id) ON DELETE CASCADE
);

-- 7. インターフェース翻訳テーブル（UI文字列の多言語版を保存）
CREATE TABLE IF NOT EXISTS ui_translations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,                     -- 翻訳キー（例：dict_name, search_buttonなど）
    language TEXT NOT NULL,                -- 言語コード
    translation TEXT NOT NULL,             -- 翻訳テキスト
    UNIQUE(key, language)                  -- 各キー+言語の組み合わせが一意であることを保証
);

-- 8. メディアファイルテーブル（音声と画像を管理）
CREATE TABLE IF NOT EXISTS media_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id INTEGER,                      -- 見出し語ID（NULLの場合は例文用）
    example_id INTEGER,                    -- 例文ID（NULLの場合は見出し語用）
    file_type TEXT NOT NULL,               -- ファイルタイプ：audio, image
    file_path TEXT NOT NULL,               -- ファイルパス
    original_filename TEXT,                -- 元のファイル名
    description TEXT,                      -- ファイルの説明
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (entry_id) REFERENCES entries(id) ON DELETE CASCADE,
    FOREIGN KEY (example_id) REFERENCES examples(id) ON DELETE CASCADE
);

-- メディアファイル用のインデックス
CREATE INDEX idx_media_files_entry_id ON media_files(entry_id);
CREATE INDEX idx_media_files_example_id ON media_files(example_id);

-- UI翻訳サンプルデータを挿入
INSERT INTO ui_translations (key, language, translation) VALUES
-- 辞典名
('dict_name', 'ja', '与那国語辞典'),
('dict_name', 'yonaguni', 'どぅなんむぬい辞典'),
('dict_name', 'zh-tw', '與那國語詞典'),
('dict_name', 'en', 'Yonaguni Dictionary'),
-- ナビゲーションメニュー
('nav_home', 'ja', 'ホーム'),
('nav_about_language', 'ja', '与那国語について'),
('nav_grammar', 'ja', '文法'),
('nav_dialect_materials', 'ja', '方言資料'),
('nav_about_dict', 'ja', 'この辞典について'),
-- 検索オプション
('search_direction_ja_to_yo', 'ja', '日本語→与那国語'),
('search_direction_yo_to_ja', 'ja', '与那国語→日本語'),
('search_button', 'ja', '検索'),
('search_type_headword', 'ja', '見出し語のみ'),
('search_type_fulltext', 'ja', '例文全文検索'),
('match_type_prefix', 'ja', '前方一致'),
('match_type_suffix', 'ja', '後方一致'),
-- 開発中の提示
('under_development', 'ja', '開発中'),
-- 見出し語詳細ページラベル
('label_kana', 'ja', 'かな表記'),
('label_ipa', 'ja', 'IPA表記'),
('label_pos', 'ja', '品詞'),
('label_verb_class', 'ja', '動詞クラス'),
('label_tone', 'ja', '音調'),
('label_meaning', 'ja', '意味'),
('label_synonyms', 'ja', '同義語'),
('label_conjugation', 'ja', '活用形'),
('label_etymology', 'ja', '語源'),
('label_historical_change', 'ja', '歴史的音変化'),
('label_examples', 'ja', '例文'),
('label_word_by_word', 'ja', '逐語訳'),
('label_free_translation', 'ja', '意訳');

-- テスト見出し語データを挿入
INSERT INTO entries (headword, kana, ipa, pos, tone, etymology) VALUES
('どぅなん', 'どぅなん', 'dunan', '名詞', '平板型', '与那国の古称'),
('あがる', 'あがる', 'agaru', '動詞', '上昇型', '日本語「上がる」から');

-- 意味を挿入
INSERT INTO meanings (entry_id, language, meaning_number, definition) VALUES
(1, 'ja', 1, '与那国島'),
(1, 'zh-tw', 1, '與那國島'),
(1, 'en', 1, 'Yonaguni Island'),
(2, 'ja', 1, '上がる、登る'),
(2, 'ja', 2, '（太陽が）昇る');

-- 例文を挿入
INSERT INTO examples (entry_id, yonaguni_sentence) VALUES
(1, 'どぅなんぬ　くとぅば'),
(2, 'てぃだぬ　あがたん');

-- 例文翻訳を挿入
INSERT INTO example_translations (example_id, language, word_by_word, free_translation) VALUES
(1, 'ja', '与那国-の　言葉', '与那国の言葉'),
(2, 'ja', '太陽-が　上がった', '太陽が昇った');
