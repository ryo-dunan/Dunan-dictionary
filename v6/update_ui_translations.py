# update_ui_translations.py - データベース内のUI翻訳を更新
# このスクリプトを実行してすべての言語のUI翻訳を追加

import sqlite3
import os

def update_ui_translations():
    """データベース内のUI翻訳を更新"""
    
    # データベースが存在するかチェック
    if not os.path.exists('database/yonaguni_dict.db'):
        print("❌ エラー：データベースファイルが存在しません！先に init_database.py を実行してデータベースを初期化してください。")
        return
    
    # SQLファイルが存在するかチェック
    if not os.path.exists('database/ui_translations.sql'):
        print("❌ エラー：ui_translations.sql ファイルが存在しません！")
        print("提供されたUI翻訳SQLコードを database/ui_translations.sql として保存してください")
        return
    
    # データベースに接続
    conn = sqlite3.connect('database/yonaguni_dict.db')
    cursor = conn.cursor()
    
    try:
        # SQLファイルを読み込んで実行
        with open('database/ui_translations.sql', 'r', encoding='utf-8') as f:
            sql_script = f.read()
        
        cursor.executescript(sql_script)
        conn.commit()
        
        # 翻訳数を確認
        cursor.execute("SELECT COUNT(DISTINCT key) as key_count, COUNT(DISTINCT language) as lang_count FROM ui_translations")
        result = cursor.fetchone()
        
        print(f"✅ UI翻訳更新成功！")
        print(f"   - 翻訳キー数: {result[0]}")
        print(f"   - サポート言語数: {result[1]}")
        
        # サポートされる言語を表示
        cursor.execute("SELECT DISTINCT language FROM ui_translations ORDER BY language")
        languages = [row[0] for row in cursor.fetchall()]
        print(f"   - サポートされる言語: {', '.join(languages)}")
        
    except Exception as e:
        print(f"❌ 更新失敗: {e}")
        conn.rollback()
    
    finally:
        conn.close()

if __name__ == '__main__':
    update_ui_translations()