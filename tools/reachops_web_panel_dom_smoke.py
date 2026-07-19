# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.reachops_web_ui import html_page


def extract_inline_script(html: str) -> str:
    matches = re.findall(r"<script>(.*?)</script>", html, flags=re.S)
    return "\n".join(matches)


def run_dom_smoke() -> dict:
    html = html_page().decode("utf-8")
    script = extract_inline_script(html)
    checks: dict[str, bool] = {}
    if not script.strip():
        return {"status": "failed", "passed": False, "failed_checks": ["script_missing"], "checks": {"script_missing": False}}

    node_source = f"""
const vm = require('node:vm');
const calls = [];
const elements = {{}};
const responses = {{
  '/api/logs': {{running:false, paused:false, started_at:0, elapsed_seconds:0, last_stage:'', exit_code:null, run_session_state:'BLOCKED', run_session:{{schema_version:'reachops.run_session.v1', state:'BLOCKED'}}, evidence_bundle:{{schema_version:'reachops.evidence_bundle.v1', page_state_summary:{{schema_version:'reachops.page_state_summary.v1', snapshot_count:2, blocking_count:1, unknown_count:1}}, repair_summary:{{schema_version:'reachops.repair_summary.v1', decision_count:1, block_count:1, audit_events:[{{executable_steps:[{{step:'capture_unknown_state_bundle'}},{{step:'record_offline_learning_candidate'}}]}}]}}, risk_summary:{{schema_version:'reachops.risk_summary.v1', decision_count:1, blocked_count:1, block_execution_count:1, risk_action_count:1, human_review_required_count:1, decisions:[{{risk_actions:[{{step:'block_execution'}}]}}]}}, account_health_summary:{{schema_version:'reachops.account_health_summary.v1', event_count:2, cooldown_event_count:1, forced_cooldown_count:1, consecutive_failure_cooldown_count:1}}, run_recovery_summary:{{schema_version:'reachops.run_recovery_summary.v1', recovered:true, recovery_count:1, latest_reason:'PROCESS_INTERRUPTED', last_stage:'COLLECT profile=profile-1', result_error:'process_interrupted', no_ai_token_used:true}}, autonomous_preflight_reconciliation:{{schema_version:'reachops.autonomous_preflight_reconciliation.v1', status:'partially_matched', matched_route_count:1, unobserved_route_count:1, actual_page_states:['UNKNOWN_PAGE_STATE'], actual_risk_reasons:['LIVE_SUBMIT_NOT_AUTHORIZED'], risk_gate_aligned:true}}, autonomy_readiness_summary:{{schema_version:'reachops.autonomy_readiness_summary.v1', ready:false, passed_count:6, failed_count:2, failed_checks:['page_state_sensed','risk_gate_audited']}}, product_capability_summary:{{schema_version:'reachops.product_capability_summary.v1', ready:false, passed_count:3, failed_count:5, failed_phases:['phase_4_page_state_sensing','phase_6_account_risk_gate'], phases:[{{key:'phase_3_autonomous_execution', passed:true}},{{key:'phase_4_page_state_sensing', passed:false}}]}}}}, lines:[]}},
  '/api/snapshot': {{summary:{{}}, campaign_funnel:{{}}, operations:{{counts:{{}}, lead_view:[], outreach_view:[], profile_queue:[], collection_tasks:[], outreach_executions:[], action_queue:[]}}, candidate_users:[], action_queue:[], profile_health:[], report_artifacts:[]}},
  '/api/acceptance': {{acceptance:{{readiness:'not_started', checks:{{}}, blockers:[], next_actions:[]}}, client_delivery:{{status:'blocked_by_environment', final_delivery_ready:false, failed_checks:['acceptance:ready']}}, mvp_acceptance:{{status:'mvp_accepted_external_pending', mvp_local_ready:true, final_delivery_ready:false, failed_checks:[], path:'/tmp/latest_mvp_acceptance_summary.json'}}, two_phase_acceptance:{{status:'local_mvp_accepted_final_pending', local_mvp_ready:true, final_delivery_ready:false, failed_items:['windows_final_artifacts','authorized_live_submit'], blocking_scopes:['external_authorized_execution','final_acceptance_gate','windows_final_artifacts'], path:'/tmp/latest_two_phase_acceptance_matrix.json', markdown_path:'/tmp/latest_two_phase_acceptance_matrix.md'}}, goal_delivery:{{status:'local_mvp_accepted_final_pending', local_mvp_ready:true, windows_build_ready:true, final_delivery_ready:false, delivery_boundary:{{summary:'本地 MVP 和客户端门禁已可验收；整项目最终交付仍未完成。', local_mvp_scope_ready:true, client_gate_scope_ready:true, windows_build_input_scope_ready:true, overall_final_delivery_scope_ready:false, client_gate_final_delivery_ready_is_not_overall_final_delivery:true, blocking_scopes:['windows_final_artifacts','external_authorized_execution']}}, failed_checks:['delivery_package:passed'], blockers:['windows_final_artifacts'], windows_package_preflight:{{status:'ready_for_windows_build', ready_for_windows_build:true, final_delivery_ready:false, missing_final_artifacts:['exe','installer','manifest','acceptance_summary'], default_build_requires_installer:true, skip_installer_is_non_final:true, preflight_report_path:'/tmp/windows_package_preflight.json'}}, path:'/tmp/latest_goal_delivery_report.json', summary_path:'/tmp/latest_goal_delivery_summary.md'}}, remediation_report:{{account_plan_markdown_path:'/tmp/gb_account_repair_plan.md', account_plan_json_path:'/tmp/gb_account_repair_plan.json', latest_account_plan_markdown_path:'/tmp/latest_account_repair_plan.md', latest_account_plan_json_path:'/tmp/latest_account_repair_plan.json'}}, account_repair_summary:{{status:'ok', profile_group:'Canada', operator_steps:['先处理 IXBROWSER_KERNEL_MISMATCH。'], error_groups:[{{error:'IXBROWSER_KERNEL_MISMATCH', count:39, profile_ids_sample:['21644','21647'], recommended_action:'修改内核版本或移出执行分组。'}}, {{error:'LOGIN_REQUIRED', count:13, profile_ids_sample:[], recommended_action:'完成 TikTok 登录。'}}]}}, latest_batch:{{}}, latest_profile_preflight:{{}}, operations:{{counts:{{}}, lead_view:[], outreach_view:[], profile_queue:[]}}}},
  '/api/product-capability': {{status:'ok', schema_version:'reachops.product_capability_summary.v1', product_capability_summary:{{schema_version:'reachops.product_capability_summary.v1', ready:true, passed_count:8, failed_count:0, failed_phases:[], phases:[{{key:'phase_3_autonomous_execution', passed:true}},{{key:'phase_8_evidence_delivery_loop', passed:true}}]}}, product_development_goals:{{schema_version:'reachops.product_development_goals.v1', ready:true, stage_count:8, current_focus:{{title:'证据与交付闭环'}}, stages:[]}}, delivery_boundary:{{schema_version:'reachops.delivery_boundary.v1', status:'local_capability_ready_final_pending', local_product_capability_ready:true, product_capability_ready:true, product_development_ready:true, final_delivery_ready:false, external_validation_pending:true, windows_final_artifacts_pending:true, pending_scopes:['external_authorized_execution','windows_final_artifacts'], final_delivery_blockers:[{{scope:'external_authorized_execution'}},{{scope:'windows_final_artifacts'}}], final_delivery_evidence_plan:{{schema_version:'reachops.final_delivery_evidence_plan.v1', ready:false, pending_scopes:['external_authorized_execution','windows_final_artifacts'], items:[{{scope:'external_authorized_execution', proof_fields:['goal_status.pending_external_validation=[]']}},{{scope:'windows_final_artifacts', required_artifacts:['dist\\\\ReachOps\\\\ReachOps.exe']}}]}}, next_actions:['完成授权真实触达验收。','生成 Windows 最终包。'], boundary_note:'本地产品能力 ready 只证明自治链路闭环；final_delivery_ready=true 才代表真实授权执行和最终客户端交付完成。', no_browser_started:true, no_submit:true}}, final_delivery_ready:false, external_validation_pending:true, no_ai_token_used:true, no_browser_started:true, no_submit:true}},
  '/api/activation': {{status:'blocked', ready:false, activation_status_exists:false, activation_status_path:'/tmp/reachops_activation_status.json', failed_checks:['activation_status_file_exists'], next_actions:['生成或放置真实激活状态文件，并设置 ActivationStatusPath。']}},
  '/api/ixbrowser-status': {{status:'blocked', ready:false, base_url:'http://127.0.0.1:53200/api/v2/', error:'ixBrowser Local API 未启动或端口不可连接', error_detail:'connection refused', no_browser_started:true, no_submit:true, next_actions:['确认 ixBrowser 客户端已启动，并在 ixBrowser 设置中开启 Local API。']}},
  '/api/start-preview': {{status:'ok', mode:'preflight', mode_label:'采集 + 触达预检', max_videos:3, max_comments:20, profile_limit:3, timeout_seconds:900, submit_policy:'预检，不提交', gate_state:'可启动', start_allowed:true, execution_plan_id:'plan_dom_preview', execution_plan_schema:'reachops.execution_plan.v1', no_browser_started:true, no_submit:true, preflight_decision:{{schema_version:'reachops.start_preflight_decision.v1', status:'ready', start_allowed:true, gate_state:'可启动', blockers:[], next_actions:['可以启动本地执行。'], submit_policy:'预检，不提交', no_ai_token_used:true, no_browser_started:true, no_submit:true}}, autonomous_preflight_forecast:{{schema_version:'reachops.autonomous_preflight_forecast.v1', status:'ready', start_allowed:true, predicted_state_sequence:['CREATED','PRECHECK','PROFILE_OPENING','COLLECTING','SCORING','ACTION_PLANNING','REPAIRING','COMPLETED'], predicted_blockers:[], repair_routes:[{{state:'LOGIN_REQUIRED', action:'quarantine_profile'}},{{state:'DOM_STALLED', action:'refresh_then_degrade'}},{{state:'MODAL_BLOCKED', action:'dismiss_known_modal_then_retry'}},{{state:'UNKNOWN_PAGE_STATE', action:'capture_error_bundle_then_block'}}], evidence_requirements:['execution_plan_snapshot','run_session_state_history','page_state_sidecar','repair_decision'], runtime_invariants:{{no_ai_token_during_execution:true, no_browser_started:true, no_submit:true, never_bypass_login_or_captcha:true, live_submit_allowed:false}}, no_ai_token_used:true, no_browser_started:true, no_submit:true}}}},
  '/api/final-status': {{status:'blocked', final_delivery_ready:false, no_browser_started:true, no_submit:true, delivery_boundary:{{schema_version:'reachops.delivery_boundary.v1', status:'local_capability_ready_final_pending', local_product_capability_ready:true, product_capability_ready:true, product_development_ready:true, final_delivery_ready:false, external_validation_pending:true, windows_final_artifacts_pending:true, pending_scopes:['external_authorized_execution','windows_final_artifacts'], boundary_note:'本地产品能力 ready 只证明自治链路闭环；final_delivery_ready=true 才代表真实授权执行和最终客户端交付完成。'}}, delivery_boundary_status:'local_capability_ready_final_pending', local_product_capability_ready:true, product_capability_ready:true, product_development_ready:true, external_validation_pending:true, windows_final_artifacts_pending:true, pending_scopes:['external_authorized_execution','windows_final_artifacts'], report_path:'/tmp/latest_live_acceptance_readiness.md', json_report_path:'/tmp/latest_live_acceptance_readiness.json', handoff_bundle_path:'/tmp/latest_reachops_authorization_handoff.zip', handoff_bundle_size:7631, handoff_bundle_verification:{{status:'passed', passed:true, failures:[], forbidden_files:[]}}, operator_commands:['powershell -ExecutionPolicy Bypass -File tools\\\\init_reachops_acceptance_inputs_windows.ps1 -Json','python tools\\\\reachops_live_acceptance_status.py --local-inputs-path tools\\\\reachops_acceptance_inputs.local.ps1 --write-report --json-report-path --json'], local_inputs:{{field_status:{{ProfileIds:{{ready:false,state:'placeholder',required_action:'替换 ProfileIds 的占位值。'}},CommentVideoUrl:{{ready:false,state:'placeholder',required_action:'替换 CommentVideoUrl 的占位值。'}},FollowProfileUrl:{{ready:false,state:'placeholder',required_action:'替换 FollowProfileUrl 的占位值。'}},DmProfileUrl:{{ready:false,state:'placeholder',required_action:'替换 DmProfileUrl 的占位值。'}},TargetUsername:{{ready:false,state:'placeholder',required_action:'替换 TargetUsername 的占位值。'}},ActivationStatusPath:{{ready:false,state:'placeholder',required_action:'替换 ActivationStatusPath 的占位值。'}},ConfirmAuthorizedTargets:{{ready:false,state:'authorization_not_confirmed',required_action:'确认所有 TikTok 目标已授权后，将 ConfirmAuthorizedTargets 设置为 $true。'}}}}}}, live_validation:{{status:'blocked', selected_profile_ids:[], selected_profile_count:0, missing_inputs:['ixBrowser 数字 Profile ID','已授权 TikTok 视频链接'], blocking_summary:{{profile_ready:false, target_ready:false, activation_ready:false, authorization_confirmed:false, next_blocking_item:'ixBrowser 数字 Profile ID'}}}}, mvp_acceptance:{{status:'mvp_accepted_external_pending', mvp_local_ready:true, final_delivery_ready:false, failed_checks:[], path:'/tmp/latest_mvp_acceptance_summary.json'}}, goal_delivery:{{status:'local_mvp_accepted_final_pending', local_mvp_ready:true, windows_build_ready:true, final_delivery_ready:false, delivery_boundary:{{summary:'本地 MVP 和客户端门禁已可验收；整项目最终交付仍未完成。', local_mvp_scope_ready:true, client_gate_scope_ready:true, windows_build_input_scope_ready:true, overall_final_delivery_scope_ready:false, client_gate_final_delivery_ready_is_not_overall_final_delivery:true, blocking_scopes:['windows_final_artifacts','external_authorized_execution']}}, final_delivery_blockers:[{{scope:'external_authorized_execution', status:'ready_for_external_validation', required_evidence:['授权 TikTok 目标','comment_visible_confirmed=true'], next_action:'完成授权真实触达验收，确保 goal_status.status=passed 且 pending_external_validation=[]。'}},{{scope:'windows_final_artifacts', status:'failed', required_artifacts:['dist\\\\ReachOps\\\\ReachOps.exe','reports\\\\reachops_acceptance\\\\acceptance_summary.json'], next_action:'在 Windows 实机生成 exe、installer、update manifest 和通过的 acceptance_summary.json，然后复跑 tools\\\\reachops_delivery_package_check.py --json。'}}], deliverable_index:{{local_mvp_acceptance:{{ready:true}}, windows_final_package:{{ready:false}}, final_acceptance_gate:{{ready:false}}}}, failed_checks:['delivery_package:passed'], blockers:[{{scope:'windows_final_artifacts', status:'failed', remediation_plan:{{commands:['powershell -ExecutionPolicy Bypass -File tools\\\\build_reachops_windows.ps1','powershell -ExecutionPolicy Bypass -File tools\\\\run_reachops_acceptance_windows.ps1 -RunLiveSubmit -ConfirmAuthorizedTargets','python tools\\\\reachops_final_acceptance_gate.py --json']}}}}], windows_package_preflight:{{status:'ready_for_windows_build', ready_for_windows_build:true, final_delivery_ready:false, missing_final_artifacts:['exe','installer','manifest','acceptance_summary'], default_build_requires_installer:true, skip_installer_is_non_final:true, preflight_report_path:'/tmp/windows_package_preflight.json'}}, path:'/tmp/latest_goal_delivery_report.json', summary_path:'/tmp/latest_goal_delivery_summary.md'}}, final_delivery_evidence_plan:{{schema_version:'reachops.final_delivery_evidence_plan.v1', ready:false, pending_scopes:['external_authorized_execution','windows_final_artifacts'], items:[{{scope:'external_authorized_execution', status:'ready_for_external_validation', required_evidence:['授权 TikTok 目标','comment_visible_confirmed=true'], proof_fields:['goal_status.pending_external_validation=[]'], commands:['python tools\\\\reachops_goal_status_report.py --strict-external --json']}},{{scope:'windows_final_artifacts', status:'failed', required_artifacts:['dist\\\\ReachOps\\\\ReachOps.exe','reports\\\\reachops_acceptance\\\\acceptance_summary.json'], proof_fields:['delivery_package.final_delivery_ready=true'], commands:['python tools\\\\reachops_delivery_package_check.py --json']}}]}}, failed_checks:['live_validation:inputs','delivery_package:passed','final_acceptance_gate:passed'], blocking_plan:[{{stage:'授权输入', status:'blocked', blockers:['已授权 TikTok 视频链接'], actions:['运行 tools\\\\init_reachops_acceptance_inputs_windows.ps1 生成本地验收输入文件。','填入已授权 TikTok 视频链接 CommentVideoUrl。']}},{{stage:'激活状态', status:'blocked', blockers:['激活状态未 ready，不能进入真实提交验收。'], actions:['生成或放置真实激活状态文件，并设置 ActivationStatusPath。']}},{{stage:'Windows交付包', status:'blocked', blockers:['Windows 交付包未达到 final_delivery_ready=true。'], actions:['在 Windows 实机生成 exe、installer、manifest 和 acceptance_summary.json 后复跑 package check。']}},{{stage:'最终门禁', status:'blocked', blockers:['final acceptance gate 未达到 status=passed 且 final_delivery_ready=true。'], actions:['运行 tools\\\\reachops_final_acceptance_gate.py --json 并确认 status=passed、final_delivery_ready=true。']}}], blocked_reasons:['Windows 交付包未达到 final_delivery_ready=true。'], next_required_actions:['运行 tools\\\\init_reachops_acceptance_inputs_windows.ps1 生成本地验收输入文件，然后填入已授权 TikTok 目标和激活状态路径。'], verification_commands:['python tools\\\\reachops_client_delivery_check.py --json','python tools\\\\reachops_goal_delivery_runner.py --json','python tools\\\\reachops_delivery_package_check.py --json','python tools\\\\reachops_final_acceptance_gate.py --json']}},
  '/api/groups?refresh=1': {{groups:[
    {{name:'Canada', label:'Canada / 2账号', count:2, count_known:true, count_label:'2账号', count_status:'known', count_source:'ixbrowser_profile_list'}},
    {{name:'United States', label:'United States / 3账号', count:3, count_known:true, count_label:'3账号', count_status:'known', count_source:'ixbrowser_profile_list'}}
  ], profile_count:5, known_group_count:2, counts_resolved:true}}
}};

function makeClassList(el) {{
  return {{
    add: (...names) => {{ names.forEach(name => el.classes.add(name)); }},
    remove: (...names) => {{ names.forEach(name => el.classes.delete(name)); }},
    contains: name => el.classes.has(name)
  }};
}}
function makeElement(id) {{
  const el = {{
    id,
    value: '',
    textContent: '',
    innerHTML: '',
    className: '',
    title: '',
    disabled: false,
    checked: false,
    dataset: {{}},
    children: [],
    options: [],
    classes: new Set(),
    selectedOptions: [{{textContent:''}}],
    closest: () => null,
    appendChild: child => {{ el.children.push(child); el.textContent += child.textContent || ''; return child; }},
    scrollHeight: 0,
    scrollTop: 0,
  }};
  el.classList = makeClassList(el);
  return el;
}}
function getElement(id) {{
  if (!elements[id]) elements[id] = makeElement(id);
  return elements[id];
}}
['target','sourceType','group','mode','volume','profiles','commentText','liveConfirm','accountRepairConfirmed','ixbrowserApiPort'].forEach(getElement);
elements.target.value = 'anti aging serum';
elements.sourceType.value = 'keyword'; elements.sourceType.selectedOptions = [{{textContent:'关键词搜索'}}];
elements.group.value = 'United States';
elements.mode.value = 'preflight'; elements.mode.selectedOptions = [{{textContent:'采集 + 触达预检'}}];
elements.volume.value = 'quick'; elements.volume.selectedOptions = [{{textContent:'快速'}}];
elements.profiles.value = '3';
elements.commentText.value = 'Hi';
elements.ixbrowserApiPort.value = '53201';

async function fetchMock(url, options = {{}}) {{
  const body = options.body ? JSON.parse(options.body) : null;
  calls.push({{url, method: options.method || 'GET', body}});
  if (url === '/api/start') {{
    return {{ok:true, status:200, json: async () => ({{status:'started', pid:54321, mode:'采集 + 触达预检'}})}};
  }}
  if (url === '/api/start-from-plan-preview') {{
    return {{ok:true, status:200, json: async () => ({{
      status:'ok',
      execution_plan_replay:true,
      execution_plan_id:'plan_dom_replay',
      plan_fingerprint_sha256:'sha256-dom-replay',
      execution_plan_schema:'reachops.execution_plan.v1',
      gate_state:'可重放',
      mode:'preflight',
      no_browser:true,
      no_submit:true,
      preflight_decision:{{start_allowed:true, blockers:[], next_actions:['可从最近一次 ExecutionPlan 重放。']}}
    }})}};
  }}
  if (url === '/api/start-from-plan') {{
    return {{ok:true, status:200, json: async () => ({{
      status:'started',
      pid:65432,
      execution_plan_replay:true,
      execution_plan_id:'plan_dom_replay',
      plan_fingerprint_sha256:'sha256-dom-replay',
      no_ai_token_used:true
    }})}};
  }}
  if (url === '/api/control') {{
    const action = body && body.action;
    const status = action === 'pause' ? 'paused' : (action === 'resume' ? 'running' : (action === 'stop' ? 'stopped' : 'rejected'));
    return {{ok: status !== 'rejected', status: status === 'rejected' ? 400 : 200, json: async () => ({{status, pid:54321, error: status === 'rejected' ? 'unknown_action' : ''}})}};
  }}
  if (url === '/api/acceptance-input-init') {{
    return {{ok:true, status:200, json: async () => ({{status:'created', created:true, path:'/tmp/reachops_acceptance_inputs.local.ps1', no_browser_started:true, no_submit:true, next_required_actions:['打开 tools\\\\reachops_acceptance_inputs.local.ps1，替换所有占位值。']}})}};
  }}
  if (url === '/api/mvp-acceptance-refresh') {{
    return {{ok:true, status:200, json: async () => ({{status:'mvp_accepted_external_pending', mvp_local_ready:true, final_delivery_ready:false, failed_checks:[]}})}};
  }}
  if (url === '/api/goal-delivery-refresh') {{
    return {{ok:true, status:200, json: async () => ({{status:'local_mvp_accepted_final_pending', local_mvp_ready:true, windows_build_ready:true, final_delivery_ready:false, failed_checks:['delivery_package:passed'], blockers:['windows_final_artifacts'], windows_package_preflight:{{status:'ready_for_windows_build', missing_final_artifacts:['exe','installer','manifest','acceptance_summary'], default_build_requires_installer:true, skip_installer_is_non_final:true}}}})}};
  }}
  if (url === '/api/ixbrowser-config') {{
    return {{ok:true, status:200, json: async () => ({{status:'saved', port: body && body.port, base_url:`http://127.0.0.1:${{body && body.port}}/api/v2/`, no_browser_started:true, no_submit:true, next_actions:['端口已应用。点击“刷新分组”重新读取 ixBrowser 配置列表。']}})}};
  }}
  if (url === '/api/account-repair-apply') {{
    return {{ok:true, status:200, json: async () => ({{status:'applied', ok:true, selected_count:2, moved_count:2, failed_count:0, profile_group:'Canada', results:[{{profile_id:'21644', ok:true, group_name:'封禁账号'}},{{profile_id:'21647', ok:true, group_name:'封禁账号'}}], next_actions:['点击刷新分组确认坏账号已移入封禁账号分组。']}})}};
  }}
  if (url === '/api/offline-learning/review') {{
    return {{ok:true, status:200, json: async () => ({{
      status:'review_recorded',
      no_ai_token_used:true,
      no_browser_started:true,
      no_submit:true,
      review:{{decision:body && body.decision, auto_apply:false, runtime_effect:'review_recorded_only'}},
      offline_learning:{{
        schema_version:'reachops.offline_learning.v1',
        record_count:1,
        no_ai_token_used:true,
        policy_review_summary:{{schema_version:'reachops.offline_policy_review.v1', review_count:1, approved_count:body && body.decision === 'approved' ? 1 : 0, rejected_count:body && body.decision === 'rejected' ? 1 : 0, runtime_auto_apply_count:0}},
        policy_candidates:{{schema_version:'reachops.offline_policy_candidates.v1', candidate_count:1, candidates:[{{candidate_id:'opc_dom_modal', candidate_state:'MODAL_BLOCKED', candidate_action:'dismiss_modal', occurrence_count:2, auto_apply:false, review_status:body && body.decision, review:{{decision:body && body.decision}}}}]}}
      }}
    }})}};
  }}
  if (url === '/api/execution-plan') {{
    return {{ok:true, status:200, json: async () => ({{
      status:'ok',
      exists:true,
      schema_version:'reachops.execution_plan.v1',
      plan_id:'plan_dom_download',
      path:'/tmp/plan_dom_download.json',
      download_url:'/api/download?path=%2Ftmp%2Fplan_dom_download.json',
      no_browser_started:true,
      no_submit:true
    }})}};
  }}
  if (url === '/api/ai-console') {{
    if ((body && body.message || '').includes('分析未知')) {{
      return {{ok:true, status:200, json: async () => ({{status:'ok', intent:'unknown_state_analysis', no_ai_token_used:true, reply:'未知状态账本共有 1 类记录。候选分类是 UNKNOWN_PAGE_STATE，建议策略是 capture_unknown_state_bundle。', execution_plan:{{schema_version:'reachops.execution_plan.v1', plan_id:'plan_dom_unknown_analysis', mode:'collect', profile_group:'Canada', limits:{{max_videos:3, max_comments:20}}, authorization:{{live_confirmed:false}}}}, execution_plan_id:'plan_dom_unknown_analysis', execution_plan_schema:'reachops.execution_plan.v1', offline_learning:{{schema_version:'reachops.offline_learning.v1', record_count:1, evidence_path_count:2, no_ai_token_used:true, policy_review_summary:{{schema_version:'reachops.offline_policy_review.v1', review_count:0, approved_count:0, rejected_count:0, runtime_auto_apply_count:0}}, policy_candidates:{{schema_version:'reachops.offline_policy_candidates.v1', candidate_count:1, candidates:[{{candidate_id:'opc_dom_modal', candidate_state:'MODAL_BLOCKED', candidate_action:'dismiss_modal', occurrence_count:2, auto_apply:false, requires_human_review:true}}]}}}}, machine_actions:['读取 offline_learning unknown_states 本地账本','输出候选规则但保持 RiskGate 默认阻断'], timeline_summary:['未知状态：UNKNOWN_PAGE_STATE signature=modal_x occurrences=2','候选规则：MODAL_BLOCKED -> dismiss_modal occurrences=2'], next_actions:['复核候选规则队列；人工确认前不写入运行时策略。']}})}};
    }}
    if ((body && body.message || '').includes('产品能力矩阵')) {{
      return {{ok:true, status:200, json: async () => ({{status:'ok', intent:'product_capability_status', no_ai_token_used:true, reply:'产品能力矩阵 ready=false，8 阶段通过 3 个，未闭环 5 个。', execution_plan:{{schema_version:'reachops.execution_plan.v1', plan_id:'plan_dom_product_capability', mode:'collect', profile_group:'Canada', limits:{{max_videos:3, max_comments:20}}, authorization:{{live_confirmed:false}}}}, execution_plan_id:'plan_dom_product_capability', execution_plan_schema:'reachops.execution_plan.v1', product_capability_summary:{{schema_version:'reachops.product_capability_summary.v1', ready:false, passed_count:3, failed_count:5, failed_phases:['phase_4_page_state_sensing'], phases:[{{key:'phase_3_autonomous_execution', passed:true}},{{key:'phase_4_page_state_sensing', passed:false}}]}}, machine_actions:['读取 evidence_bundle.product_capability_summary','按八阶段产品目标计算 passed/failed','保持本地规则解释，不调用外部 AI'], timeline_summary:['产品能力矩阵：passed=3 failed=5','未闭环阶段：phase_4_page_state_sensing / 页面状态感知'], next_actions:['补齐页面快照、DOM 摘要、截图或未知状态包。']}})}};
    }}
    return {{ok:true, status:200, json: async () => ({{status:'ok', intent:'plan_update', no_ai_token_used:true, reply:'已按你的意图调整为 只采集，执行开始后由本地程序自动执行。', plan_patch:{{mode:'collect', liveConfirm:false}}, execution_plan:{{schema_version:'reachops.execution_plan.v1', plan_id:'plan_dom_ai_console', mode:'collect', profile_group:'Canada', limits:{{max_videos:3, max_comments:20}}, authorization:{{live_confirmed:false}}}}, execution_plan_id:'plan_dom_ai_console', execution_plan_schema:'reachops.execution_plan.v1', preflight_decision:{{schema_version:'reachops.start_preflight_decision.v1', status:'ready', start_allowed:true, gate_state:'可启动', blockers:[], next_actions:['可以启动本地执行。'], no_ai_token_used:true, no_browser_started:true, no_submit:true}}, autonomous_preflight_forecast:{{schema_version:'reachops.autonomous_preflight_forecast.v1', status:'ready', start_allowed:true, predicted_state_sequence:['CREATED','PRECHECK','PROFILE_OPENING','COLLECTING','REPAIRING','COMPLETED'], repair_routes:[{{state:'LOGIN_REQUIRED', action:'quarantine_profile'}},{{state:'DOM_STALLED', action:'refresh_then_degrade'}},{{state:'UNKNOWN_PAGE_STATE', action:'capture_error_bundle_then_block'}}], evidence_requirements:['execution_plan_snapshot','run_session_state_history'], runtime_invariants:{{no_ai_token_during_execution:true, no_browser_started:true, no_submit:true}}, no_ai_token_used:true, no_browser_started:true, no_submit:true}}, client_delivery:{{status:'blocked_by_accounts', readiness:'blocked_by_accounts', acceptance_ready:false, final_delivery_ready:false, failed_checks:['acceptance:ready'], blockers:['账号预检没有可用账号'], next_actions:['先在 ixBrowser 手动打开 Canada 中至少 1 个账号。']}}, client_delivery_summary:{{status:'blocked_by_accounts', readiness:'blocked_by_accounts', acceptance_ready:false, final_delivery_ready:false, failed_checks:['acceptance:ready'], blocker_count:1, next_action_count:1, no_ai_token_used:true, no_browser_started:true, no_submit:true}}, machine_actions:['自修复机器步骤：capture_page_state_bundle, backoff'], timeline_summary:['风险门禁阻断：LIVE_SUBMIT_NOT_AUTHORIZED profile=profile-1','页面状态：CAPTCHA_DETECTED signals=captcha_or_verification_text'], next_actions:['检查执行计划预览。']}})}};
  }}
  const fallback = responses[url] || {{}};
  if ((url === '/api/final-status' || url === '/api/acceptance') && !fallback.two_phase_acceptance) {{
    fallback.two_phase_acceptance = {{
      status:'local_mvp_accepted_final_pending',
      local_mvp_ready:true,
      final_delivery_ready:false,
      failed_items:['windows_final_artifacts','authorized_live_submit'],
      blocking_scopes:['external_authorized_execution','final_acceptance_gate','windows_final_artifacts'],
      path:'/tmp/latest_two_phase_acceptance_matrix.json',
      markdown_path:'/tmp/latest_two_phase_acceptance_matrix.md'
    }};
  }}
  return {{ok:true, status:200, json: async () => fallback}};
}}

const documentMock = {{
  getElementById: getElement,
  createElement: tag => makeElement('created-' + tag + '-' + Object.keys(elements).length),
  querySelectorAll: selector => selector === '.tab' ? [makeElement('tab1'), makeElement('tab2')] : [],
  addEventListener: () => {{}},
}};

const context = {{
  console,
  document: documentMock,
  fetch: fetchMock,
  setInterval: () => 0,
  setTimeout: (fn) => {{ fn(); return 0; }},
  String,
  Number,
  Math,
  Array,
  Object,
  RegExp,
  JSON,
  Date,
}};
context.window = context;
context.__openedUrls = [];
context.open = (url, target, features) => {{ context.__openedUrls.push({{url, target, features}}); }};
vm.createContext(context);
  vm.runInContext({json.dumps(script)}, context, {{timeout: 5000}});

(async () => {{
  await new Promise(resolve => setImmediate(resolve));
  await elements.refreshGroups.onclick();
  elements.group.value = 'Canada';
  elements.mode.value = 'live_comment';
  elements.mode.selectedOptions = [{{textContent:'采集 + 真实评论'}}];
  elements.liveConfirm.checked = false;
  const beforeUnconfirmedLive = calls.filter(call => call.url === '/api/start').length;
  await elements.start.onclick();
  const afterUnconfirmedLive = calls.filter(call => call.url === '/api/start').length;
  const unconfirmedLiveTitle = elements.operatorDecisionTitle.textContent;
  elements.mode.value = 'preflight';
  elements.mode.selectedOptions = [{{textContent:'采集 + 触达预检'}}];
	  await elements.start.onclick();
	  const currentGroupBeforePortApply = elements.currentGroup.textContent;
	  const selectedGroupNameBeforePortApply = elements.selectedGroupName.textContent;
  const selectedGroupCountBeforePortApply = elements.selectedGroupCount.textContent;
	  const selectedGroupIdBeforePortApply = elements.selectedGroupId.textContent;
  const startCallsBeforeAccountGate = calls.filter(call => call.url === '/api/start').length;
  responses['/api/acceptance'].acceptance = {{
    readiness:'not_started',
    checks:{{}},
    blockers:[],
    next_actions:[]
  }};
  responses['/api/acceptance'].client_delivery = {{
    status:'blocked_by_accounts',
    readiness:'blocked_by_accounts',
    final_delivery_ready:false,
    failed_checks:['acceptance:ready']
  }};
  responses['/api/acceptance'].latest_batch = {{profile_group:'Canada'}};
  responses['/api/acceptance'].latest_profile_preflight = {{checked:10, available:0}};
  await context.refreshAcceptance();
  const clientDeliveryOnlyGateStartDisabled = elements.start.disabled;
  const clientDeliveryOnlyGateStartTitle = elements.start.title;
  const clientDeliveryOnlyGateStateText = elements.accountGateState.textContent;
  responses['/api/acceptance'].acceptance = {{
    readiness:'blocked_by_accounts',
    checks:{{profile_available_count:0}},
    blockers:['账号预检没有可用账号，无法进入真实采集/触达。'],
    next_actions:['先修复账号后再重检。']
  }};
  responses['/api/acceptance'].latest_batch = {{profile_group:'Canada'}};
  responses['/api/acceptance'].latest_profile_preflight = {{checked:10, available:0}};
  await context.refreshAcceptance();
  const accountGateStartDisabled = elements.start.disabled;
  const accountRepairApplyDisabled = elements.applyAccountRepair.disabled;
  const accountRepairApplyTitle = elements.applyAccountRepair.title;
  const accountGateStartTitle = elements.start.title;
  const accountGateStateText = elements.accountGateState.textContent;
  const accountGateAcceptanceBlockers = elements.acceptanceBlockers.innerHTML;
  responses['/api/acceptance'].client_delivery.account_repair_apply = {{
    stale:true,
    stale_reason:'newer_account_repair_plan_for_current_batch',
    pending_recheck:false,
    profile_group:'Canada',
    moved_count:1
  }};
  await context.refreshAcceptance();
  const accountRepairStaleBlockers = elements.acceptanceBlockers.innerHTML;
  const startCallsBeforeStaleAccountRepairStart = calls.filter(call => call.url === '/api/start').length;
  await elements.start.onclick();
  const startCallsAfterStaleAccountRepairStart = calls.filter(call => call.url === '/api/start').length;
  const accountRepairStaleStartTitle = elements.operatorDecisionTitle.textContent;
  const accountRepairStaleStartBody = elements.operatorDecisionBody.textContent;
  const accountRepairStaleStartActions = elements.operatorNextList.innerHTML;
  responses['/api/acceptance'].client_delivery.account_repair_apply = {{}};
  elements.group.value = 'United States';
  await elements.group.onchange();
  const accountGateDifferentGroupStartDisabled = elements.start.disabled;
  const accountGateDifferentGroupStartTitle = elements.start.title;
  const accountGateDifferentGroupStateText = elements.accountGateState.textContent;
  elements.group.value = 'Canada';
  await elements.group.onchange();
  const accountGateSameGroupStartDisabledAfterSwitch = elements.start.disabled;
  await elements.start.onclick();
  const startCallsAfterAccountGate = calls.filter(call => call.url === '/api/start').length;
  const accountGateBlockedTitle = elements.operatorDecisionTitle.textContent;
  const accountGateBlockedActions = elements.operatorNextList.innerHTML;
  await elements.applyAccountRepair.onclick();
  const accountRepairApplyTitleAfterClick = elements.operatorDecisionTitle.textContent;
  const accountRepairApplyBodyAfterClick = elements.operatorDecisionBody.textContent;
  const accountRepairApplyActionsAfterClick = elements.operatorNextList.innerHTML;
  const accountRepairAutoConfirmedAfterApply = elements.accountRepairConfirmed.checked === true;
  const accountRepairConfirmedStartDisabled = elements.start.disabled;
  const accountRepairConfirmedStartTitle = elements.start.title;
  elements.group.value = 'United States';
  await elements.group.onchange();
  const accountRepairConfirmClearedOnGroupSwitch = elements.accountRepairConfirmed.checked === false;
  elements.group.value = 'Canada';
  await elements.group.onchange();
  responses['/api/acceptance'].acceptance = {{
    readiness:'blocked_by_accounts',
    checks:{{profile_available_count:0}},
    blockers:['账号预检没有可用账号，无法进入真实采集/触达。'],
    next_actions:['点击开始获客复测 Canada 分组。']
  }};
  responses['/api/acceptance'].client_delivery = {{
    status:'blocked_by_accounts',
    readiness:'blocked_by_accounts',
    final_delivery_ready:false,
    failed_checks:['acceptance:ready'],
    account_repair_apply:{{pending_recheck:true, profile_group:'United States', moved_count:2}}
  }};
  responses['/api/acceptance'].latest_batch = {{profile_group:'United States'}};
  responses['/api/acceptance'].latest_profile_preflight = {{checked:10, available:0}};
  await context.refreshAcceptance();
  const accountRepairPendingRecheckAutoConfirmed = elements.accountRepairConfirmed.checked === true;
  const accountRepairPendingRecheckStartDisabled = elements.start.disabled;
  const accountRepairPendingRecheckStartTitle = elements.start.title;
  const accountRepairPendingRecheckGateStateText = elements.accountGateState.textContent;
	  await elements.pause.onclick();
  await elements.resume.onclick();
  await elements.stop.onclick();
  const controlTitle = elements.operatorDecisionTitle.textContent;
  const controlBody = elements.operatorDecisionBody.textContent;
  await elements.initAcceptanceInputs.onclick();
  const initNoticeTitle = elements.operatorDecisionTitle.textContent;
  const initNoticeBody = elements.operatorDecisionBody.textContent;
  await elements.refreshMvpAcceptance.onclick();
  const mvpNoticeTitle = elements.operatorDecisionTitle.textContent;
  const mvpNoticeBody = elements.operatorDecisionBody.textContent;
  await elements.refreshGoalDelivery.onclick();
  const goalNoticeTitle = elements.operatorDecisionTitle.textContent;
  const goalNoticeBody = elements.operatorDecisionBody.textContent;
  elements.ixbrowserApiPort.value = '53201';
  await elements.applyIxBrowserPort.onclick();
  const ixPortNoticeTitle = elements.operatorDecisionTitle.textContent;
  const ixPortNoticeBody = elements.operatorDecisionBody.textContent;
  elements.aiConsoleInput.value = '只采集不评论';
  const startCallsBeforeAiConsole = calls.filter(call => call.url === '/api/start').length;
  await elements.aiConsoleSend.onclick();
  const startCallsAfterAiConsole = calls.filter(call => call.url === '/api/start').length;
  const aiConsoleCalls = calls.filter(call => call.url === '/api/ai-console').length;
  const aiConsoleMode = elements.mode.value;
  const aiConsoleIntent = elements.aiConsoleIntent.textContent;
  const aiConsoleState = elements.aiConsoleState.textContent;
  const aiPlanId = elements.aiPlanId.textContent;
  const aiNextList = elements.aiConsoleNextList.innerHTML;
  const aiMachineActions = elements.aiConsoleMachineList.innerHTML;
  const aiTimelineSummary = elements.aiConsoleTimelineList.innerHTML;
  const previewAutonomyAfterAi = elements.previewAutonomy.textContent;
  const previewAutonomyListAfterAi = elements.previewAutonomyList.innerHTML;
  const startCallsBeforeUnknownAnalysis = calls.filter(call => call.url === '/api/start').length;
  await elements.aiConsoleAnalyzeUnknown.onclick();
  const startCallsAfterUnknownAnalysis = calls.filter(call => call.url === '/api/start').length;
  const unknownAnalysisIntent = elements.aiConsoleIntent.textContent;
  const unknownAnalysisTitle = elements.aiConsoleNoticeTitle.textContent;
  const unknownAnalysisMachineActions = elements.aiConsoleMachineList.innerHTML;
  const unknownAnalysisTimeline = elements.aiConsoleTimelineList.innerHTML;
  const offlinePolicyStateAfterUnknown = elements.offlinePolicyReviewState.textContent;
  const offlinePolicyBodyAfterUnknown = elements.offlinePolicyReviewBody.textContent;
  const approveOfflineDisabledAfterUnknown = elements.approveOfflinePolicyCandidate.disabled;
  const startCallsBeforeOfflinePolicyReview = calls.filter(call => call.url === '/api/start').length;
  await elements.approveOfflinePolicyCandidate.onclick();
  const startCallsAfterOfflinePolicyReview = calls.filter(call => call.url === '/api/start').length;
  const offlinePolicyReviewTitle = elements.operatorDecisionTitle.textContent;
  const offlinePolicyReviewBody = elements.operatorDecisionBody.textContent;
  const offlinePolicyStateAfterReview = elements.offlinePolicyReviewState.textContent;
  const startCallsBeforeProductCapability = calls.filter(call => call.url === '/api/start').length;
  await elements.aiConsoleProductCapability.onclick();
  const startCallsAfterProductCapability = calls.filter(call => call.url === '/api/start').length;
  const productCapabilityIntent = elements.aiConsoleIntent.textContent;
  const productCapabilityTitle = elements.aiConsoleNoticeTitle.textContent;
  const productCapabilityMachineActions = elements.aiConsoleMachineList.innerHTML;
  const productCapabilityTimeline = elements.aiConsoleTimelineList.innerHTML;
  const hourglassState = elements.hourglassState.textContent;
  const hourglassDecisionTitle = elements.hourglassDecisionTitle.textContent;
  const hourglassDecisionBody = elements.hourglassDecisionBody.textContent;
  const hourglassLegend = elements.hourglassLegend.innerHTML;
  const hourglassParticles = elements.hourglassParticles.innerHTML;
  const startCallsBeforeReplayPreview = calls.filter(call => call.url === '/api/start').length;
  const startFromPlanCallsBeforeReplayPreview = calls.filter(call => call.url === '/api/start-from-plan').length;
  await elements.previewPlanReplay.onclick();
  const startCallsAfterReplayPreview = calls.filter(call => call.url === '/api/start').length;
  const startFromPlanCallsAfterReplayPreview = calls.filter(call => call.url === '/api/start-from-plan').length;
  const replayPreviewTitle = elements.operatorDecisionTitle.textContent;
  const replayPreviewBody = elements.operatorDecisionBody.textContent;
  const replayPreviewPlan = elements.previewPlan.textContent;
  const startCallsBeforeReplayStart = calls.filter(call => call.url === '/api/start').length;
  const startFromPlanCallsBeforeReplayStart = calls.filter(call => call.url === '/api/start-from-plan').length;
  await elements.startFromPlan.onclick();
  const startCallsAfterReplayStart = calls.filter(call => call.url === '/api/start').length;
  const startFromPlanCallsAfterReplayStart = calls.filter(call => call.url === '/api/start-from-plan').length;
  const replayStartTitle = elements.operatorDecisionTitle.textContent;
  const replayStartBody = elements.operatorDecisionBody.textContent;
  const startCallsBeforeExecutionPlanDownload = calls.filter(call => call.url === '/api/start').length;
  await elements.downloadExecutionPlan.onclick();
  const startCallsAfterExecutionPlanDownload = calls.filter(call => call.url === '/api/start').length;
  const downloadExecutionPlanTitle = elements.operatorDecisionTitle.textContent;
  const downloadExecutionPlanBody = elements.operatorDecisionBody.textContent;
  const downloadExecutionPlanUrl = context.__reachopsLastDownloadUrl || '';
  const openedDownloadUrl = ((context.__openedUrls || [])[0] || {{}}).url || '';
  await new Promise(resolve => setImmediate(resolve));
  const result = {{
    calls,
    unconfirmedLiveRequestCount: afterUnconfirmedLive - beforeUnconfirmedLive,
    unconfirmedLiveTitle,
    controlTitle,
    controlBody,
    operatorTitle: elements.operatorDecisionTitle.textContent,
    operatorBody: elements.operatorDecisionBody.textContent,
    ixbrowserApiState: elements.ixbrowserApiState.textContent,
    ixbrowserApiTitle: elements.ixbrowserApiState.title,
    ixbrowserStatusActions: elements.ixbrowserStatusActions.innerHTML,
    activationState: elements.activationState.textContent,
    activationActions: elements.activationActions.innerHTML,
    acceptanceState: elements.acceptanceState.textContent,
    reportTable: elements.reportTable.innerHTML,
    finalStatusState: elements.finalStatusState.textContent,
	    finalStatusTitle: elements.finalStatusState.title,
	    finalStatusActions: elements.finalStatusActions.innerHTML,
	    finalStatusCommands: elements.finalStatusCommands.innerHTML,
    initNoticeTitle,
    initNoticeBody,
    mvpNoticeTitle,
    mvpNoticeBody,
    goalNoticeTitle,
    goalNoticeBody,
    ixPortNoticeTitle,
    ixPortNoticeBody,
    aiConsoleStartDelta:startCallsAfterAiConsole - startCallsBeforeAiConsole,
    aiConsoleCalls,
    aiConsoleMode,
    aiConsoleIntent,
    aiConsoleState,
    aiPlanId,
    aiNextList,
    aiMachineActions,
    aiTimelineSummary,
    previewAutonomyAfterAi,
    previewAutonomyListAfterAi,
    unknownAnalysisStartDelta:startCallsAfterUnknownAnalysis - startCallsBeforeUnknownAnalysis,
    unknownAnalysisIntent,
    unknownAnalysisTitle,
    unknownAnalysisMachineActions,
    unknownAnalysisTimeline,
    offlinePolicyStateAfterUnknown,
    offlinePolicyBodyAfterUnknown,
    approveOfflineDisabledAfterUnknown,
    offlinePolicyReviewStartDelta:startCallsAfterOfflinePolicyReview - startCallsBeforeOfflinePolicyReview,
    offlinePolicyReviewTitle,
    offlinePolicyReviewBody,
    offlinePolicyStateAfterReview,
    productCapabilityStartDelta:startCallsAfterProductCapability - startCallsBeforeProductCapability,
    productCapabilityIntent,
    productCapabilityTitle,
    productCapabilityMachineActions,
    productCapabilityTimeline,
    hourglassState,
    hourglassDecisionTitle,
    hourglassDecisionBody,
    hourglassLegend,
    hourglassParticles,
    replayPreviewStartDelta:startCallsAfterReplayPreview - startCallsBeforeReplayPreview,
    replayPreviewStartFromPlanDelta:startFromPlanCallsAfterReplayPreview - startFromPlanCallsBeforeReplayPreview,
    replayPreviewTitle,
    replayPreviewBody,
    replayPreviewPlan,
    replayStartDelta:startCallsAfterReplayStart - startCallsBeforeReplayStart,
    replayStartFromPlanDelta:startFromPlanCallsAfterReplayStart - startFromPlanCallsBeforeReplayStart,
    replayStartTitle,
    replayStartBody,
    downloadExecutionPlanStartDelta:startCallsAfterExecutionPlanDownload - startCallsBeforeExecutionPlanDownload,
    downloadExecutionPlanTitle,
    downloadExecutionPlanBody,
    downloadExecutionPlanUrl,
    openedDownloadUrl,
    startDisabled: elements.start.disabled,
    groupInnerHTML: elements.group.innerHTML,
	    groupDetails: elements.groupDetails.innerHTML,
	    groupCount: elements.groupCount.textContent,
	    currentGroup: elements.currentGroup.textContent,
	    selectedGroupName: elements.selectedGroupName.textContent,
	    selectedGroupCount: elements.selectedGroupCount.textContent,
	    selectedGroupId: elements.selectedGroupId.textContent,
	    currentGroupBeforePortApply,
	    selectedGroupNameBeforePortApply,
	    selectedGroupCountBeforePortApply,
	    selectedGroupIdBeforePortApply,
	    clientDeliveryOnlyGateStartDisabled,
	    clientDeliveryOnlyGateStartTitle,
	    clientDeliveryOnlyGateStateText,
	    accountGateStartDisabled,
	    accountRepairApplyDisabled,
	    accountRepairApplyTitle,
	    accountGateStartTitle,
	    accountGateStateText,
	    accountGateAcceptanceBlockers,
	    accountRepairStaleBlockers,
	    accountRepairStaleStartRequestDelta:startCallsAfterStaleAccountRepairStart - startCallsBeforeStaleAccountRepairStart,
	    accountRepairStaleStartTitle,
	    accountRepairStaleStartBody,
	    accountRepairStaleStartActions,
	    accountGateDifferentGroupStartDisabled,
	    accountGateDifferentGroupStartTitle,
	    accountGateDifferentGroupStateText,
	    accountGateSameGroupStartDisabledAfterSwitch,
	    accountGateStartRequestDelta:startCallsAfterAccountGate - startCallsBeforeAccountGate,
	    accountGateBlockedTitle,
	    accountGateBlockedActions,
	    accountRepairApplyTitleAfterClick,
	    accountRepairApplyBodyAfterClick,
	    accountRepairApplyActionsAfterClick,
	    accountRepairAutoConfirmedAfterApply,
	    accountRepairConfirmedStartDisabled,
	    accountRepairConfirmedStartTitle,
	    accountRepairConfirmClearedOnGroupSwitch,
	    accountRepairPendingRecheckAutoConfirmed,
	    accountRepairPendingRecheckStartDisabled,
	    accountRepairPendingRecheckStartTitle,
	    accountRepairPendingRecheckGateStateText,
	    accountRepairPendingRecheckDebug: context.__reachopsAccountRepairDebug,
	  }};
  console.log(JSON.stringify(result));
}})().catch(err => {{
  console.error(err && err.stack ? err.stack : String(err));
  process.exit(3);
}});
"""

    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as fh:
        fh.write(node_source)
        node_path = Path(fh.name)
    try:
        completed = subprocess.run(
            ["node", str(node_path)],
            cwd=str(ROOT_DIR),
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )
    finally:
        try:
            node_path.unlink()
        except OSError:
            pass

    stdout = completed.stdout or ""
    stderr = completed.stderr or ""

    if completed.returncode != 0:
        return {
            "status": "failed",
            "passed": False,
            "failed_checks": ["node_dom_execution"],
            "checks": {"node_dom_execution": False},
            "stdout": stdout[-2000:],
            "stderr": stderr[-2000:],
        }

    try:
        payload = json.loads(stdout.strip().splitlines()[-1])
    except Exception as exc:
        return {
            "status": "failed",
            "passed": False,
            "failed_checks": ["node_dom_result_parse"],
            "checks": {"node_dom_result_parse": False},
            "stdout": stdout[-2000:],
            "stderr": stderr[-2000:],
            "error": str(exc),
        }

    calls = payload.get("calls") or []
    post_calls = [row for row in calls if row.get("method") == "POST"]
    checks["html_start_button_disabled_until_group_ready"] = (
        'id="start" disabled' in html
        and "let groupListReady = false" in html
        and "function updateStartAvailability()" in html
        and "!groupListReady || blockedByAccountGate" in html
    )
    checks["html_toolbar_uses_responsive_grid"] = (
        "controlPanel" in html
        and "taskForm" in html
        and "taskParams" in html
        and "taskActions" in html
        and "grid-template-columns:repeat(auto-fit,minmax(176px,1fr))" in html
        and "grid-template-columns:minmax(180px,1fr) repeat(3,minmax(86px,.42fr))" in html
        and "grid-template-columns:repeat(auto-fit,minmax(106px,1fr))" in html
        and "grid-template-columns:repeat(auto-fit,minmax(92px,1fr))" in html
        and ".selectedGroupBar { grid-template-columns:1fr; }" in html
    )
    checks["html_group_refresh_button_next_to_select"] = 'id="refreshGroupsInline"' in html and 'class="groupField"' in html and 'class="groupControl"' in html and "$('refreshGroupsInline').onclick" in html and "refreshIxBrowserStatus(); refreshGroups();" in html and "待读取账号数" not in html
    checks["html_selected_group_quantity_is_first_screen_visible"] = 'id="selectedGroupBar"' in html and 'id="selectedGroupCount"' in html and '可读取账号数' in html and "updateSelectedGroupQuantity();" in html
    checks["html_local_ai_console_is_visible_and_deterministic"] = (
        'id="aiConsolePanel"' in html
        and 'id="aiConsoleInput"' in html
        and 'id="aiConsoleSend"' in html
        and 'id="aiConsoleAnalyzeUnknown"' in html
        and 'id="aiConsoleExplainStatus"' in html
        and 'id="aiConsoleProductCapability"' in html
        and "postJson('/api/ai-console'" in html
        and "本地规则 / 0 token" in html
        and payload.get("aiConsoleCalls") == 1
        and payload.get("aiConsoleStartDelta") == 0
        and payload.get("aiConsoleMode") == "collect"
        and payload.get("aiConsoleIntent") == "plan_update"
        and payload.get("aiPlanId") == "plan_dom_ai_console"
        and "客户端门禁：blocked_by_accounts" in str(payload.get("aiNextList") or "")
        and "acceptance_ready=false" in str(payload.get("aiNextList") or "")
        and "final_delivery_ready=false" in str(payload.get("aiNextList") or "")
        and "capture_page_state_bundle" in str(payload.get("aiMachineActions") or "")
        and "自治预判" in str(payload.get("aiMachineActions") or "")
        and "UNKNOWN_PAGE_STATE" in str(payload.get("aiMachineActions") or "")
        and "LIVE_SUBMIT_NOT_AUTHORIZED" in str(payload.get("aiTimelineSummary") or "")
        and "reachops.autonomous_preflight_forecast.v1" in str(payload.get("previewAutonomyAfterAi") or "")
        and "状态链：CREATED" in str(payload.get("previewAutonomyListAfterAi") or "")
        and "自修复：LOGIN_REQUIRED" in str(payload.get("previewAutonomyListAfterAi") or "")
    )
    checks["html_ai_console_unknown_state_analysis_is_explicit_and_local"] = (
        'id="aiConsoleAnalyzeUnknown"' in html
        and "分析未知错误" in html
        and payload.get("unknownAnalysisStartDelta") == 0
        and payload.get("unknownAnalysisIntent") == "unknown_state_analysis"
        and payload.get("unknownAnalysisTitle") == "未知状态分析"
        and "offline_learning" in str(payload.get("unknownAnalysisMachineActions") or "")
        and "RiskGate 默认阻断" in str(payload.get("unknownAnalysisMachineActions") or "")
        and "UNKNOWN_PAGE_STATE" in str(payload.get("unknownAnalysisTimeline") or "")
        and "候选规则" in str(payload.get("unknownAnalysisTimeline") or "")
    )
    checks["html_ai_console_offline_policy_review_is_api_bound"] = (
        'id="offlinePolicyReview"' in html
        and 'id="approveOfflinePolicyCandidate"' in html
        and 'id="rejectOfflinePolicyCandidate"' in html
        and "postJson('/api/offline-learning/review'" in html
        and "reviewOfflinePolicyCandidate('approved')" in html
        and "reviewOfflinePolicyCandidate('rejected')" in html
        and "auto_apply=false" in html
        and payload.get("offlinePolicyStateAfterUnknown") == "待复核"
        and payload.get("approveOfflineDisabledAfterUnknown") is False
        and "MODAL_BLOCKED -> dismiss_modal" in str(payload.get("offlinePolicyBodyAfterUnknown") or "")
        and payload.get("offlinePolicyReviewStartDelta") == 0
        and payload.get("offlinePolicyReviewTitle") == "候选规则复核已记录"
        and "auto_apply=false" in str(payload.get("offlinePolicyReviewBody") or "")
        and payload.get("offlinePolicyStateAfterReview") == "已批准"
        and any(
            row.get("url") == "/api/offline-learning/review"
            and row.get("method") == "POST"
            and (row.get("body") or {}).get("candidate_state") == "MODAL_BLOCKED"
            and (row.get("body") or {}).get("candidate_action") == "dismiss_modal"
            and (row.get("body") or {}).get("decision") == "approved"
            for row in post_calls
        )
    )
    checks["html_ai_console_product_capability_is_explicit_and_local"] = (
        'id="aiConsoleProductCapability"' in html
        and "能力矩阵" in html
        and "产品能力矩阵现在做到哪了" in html
        and payload.get("productCapabilityStartDelta") == 0
        and payload.get("productCapabilityIntent") == "product_capability_status"
        and payload.get("productCapabilityTitle") == "产品能力矩阵"
        and "八阶段" in str(payload.get("productCapabilityMachineActions") or "")
        and "产品能力矩阵" in str(payload.get("productCapabilityTimeline") or "")
    )
    checks["html_start_preview_uses_structured_preflight_decision"] = (
        "preflight_decision" in html
        and "autonomous_preflight_forecast" in html
        and 'id="previewAutonomy"' in html
        and 'id="previewAutonomyList"' in html
        and "start_allowed" in html
        and "next_actions" in html
        and "gate_state" in html
        and "predicted_state_sequence" in html
        and "repair_routes" in html
        and "evidence_requirements" in html
    )
    checks["html_execution_plan_replay_controls_are_api_bound"] = (
        'id="previewPlanReplay"' in html
        and 'id="startFromPlan"' in html
        and "预检重放计划" in html
        and "重放计划执行" in html
        and "getJson('/api/start-from-plan-preview')" in html
        and "postJson('/api/start-from-plan'" in html
        and "$('previewPlanReplay').onclick = previewPlanReplay" in html
        and "$('startFromPlan').onclick = startFromPlan" in html
        and payload.get("replayPreviewStartDelta") == 0
        and payload.get("replayPreviewStartFromPlanDelta") == 0
        and payload.get("replayPreviewTitle") == "重放计划可启动"
        and payload.get("replayPreviewPlan") == "plan_dom_replay"
        and "sha256-dom-replay" in str(payload.get("replayPreviewBody") or "")
        and payload.get("replayStartDelta") == 0
        and payload.get("replayStartFromPlanDelta") == 1
        and any(row.get("url") == "/api/start-from-plan" and row.get("method") == "POST" and (row.get("body") or {}) == {} for row in calls)
    )
    checks["html_execution_plan_download_is_api_bound"] = (
        'id="downloadExecutionPlan"' in html
        and "下载执行计划" in html
        and "getJson('/api/execution-plan')" in html
        and "$('downloadExecutionPlan').onclick = downloadExecutionPlan" in html
        and "window.__reachopsLastDownloadUrl" in html
        and payload.get("downloadExecutionPlanStartDelta") == 0
        and payload.get("downloadExecutionPlanTitle") == "执行计划已准备下载"
        and "plan_dom_download" in str(payload.get("downloadExecutionPlanBody") or "")
        and "plan_dom_download.json" in str(payload.get("downloadExecutionPlanUrl") or "")
        and payload.get("openedDownloadUrl") == payload.get("downloadExecutionPlanUrl")
        and any(row.get("url") == "/api/execution-plan" and row.get("method") == "GET" for row in calls)
    )
    checks["html_exposes_ai_usage_audit_contract"] = (
        "ai_usage_ledger" in html
        and "ai_usage_summary" in html
        and "no_ai_token_used" in html
        and "本地规则 / 0 token" in html
    )
    checks["hourglass_renders_real_page_repair_risk_state"] = (
        "page_state_summary" in html
        and "repair_summary" in html
        and "risk_summary" in html
        and "account_health_summary" in html
        and "run_recovery_summary" in html
        and "autonomous_preflight_reconciliation" in html
        and "autonomy_readiness_summary" in html
        and "product_capability_summary" in html
        and "delivery_boundary" in html
        and "refreshProductCapability" in html
        and any(row.get("url") == "/api/product-capability" and row.get("method") == "GET" for row in calls)
        and "产品闭环" in html
        and "交付边界" in html
        and "自治链路" in html
        and payload.get("hourglassState") == "页面状态阻断"
        and "未知页面状态" in str(payload.get("hourglassDecisionTitle") or "")
        and "page_snapshots=2" in str(payload.get("hourglassDecisionBody") or "")
        and "页面状态" in str(payload.get("hourglassLegend") or "")
        and "自修复" in str(payload.get("hourglassLegend") or "")
        and "风险动作" in str(payload.get("hourglassLegend") or "")
        and "账号健康" in str(payload.get("hourglassLegend") or "")
        and "中断恢复" in str(payload.get("hourglassLegend") or "")
        and "预判对账" in str(payload.get("hourglassLegend") or "")
        and "自治链路" in str(payload.get("hourglassLegend") or "")
        and "产品闭环" in str(payload.get("hourglassLegend") or "")
        and "交付边界" in str(payload.get("hourglassLegend") or "")
    )
    hourglass_particles = str(payload.get("hourglassParticles") or "")
    checks["hourglass_particles_are_bound_to_runtime_evidence"] = (
        "class=\"particle page\"" in hourglass_particles
        and "class=\"particle repair\"" in hourglass_particles
        and "class=\"particle risk\"" in hourglass_particles
        and "class=\"particle account\"" in hourglass_particles
        and "class=\"particle recovery\"" in hourglass_particles
        and "class=\"particle reconcile\"" in hourglass_particles
        and "class=\"particle autonomy\"" in hourglass_particles
        and "class=\"particle product\"" in hourglass_particles
        and "class=\"particle delivery\"" in hourglass_particles
        and "title=\"页面状态：2\"" in hourglass_particles
        and "title=\"自修复：1\"" in hourglass_particles
        and "title=\"风险动作：2\"" in hourglass_particles
        and "title=\"账号健康：3\"" in hourglass_particles
        and "title=\"中断恢复：1\"" in hourglass_particles
        and "title=\"自治链路：8\"" in hourglass_particles
        and "title=\"产品闭环：8\"" in hourglass_particles
        and "title=\"交付边界：2\"" in hourglass_particles
    )
    checks["html_group_refresh_has_inflight_guard"] = "groupRefreshInFlight" in html and "刷新中，保留上次读取" in html and "同步确认中" in html
    checks["html_refresh_failures_are_operator_visible"] = "本地服务连接失败" in html and "读取失败：本地服务连接失败" in html and "$('runState').textContent = 'OFFLINE'" in html
    checks["html_profile_close_reason_is_operator_visible"] = "浏览器处理" in html and "不是闪退" in html and "closeActionLabel" in html
    checks["ixbrowser_status_visible_to_operator"] = any(row.get("url") == "/api/ixbrowser-status" for row in calls) and "blocked" in str(payload.get("ixbrowserApiState") or "") and "ixBrowser Local API" in str(payload.get("ixbrowserApiState") or "") and "开启 Local API" in str(payload.get("ixbrowserApiTitle") or "") and "开启 Local API" in str(payload.get("ixbrowserStatusActions") or "")
    checks["ixbrowser_port_config_posts_api"] = any(row.get("url") == "/api/ixbrowser-config" and str((row.get("body") or {}).get("port")) == "53201" for row in post_calls) and payload.get("ixPortNoticeTitle") == "ixBrowser端口已应用"
    checks["click_start_posts_api_start"] = any(row.get("url") == "/api/start" for row in post_calls)
    checks["click_start_posts_operator_payload"] = any(
        row.get("url") == "/api/start"
        and (row.get("body") or {}).get("target") == "anti aging serum"
        and (row.get("body") or {}).get("sourceType") == "keyword"
        and (row.get("body") or {}).get("group") == "Canada"
        and (row.get("body") or {}).get("commentText") == "Hi"
        and (row.get("body") or {}).get("accountRepairConfirmed") is False
        for row in post_calls
    )
    checks["account_repair_recheck_control_visible"] = (
        'id="accountRepairConfirmed"' in html
        and 'id="applyAccountRepair"' in html
        and "/api/account-repair-apply" in html
        and "applyAccountRepairPlan" in html
        and "隔离坏账号" in html
        and "已修复账号，允许重新预检" in html
        and "accountRepairConfirmed:$('accountRepairConfirmed').checked" in html
        and "账号池无可执行账号，已禁止重复启动" in html
        and "账号修复计划：" in html
        and 'data-reachops-ui-version="reachops-unified-ui-2026-07-05-v20-ai-machine-actions"' in html
        and 'id="aiConsoleMachineList"' in html
        and 'id="aiConsoleTimelineList"' in html
        and "machine_actions" in html
        and "timeline_summary" in html
        and 'id="accountGateState"' in html
        and "账号门禁已启用" in html
        and 'id="uiVersion"' in html
        and "${blockedGroupLabel} 账号阻断" in html
        and "accountGatePendingRecheck" in html
        and "等待重新预检" in html
        and "旧账号修复结果已失效" in html
        and "请先刷新 ixBrowser 配置分组" in html
        and "最近一次账号预检没有可用账号" in html
        and "ReachOps 本地客户端控制台" in html
        and "127.0.0.1 控制台" in html
        and "客户端 v20" in html
        and "accountRepairActionItems" in html
        and "accountGateAppliesToCurrentGroup() && !isAccountRepairConfirmed()" in html
    )
    checks["account_gate_blocks_start_until_repair_confirmed"] = (
        payload.get("clientDeliveryOnlyGateStartDisabled") is True
        and "Canada 最近一次账号预检没有可用账号" in str(payload.get("clientDeliveryOnlyGateStartTitle") or "")
        and payload.get("clientDeliveryOnlyGateStateText") == "Canada 账号阻断"
        and payload.get("accountGateStartDisabled") is True
        and payload.get("accountRepairApplyDisabled") is False
        and "硬失败账号移入封禁账号分组" in str(payload.get("accountRepairApplyTitle") or "")
        and "Canada 最近一次账号预检没有可用账号" in str(payload.get("accountGateStartTitle") or "")
        and payload.get("accountGateStateText") == "Canada 账号阻断"
        and "IXBROWSER_KERNEL_MISMATCH" in str(payload.get("accountGateAcceptanceBlockers") or "")
        and "LOGIN_REQUIRED" in str(payload.get("accountGateAcceptanceBlockers") or "")
        and "旧账号修复结果已失效" in str(payload.get("accountRepairStaleBlockers") or "")
        and "不要继续勾选旧的重新预检" in str(payload.get("accountRepairStaleBlockers") or "")
        and payload.get("accountRepairStaleStartRequestDelta") == 0
        and payload.get("accountRepairStaleStartTitle") == "账号修复后再启动"
        and "旧账号修复结果已失效" in str(payload.get("accountRepairStaleStartBody") or "")
        and "最新账号修复计划" in str(payload.get("accountRepairStaleStartActions") or "")
        and payload.get("accountGateDifferentGroupStartDisabled") is False
        and payload.get("accountGateDifferentGroupStartTitle") == "开始获客"
        and payload.get("accountGateDifferentGroupStateText") == "账号门禁已启用"
        and payload.get("accountGateSameGroupStartDisabledAfterSwitch") is True
        and payload.get("accountGateStartRequestDelta") == 0
        and payload.get("accountGateBlockedTitle") == "账号修复后再启动"
        and "IXBROWSER_KERNEL_MISMATCH" in str(payload.get("accountGateBlockedActions") or "")
        and "LOGIN_REQUIRED" in str(payload.get("accountGateBlockedActions") or "")
        and payload.get("accountRepairApplyTitleAfterClick") == "账号修复计划已执行"
        and "已隔离=2" in str(payload.get("accountRepairApplyBodyAfterClick") or "")
        and "可以直接点击开始获客复测" in str(payload.get("accountRepairApplyBodyAfterClick") or "")
        and "已隔离账号 21644" in str(payload.get("accountRepairApplyActionsAfterClick") or "")
        and payload.get("accountRepairAutoConfirmedAfterApply") is True
        and payload.get("accountRepairConfirmedStartDisabled") is False
        and payload.get("accountRepairConfirmedStartTitle") == "开始获客"
        and payload.get("accountRepairConfirmClearedOnGroupSwitch") is True
    )
    checks["account_repair_pending_recheck_refresh_unlocks_start"] = (
        payload.get("accountRepairPendingRecheckAutoConfirmed") is True
        and payload.get("accountRepairPendingRecheckStartDisabled") is False
        and payload.get("accountRepairPendingRecheckStartTitle") == "开始获客"
        and payload.get("accountRepairPendingRecheckGateStateText") == "United States 等待重新预检"
    )
    checks["refresh_groups_loads_config_list"] = any(row.get("url") == "/api/groups?refresh=1" for row in calls) and "Canada" in str(payload.get("groupInnerHTML") or "") and "United States" in str(payload.get("groupInnerHTML") or "")
    checks["refresh_groups_shows_each_group_count"] = "Canada（2账号）" in str(payload.get("groupInnerHTML") or "") and "United States（3账号）" in str(payload.get("groupInnerHTML") or "") and "ixbrowser_profile_list" in str(payload.get("groupDetails") or "")
    checks["selected_group_quantity_updates_after_selection"] = payload.get("selectedGroupNameBeforePortApply") == "Canada" and payload.get("selectedGroupCountBeforePortApply") == "2账号"
    checks["selected_config_group_drives_start_payload"] = any(
        row.get("url") == "/api/start" and (row.get("body") or {}).get("group") == "Canada"
        for row in post_calls
    ) and payload.get("currentGroupBeforePortApply") == "Canada（2账号）"
    checks["click_controls_post_api_control"] = {
        (row.get("body") or {}).get("action")
        for row in post_calls
        if row.get("url") == "/api/control"
    } >= {"pause", "resume", "stop"}
    checks["click_account_repair_apply_posts_api"] = any(
        row.get("url") == "/api/account-repair-apply"
        and row.get("method") == "POST"
        and (row.get("body") or {}).get("confirm") is True
        and (row.get("body") or {}).get("group") == "Canada"
        for row in post_calls
    )
    checks["click_init_acceptance_inputs_posts_api"] = any(
        row.get("url") == "/api/acceptance-input-init" and row.get("method") == "POST"
        for row in post_calls
    )
    checks["click_refresh_mvp_acceptance_posts_api"] = any(
        row.get("url") == "/api/mvp-acceptance-refresh" and row.get("method") == "POST"
        for row in post_calls
    )
    checks["click_refresh_goal_delivery_posts_api"] = any(
        row.get("url") == "/api/goal-delivery-refresh" and row.get("method") == "POST"
        for row in post_calls
    )
    checks["unconfirmed_live_comment_click_does_not_post_start"] = (
        payload.get("unconfirmedLiveRequestCount") == 0
        and payload.get("unconfirmedLiveTitle") == "真实评论未确认"
    )
    checks["operator_notice_updates_after_api_response"] = str(payload.get("controlTitle") or "").startswith("控制已执行")
    checks["activation_status_is_visible_to_operator"] = "无激活文件" in str(payload.get("activationState") or "")
    checks["activation_next_actions_visible_to_operator"] = "生成或放置真实激活状态文件" in str(payload.get("activationActions") or "")
    checks["final_status_is_visible_to_operator"] = "不可最终交付" in str(payload.get("finalStatusState") or "")
    checks["final_status_actions_visible_to_operator"] = "init_reachops_acceptance_inputs_windows.ps1" in str(payload.get("finalStatusActions") or "")
    checks["final_status_shows_mvp_local_acceptance"] = "本地MVP已验收" in str(payload.get("finalStatusActions") or "")
    checks["final_status_shows_goal_delivery_boundary"] = "目标模式：local_mvp_accepted_final_pending" in str(payload.get("finalStatusActions") or "") and "最终交付=false" in str(payload.get("finalStatusActions") or "")
    checks["final_status_shows_local_product_boundary"] = "本地产品边界：local_capability_ready_final_pending" in str(payload.get("finalStatusActions") or "") and "产品能力=true" in str(payload.get("finalStatusActions") or "") and "本地边界待完成：external_authorized_execution" in str(payload.get("finalStatusActions") or "")
    checks["final_status_shows_pm_delivery_boundary"] = "交付边界：" in str(payload.get("finalStatusActions") or "") and "整体最终交付=false" in str(payload.get("finalStatusActions") or "") and "不代表整项目最终交付完成" in str(payload.get("finalStatusActions") or "")
    checks["final_status_shows_goal_summary_path"] = "目标摘要：" in str(payload.get("finalStatusActions") or "") and "latest_goal_delivery_summary.md" in str(payload.get("finalStatusActions") or "")
    checks["final_status_shows_two_phase_matrix"] = "两阶段矩阵：local_mvp_accepted_final_pending" in str(payload.get("finalStatusActions") or "") and "两阶段阻断：external_authorized_execution" in str(payload.get("finalStatusActions") or "")
    checks["final_status_shows_two_phase_matrix_links"] = "两阶段矩阵JSON：" in str(payload.get("finalStatusActions") or "") and "latest_two_phase_acceptance_matrix.json" in str(payload.get("finalStatusActions") or "") and "两阶段矩阵Markdown：" in str(payload.get("finalStatusActions") or "") and "latest_two_phase_acceptance_matrix.md" in str(payload.get("finalStatusActions") or "")
    checks["final_status_shows_live_validation_summary"] = "授权输入：账号=0" in str(payload.get("finalStatusActions") or "") and "当前首要阻断：ixBrowser 数字 Profile ID" in str(payload.get("finalStatusActions") or "")
    checks["final_status_shows_local_input_field_status"] = "字段：ProfileIds = placeholder" in str(payload.get("finalStatusActions") or "") and "字段：ActivationStatusPath = placeholder" in str(payload.get("finalStatusActions") or "") and "字段：ConfirmAuthorizedTargets = authorization_not_confirmed" in str(payload.get("finalStatusActions") or "")
    checks["final_status_shows_structured_blocking_plan"] = "阶段：授权输入 / blocked" in str(payload.get("finalStatusActions") or "") and "阶段：激活状态 / blocked" in str(payload.get("finalStatusActions") or "") and "阶段：Windows交付包 / blocked" in str(payload.get("finalStatusActions") or "") and "阶段：最终门禁 / blocked" in str(payload.get("finalStatusActions") or "")
    checks["final_status_shows_deliverable_index"] = "交付索引：" in str(payload.get("finalStatusActions") or "") and "Windows最终包=missing" in str(payload.get("finalStatusActions") or "") and "最终门禁=blocked" in str(payload.get("finalStatusActions") or "")
    checks["final_status_shows_final_delivery_blockers"] = "最终阻断：external_authorized_execution" in str(payload.get("finalStatusActions") or "") and "最终阻断：windows_final_artifacts" in str(payload.get("finalStatusActions") or "")
    checks["final_status_shows_required_final_evidence"] = "必需证据：comment_visible_confirmed=true" in str(payload.get("finalStatusActions") or "") and "必需产物：reports\\reachops_acceptance\\acceptance_summary.json" in str(payload.get("finalStatusActions") or "")
    checks["final_status_shows_final_delivery_evidence_plan"] = "证据计划：reachops.final_delivery_evidence_plan.v1" in str(payload.get("finalStatusActions") or "") and "证据项：external_authorized_execution" in str(payload.get("finalStatusActions") or "") and "验收字段：goal_status.pending_external_validation=[]" in str(payload.get("finalStatusActions") or "") and "验收命令：python tools\\reachops_delivery_package_check.py --json" in str(payload.get("finalStatusActions") or "")
    checks["final_status_shows_live_readiness_report_link"] = "授权准备报告：" in str(payload.get("finalStatusActions") or "") and "latest_live_acceptance_readiness.md" in str(payload.get("finalStatusActions") or "") and "/api/download?path=" in str(payload.get("finalStatusActions") or "")
    checks["final_status_shows_live_readiness_json_link"] = "授权交接JSON：" in str(payload.get("finalStatusActions") or "") and "latest_live_acceptance_readiness.json" in str(payload.get("finalStatusActions") or "") and "/api/download?path=" in str(payload.get("finalStatusActions") or "")
    checks["final_status_shows_authorization_handoff_bundle_link"] = "授权交接包：" in str(payload.get("finalStatusActions") or "") and "latest_reachops_authorization_handoff.zip" in str(payload.get("finalStatusActions") or "") and "/api/download?path=" in str(payload.get("finalStatusActions") or "")
    checks["final_status_shows_authorization_handoff_bundle_verification"] = "授权交接包校验：passed" in str(payload.get("finalStatusActions") or "")
    checks["final_status_shows_operator_commands"] = "操作命令：powershell -ExecutionPolicy Bypass -File tools\\init_reachops_acceptance_inputs_windows.ps1 -Json" in str(payload.get("finalStatusActions") or "") and "--write-report --json-report-path --json" in str(payload.get("finalStatusActions") or "")
    checks["final_status_hides_flat_blocker_noise"] = "交付命令：" not in str(payload.get("finalStatusActions") or "") and "失败检查：live_validation:inputs" not in str(payload.get("finalStatusActions") or "") and "PM阻断范围：" not in str(payload.get("finalStatusActions") or "")
    checks["final_status_commands_visible_to_operator"] = "reachops_final_acceptance_gate.py" in str(payload.get("finalStatusCommands") or "") and "reachops_delivery_package_check.py" in str(payload.get("finalStatusCommands") or "") and "reachops_goal_delivery_runner.py" in str(payload.get("finalStatusCommands") or "")
    checks["init_acceptance_inputs_feedback_visible_to_operator"] = (
        "已生成本地验收输入" in str(payload.get("initNoticeTitle") or "")
        and (
            "HTTP 200" in str(payload.get("initNoticeBody") or "")
            or "created" in str(payload.get("initNoticeBody") or "")
            or "reachops_acceptance_inputs.local.ps1" in str(payload.get("initNoticeBody") or "")
        )
    )
    checks["mvp_acceptance_visible_to_operator"] = "MVP已通过" in str(payload.get("acceptanceState") or "") and "latest_mvp_acceptance_summary" in str(payload.get("reportTable") or "")
    checks["goal_delivery_visible_to_operator"] = "目标：local_mvp_accepted_final_pending" in str(payload.get("acceptanceState") or "") and "latest_goal_delivery_report" in str(payload.get("reportTable") or "") and "Windows打包前置门禁" in str(payload.get("reportTable") or "")
    checks["goal_delivery_summary_visible_to_operator"] = "目标模式PM摘要" in str(payload.get("reportTable") or "") and "latest_goal_delivery_summary.md" in str(payload.get("reportTable") or "")
    checks["goal_delivery_summary_download_link_visible"] = "/api/download?path=" in str(payload.get("reportTable") or "") and "latest_goal_delivery_summary.md" in str(payload.get("reportTable") or "")
    checks["two_phase_matrix_visible_to_operator"] = "两阶段验收矩阵 JSON" in str(payload.get("reportTable") or "") and "latest_two_phase_acceptance_matrix.json" in str(payload.get("reportTable") or "") and "两阶段验收矩阵 Markdown" in str(payload.get("reportTable") or "")
    checks["account_repair_plan_visible_to_operator"] = (
        "最新账号修复计划" in str(payload.get("reportTable") or "")
        and "latest_account_repair_plan.md" in str(payload.get("reportTable") or "")
        and "latest_account_repair_plan.json" in str(payload.get("reportTable") or "")
        and "/api/download?path=" in str(payload.get("reportTable") or "")
    )
    checks["refresh_mvp_acceptance_feedback_visible_to_operator"] = (
        "MVP验收已刷新" in str(payload.get("mvpNoticeTitle") or "")
        and (
            "HTTP 200" in str(payload.get("mvpNoticeBody") or "")
            or "mvp_accepted_external_pending" in str(payload.get("mvpNoticeBody") or "")
            or "mvp_local_ready" in str(payload.get("mvpNoticeBody") or "")
        )
    )
    checks["refresh_goal_delivery_feedback_visible_to_operator"] = (
        "目标报告已刷新" in str(payload.get("goalNoticeTitle") or "")
        and (
            "HTTP 200" in str(payload.get("goalNoticeBody") or "")
            or "local_mvp_accepted_final_pending" in str(payload.get("goalNoticeBody") or "")
            or "windows_build_ready" in str(payload.get("goalNoticeBody") or "")
        )
    )
    checks["start_button_reenabled_after_click"] = payload.get("startDisabled") is False
    failed = [name for name, ok in checks.items() if not ok]
    return {
        "status": "passed" if not failed else "failed",
        "passed": not failed,
        "failed_checks": failed,
        "checks": checks,
        "call_count": len(calls),
        "post_calls": post_calls,
        "operator_title": payload.get("operatorTitle"),
        "operator_body": payload.get("operatorBody"),
        "control_title": payload.get("controlTitle"),
        "control_body": payload.get("controlBody"),
        "activation_state": payload.get("activationState"),
        "final_status_state": payload.get("finalStatusState"),
        "final_status_title": payload.get("finalStatusTitle"),
        "final_status_actions": payload.get("finalStatusActions"),
        "final_status_commands": payload.get("finalStatusCommands"),
        "hourglass_debug": {
            "state": payload.get("hourglassState"),
            "decision_title": payload.get("hourglassDecisionTitle"),
            "decision_body": payload.get("hourglassDecisionBody"),
            "particles_sample": str(payload.get("hourglassParticles") or "")[:1600],
        },
        "init_notice_title": payload.get("initNoticeTitle"),
        "init_notice_body": payload.get("initNoticeBody"),
        "mvp_notice_title": payload.get("mvpNoticeTitle"),
        "mvp_notice_body": payload.get("mvpNoticeBody"),
        "pending_recheck_debug": {
            "auto_confirmed": payload.get("accountRepairPendingRecheckAutoConfirmed"),
            "start_disabled": payload.get("accountRepairPendingRecheckStartDisabled"),
            "start_title": payload.get("accountRepairPendingRecheckStartTitle"),
            "gate_state": payload.get("accountRepairPendingRecheckGateStateText"),
            "frontend_debug": payload.get("accountRepairPendingRecheckDebug"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Execute ReachOps Web panel JavaScript against a minimal DOM/fetch harness.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = run_dom_smoke()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    else:
        print(f"status={result['status']} failed_checks={','.join(result['failed_checks']) or '-'}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
