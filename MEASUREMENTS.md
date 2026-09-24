# Qwen-Image-2.1 / ComfyUI 実測ログ（RTX 4070 12GB）

このリポジトリの README に出ている数字の元になった生の計測記録です。
ComfyUI + 公式 `int8_convrot` 重みの話だけを書いています。

## 計測方法（共通の前提）

- 機材: RTX 4070 12GB（sm_89 / ドライバ 610.57.04 / CUDA 12.9）、重みは Comfy-Org の
  `qwen_image_2.1_int8_convrot.safetensors` + `qwen3vl_8b_int8_convrot.safetensors` +
  `qwen_image_2.1_vae_bf16.safetensors`。
- 比較はすべて**同一プロンプト・同一seed**。cfg 1.0 / euler simple、ステップ数は明記した箇所を除き
  長辺1024px以下は12、それより大きければ20（1:1の1MPは12、4:3・16:9の1MPは20）。
- 「warm」は**モデルがすでに読み込まれた状態での2回目以降**。ComfyUI を再起動した直後の1回目は
  これより遅い（別項目参照）。
- 時間は ComfyUI の history に出る `execution_start` → `execution_success`（exec）と、
  API に投げてから画像が返るまでの wall の両方。表は主に exec。
- 同じプロンプト+seedで測ると ComfyUI 本体の実行キャッシュに当たって0.1秒で返るので、
  **時間を測るときは毎回 seed を変えて**います（下の「実行キャッシュ」参照）。
  なお `control after generate` は**既定で randomize**（ノードが有効化しており、同梱ワークフローも
  randomize）なので、UIから手で押す限りこのキャッシュには当たりません。この文書の数値は再現できるよう seed を固定して測っています。
- スクリプト: `test_qwen21.py`（サイズ3種・3枚バッチ・編集2種）、`test_qwen21_edit.py`（任意画像の編集）。

## 1. 主要な数字

| ケース | 時間 |
|---|---:|
| 1024x1024（1MP）・12ステップ・cfg 1.0 | **9.6 秒**（warm。再起動直後は13〜14秒） |
| 1024x1024・25ステップ（公式ワークフロー相当・cfg 1.0） | 14.0 秒 |
| 1920x1088（16:9・2MP）・20ステップ | 30.7 秒 |
| **2048x2048（4MP・ネイティブ2K）・20ステップ** | **90.5 秒** |
| 2048x2048・12ステップ | 56.2 秒（2Kでは12ステップは描き込み不足。20を使う） |
| 1024x1024 を3枚まとめて（`count=3`） | 24.2 秒（1枚あたり約8秒） |
| 参照画像1枚で編集（1024x1024・12ステップ） | 16〜17 秒 |
| 参照画像2枚で編集 | 25.9 秒 |
| 参照画像3枚で編集 | 36.4 秒 |

- 1ステップあたり: **1MPで約0.34秒 / 4MPで約4.3秒**（固定費を除いた、ステップ数に比例する部分）。
- 固定費（プロンプトの符号化・VAEデコード・モデルの入れ替え）が**約5秒**。
  1024x1024・12ステップの9.6秒のうち、およそ5秒がこれで、残りが12ステップ分。
  だからステップ数を12→25に増やしても 9.6 → 14.0 秒（+4.4秒）しか増えない。
- **再起動直後が遅い理由**: 重み17GBは12GBのVRAMに載りきらないため、ComfyUI の動的VRAM機構が
  必要な部分を毎回入れ替える。再起動後の1回目だけはこの入れ替えとグラフ準備を全部払うので
  1MP12ステップが13〜14秒かかり、2回目以降（warm）は9.6秒になる。
- **`count=3` が1枚あたり安い理由**: 上と同じ固定費・テキスト符号化・モデル入れ替えを
  バッチ全体で1回しか払わないため。3枚で24.2秒＝1枚あたり約8秒で、3回別々に走らせるより安い。

## 2. 編集モード（参照画像あり）の実測

| 参照画像の枚数 | 時間（1024x1024・12ステップ） |
|---|---:|
| 1枚 | 17.0 秒 |
| 2枚 | 25.9 秒 |
| 3枚 | 36.4 秒 |

- 増え方はほぼ線形で、**1枚あたり+9〜10秒**。理由は参照画像1枚につき約**4096トークン**
  （＋視覚側のパディング768）ぶんの情報がテキストエンコーダと画像生成器に追加されるためで、
  重みのサイズではなくこれが12GBカードで何枚まで入るかを決めている。
- **`reference_fit` の挙動**: `match output`（既定）は参照画像を出力解像度に合わせてリサイズする。
  `keep original size` は参照を元のサイズのまま使う（テキストエンコーダに `resolution=0` を渡す）。
  後者が軽くなるのは**参照が出力より大きいときだけ**で、1024x1024の参照では両者ほぼ同じ
  （実測 15.9秒 vs 16.7秒。別プロンプト・別seedなので厳密なA/Bではない）。参照1枚あたりの
  トークン数を抑えられるので、3枚以上を12GBに収める手段にはなる。
- **編集モードの出力サイズは参照画像の縦横比で決まる**（`aspect_ratio` は効かない）。このとき
  `megapixels` が決めるのは**面積**で、テキストエンコーダは「ウィジェットの長辺を一辺とする正方形と
  同じ面積」になるよう参照を縮尺する。実測: 16:9の参照（768x432）＋ `megapixels=2` / `aspect_ratio=1:1`
  → 出力 **1920x1088**（1440x1440とほぼ同じ面積。ウィジェット通りなら1440x1440）。`megapixels=0.5`
  では **992x544**（736x736とほぼ同じ面積）。
  ノードの `info` は潜在表現から読んだ実サイズを報告する（以前はウィジェット値を報告していた）。
- 1枚参照の編集は12ステップで16〜17秒（API実測15.9〜17.0秒）。3ステップ違うだけの12 vs 20を
  同一seedでA/Bすると、**12のほうが被写体を少しよく保ち、かつ約4秒速い**。公式の編集テンプレートは
  25ステップなので、ここは好みの範囲。
- **編集プロンプトの書き方**: 「変えたいこと」を言ってから「残したいもの」を言う。
  例: *"change the tablecloth to a deep blue linen and add a small sprig of rosemary,
  keep the teapot and cups exactly as they are"* — テーブルクロスとローズマリーは変わり、
  ティーポット・針金の取っ手・注ぎ口・蓋・カップ2つは無傷で残った（目視で確認）。

## 3. ノード「Qwen 2.1 Fast Generate」の実測値

`custom_nodes/qwen21_fast/`（`Qwen21FastGenerate`）を ComfyUI の API 経由で最終スキーマで回した値。

| ケース | exec | wall |
|---|---:|---:|
| `t2i_1mp`（1024x1024・12ステップ・cfg 1.0） | 13.6 秒 | 14.0 秒 |
| `t2i_16x9_2mp`（1920x1088・20ステップ） | 30.7 秒 | 31.0 秒 |
| `t2i_1mp_count3`（1024x1024 を3枚） | 24.2 秒 | 25.0 秒 |
| `edit_match_output`（参照1枚・`match output`） | 15.9 秒 | 16.1 秒 |
| `edit_keep_size`（参照1枚・`keep original size`） | 16.7 秒 | 17.0 秒 |

- ノード側で `steps=0` のときは**長辺が1024px以下なら12**、それより大きければ20を選ぶ（上の実測に基づく既定）。
- **読み込んだモデルはノード内でキャッシュしている**: 7GBのDiTを読み直すと1実行あたり
  約2.5〜5秒かかるため、読み込んだオブジェクトを**コンポーネント単位**（`model` / `clip` / `vae`）で
  名前をキーに保持する。名前を変えたときはその1つだけ読み直し、差し替えるときは古い方を先に手放す。
- 同じプロンプト+seedを再投入すると **0.1秒で返る**（ComfyUI本体の実行キャッシュ。GPUは動かない）。
  これは正常動作だが、時間を測るときは seed を必ず変えること。

### 3-1. GGUF 対 int8 の A/B（同一プロンプト・同一 seed・1024x1024/12ステップ・各6回）

| DiT（他は同一: int8 エンコーダ + Comfy-Org VAE） | exec 中央値 | 範囲 | サンプラー自身の s/step | 固定費（最小二乗） | ピークVRAM |
|---|---:|---|---:|---:|---:|
| 公式 `int8_convrot`（`UNETLoader`） | **11.8 秒** | 10.4〜13.1 秒 | 0.52 | 5.65 秒 | 11.6〜11.7 GB |
| unsloth `qwen-image-2.1-Q4_K_M.gguf`（`UnetLoaderGGUF`） | **24.3 秒** | 21.7〜26.3 秒 | 1.38 | 6.89 秒 | 11.1〜11.8 GB |

- 比は **end-to-end で約2.0倍**（warm のみの中央値でも 11.7 対 23.4 秒＝2.00倍）、**ステップあたり約2.6倍**。
  両アームが共通で約6秒の固定費（テキストエンコード＋VAEデコード＋起動）を払うため、12ステップでは
  end-to-end の比率がステップ比より小さく出る。
- 出力は同一 seed でピクセル相関 **0.9929**（平均絶対差 0.0144）。同じ絵ではないが近い。同一アームの
  繰り返しはビット一致（相関 1.000000）。
- 注意: この計測は他の CPU/ディスク作業（Unsloth Desktop のインストール）と同時に走らせており、
  **絶対値は10%程度高め**に出ている可能性がある。比は安定（ペアごとに1.65〜2.53倍、中央値で2.07倍）。
  以前 quiet なマシンで測った 9.6 秒はこの表の int8 より速いが、同一条件での再測では 10.4 秒未満は出なかった。
- GGUF アームは `/free` で重みを落としてから実行（cold を本当に cold にした）。同じグラフの再投入は
  0.0〜0.14 秒で返る（ComfyUI の結果キャッシュ）ため、比較のたびに seed を固定しつつグラフを変えて実行した。

### 3-2. 参考: 他エンジンとの比較（1024x1024・12ステップ・同一プロンプト・cfg/guidance 1.0・seed 4242）

| エンジン | 重み | 時間 | 1ステップ | 備考 |
|---|---|---:|---:|---|
| **ComfyUI（このリポジトリの手順）** | 公式 `int8_convrot` | **11.8 秒** | 0.52 秒 | 12GBに常駐（9.5GB）。W8A8 cuBLAS |
| stable-diffusion.cpp（単体C++） | unsloth GGUF Q4_K_M | 16.0 秒 | — | 以前の計測 |
| ComfyUI | unsloth GGUF Q4_K_M | 24.3 秒 | 1.38 秒 | 毎ステップ重みを展開 |
| Unsloth Desktop（diffusers 経路） | unsloth GGUF Q4_K_M | 29.5 秒 | 2.15 秒 | streaming CPU offload、fbcache 不可 |

- Unsloth Desktop は**そのGGUFの本来の想定環境**（公式ドキュメントは12〜16GBに GGUF Q4_K_M / 1024x1024 を推奨）だが、
  このカードでは4経路中もっとも遅い。内訳は 12ステップ29.5秒 対 20ステップ46.7秒 から **約2.15秒/step＋固定費約3.7秒**で、
  遅さは**ステップ側**にある（ComfyUI int8 は0.52秒/step）。
- 理由は GGUF そのものより**オフロード**：`images/status` が `cpu_offload: true, offload_policy: "streaming"`、
  `vae_tiling: true`、`dtype: bfloat16` を返し、ログには `fbcache unavailable (transformer reuses a prefix KV
  cache ...)` が出る（12GBに収まらない構成を毎ステップRAMから流している）。初回は加えて torch.compile の
  バンドル生成に約84秒かかり、2回目以降は29.5秒に落ち着く。
- Unsloth Desktop の `transformer_quant: int8`（pre-quant 7.26GB を使う速い経路）は、**この12GBカードでは
  使えない**（実測）。`memory_mode: fast`（重みを常駐させる指定）でも同じで、バックエンドのログは
  `required=35712 MiB budget=7361 MiB free=9409 MiB policy=model (fast requested but weights do not fit
  resident; offloading)` と記録する。ロードは次のエラーで拒否される:
  `the quantised build still needs 'model' offload here (35712 MiB required vs a 7318 MiB budget), and
  torchao tensors cannot be offloaded`。つまり12GBでは**GGUF＋dequant 経路しか選べない**。
- したがって Unsloth Desktop の 2.08 秒/step は「4bit重みを毎ステップbf16へ展開する」コストと、
  diffusers 側の実行オーバーヘッドの合算。同じ GGUF ファイルでも ComfyUI は 1.38 秒/step、
  dequant が不要な int8 は 0.52 秒/step（ComfyUI は int8 safetensors を低VRAM向けに部分ステージング
  できるので12GBでも成立するが、Unsloth の torchao int8 にはその逃げ道が無い）。

## 4. ComfyUI 側の落とし穴（実際に踏んだもの）

1. **cfg を1.0より上げると計算が2倍**。cfg > 1 ではステップごとに無条件（unconditional）側の
   フォワードパスがもう1回走るため、概ね2倍の時間になる。公式設定は cfg 1.0 / euler simple。
   ノードが cfg とサンプラーを表に出していないのはこのため（1.0固定）。ネガティブプロンプト欄も
   ない: cfg 1.0 では ComfyUI が無条件パスを丸ごと省略する（`comfy/samplers.py` の
   `math.isclose(cond_scale, 1.0)`）ので、ネガティブ条件は評価されず、入力しても何も起きない。
2. **GGUF の再パックは ComfyUI では遅い**。unsloth の **DiT GGUF は `kv_count=0`**（メタデータ無し）で、
   `general.architecture` が読めないため ComfyUI-GGUF は推測経路に落ち、`Unknown model architecture!` に
   なる。テキストエンコーダの GGUF は**正しいメタデータ**（`general.architecture=qwen3vl`、kv 45件、
   `embedding_length=4096`、`feed_forward_length=12288`）を持っており、以前の
   `rms_norm: ... got [1, 512, 12288]` の原因はメタデータ欠落ではない（12288 はこのファイルが宣言している値）。
   GGUFを使うには
   `ComfyUI-GGUF` カスタムノードと、`custom_nodes/ComfyUI-GGUF/tools/convert.py` に
   Qwen-Image-2.1 のシグネチャ（`arch = "qwen_image"`、キー
   `transformer_blocks.0.img_mlp.gate_up.weight`）を足す小さなパッチが要る。パッチで通しても
   **end-to-end で約2.0倍遅い**（上の 3-1 のA/B: 11.8秒 対 24.3秒、ステップあたりは約2.6倍）
   — ComfyUI が int8 カーネルを使えず毎回展開するため。よってこの環境では公式 `int8_convrot`
   safetensors を使う。
3. **Qwen-Image-2.1 の VAE は2種類あり、レイアウトが違う**。どちらも**4チャンネル（アルファ対応）**で、
   出力畳み込みが Comfy-Org 版は `decoder.head.2.weight [4,144,1,3,3]`（modelspec/3D）、
   unsloth の FP8 リポジトリ内のものは `decoder.conv_out.weight [4,144,3,3]`（diffusers/2D）。
   ComfyUI の Qwen-Image-2.1 が期待するのは modelspec 側なので、unsloth 版を選ぶと
   `encoder.conv_in` / `decoder.conv_out` で `size mismatch` の山になる。
   3チャンネルの Qwen VAE（`decoder.head.2.weight [3,96,3,3,3]`）は **Qwen-Image 1.0** のもので別モデル。
4. **ComfyUI は同一グラフをキャッシュする**。同じプロンプト+seedだと 0.1秒で返り、GPUは動かない。
5. **`QwenImage21Cache`（量子化 prefix-KV キャッシュ）はこの環境で動かない**。int8 も int4 も
   `aimdo memory compile error` で落ちる（動的VRAMの C 拡張が、このドライバ/torchビルドの組み合わせでは使えないため）。
   そのためノードは意図的にこれを公開していない。`comfy_aimdo` がこのドライバ/torchビルドに
   対応したら再検討。

## 5. 使ったファイルとグラフ構成

ComfyUI が見る場所へハードリンクして使っている（`install.sh` がやるのと同じ配置）:

- `diffusion_models/qwen_image_2.1_int8_convrot.safetensors`（7.26 GB、Comfy-Org）
- `text_encoders/qwen3vl_8b_int8_convrot.safetensors`（9.35 GB、Comfy-Org）
- `vae/qwen_image_2.1_vae_bf16.safetensors`（0.68 GB、Comfy-Org）

グラフ:

```
UNETLoader → CLIPLoader (type=qwen_image) → TextEncodeQwenImage21 → KSampler → VAEDecode → SaveImage
```

ノード `Qwen 2.1 Fast Generate` は上のコアノードを内部で組み合わせているだけで、
ComfyUI 側のモデル実装を自前で持っていない。

## 6. 再現手順

```bash
cd <このリポジトリ>
./check.sh                 # bash構文 / py_compile / ワークフローJSON の静的チェック
python3 test_qwen21.py     # 起動中のComfyUIに対し 5ケースを実行（5/5 ok で成功）
python3 test_qwen21_edit.py <参照.png> "<指示文>" [メガピクセル] [keep]   # 任意画像の編集を1回だけ
```

ワークフローを開いて手で回す場合は `workflows/` 内の3つのJSONを
`~/ComfyUI/user/default/workflows/` にコピーする。画像編集の2つは
`docs/demo/source.png` を `~/ComfyUI/input/qwen21_demo_source.png` にコピーして使う。
