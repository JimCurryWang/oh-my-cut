# taste/

```
taste/
├── <style>/
│   ├── videos/          參考影片（不進 git）。自己放，或用 yt-dlp 下載
│   └── profile/         /taste-profile 產生的快取
│       ├── style.md         可讀的風格描述 —— 可以直接改
│       ├── style.json       skill 讀的數字與設定
│       ├── style.stats.json 腳本量測的原始數字
│       ├── manifest.json    影片指紋；影片有變才會重跑
│       └── index/           每支參考影片的索引與觀察筆記
└── _me/
    ├── preferences.md   我核准過的規則（優先度最高）
    └── decisions.jsonl  A/B 選擇與口頭回饋的紀錄
```

新增一種風格：建 `taste/<名稱>/videos/`，放進 2–5 支影片，執行 `/taste-profile <名稱>`。
一種風格放「手法一致」的影片；手法差很多的請分成兩種風格。
