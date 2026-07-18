# -*- coding: utf-8 -*-
# convert_excel_to_json.py - 辞書Excelファイルを一括導入用JSONに変換するスクリプト

import pandas as pd
import json
import re

def clean_data(data):
    """
    データから前後の空白を削除し、空の場合はNoneを返す
    """
    if isinstance(data, str):
        stripped_data = data.strip()
        return stripped_data if stripped_data else None
    return data

def split_semicolon_or_comma(text):
    """
    セミコロン、全角コンマ、半角コンマで文字列を分割する
    """
    if not text or pd.isna(text):
        return []
    # 複数の区切り文字（；、;、 、,）で分割
    items = re.split(r'[；;、,]', str(text))
    # 各要素の前後の空白を削除し、空の要素を削除
    return [item.strip() for item in items if item and item.strip()]


def convert_excel_to_json(excel_path, json_path):
    """
    Excelファイルを読み込み、指定されたJSONフォーマットに変換して保存する
    
    :param excel_path: 入力となるExcel/CSVファイルのパス
    :param json_path: 出力するJSONファイルのパス
    """
    
    # 複数の文字コードを試す
    encodings_to_try = ['utf-8', 'utf-8-sig', 'cp932']
    df = None
    
    # 新しいファイルに合わせて、ヘッダー前にスキップする行数を1に設定
    rows_to_skip = 1
    
    for encoding in encodings_to_try:
        try:
            df = pd.read_csv(excel_path, encoding=encoding, skiprows=rows_to_skip)
            print(f"情報: ファイルを '{encoding}' として正常に読み込みました（先頭{rows_to_skip}行をスキップ）。")
            break
        except UnicodeDecodeError:
            continue
        except FileNotFoundError:
            print(f"エラー: ファイルが見つかりません: {excel_path}")
            return
        except Exception as e:
            if 'Error tokenizing data' in str(e):
                continue
            print(f"ファイルの読み込み中に予期せぬエラーが発生しました: {e}")
            return
            
    if df is None:
        print(f"エラー: ファイルの読み込みに失敗しました。")
        print(f"試したエンコーディング: {', '.join(encodings_to_try)}")
        print("お手数ですが、テキストエディタでファイルを開き、「UTF-8」形式で保存し直してから再度お試しください。")
        return

    # --- ★★★ 修正点 ① ★★★ ---
    # 列名の前後に空白があった場合に備えて、空白を削除する
    df.columns = df.columns.str.strip()
    
    # --- ★★★ 修正点 ② ★★★ ---
    # 1列目の列名にBOM (Byte Order Mark `\ufeff`) が含まれている可能性に対処
    if df.columns[0].startswith('\ufeff'):
        # BOMを削除して列名を変更する
        df.rename(columns={df.columns[0]: df.columns[0].lstrip('\ufeff')}, inplace=True)

    print(f"情報: 検出された列名 -> {df.columns.tolist()}")

    # NaN（Not a Number）をNoneに置換
    df = df.where(pd.notna(df), None)

    all_entries = []

    for index, row in df.iterrows():
        # 見出し語列が存在し、かつ値がある行のみ処理
        if '見出し' not in row or pd.isna(row['見出し']):
            continue

        meanings_ja = split_semicolon_or_comma(row.get('意味'))
        synonyms_list = split_semicolon_or_comma(row.get('同義語'))
            
        verb_class_value = clean_data(row.get('音韻')) if clean_data(row.get('品詞')) == '動詞' else None

        entry = {
            "headword": clean_data(row.get('見出し')),
            "kana": clean_data(row.get('見出し')),
            "ipa": clean_data(row.get('音韻')),
            "pos": clean_data(row.get('品詞')),
            "verb_class": verb_class_value,
            "tone": clean_data(row.get('トーン')),
            "etymology": clean_data(row.get('語源')),
            "historical_change": clean_data(row.get('音変化')),
            "synonyms": synonyms_list,
            "meanings": {"ja": meanings_ja},
            "conjugations": [],
            "examples": []
        }
        
        all_entries.append(entry)

    if not all_entries:
        print("警告: 処理できるデータが見つかりませんでした。CSVの列名（見出し、品詞など）が正しいか、スクリプトで検出された列名と一致しているか確認してください。")
        return

    try:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(all_entries, f, ensure_ascii=False, indent=2)
        print(f"✅ 変換成功！ {len(all_entries)}件の見出し語を '{json_path}' に保存しました。")
    except Exception as e:
        print(f"JSONファイルへの書き込み中にエラーが発生しました: {e}")


# --- ここから実行部分 ---
if __name__ == "__main__":
    # 入力ファイル名（ユーザーがアップロードしたファイル名に合わせてください）
    input_filename = "どぅなんむぬい辞典第２版excel.csv"
    
    output_filename = "yonaguni_dict_import.json"
    
    convert_excel_to_json(input_filename, output_filename)
