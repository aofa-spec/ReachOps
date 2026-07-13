# ReachOps 商业化审计行动索引

- 日期：2026-07-13
- 审计基线：`main@0c6d6e503b9c29653ddda131384d93fc9bc3a564`
- 主审计：`ReachOps/docs/REACHOPS_PRODUCT_COMMERCIAL_AUDIT_2026-07-13.md`
- 当前发布结论：`Controlled Alpha`，可做内部演示与受控无提交试点，不可声明 GA

## 1. 产品决策

### 当前应销售的产品

**TikTok 社媒意图雷达 + 人工授权的本地销售执行工作台。**

客户价值链：

```text
公开互动信号
-> 意图识别与可解释排序
-> 人工接受的合格商机
-> 授权跟进
-> 回复 / 有效对话
-> 会议 / 报价 / 订单
```

### 当前不得承诺

- 全自动群控获客；
- 无人值守批量评论、关注或私信；
- 已验证稳定出单；
- 可规避平台风控；
- 已完成全渠道获客平台；
- fixture / dry-run 数据等同真实客户效果。

### 北极星指标

`WAQO = Weekly Accepted Qualified Opportunities`

定义：每周由人工负责人接受、来源与证据可追溯、完成去重，并进入有效跟进流程的合格商机数。

## 2. 发布门禁

| 阶段 | 当前判定 | 必须满足 |
|---|---|---|
| 内部演示 | 有条件通过 | 默认 no-submit、明确环境阻断、结果不冒充真实效果 |
| 无提交真实试点 | 暂未通过 | 真实账号池、100 次真实运行、质量和证据门槛 |
| 人工授权付费试点 | 不通过 | G0-G2 全过，授权/更新安全和受控动作门槛通过 |
| 可复制商业交付 | 不通过 | 商业控制面、数据治理、支持与单位经济闭环 |
| GA | 不通过 | G0-G5 全部通过，连续两个版本周期无 P0 回归 |

## 3. 已创建 Issue

### P0：进入付费试点前必须关闭

1. `#1 Enforce CI, PR review, and deterministic release baseline`
   - 合并 CI；开启主分支保护；依赖锁定；许可证清单；release evidence JSON；rollback note。
2. `#2 Freeze the /api/start contract and restore a zero-failure test baseline`
   - 统一启动门禁、缓存策略和错误合同；全量测试归零。
3. `#3 Certify a real account-readiness pool and no-submit evidence pack`
   - 建立至少 30 个已验收账号；完成 100 次真实无提交运行。
4. `#4 Harden licensing, entitlement, and the update supply chain`
   - 签名授权与更新；打包态不可旁路；HTTPS、撤销、设备审计。
5. `#5 Add versioned migrations, backup/restore, retention, and privacy controls`
   - 版本化迁移、备份恢复、数据目录、导出删除和保留策略。
6. `#6 Instrument WAQO and the full lead-to-revenue outcome funnel`
   - 从信号、线索、接受、触达到回复、会议、报价、订单和收入。

### P1：付费试点到可复制交付

7. `#7 Build the commercial control plane and decouple channel connectors`
   - Workspace/RBAC/seat/entitlement；连接器契约；拆分 Web 单体。

## 4. 优先顺序

```text
#1 CI 与分支保护
  -> #2 测试与启动合同归零
  -> #3 真实账号池与无提交证据
  -> #4 授权/更新安全 + #5 数据治理（可并行）
  -> #6 商业结果漏斗
  -> G2 无提交试点签字
  -> G3 受控动作试点
  -> #7 商业控制面和连接器解耦
  -> G4 付费与单位经济验证
  -> G5 GA
```

## 5. PR 审查清单

本审计 PR 只建立治理和验收基线，不宣称修复业务阻断。

审查人需要确认：

- [ ] 产品定位已从“全自动获客平台”收窄到当前真实能力；
- [ ] 评分 42/100 和 Controlled Alpha 判定符合证据；
- [ ] G0-G5 的门槛可以被脚本、报告或客户样本证明；
- [ ] CI 明确区分离线工程检查与外部真实验收；
- [ ] 所有 P0 Issue 有负责人、截止日期和验收证据路径；
- [ ] 未把历史 Windows 或 fixture 结果当作当前最终交付证据；
- [ ] 合并后设置 `main` 分支保护并把 CI 设为 required checks。

## 6. 第一阶段验收命令

离线工程门禁：

```bash
python -m compileall -q ReachOps tools tests
python -m unittest discover -s tests -p "test_*.py" -v
python tools/verify_reachops_dependency_baseline.py --json
python tools/reachops_delivery_audit.py --json
python tools/reachops_web_panel_dom_smoke.py --json
python tools/reachops_web_panel_runtime_smoke.py --json
python tools/reachops_repository_cleanliness_check.py --json
```

真实环境门禁不能由 GitHub CI 代替：

```bash
python tools/reachops_client_delivery_check.py --json
python tools/reachops_goal_delivery_runner.py --json
python tools/reachops_delivery_package_check.py --json
python tools/reachops_final_acceptance_gate.py --json
python tools/reachops_release_evidence.py --json
```

另外必须提交：`reachops-release-evidence.json`、`reachops-rollback-note.md`、真实账号验收表、人工标注集、无提交运行证据包、授权动作审批与结果样本、客户 outcome 与单位经济报告。

## 7. 签字规则

任何阶段只有在以下条件同时成立时才允许签字：

1. 结论来自当前版本和当前环境，不使用过期成功快照覆盖实时失败；
2. 所有指标有样本量、时间范围、客户/环境边界和证据路径；
3. fixture、dry-run、preflight 与 live outcome 分开统计；
4. 未授权动作、重复触达、验证码绕过和数据泄露均为 0；
5. 产品、工程、安全、运营和商业负责人分别签字；
6. 未满足项只能标记 `blocked` 或 `pending_external_validation`，不得标记 `passed`。
