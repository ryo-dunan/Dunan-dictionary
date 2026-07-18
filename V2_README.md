# 与那国語オンライン辞書 v2（移行中）

v2は現行アプリとDBを直接変更せず、コピーしたDB上で開発します。

## 初回移行

```bash
cd 与那国語オンライン辞書
./v6/venv/bin/python scripts/migrate_to_v2.py
./v6/venv/bin/python scripts/manage_users.py owner "管理者名" --role admin
```

移行処理は先に `backups/` へ日時付きバックアップを作り、孤立レコードを
`quarantine_records` に保全してからv2 DBを生成します。既存DBは変更しません。

## 起動

秘密鍵を環境変数で設定して起動します。秘密鍵やパスワードをファイルへ書かないでください。

```bash
export YONAGUNI_SECRET_KEY="十分に長いランダムな値"
./v6/venv/bin/python run_v2.py
```

管理画面は `http://127.0.0.1:5001/v2/login` です。本番ではHTTPSを使い、
`YONAGUNI_HTTPS=1` を設定します。

## 現在利用できる編集フロー

1. ダッシュボードから「新しい語彙を登録」を開く
2. 見出し語、意味、例文などを下書き保存する
3. 自分以外のメンバーへ確認を依頼する
4. 確認担当者が、公開・コメント付き差し戻し・管理者判断のいずれかを選ぶ

公開が選ばれるまで語彙は `unpublished` のままです。登録者・修正者本人を
確認者に指定する操作は、画面とデータベース制約の両方で拒否されます。

## テスト

```bash
./v6/venv/bin/python -m unittest discover -s tests -v
```

運用開始手順は [OPERATIONS.md](OPERATIONS.md)、編集担当者向け説明は
[USER_GUIDE.md](USER_GUIDE.md) を参照してください。

## Renderへデプロイ

このリポジトリには、アカウントと操作履歴を除去した公開用初期DBが含まれます。
Renderでは `render.yaml` を使ってBlueprintを作成してください。初回作成画面で
次の3項目を入力します。

- `YONAGUNI_ADMIN_USERNAME`
- `YONAGUNI_ADMIN_DISPLAY_NAME`
- `YONAGUNI_ADMIN_PASSWORD`（12文字以上）

初回起動時だけ初期DBと同梱媒体を永続ディスクへコピーし、管理者を作成します。
その後のデプロイでは運用DB、アップロード媒体、バックアップを上書きしません。
永続ディスクを使用するため、BlueprintはStarterプランを指定しています。

初期DBを現在のローカル辞書から更新する場合は、運用DBを直接公開せず、次を実行します。

```bash
python scripts/build_render_seed.py
```
