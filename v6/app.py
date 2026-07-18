# app.py - 与那国語辞典バックエンド主プログラム
# このファイルはWebアプリケーションの核心で、すべてのHTTPリクエストとデータベース操作を処理する

from flask import Flask, render_template, request, jsonify, send_from_directory, session, redirect, url_for
from flask_cors import CORS  # クロスドメインリクエストを処理
from functools import wraps
import sqlite3
import json
import os
from datetime import datetime
from werkzeug.utils import secure_filename
import shutil
import secrets
import hmac
from urllib.parse import urlsplit

# Flaskアプリケーションインスタンスを作成
app = Flask(__name__)
# CORSを有効化し、フロントエンドのクロスドメインアクセスを許可
# v2 is same-origin only. Legacy cross-origin access must be explicitly configured
# by a deployment proxy rather than being allowed for every site here.

# --- 認証設定 ---
# セキュリティのため、このキーは複雑なランダムな文字列に変更することを強く推奨します
app.secret_key = os.environ.get('YONAGUNI_LEGACY_SECRET_KEY') or secrets.token_hex(32)
ADMIN_USERNAME = os.environ.get('YONAGUNI_LEGACY_ADMIN_USERNAME')
ADMIN_PASSWORD = os.environ.get('YONAGUNI_LEGACY_ADMIN_PASSWORD')
LEGACY_ADMIN_ENABLED = os.environ.get('YONAGUNI_ENABLE_LEGACY_ADMIN') == '1'
# ---

# データベースファイルパス
DATABASE = 'database/yonaguni_dict.db'

# メディアファイルの設定
UPLOAD_FOLDER = 'static/media'
ALLOWED_AUDIO_EXTENSIONS = {'mp3', 'wav'}
ALLOWED_IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 最大16MB

# メディアフォルダを作成
os.makedirs(os.path.join('static', 'media', 'audio'), exist_ok=True)
os.makedirs(os.path.join('static', 'media', 'images'), exist_ok=True)


# ログイン必須デコレーター
def login_required(f):
    """
    このデコレーターをルートに追加すると、ログインしていないユーザーは
    ログインページにリダイレクトされるようになります。
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not LEGACY_ADMIN_ENABLED:
            return jsonify({'success': False, 'error': 'Legacy administration is disabled'}), 410
        if 'logged_in' not in session:
            # APIリクエストの場合はJSONでエラーを返す
            if request.path.startswith('/api/'):
                 return jsonify({'success': False, 'error': 'Authentication required'}), 401
            # 通常のページアクセスの場合はログインページにリダイレクト
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def get_db_connection():
    """
    データベース接続を作成して返す
    データベースにアクセスする必要があるたびにこの関数を呼び出す
    """
    conn = sqlite3.connect(DATABASE)
    # row_factoryを設定し、クエリ結果を辞書のようにアクセスできるようにする
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn

def init_db():
    """
    データベースを初期化
    SQLファイルを読み込んで実行し、必要なテーブルをすべて作成
    """
    with open('database/schema.sql', 'r', encoding='utf-8') as f:
        sql_script = f.read()
    
    conn = get_db_connection()
    conn.executescript(sql_script)
    conn.commit()
    conn.close()
    print("データベース初期化完了！")

# --- 公開ルート ---

@app.route('/')
def index():
    """
    メインページルート
    メインHTMLページを返す
    """
    return render_template('index.html')

@app.route('/api/ui-translations/<language>')
def get_ui_translations(language):
    """
    指定言語のUI翻訳を取得
    パラメータ：language - 言語コード（ja, zh-tw, en, yonaguni）
    戻り値：JSON形式の翻訳キーと値のペア
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 指定言語のすべてのUI翻訳をクエリ
    cursor.execute('''
        SELECT key, translation 
        FROM ui_translations 
        WHERE language = ?
    ''', (language,))
    
    # 結果を辞書形式に変換
    translations = {}
    for row in cursor.fetchall():
        translations[row['key']] = row['translation']
    
    conn.close()
    return jsonify(translations)

@app.route('/api/search', methods=['POST'])
def search():
    """
    検索APIエンドポイント
    検索パラメータを受け取り、マッチする見出し語リストを返す
    """
    # リクエストパラメータを取得
    data = request.json
    query = data.get('query', '')  # 検索キーワード
    search_type = data.get('search_type', 'headword')  # 検索タイプ：headword、fulltext、conjugation
    match_type = data.get('match_type', 'prefix')  # マッチタイプ：prefix または suffix
    direction = data.get('direction', 'yo_to_ja')  # 検索方向
    language = data.get('language', 'ja')  # インターフェース言語
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    results = []
    
    # インターフェース言語に基づいて検索結果言語を調整
    # インターフェースが与那国語の場合、日本語の釈義を優先表示
    result_language = 'ja' if language == 'yonaguni' else language
    
    if search_type == 'headword':
        # 見出し語検索
        if direction == 'yo_to_ja':
            # 与那国語から他言語へ
            if match_type == 'prefix':
                # 前方一致
                cursor.execute('''
                    SELECT DISTINCT e.id, e.headword, e.kana, e.pos,
                           m.definition
                    FROM entries e
                    LEFT JOIN meanings m ON e.id = m.entry_id
                    WHERE (e.headword LIKE ? OR e.kana LIKE ?)
                    AND m.language = ?
                    AND m.meaning_number = 1
                    ORDER BY e.headword
                    LIMIT 50
                ''', (query + '%', query + '%', result_language))
            elif match_type == 'suffix':
                # 後方一致
                cursor.execute('''
                    SELECT DISTINCT e.id, e.headword, e.kana, e.pos,
                           m.definition
                    FROM entries e
                    LEFT JOIN meanings m ON e.id = m.entry_id
                    WHERE (e.headword LIKE ? OR e.kana LIKE ?)
                    AND m.language = ?
                    AND m.meaning_number = 1
                    ORDER BY e.headword
                    LIMIT 50
                ''', ('%' + query, '%' + query, result_language))
            else:
                # 含む（contains）
                cursor.execute('''
                    SELECT DISTINCT e.id, e.headword, e.kana, e.pos,
                           m.definition
                    FROM entries e
                    LEFT JOIN meanings m ON e.id = m.entry_id
                    WHERE (e.headword LIKE ? OR e.kana LIKE ?)
                    AND m.language = ?
                    AND m.meaning_number = 1
                    ORDER BY e.headword
                    LIMIT 50
                ''', ('%' + query + '%', '%' + query + '%', result_language))
        else:
            # 他言語から与那国語へ
            if match_type == 'prefix':
                cursor.execute('''
                    SELECT DISTINCT e.id, e.headword, e.kana, e.pos,
                           m.definition
                    FROM entries e
                    JOIN meanings m ON e.id = m.entry_id
                    WHERE m.definition LIKE ?
                    AND m.language = ?
                    ORDER BY e.headword
                    LIMIT 50
                ''', (query + '%', result_language))
            elif match_type == 'suffix':
                cursor.execute('''
                    SELECT DISTINCT e.id, e.headword, e.kana, e.pos,
                           m.definition
                    FROM entries e
                    JOIN meanings m ON e.id = m.entry_id
                    WHERE m.definition LIKE ?
                    AND m.language = ?
                    ORDER BY e.headword
                    LIMIT 50
                ''', ('%' + query, result_language))
            else:
                # 含む（contains）
                cursor.execute('''
                    SELECT DISTINCT e.id, e.headword, e.kana, e.pos,
                           m.definition
                    FROM entries e
                    JOIN meanings m ON e.id = m.entry_id
                    WHERE m.definition LIKE ?
                    AND m.language = ?
                    ORDER BY e.headword
                    LIMIT 50
                ''', ('%' + query + '%', result_language))
    
    elif search_type == 'conjugation':
        # 動詞活用形検索
        if match_type == 'prefix':
            cursor.execute('''
                SELECT DISTINCT e.id, e.headword, e.kana, e.pos,
                       m.definition, c.form_name, c.conjugated_form
                FROM entries e
                JOIN conjugations c ON e.id = c.entry_id
                LEFT JOIN meanings m ON e.id = m.entry_id
                WHERE c.conjugated_form LIKE ?
                AND m.language = ?
                AND m.meaning_number = 1
                ORDER BY e.headword
                LIMIT 50
            ''', (query + '%', result_language))
        elif match_type == 'suffix':
            cursor.execute('''
                SELECT DISTINCT e.id, e.headword, e.kana, e.pos,
                       m.definition, c.form_name, c.conjugated_form
                FROM entries e
                JOIN conjugations c ON e.id = c.entry_id
                LEFT JOIN meanings m ON e.id = m.entry_id
                WHERE c.conjugated_form LIKE ?
                AND m.language = ?
                AND m.meaning_number = 1
                ORDER BY e.headword
                LIMIT 50
            ''', ('%' + query, result_language))
        else:
            # 含む（contains）
            cursor.execute('''
                SELECT DISTINCT e.id, e.headword, e.kana, e.pos,
                       m.definition, c.form_name, c.conjugated_form
                FROM entries e
                JOIN conjugations c ON e.id = c.entry_id
                LEFT JOIN meanings m ON e.id = m.entry_id
                WHERE c.conjugated_form LIKE ?
                AND m.language = ?
                AND m.meaning_number = 1
                ORDER BY e.headword
                LIMIT 50
            ''', ('%' + query + '%', result_language))
    
    else:
        # 全文検索（例文を含む）
        cursor.execute('''
            SELECT DISTINCT e.id, e.headword, e.kana, e.pos,
                   m.definition, ex.yonaguni_sentence
            FROM entries e
            LEFT JOIN meanings m ON e.id = m.entry_id
            LEFT JOIN examples ex ON e.id = ex.entry_id
            LEFT JOIN example_translations et ON ex.id = et.example_id
            WHERE (e.headword LIKE ? OR e.kana LIKE ? 
                   OR ex.yonaguni_sentence LIKE ?
                   OR et.free_translation LIKE ?)
            AND m.language = ?
            AND m.meaning_number = 1
            ORDER BY e.headword
            LIMIT 50
        ''', ('%' + query + '%', '%' + query + '%', 
             '%' + query + '%', '%' + query + '%', result_language))
    
    # 検索結果をフォーマット
    seen_ids = set()  # 重複除去用
    for row in cursor.fetchall():
        if row['id'] not in seen_ids:
            seen_ids.add(row['id'])
            result_item = {
                'id': row['id'],
                'headword': row['headword'],
                'kana': row['kana'],
                'pos': row['pos'],
                'definition': row['definition']
            }
            # 活用形検索の場合、マッチした活用形も含める
            if search_type == 'conjugation' and 'conjugated_form' in row.keys():
                result_item['matched_form'] = row['conjugated_form']
                result_item['form_name'] = row['form_name']
            results.append(result_item)
    
    conn.close()
    return jsonify({'results': results})

@app.route('/api/entry/<int:entry_id>')
def get_entry(entry_id):
    """
    単一の見出し語の詳細情報を取得
    パラメータ：entry_id - 見出し語ID
    戻り値：見出し語のすべての情報を含むJSONオブジェクト
    """
    language = request.args.get('language', 'ja')
    # インターフェース言語が与那国語の場合、日本語で釈義を表示
    display_language = 'ja' if language == 'yonaguni' else language
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 見出し語の基本情報を取得
    cursor.execute('SELECT * FROM entries WHERE id = ?', (entry_id,))
    entry = cursor.fetchone()
    
    if not entry:
        conn.close()
        return jsonify({'error': 'Entry not found'}), 404
    
    # レスポンスデータを構築
    result = {
        'id': entry['id'],
        'headword': entry['headword'],
        'kana': entry['kana'],
        'ipa': entry['ipa'],
        'pos': entry['pos'],
        'verb_class': entry['verb_class'],
        'verb_stem': entry['verb_stem'],
        'tone': entry['tone'],
        'etymology': entry['etymology'],
        'historical_change': entry['historical_change']
    }
    
    # 意味を取得（多義語対応）
    cursor.execute('''
        SELECT meaning_number, definition 
        FROM meanings 
        WHERE entry_id = ? AND language = ?
        ORDER BY meaning_number
    ''', (entry_id, display_language))
    result['meanings'] = [{'number': row['meaning_number'], 
                          'definition': row['definition']} 
                         for row in cursor.fetchall()]
    
    # 同義語を取得
    cursor.execute('SELECT synonym FROM synonyms WHERE entry_id = ?', (entry_id,))
    result['synonyms'] = [row['synonym'] for row in cursor.fetchall()]
    
    # 動詞活用を取得（動詞の場合）
    if entry['pos'] == '動詞':
        cursor.execute('''
            SELECT form_name, conjugated_form 
            FROM conjugations 
            WHERE entry_id = ?
        ''', (entry_id,))
        result['conjugations'] = [{'form': row['form_name'], 
                                  'conjugated': row['conjugated_form']} 
                                 for row in cursor.fetchall()]
    
    # 例文と翻訳を取得
    cursor.execute('''
        SELECT ex.id, ex.yonaguni_sentence,
               et.word_by_word, et.free_translation
        FROM examples ex
        LEFT JOIN example_translations et ON ex.id = et.example_id
        WHERE ex.entry_id = ? AND et.language = ?
    ''', (entry_id, display_language))
    
    examples = []
    for row in cursor.fetchall():
        example_data = {
            'id': row['id'],
            'yonaguni': row['yonaguni_sentence'],
            'word_by_word': row['word_by_word'],
            'translation': row['free_translation']
        }
        
        # 例文の音声ファイルを取得
        cursor.execute('''
            SELECT file_path
            FROM media_files
            WHERE example_id = ? AND file_type = 'audio'
        ''', (row['id'],))
        
        audio_row = cursor.fetchone()
        if audio_row:
            example_data['audio'] = audio_row['file_path']
        
        examples.append(example_data)
    
    result['examples'] = examples
    
    # 見出し語の音声ファイルを取得
    cursor.execute('''
        SELECT file_path
        FROM media_files
        WHERE entry_id = ? AND file_type = 'audio' AND example_id IS NULL
    ''', (entry_id,))
    
    audio_row = cursor.fetchone()
    if audio_row:
        result['audio'] = audio_row['file_path']
    
    # 見出し語の画像ファイルを取得
    cursor.execute('''
        SELECT file_path
        FROM media_files
        WHERE entry_id = ? AND file_type = 'image' AND example_id IS NULL
    ''', (entry_id,))
    
    images = []
    for row in cursor.fetchall():
        images.append(row['file_path'])
    if images:
        result['images'] = images
    
    conn.close()
    return jsonify(result)


# --- 認証ルート ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    """ログインページ"""
    error = None
    if not LEGACY_ADMIN_ENABLED:
        return redirect(url_for('index'))
    if request.method == 'POST':
        valid_username = bool(ADMIN_USERNAME and hmac.compare_digest(request.form.get('username', ''), ADMIN_USERNAME))
        valid_password = bool(ADMIN_PASSWORD and hmac.compare_digest(request.form.get('password', ''), ADMIN_PASSWORD))
        if valid_username and valid_password:
            session['logged_in'] = True
            next_url = request.args.get('next')
            # 安全なリダイレクト
            if next_url:
                target = urlsplit(next_url)
                if target.netloc or target.scheme:
                    next_url = None
            return redirect(next_url or url_for('admin'))
        else:
            error = 'ユーザーネームまたはパスワードが正しくありません。'
    # ログイン済みの場合は管理ページへ
    if 'logged_in' in session:
        return redirect(url_for('admin'))
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    """ログアウト処理"""
    session.pop('logged_in', None)
    return redirect(url_for('index'))

# --- 管理者用ルート ---

@app.route('/admin')
@login_required
def admin():
    """
    管理ページルート
    管理用HTMLページを返す
    """
    return render_template('admin.html')

@app.route('/api/entries')
@login_required
def get_all_entries():
    """
    すべての見出し語を取得（管理ページ用）
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT e.id, e.headword, e.kana, e.pos, e.verb_class, e.verb_stem,
               m.definition
        FROM entries e
        LEFT JOIN meanings m ON e.id = m.entry_id
        WHERE m.language = 'ja' AND m.meaning_number = 1
        GROUP BY e.id
        ORDER BY e.headword
    ''')
    
    entries = []
    for row in cursor.fetchall():
        entries.append({
            'id': row['id'],
            'headword': row['headword'],
            'kana': row['kana'],
            'pos': row['pos'],
            'verb_class': row['verb_class'],
            'verb_stem': row['verb_stem'],
            'definition': row['definition']
        })
    
    conn.close()
    return jsonify({'entries': entries})

@app.route('/api/add-entry', methods=['POST'])
@login_required
def add_entry():
    """
    新しい見出し語を追加
    JSON形式の見出し語データを受け取り、データベースに挿入
    """
    data = request.json
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # トランザクション開始
        conn.execute('BEGIN')
        
        # 見出し語の基本情報を挿入
        cursor.execute('''
            INSERT INTO entries 
            (headword, kana, ipa, pos, verb_class, verb_stem, tone, etymology, historical_change)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data['headword'],
            data.get('kana'),
            data.get('ipa'),
            data.get('pos'),
            data.get('verb_class'),
            data.get('verb_stem'),
            data.get('tone'),
            data.get('etymology'),
            data.get('historical_change')
        ))
        
        entry_id = cursor.lastrowid
        
        # 意味を挿入（多言語対応）
        for lang_code, meanings in data.get('meanings', {}).items():
            for i, meaning in enumerate(meanings, 1):
                cursor.execute('''
                    INSERT INTO meanings 
                    (entry_id, language, meaning_number, definition)
                    VALUES (?, ?, ?, ?)
                ''', (entry_id, lang_code, i, meaning))
        
        # 同義語を挿入
        for synonym in data.get('synonyms', []):
            cursor.execute('''
                INSERT INTO synonyms (entry_id, synonym)
                VALUES (?, ?)
            ''', (entry_id, synonym))
        
        # 動詞活用を挿入
        for conjugation in data.get('conjugations', []):
            cursor.execute('''
                INSERT INTO conjugations 
                (entry_id, form_name, conjugated_form)
                VALUES (?, ?, ?)
            ''', (entry_id, conjugation['form'], conjugation['conjugated']))
        
        # 例文を挿入
        for example in data.get('examples', []):
            cursor.execute('''
                INSERT INTO examples (entry_id, yonaguni_sentence)
                VALUES (?, ?)
            ''', (entry_id, example['yonaguni']))
            
            example_id = cursor.lastrowid
            
            # 例文翻訳を挿入
            for lang_code, translation in example.get('translations', {}).items():
                cursor.execute('''
                    INSERT INTO example_translations 
                    (example_id, language, word_by_word, free_translation)
                    VALUES (?, ?, ?, ?)
                ''', (example_id, lang_code, 
                      translation.get('word_by_word'), 
                      translation.get('free_translation')))
        
        # トランザクションをコミット
        conn.commit()
        
        return jsonify({'success': True, 'entry_id': entry_id})
        
    except Exception as e:
        # エラー発生時はロールバック
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    
    finally:
        conn.close()

@app.route('/api/update-entry/<int:entry_id>', methods=['PUT'])
@login_required
def update_entry(entry_id):
    """
    既存の見出し語を更新
    """
    data = request.json
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # トランザクション開始
        conn.execute('BEGIN')
        
        # 見出し語の基本情報を更新
        cursor.execute('''
            UPDATE entries SET
                headword = ?, kana = ?, ipa = ?, pos = ?, 
                verb_class = ?, verb_stem = ?, tone = ?, etymology = ?, historical_change = ?
            WHERE id = ?
        ''', (
            data['headword'],
            data.get('kana'),
            data.get('ipa'),
            data.get('pos'),
            data.get('verb_class'),
            data.get('verb_stem'),
            data.get('tone'),
            data.get('etymology'),
            data.get('historical_change'),
            entry_id
        ))
        
        # 既存の関連データを削除
        cursor.execute('DELETE FROM meanings WHERE entry_id = ?', (entry_id,))
        cursor.execute('DELETE FROM synonyms WHERE entry_id = ?', (entry_id,))
        cursor.execute('DELETE FROM conjugations WHERE entry_id = ?', (entry_id,))
        cursor.execute('DELETE FROM examples WHERE entry_id = ?', (entry_id,))
        
        # 新しいデータを挿入
        # 意味
        for lang_code, meanings in data.get('meanings', {}).items():
            for i, meaning in enumerate(meanings, 1):
                cursor.execute('''
                    INSERT INTO meanings 
                    (entry_id, language, meaning_number, definition)
                    VALUES (?, ?, ?, ?)
                ''', (entry_id, lang_code, i, meaning))
        
        # 同義語
        for synonym in data.get('synonyms', []):
            cursor.execute('''
                INSERT INTO synonyms (entry_id, synonym)
                VALUES (?, ?)
            ''', (entry_id, synonym))
        
        # 動詞活用
        for conjugation in data.get('conjugations', []):
            cursor.execute('''
                INSERT INTO conjugations 
                (entry_id, form_name, conjugated_form)
                VALUES (?, ?, ?)
            ''', (entry_id, conjugation['form'], conjugation['conjugated']))
        
        # 例文
        for example in data.get('examples', []):
            cursor.execute('''
                INSERT INTO examples (entry_id, yonaguni_sentence)
                VALUES (?, ?)
            ''', (entry_id, example['yonaguni']))
            
            example_id = cursor.lastrowid
            
            # 例文翻訳
            for lang_code, translation in example.get('translations', {}).items():
                cursor.execute('''
                    INSERT INTO example_translations 
                    (example_id, language, word_by_word, free_translation)
                    VALUES (?, ?, ?, ?)
                ''', (example_id, lang_code, 
                      translation.get('word_by_word'), 
                      translation.get('free_translation')))
        
        # トランザクションをコミット
        conn.commit()
        
        return jsonify({'success': True})
        
    except Exception as e:
        # エラー発生時はロールバック
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    
    finally:
        conn.close()

@app.route('/api/bulk-delete-entries', methods=['POST'])
@login_required
def bulk_delete_entries():
    """
    複数の見出し語を一括で削除
    """
    data = request.json
    ids_to_delete = data.get('ids')

    if not ids_to_delete or not isinstance(ids_to_delete, list):
        return jsonify({'success': False, 'error': '削除するIDのリストが無効です。'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        conn.execute('BEGIN')
        # プレースホルダ (?) をIDの数だけ生成
        placeholders = ','.join('?' for _ in ids_to_delete)
        # カスケード削除により関連データも自動的に削除される
        cursor.execute(f'DELETE FROM entries WHERE id IN ({placeholders})', ids_to_delete)
        conn.commit()
        return jsonify({'success': True, 'deleted_count': len(ids_to_delete)})
        
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    
    finally:
        conn.close()

@app.route('/api/delete-all-entries', methods=['DELETE'])
@login_required
def delete_all_entries():
    """
    すべての見出し語を削除
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        conn.execute('BEGIN')
        # 関連テーブルもCASCADE DELETEで削除される
        cursor.execute('DELETE FROM entries')
        # media_filesテーブルも別途クリアする
        cursor.execute('DELETE FROM media_files')
        conn.commit()

        # メディアフォルダ内のファイルを削除
        for folder in ['audio', 'images']:
            folder_path = os.path.join(app.config['UPLOAD_FOLDER'], folder)
            for filename in os.listdir(folder_path):
                file_path = os.path.join(folder_path, filename)
                if os.path.isfile(file_path):
                    os.unlink(file_path)

        return jsonify({'success': True})
        
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    
    finally:
        conn.close()

@app.route('/api/delete-entry/<int:entry_id>', methods=['DELETE'])
@login_required
def delete_entry(entry_id):
    """
    見出し語を削除
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # カスケード削除により関連データも自動的に削除される
        cursor.execute('DELETE FROM entries WHERE id = ?', (entry_id,))
        conn.commit()
        
        return jsonify({'success': True})
        
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    
    finally:
        conn.close()

@app.route('/api/bulk-import', methods=['POST'])
@login_required
def bulk_import():
    """
    JSONデータから見出し語を一括でインポートする
    """
    entries_data = request.json
    if not isinstance(entries_data, list):
        return jsonify({'success': False, 'error': 'データは配列形式でなければなりません。'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 処理結果を記録する変数
    success_count = 0
    errors = []

    # 各見出し語をループ処理
    for index, data in enumerate(entries_data):
        try:
            # トランザクション開始 (各エントリごと)
            conn.execute('BEGIN')

            # 見出し語の基本情報を挿入
            cursor.execute('''
                INSERT INTO entries 
                (headword, kana, ipa, pos, verb_class, verb_stem, tone, etymology, historical_change)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                data['headword'],
                data.get('kana'),
                data.get('ipa'),
                data.get('pos'),
                data.get('verb_class'),
                data.get('verb_stem'),
                data.get('tone'),
                data.get('etymology'),
                data.get('historical_change')
            ))
            
            entry_id = cursor.lastrowid
            
            # 意味を挿入（多言語対応）
            for lang_code, meanings in data.get('meanings', {}).items():
                for i, meaning in enumerate(meanings, 1):
                    cursor.execute('''
                        INSERT INTO meanings 
                        (entry_id, language, meaning_number, definition)
                        VALUES (?, ?, ?, ?)
                    ''', (entry_id, lang_code, i, meaning))
            
            # 同義語を挿入
            for synonym in data.get('synonyms', []):
                cursor.execute('''
                    INSERT INTO synonyms (entry_id, synonym)
                    VALUES (?, ?)
                ''', (entry_id, synonym))
            
            # 動詞活用を挿入
            for conjugation in data.get('conjugations', []):
                cursor.execute('''
                    INSERT INTO conjugations 
                    (entry_id, form_name, conjugated_form)
                    VALUES (?, ?, ?)
                ''', (entry_id, conjugation['form'], conjugation['conjugated']))
            
            # 例文を挿入
            for example in data.get('examples', []):
                cursor.execute('''
                    INSERT INTO examples (entry_id, yonaguni_sentence)
                    VALUES (?, ?)
                ''', (entry_id, example['yonaguni']))
                
                example_id = cursor.lastrowid
                
                # 例文翻訳を挿入
                for lang_code, translation in example.get('translations', {}).items():
                    cursor.execute('''
                        INSERT INTO example_translations 
                        (example_id, language, word_by_word, free_translation)
                        VALUES (?, ?, ?, ?)
                    ''', (example_id, lang_code, 
                          translation.get('word_by_word'), 
                          translation.get('free_translation')))
            
            # この見出し語のトランザクションをコミット
            conn.commit()
            success_count += 1
            
        except Exception as e:
            # エラー発生時はロールバック
            conn.rollback()
            errors.append({
                'index': index + 1,
                'headword': data.get('headword', 'N/A'),
                'error': str(e)
            })
    
    conn.close()

    return jsonify({
        'success': True,
        'total_entries': len(entries_data),
        'success_count': success_count,
        'error_count': len(errors),
        'errors': errors
    })

def allowed_file(filename, file_type):
    """
    ファイルの拡張子をチェック
    """
    if '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    if file_type == 'audio':
        return ext in ALLOWED_AUDIO_EXTENSIONS
    elif file_type == 'image':
        return ext in ALLOWED_IMAGE_EXTENSIONS
    return False

def generate_filename(entry_ipa, example_number=None, file_type='audio', original_filename=''):
    """
    ファイル名を生成（IPA表記に基づく）
    """
    if not entry_ipa:
        entry_ipa = 'unknown'
    
    # ファイル拡張子を取得
    ext = original_filename.rsplit('.', 1)[1].lower() if '.' in original_filename else 'mp3'
    
    # 基本ファイル名を生成
    if example_number is not None:
        base_filename = f"{secure_filename(entry_ipa) or 'unknown'}_{example_number}"
    else:
        base_filename = secure_filename(entry_ipa) or 'unknown'
    
    # フォルダパスを決定
    folder = 'audio' if file_type == 'audio' else 'images'
    
    # 重複チェックとファイル名調整
    counter = 0
    while True:
        if counter == 0:
            filename = f"{base_filename}.{ext}"
        else:
            filename = f"{base_filename}_{counter}.{ext}"
        
        filepath = os.path.join('static', 'media', folder, filename)
        if not os.path.exists(filepath):
            break
        counter += 1
    
    return os.path.join(folder, filename)

@app.route('/api/upload-media', methods=['POST'])
@login_required
def upload_media():
    """
    メディアファイル（音声・画像）をアップロード
    """
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'ファイルがありません'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'ファイルが選択されていません'}), 400
    
    # パラメータを取得
    entry_id = request.form.get('entry_id', type=int)
    example_id = request.form.get('example_id', type=int)
    file_type = request.form.get('file_type', 'audio')
    
    if not allowed_file(file.filename, file_type):
        return jsonify({'success': False, 'error': '許可されていないファイル形式です'}), 400
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 既存のファイルを削除（同じタイプのファイルがある場合）
        if entry_id and not example_id:
            # 見出し語のメディア
            cursor.execute('''
                SELECT id, file_path FROM media_files 
                WHERE entry_id = ? AND file_type = ? AND example_id IS NULL
            ''', (entry_id, file_type))
        elif example_id:
            # 例文のメディア
            cursor.execute('''
                SELECT id, file_path FROM media_files 
                WHERE example_id = ? AND file_type = ?
            ''', (example_id, file_type))
        
        existing_files = cursor.fetchall()
        for existing in existing_files:
            # ファイルを削除
            old_filepath = os.path.join('static', 'media', existing['file_path'])
            if os.path.exists(old_filepath):
                os.remove(old_filepath)
            # データベースから削除
            cursor.execute('DELETE FROM media_files WHERE id = ?', (existing['id'],))
        
        # 見出し語のIPA表記を取得
        entry_ipa = 'unknown'
        if entry_id:
            cursor.execute('SELECT ipa FROM entries WHERE id = ?', (entry_id,))
            row = cursor.fetchone()
            if row and row['ipa']:
                entry_ipa = row['ipa']
        elif example_id:
            cursor.execute('''
                SELECT e.ipa, ex.id 
                FROM examples ex 
                JOIN entries e ON ex.entry_id = e.id 
                WHERE ex.id = ?
            ''', (example_id,))
            row = cursor.fetchone()
            if row and row['ipa']:
                entry_ipa = row['ipa']
        
        # 例文番号を取得
        example_number = None
        if example_id:
            cursor.execute('''
                SELECT COUNT(*) as num 
                FROM examples 
                WHERE entry_id = (SELECT entry_id FROM examples WHERE id = ?)
                AND id <= ?
            ''', (example_id, example_id))
            row = cursor.fetchone()
            example_number = row['num'] if row else 1
        
        # ファイル名を生成
        filename = generate_filename(entry_ipa, example_number, file_type, file.filename)
        filepath = os.path.join('static', 'media', filename)
        
        # ファイルを保存
        file.save(filepath)
        
        # データベースに記録
        cursor.execute('''
            INSERT INTO media_files (entry_id, example_id, file_type, file_path, original_filename)
            VALUES (?, ?, ?, ?, ?)
        ''', (entry_id, example_id, file_type, filename, secure_filename(file.filename)))
        
        conn.commit()
        
        return jsonify({
            'success': True,
            'filename': filename,
            'filepath': f'/static/media/{filename}'
        })
        
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    
    finally:
        conn.close()

@app.route('/api/delete-media/<int:media_id>', methods=['DELETE'])
@login_required
def delete_media(media_id):
    """
    メディアファイルを削除
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # ファイル情報を取得
        cursor.execute('SELECT file_path FROM media_files WHERE id = ?', (media_id,))
        row = cursor.fetchone()
        
        if row:
            # ファイルを削除
            filepath = os.path.join('static', 'media', row['file_path'])
            if os.path.exists(filepath):
                os.remove(filepath)
            
            # データベースから削除
            cursor.execute('DELETE FROM media_files WHERE id = ?', (media_id,))
            conn.commit()
            
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'ファイルが見つかりません'}), 404
            
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    
    finally:
        conn.close()

@app.route('/static/media/<path:filename>')
def serve_media(filename):
    """
    メディアファイルを提供
    """
    # UPLOAD_FOLDER ('static/media') からの相対パスを指定
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# メインプログラムエントリーポイント
if __name__ == '__main__':
    # データベースを初期化（初回実行時）
    # init_db()  # 初回実行時はコメントを外す
    
    # Flask開発サーバーを起動
    # 本番・開発ともデバッガーは無効。必要な診断はログで行う
    # port=5000 ポート番号を設定
    app.run(debug=False, port=5000)
