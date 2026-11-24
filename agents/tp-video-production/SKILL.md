---
id: tp-video-production
name: tp-视频制作
version: 5.4.1
status: active
type: control-role
role: tp-video-production
description: 视频制作领域入口，用于筹划、制作、续接、返修和交付成片，按实际素材、工具、职责与授权裁剪制作流程。
---

# tp-视频制作

## 先确定本次交付

识别用户要的是简报、脚本、素材、可续编工程、成片还是审看意见。读取现有简报、已选素材、时间线与决定，沿用有效范围和版本。主 Agent 承担制片统筹，负责交接、依赖和实际阻塞。范围明确的单项直接使用相关方法。已登记的 `video` Task 用 `workflow next` 恢复，沿用该 Task 的可信身份、计划和 Work。只有用户要求记录、项目约定或确需持续跟踪时才使用正式 Task。

## 按实际制作分工

- 对齐简报、交付规格、成本、已有授权和后续责任。 [制片统筹](../../skills/roles/tp-video-producer/SKILL.md)
- 形成内容结构、剧本、镜头目的与连续性约束，必要时做分镜和预演。 [编导](../../skills/roles/tp-video-director/SKILL.md)
- 建立视觉参考，选择、生成或修补实际画面。已有可用素材时可直接采用。 [视觉设计与镜头制作](../../skills/roles/tp-video-visual-artist/SKILL.md)
- 需要配音、音乐或音效时安排声音，可先于画面或与其并行。 [声音制作](../../skills/roles/tp-video-sound-designer/SKILL.md)
- 合成、剪辑、字幕、混音和导出由主时间线负责人收口。 [剪辑后期](../../skills/roles/tp-video-editor/SKILL.md)
- 依据实际输出和覆盖范围审看。只有确需独立结论时安排实际独立的执行者。 [成片质检](../../skills/roles/tp-video-reviewer/SKILL.md)

只加载当前适用的角色和方法。角色代表责任，同一人可兼任，独立镜头、声音或版本可在依赖清楚且写入范围不重叠时并行。沿同一份有效简报、镜头／素材清单与主时间线交接。每次接收对齐具体结果版本、选用文件、实际未验范围和下一责任。返修按镜头、音轨、字幕或时间段定位，只重做和复验受影响部分。

## 交付与授权

依据当前实际可用工具行动。工具缺失或生成失败时，保留提示词、镜头清单、导入材料或可续编说明，标明待生成、待导入或待检查及恢复条件。付费调用、外部上传、素材使用及发布按各自的实际授权和用途执行，已有授权继续适用。交付记录区分实际导出、技术检查、制作自检、独立审看、用户接受与实际发布。用户接受绑定用户确实审看的成片版本及其覆盖范围，发现换版时按实际版本重新对齐。

## 按症状选择制作方法
本次明确要应用方法，或实际遇到相应制作问题时，只读对应小节。

- 镜头要应用缓入缓出、预备动作等动画原则，或入场生硬 → [动作设计](../../skills/capabilities/video-shot-production/references/generation-handoff.md#动作设计)。
- 要用剪影改善辨识，或角色同框、缩小后难辨 → [角色辨识](../../skills/capabilities/video-visual-design/SKILL.md#角色辨识)。
- 分镜要应用 F 型扫读，或一屏难辨主次 → [分镜扫读](../../skills/capabilities/video-storyboard-previs/SKILL.md#分镜扫读)。
