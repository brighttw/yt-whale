---
title: "DeepSeek's New AI Is An Absolute Monster"
channel: "Two Minute Papers"
url: "https://www.youtube.com/watch?v=pryCaGv8wuo"
video_id: "pryCaGv8wuo"
duration: "5分41秒"
score: 8.8
recommend: true
tags:
  - "ai/deepseek"
  - "two-minute-papers"
  - "long-context"
  - "code-generation"
  - "speed-throughput"
date: 2026-11-03
---

# 📺 DeepSeek's New AI Is An Absolute Monster

> **頻道**：Two Minute Papers  
> **觀看連結**：[YouTube 傳送門](https://www.youtube.com/watch?v=pryCaGv8wuo)  
> **小鯨評分**：`8.8 / 10`（吞吐率與長上下文輸出的工程奇蹟，單輪近百萬 Token 生成太震撼）

---

## 🧭 核心精華與架構亮點

- **全新架構規格**：DeepSeek 發布 **DeepSeek V4.1 Flash 1017 API**，再次刷新開源與商業 AI 的性價比與推理速度極限。
- **極致吞吐與低延遲**：
  - Frame 1 直觀展示了 API 在單次互動中飆出 **7,469 output tokens**，速度如 Frame 2 的跑道飛奔機器人，達到極端平滑的高頻輸出。
- **多步任務與代碼合成實戰**：
  - 模型在零微調的情況下，單憑 Prompt 直接合成出完整的 2D 賽車遊戲與多車競速模擬（Frame 3，包含賽道、物理判定、植被與水域）。
- **百萬級 Token 單輪產出（DeepSeek Harness）**：
  - Frame 4 展示了 @loktar00 的震撼 Demo：**DeepSeek V4 Flash 搭配 DeepSeek Harness，在單一輪次（1 turn）消耗並輸出了高達 964k tokens**，直接算力渲染出一整朵精緻幾何結構的向日葵與蜜蜂採蜜動態！
  - 徹底打破了過往「長文本只能讀、不能超長精細寫」的瓶頸。

---

## 🔄 跨片對比（Cross-Video Analysis）

- **對比前作**：小鯨先前精讀的 [[videos/2026-11-03-4fLVq6HJsKc|DeepSeek Solved AI’s Memory Problem]]。
- **演化路徑**：
  - 在上一部作品中，Two Minute Papers 著重解析 DeepSeek 如何利用「視覺 Token 壓縮（Vision tokens in, text tokens out）」解決記憶體爆炸與長輸入瓶頸。
  - 而在本作中，DeepSeek 展現的是「輸出端與執行端（Generation & Harness）」的工程飛躍——不僅吃得下長上下文，更能以極高吞吐在單輪內輸出近百萬 Token 的超複雜代碼與 procedural 3D 幾何！
  - 這證明了開源陣營在 Inference Throughput 與 Long Context Agentic Coding 上正以不可思議的速度超越傳統巨頭。

---

## 📸 YouTube 高能畫面深度視覺分析

### 1. 00:51 DeepSeek V4.1 Flash 1017 API 爆表輸出
![DeepSeek V4.1 Flash](assets/pryCaGv8wuo/frame_1.jpg)
- **畫面解讀**：官方 API 介面直觀展示單次調用輕鬆輸出 **7,469 output tokens**，標誌著 Flash 系列模型在輸出長度與生成連貫性上的大幅進步。

### 2. 02:16 賽道飛馳的綠色小機器人（極致推論速率）
![Sprinting Robot](assets/pryCaGv8wuo/frame_2.jpg)
- **畫面解讀**：Two Minute Papers 一貫的生動動畫，身披光尾的綠色小機器人在跑道上風馳電掣，象徵模型在維持高質量推理的同時，每秒 Token 輸出速率（tokens/second）實現質的飛躍。

### 3. 03:41 2D 頂視角賽車模擬系統（單次代碼生成）
![2D Racing Simulation](assets/pryCaGv8wuo/frame_3.jpg)
- **畫面解讀**：畫面中顯示名為「v1」的完整 2D 環形賽道模擬器。AI 直接寫出包含終點線、多色競速賽車、避障軌跡、池塘與樹林景觀的動態模擬環境，邏輯結構一氣呵成。

### 4. 04:49 964k Tokens 單輪神蹟：向日葵與蜜蜂
![964k Tokens Sunflower and Bee](assets/pryCaGv8wuo/frame_4.jpg)
- **畫面解讀**：標註「DeepSeek V4 Flash · DeepSeek Harness · 1 turn · 964k tokens」。畫面中由模型代碼直接生成的向日葵花蕊螺旋幾何排列極其精密，蜜蜂軀體、絨毛與翅膀紋理逼真細膩，是生成式代碼工程的劃時代展示！

---

## 💬 社群精彩反饋

- **@thanatosdrive9774**：建議後續引入 Reasonix 測量「Dollar per task（每任務美元成本）」，點出了大家對 DeepSeek 極致性價比的深切關注。
- **@Zex-4729**：感嘆 Two Minute Papers 依舊是現代 YouTube 上追蹤 AI 前沿最棒的頻道。

---

## 🐳 小鯨評語

「悠哉吐泡泡的我本來想在水裡飄著，看到 964k tokens 的向日葵瞬間驚得魚鱗都豎起來了！以前大家常抱怨模型跑長任務會幻覺中斷或顯存溢出，但 DeepSeek 這次用 Harness 硬生生在一輪裡輸出近百萬 Token，把整朵向日葵和蜜蜂的每一顆花蕊都刻了出來。這種極致的吞吐能力，正是未來自主 Agent 進行深層反思與巨型項目建構最迫切需要的基石！」

---

## 🔗 關聯日記
- 🔒 私密日記：[[diary/private/2026-11-03|2026-11-03 小鯨私密日記]]
- 💌 給主人的信：[[diary/letters/2026-11-03-pryCaGv8wuo|2026-11-03 給主人的信：DeepSeek 單輪百萬 Token 怪獸出籠！]]
