# init_database.py - データベース初期化とデータ管理スクリプト
# このスクリプトはデータベースの初期化と見出し語データの追加に使用される

import sqlite3
import json
import os

def create_database():
    """データベースを作成してテーブル構造を初期化"""
    # databaseフォルダが存在することを確認
    if not os.path.exists('database'):
        os.makedirs('database')
    
    # データベースに接続（存在しない場合は自動的に作成される）
    conn = sqlite3.connect('database/yonaguni_dict.db')
    cursor = conn.cursor()
    
    # SQL schemaファイルを読み込んで実行
    with open('database/schema.sql', 'r', encoding='utf-8') as f:
        sql_script = f.read()
    
    cursor.executescript(sql_script)
    conn.commit()
    conn.close()
    
    print("✅ データベース作成成功！")

def add_sample_entries():
    """サンプル見出し語データを追加"""
    conn = sqlite3.connect('database/yonaguni_dict.db')
    cursor = conn.cursor()
    
    # サンプル見出し語データ
    sample_entries = [
        {
            'headword': 'かい',
            'kana': 'かい',
            'ipa': 'kai',
            'pos': '名詞',
            'tone': '平板型',
            'meanings': {
                'ja': ['太陽'],
                'zh-tw': ['太陽'],
                'en': ['sun']
            },
            'examples': [
                {
                    'yonaguni': 'かいぬ　あがたん',
                    'translations': {
                        'ja': {
                            'word_by_word': '太陽-が　昇った',
                            'free_translation': '太陽が昇った'
                        }
                    }
                }
            ]
        },
        {
            'headword': 'みぬん',
            'kana': 'みぬん',
            'ipa': 'minuŋ',
            'pos': '動詞',
            'verb_class': '第一類',
            'tone': '上昇型',
            'meanings': {
                'ja': ['見る', '見える'],
                'zh-tw': ['看', '看見'],
                'en': ['to see', 'to look']
            },
            'conjugations': [
                {'form': '過去形', 'conjugated': 'みだん'},
                {'form': '否定形', 'conjugated': 'みぬぬん'},
                {'form': '連用形', 'conjugated': 'みー'}
            ],
            'examples': [
                {
                    'yonaguni': 'うみ　みぬん',
                    'translations': {
                        'ja': {
                            'word_by_word': '海　見る',
                            'free_translation': '海を見る'
                        }
                    }
                }
            ]
        },
        {
            'headword': 'どぅー',
            'kana': 'どぅー',
            'ipa': 'duː',
            'pos': '名詞',
            'tone': '平板型',
            'meanings': {
                'ja': ['自分', '自身'],
                'zh-tw': ['自己'],
                'en': ['self', 'oneself']
            }
        }
    ]
    
    # サンプルデータを挿入
    for entry_data in sample_entries:
        try:
            # 主見出し語を挿入
            cursor.execute('''
                INSERT INTO entries 
                (headword, kana, ipa, pos, verb_class, tone, etymology, historical_change)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                entry_data['headword'],
                entry_data.get('kana'),
                entry_data.get('ipa'),
                entry_data.get('pos'),
                entry_data.get('verb_class'),
                entry_data.get('tone'),
                entry_data.get('etymology'),
                entry_data.get('historical_change')
            ))
            
            entry_id = cursor.lastrowid
            
            # 意味を挿入
            if 'meanings' in entry_data:
                for lang, meanings in entry_data['meanings'].items():
                    for i, meaning in enumerate(meanings, 1):
                        cursor.execute('''
                            INSERT INTO meanings 
                            (entry_id, language, meaning_number, definition)
                            VALUES (?, ?, ?, ?)
                        ''', (entry_id, lang, i, meaning))
            
            # 動詞活用を挿入
            if 'conjugations' in entry_data:
                for conj in entry_data['conjugations']:
                    cursor.execute('''
                        INSERT INTO conjugations 
                        (entry_id, form_name, conjugated_form)
                        VALUES (?, ?, ?)
                    ''', (entry_id, conj['form'], conj['conjugated']))
            
            # 例文を挿入
            if 'examples' in entry_data:
                for example in entry_data['examples']:
                    cursor.execute('''
                        INSERT INTO examples (entry_id, yonaguni_sentence)
                        VALUES (?, ?)
                    ''', (entry_id, example['yonaguni']))
                    
                    example_id = cursor.lastrowid
                    
                    # 例文翻訳を挿入
                    if 'translations' in example:
                        for lang, trans in example['translations'].items():
                            cursor.execute('''
                                INSERT INTO example_translations 
                                (example_id, language, word_by_word, free_translation)
                                VALUES (?, ?, ?, ?)
                            ''', (example_id, lang, 
                                  trans.get('word_by_word'), 
                                  trans.get('free_translation')))
            
            print(f"✅ 見出し語追加: {entry_data['headword']}")
            
        except sqlite3.IntegrityError as e:
            print(f"⚠️  見出し語 {entry_data['headword']} は既に存在している可能性があります: {e}")
    
    conn.commit()
    conn.close()
    print("\n✅ サンプルデータ追加完了！")

def add_new_entry():
    """インタラクティブに新しい見出し語を追加"""
    print("\n=== 新規見出し語追加 ===")
    
    # 基本情報を収集
    headword = input("見出し語（与那国語）: ").strip()
    if not headword:
        print("見出し語は必須です！")
        return
    
    kana = input("かな表記（オプション）: ").strip() or None
    ipa = input("IPA表記（オプション）: ").strip() or None
    pos = input("品詞（名詞/動詞/形容詞など）: ").strip() or None
    
    verb_class = None
    if pos == '動詞':
        verb_class = input("動詞クラス: ").strip() or None
    
    tone = input("音調（オプション）: ").strip() or None
    etymology = input("語源（オプション）: ").strip() or None
    
    # 意味を収集
    meanings = {'ja': [], 'zh-tw': [], 'en': []}
    
    print("\n日本語の意味を追加（空行で終了）:")
    while True:
        meaning = input("  意味: ").strip()
        if not meaning:
            break
        meanings['ja'].append(meaning)
    
    if input("\n繁体中文の意味を追加しますか？(y/n): ").lower() == 'y':
        print("繁体中文の意味を追加（空行で終了）:")
        while True:
            meaning = input("  意味: ").strip()
            if not meaning:
                break
            meanings['zh-tw'].append(meaning)
    
    if input("\n英語の意味を追加しますか？(y/n): ").lower() == 'y':
        print("英語の意味を追加（空行で終了）:")
        while True:
            meaning = input("  意味: ").strip()
            if not meaning:
                break
            meanings['en'].append(meaning)
    
    # データ構造を構築
    entry_data = {
        'headword': headword,
        'kana': kana,
        'ipa': ipa,
        'pos': pos,
        'verb_class': verb_class,
        'tone': tone,
        'etymology': etymology,
        'meanings': {k: v for k, v in meanings.items() if v}  # 内容のある言語のみ保持
    }
    
    # データベースに保存
    conn = sqlite3.connect('database/yonaguni_dict.db')
    cursor = conn.cursor()
    
    try:
        # 主見出し語を挿入
        cursor.execute('''
            INSERT INTO entries 
            (headword, kana, ipa, pos, verb_class, tone, etymology)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            entry_data['headword'],
            entry_data.get('kana'),
            entry_data.get('ipa'),
            entry_data.get('pos'),
            entry_data.get('verb_class'),
            entry_data.get('tone'),
            entry_data.get('etymology')
        ))
        
        entry_id = cursor.lastrowid
        
        # 意味を挿入
        for lang, meanings in entry_data.get('meanings', {}).items():
            for i, meaning in enumerate(meanings, 1):
                cursor.execute('''
                    INSERT INTO meanings 
                    (entry_id, language, meaning_number, definition)
                    VALUES (?, ?, ?, ?)
                ''', (entry_id, lang, i, meaning))
        
        conn.commit()
        print(f"\n✅ 見出し語 '{headword}' の追加に成功しました！")
        
    except Exception as e:
        conn.rollback()
        print(f"\n❌ 追加失敗: {e}")
    
    finally:
        conn.close()

def export_data():
    """データベースデータをJSON形式でエクスポート"""
    conn = sqlite3.connect('database/yonaguni_dict.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # すべての見出し語を取得
    cursor.execute('SELECT * FROM entries')
    entries = cursor.fetchall()
    
    export_data = []
    
    for entry in entries:
        entry_dict = dict(entry)
        entry_id = entry['id']
        
        # 意味を取得
        cursor.execute('''
            SELECT language, meaning_number, definition 
            FROM meanings 
            WHERE entry_id = ?
            ORDER BY language, meaning_number
        ''', (entry_id,))
        
        meanings = {}
        for row in cursor.fetchall():
            lang = row['language']
            if lang not in meanings:
                meanings[lang] = []
            meanings[lang].append(row['definition'])
        entry_dict['meanings'] = meanings
        
        # 例文を取得
        cursor.execute('''
            SELECT ex.id, ex.yonaguni_sentence
            FROM examples ex
            WHERE ex.entry_id = ?
        ''', (entry_id,))
        
        examples = []
        for ex_row in cursor.fetchall():
            example = {
                'yonaguni': ex_row['yonaguni_sentence'],
                'translations': {}
            }
            
            # 例文翻訳を取得
            cursor.execute('''
                SELECT language, word_by_word, free_translation
                FROM example_translations
                WHERE example_id = ?
            ''', (ex_row['id'],))
            
            for trans_row in cursor.fetchall():
                example['translations'][trans_row['language']] = {
                    'word_by_word': trans_row['word_by_word'],
                    'free_translation': trans_row['free_translation']
                }
            
            examples.append(example)
        
        if examples:
            entry_dict['examples'] = examples
        
        export_data.append(entry_dict)
    
    conn.close()
    
    # JSONファイルとして保存
    with open('yonaguni_dict_export.json', 'w', encoding='utf-8') as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)
    
    print(f"✅ エクスポート成功！{len(export_data)} 個の見出し語を yonaguni_dict_export.json にエクスポートしました")

def main_menu():
    """メインメニュー"""
    while True:
        print("\n=== 与那国語辞典データベース管理 ===")
        print("1. データベースを初期化")
        print("2. サンプルデータを追加")
        print("3. 新規見出し語を追加")
        print("4. データをエクスポート")
        print("0. 終了")
        
        choice = input("\n操作を選択してください (0-4): ").strip()
        
        if choice == '1':
            create_database()
        elif choice == '2':
            add_sample_entries()
        elif choice == '3':
            add_new_entry()
        elif choice == '4':
            export_data()
        elif choice == '0':
            print("さようなら！")
            break
        else:
            print("無効な選択です。もう一度お試しください。")

if __name__ == '__main__':
    # まずschema.sqlファイルが存在するかチェック
    if not os.path.exists('database/schema.sql'):
        print("❌ エラー：database/schema.sql ファイルが存在しません！")
        print("先に提供されたSQLコードを database/schema.sql ファイルとして保存してください。")
    else:
        main_menu()