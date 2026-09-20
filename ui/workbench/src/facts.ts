import type { FactRecord, TaskIndexRow } from './types';
export function record(value: unknown): FactRecord {
    return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as FactRecord : {};
}
export function records(value: unknown): FactRecord[] {
    return Array.isArray(value) ? value.filter(v => v !== null && typeof v === 'object' && !Array.isArray(v)) : [];
}
export function text(value: unknown): string {
    return typeof value === 'string' ? value : typeof value === 'number' || typeof value === 'boolean' ? String(value) : '';
}
export function valueText(value: unknown): string {
    if (value === null || value === undefined || value === '')
        return '未记录';
    if (typeof value === 'boolean')
        return value ? '是' : '否';
    return typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value);
}
/* Times arrive from several sources whose ISO offsets differ inside one response
   (workbench reads carry +00:00, Runtime records carry +08:00). They are rendered on one clock —
   the viewer's local zone — so the same instant never shows two different wall times. The exact
   source string stays available through the `dateTime` attribute and the `title` tooltip. */
const ISO_DATETIME = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?$/;
function pad(value: number): string {
    return String(value).padStart(2, '0');
}
export function timestampRaw(value: unknown): string {
    const raw = text(value);
    return ISO_DATETIME.test(raw) && !Number.isNaN(Date.parse(raw)) ? raw : '';
}
/* Falls back to `valueText`, so any non-timestamp scalar keeps its existing rendering verbatim. */
export function timestampText(value: unknown): string {
    const raw = timestampRaw(value);
    if (!raw)
        return valueText(value);
    const at = new Date(raw);
    return `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())} ${pad(at.getHours())}:${pad(at.getMinutes())}:${pad(at.getSeconds())}`;
}
/* Chinese explanations for Runtime/Workbench contract enums, keyed by FIELD NAME: a value-only map
   would also hit prose (`structured`, `ok`, `task` … appear inside free text and paths). The raw
   token is always kept in parentheses, so a wording choice can never hide the source value.
   Deliberately absent: verdict tokens such as `PASS` / `FAIL` — the UI must not restate a recorded
   verdict as acceptance, and unknown values keep rendering verbatim. */
/* Role ids as they appear on events (`actor`) and task rows (`owner`). Names are taken from
   `governance/role-catalog.yaml`'s `display_name` with its redundant `tp-` prefix dropped — that
   catalog is the only authority for these names, so nothing here is invented. The two entries whose
   display name is itself English (`tp-knowledge`, `tp-wiki`) are deliberately absent: an invented
   Chinese name would be worse than the raw id, so they keep rendering verbatim.

   Declared before `explanations` on purpose: `explanations` spreads this object at initialisation
   time, so a later `const` would be in its temporal dead zone. */
const roleNames: Record<string, string> = {
    'tp-spec-coding': '统一入口',
    'tp-software-lifecycle': '软件工程生命周期',
    'tp-project-autonomy': '项目自治维护',
    'tp-base-maintenance': '基座维护',
    'tp-product-manager': '产品经理',
    'tp-software-architect': '软件架构师',
    'tp-tech-lead': '技术主管',
    'tp-security-engineer': '安全工程师',
    'tp-development-engineer': '开发工程师',
    'tp-database-engineer': '数据库工程师',
    'tp-test-engineer': '测试工程师',
    'tp-code-reviewer': '代码审查员',
    'tp-integration-engineer': '集成交付工程师',
};
const explanations: Record<string, Record<string, string>> = {
    health: { ok: '正常', degraded: '降级', unavailable: '不可用' },
    runtime_status: { available: '可用', unavailable: '不可用', UNKNOWN: '未知（未上报）' },
    status: { available: '可用', missing: '缺失', partial: '部分可用', degraded: '降级', ok: '正常', healthy: '健康', not_recorded: '未记录' },
    default_workspace_status: { not_defined: '未定义' },
    /* Skill topology: what a node is and how an edge links it. `mode` already covers 默认 / 条件性,
       which is exactly the two values those edges carry. */
    kind: { 'product-entry': '产品入口', 'domain-agent': '领域 Agent', 'formal-role': '正式角色', 'capability-skill': '能力 SKILL' },
    relation: { 'routes-to': '路由到', 'owns-role': '拥有角色', 'uses-skill': '使用 SKILL' },
    identity_source: { 'project-binding': '项目 Binding 文件' },
    source: { 'registry-root': '注册表根', installation_config: '安装配置' },
    consistency: { RECORDED: '已记录', NOT_RECORDED: '未记录', live_files: '实时文件读取' },
    summary_source: { latest_event: '最近事件' },
    source_kind: { structured: '结构化' },
    verification: { structured: '结构化', legacy_unverified: '历史未核验', not_provided: '未提供', not_recorded: '未记录' },
    verification_scope: { technical: '技术验证' },
    review_kind: { VERIFICATION: '验证', CODE: '代码' },
    severity: { info: '提示', warning: '告警', error: '错误' },
    completeness: { complete: '完整', partial: '部分' },
    event_type: { FACT: '事实记录', CHECKPOINT: '检查点', VERIFICATION_COMPLETED: '验证完成', REVIEW_COMPLETED: '审查完成', OWNER_ACCEPTANCE_DECISION: '人工验收决定' },
    operation: { CHECKPOINT: '检查点', VERIFY: '验证', REVIEW: '审查', checkpoint: '检查点', verify: '验证', review: '审查', SCOPE_CHANGE: '范围变更' },
    phase: { intake: '受理', planning: '规划', development: '开发', verification: '验证', VERIFYING: '验证中', delivery: '交付', CLOSING: '结单中', COMPLETED: '已完成' },
    from_stage: { planning: '规划', development: '开发', verification: '验证', delivery: '交付' },
    to_stage: { planning: '规划', development: '开发', verification: '验证', delivery: '交付' },
    mode: { default: '默认', conditional: '条件性', accept: '实际接受', defer: '延期', waive: '豁免' },
    result_status: { COMPLETED: '已完成', ACTIVE: '进行中', PENDING: '待处理', NOT_RECORDED: '未记录' },
    status_class: { ok: '正常', warning: '告警', unsafe: '不安全' },
    type: { local_file: '本地文件' },
    domain: { software: '软件' },
    /* A knowledge scope id as it appears inside a bare id array — the one place where a list holds raw
       ids instead of records. This entry reaches the screen only through `FactValue`'s primitive-array
       branch, which applies the PARENT field name to each element. */
    ids: { shared: '共享技术概念' },
    /* The same role id arrives under three names: `actor` on an event, `actor_role` inside a
       checkpoint/event detail, `owner` on a task-index row. All three are the same concept, so they
       share one map — `owner` keeps its own non-role value. */
    actor: roleNames,
    actor_role: roleNames,
    owner: { human_owner: '人工负责人', ...roleNames },
};
export function explainValue(key: string, value: unknown): string {
    const raw = text(value);
    const explained = explanations[key]?.[raw];
    return explained ? `${explained}（${raw}）` : '';
}
/* Chinese labels for the Runtime/Workbench field names that `Fields` renders as keys. Call-site
   `labels` overrides still win; the raw field name stays reachable through the label's title tooltip.
   Unmapped keys keep rendering verbatim — a wrong label is worse than an English one. */
const fieldLabels: Record<string, string> = {
    id: 'ID', task_id: 'Task ID', work_item_id: 'WorkItem ID', event_id: '事件 ID', last_event_id: '最近事件 ID',
    request_id: '请求 ID', transaction_id: '事务 ID', flush_id: '落盘批次 ID', change_set_id: '变更集 ID',
    root_id: '根 ID', profile_id: '配置档 ID', project_id: '项目 ID',
    title: '标题', summary: '摘要', summary_source: '摘要来源', type: '类型', state: '状态', phase: '阶段',
    operation: '操作', decision: '记录的结论', result_status: '记录的执行状态', event_type: '事件类型',
    verification: '验证', verification_scope: '验证范围', runtime_status: 'Runtime 状态',
    identity_source: '身份来源', consistency: '一致性', completeness: '完整性', integrity: '哈希核对结论',
    path: '路径', raw_path: '原始路径', display_path: '显示路径', normalized_path: '规范化路径',
    copy_path: '可复制路径', inventory_path: '清单路径', repo_roots: '仓库根',
    display_name: '显示名称', scope_label: '范围说明', occurrence_count: '引用次数', anchor: '路径锚点',
    current_exists: '读取时文件存在', inspection: '文件读取状态', current_sha256: '本次文件哈希',
    sha256: '该次引用原哈希', payload_sha256: '载荷哈希', change_set_snapshot_digest: '变更集快照摘要',
    sources: '引用来源', field: '来源字段', evidence: '证据', detail: '原始明细', response: '响应',
    checks: '检查项', producer: '产生方', actor: '记录角色', owner: '负责人', replayed: '是否为重放',
    logical_request: '逻辑请求', schema_version: '结构版本', reference_assets: '参考资产',
    created_at: '记录时间', updated_at: '更新时间', started_at: '开始时间', completed_at: '结束时间',
    workspaces: '工作区', default_workspace: '默认工作区', default_workspace_status: '默认工作区状态',
    layout: '布局', contexts: '上下文', task_index: '任务索引', in_progress_tasks: '进行中任务',
    work_sessions: '已记录工作段', timeline: '时间线', timeline_scope: '时间线范围', current_step: '当前步骤',
    steps: '阶段', nodes: '节点', dependencies: '依赖', workflow: '流程', flow_level: '流程等级',
    required: '必需', required_states: '必需状态', data_support: '数据支持', base: '安装基座',
    identity: '身份', autonomy: '自主配置', evaluation: '本次判定', effective: '当前有效',
    visual: '视觉', visual_acs: '当前有效视觉 AC', required_acs: '必需 AC', waived: '豁免', deferred: '延期',
    waiting: '结构化等待', configuration_error: '配置错误', shared_scope: '共享范围',
    witness_evidence: '见证证据', chunks: '分块数', project_count: '项目数量', paired_count: '已配对数量',
    open_count: '未关闭数量', unknown_duration_count: '时长未知数量', invalid_event_count: '无效事件数量',
    unmatched_end_count: '未配对结束数量', total: '合计', limit: '上限', returned: '已返回',
    active: '活跃', completed: '已结单', cancelled: '已取消', retired: '已退休', pending: '待处理',
    ACTIVE: '活跃', COMPLETED: '已结单', CANCELLED: '已取消', PENDING: '待处理', CLOSED: '已关闭',
    /* Task states, in the canonical upper case the Runtime uses and the lower case used as buckets.
       `other_states` keeps the canonical name as its key, hence both spellings. */
    NEW: '新建', BLOCKED: '阻塞', DEVELOPING: '开发中', ASSISTING: '协助中', VERIFYING: '验证中',
    BROWSER_VERIFYING: '浏览器验证中', REVIEWING: '评审中', CLOSING: '结单中', RETIRED: '已退休',
    TECH_DESIGNING: '技术设计中', UNRECORDED: '未记录', OTHER: '其他',
    developing: '开发中', assisting: '协助中', verifying: '验证中', tech_designing: '技术设计中',
    browser_verifying: '浏览器验证中', reviewing: '评审中', closing: '结单中', unrecorded: '未记录',
    other: '其他', other_states: '其他明细',
    current: '当前', counts: '计数', work_items: '工作项', schema: '数据契约',
    change_set: '变更集', content_digest: '内容摘要', snapshot_digest: '快照摘要', product_digest: '产品摘要',
    subject_digest: '受验主体摘要', repositories: '代码库', root_locator: '仓库定位路径',
    head: 'HEAD 提交', head_tree: 'HEAD 树', tracked_patch_sha256: '跟踪补丁哈希',
    cli_invocation_id: 'CLI 调用 ID', evidence_items: '证据条目', evidence_path: '证据引用路径',
    source_event_id: '来源事件 ID', source_kind: '来源类型', review_kind: '审查类型',
    from_state: '起始状态', to_state: '目标状态', from_stage: '起始阶段', to_stage: '目标阶段',
    milestone_id: '里程碑 ID', presentation: '展示信息', event_label: '事件名称',
    reason_label: '原因说明', status_class: '状态分类', source: '来源', name: '名称',
    actor_role: '角色标识', knowledge_signals: 'Knowledge 信号', delivery_signals: 'Delivery 信号',
    evidence_count: '证据条目数', development_event_id: '开发事件 ID',
    /* Panel-level fields: the surface that is visible before any nested "展开字段" */
    status: '状态', exists: '是否存在', registry: '注册表', registry_path: '注册表路径',
    registry_exists: '注册表文件是否存在', project_scope: '项目范围', projection: '知识库投影',
    workspace_root: '工作区根目录', workspace_id: '工作区 ID', context_key: '上下文标识',
    project_root: '项目根目录', project_name: '项目名称', db_path: '数据库路径', runtime_db: 'Runtime 数据库',
    user_root: '用户目录', source_root: '源码根', active_source_root: '当前源码根', base_root: '基座根目录',
    root: '根目录', root_path: '根路径', task_dir: '任务目录', profiles_path: '自主配置目录',
    generated_at: '生成时间', health: '健康状态', note: '说明', version: '版本',
    base_version: '基座版本', contract_version: '契约版本', version_match: '版本是否匹配',
    valid: '是否有效', configured: '是否已配置', resolved: '是否已解析', declared: '是否已声明',
    database: '数据库文件', documents: '文档数', issues: '问题', ids: 'ID 列表', count: '数量',
    /* Structures, enums and subjects */
    wiki: 'Wiki', knowledge: 'Knowledge', task: '任务', project: '项目', workspace: '工作区',
    resolver: '解析器', registered_projects: '已注册项目', skill_topology: '技能拓扑',
    task_statistics: '任务统计', archived_tasks: '已归档任务', latest_checkpoint: '最近 checkpoint',
    acceptance: '验收', review: '审查', delivery: '交付', owner_acceptance: '责任人验收',
    binding: '绑定', profiles: '配置档', profile_count: '配置档数量', execution_mode: '执行方式',
    execution_mode_declared: '执行方式是否声明', edges: '连线', node_count: '节点数', edge_count: '连线数',
    blockers: '阻塞项', risk_level: '风险等级', items: '条目', rows: '行', scope: '范围',
    /* Timeline, ledger and event detail */
    history: '历史', history_scope: '历史范围', recorded: '已记录', ledger_trusted: '账本是否可信',
    applicability: '适用性', current_applicability: '当前适用性', reasons: '原因',
    last_recorded_at: '最近记录时间', last_event_type: '最近事件类型', last_end_reason: '最近结束原因',
    open_sessions: '未结束工作段', work_unit: '工作单元', agent_thread_binding: '代理线程绑定',
    work_item_parent: '工作项父级', task_revision: '任务修订', error: '错误',
    completed_steps: '已完成阶段', next_step: '下一步', reference_steps: '参考阶段', route: '路由',
    completion_scope: '结单范围', new: '新增', blocked: '阻塞', verification_attention: '待处理验证（不计入合计）',
    page_verification: '页面验证', database_operations: '数据库操作', no_acceptance_required: '无需验收',
    legacy_blocker: '历史阻塞项', problems: '问题', read: '读取', context: '上下文', data: '数据',
};
export function fieldLabel(key: string, overrides: Record<string, string> = {}): string {
    return overrides[key] ?? fieldLabels[key] ?? key;
}
export function stageLabel(step: unknown): string {
    const row = record(step), display = record(row.stage_display);
    const id = text(row.stage);
    if (!id)
        return '';
    return display.configured === true && text(display.label) ? text(display.label) : `${id}（展示名称未配置）`;
}
const states: Record<string, Record<string, string>> = {
    task: { NEW: '新建', ACTIVE: '活跃', BLOCKED: '阻塞', COMPLETED: '已结单', CANCELLED: '已取消' },
    work_item: { PENDING: '待处理', ACTIVE: '已认领', COMPLETED: '工作项已完成' },
};
export function stateLabel(kind: string, state: unknown): string {
    const raw = text(state);
    if (!raw)
        return '未记录';
    const label = states[kind]?.[raw];
    return label ? `${label} · ${raw}` : `${raw}（未识别）`;
}
export function stateTone(kind: string, state: unknown): string {
    const raw = text(state);
    if (!states[kind]?.[raw])
        return 'unknown';
    return raw === 'BLOCKED' ? 'blocked' : raw === 'COMPLETED' ? 'completed' : raw === 'ACTIVE' ? 'active' : 'neutral';
}
/* Two sentinel views that together partition every row into 活跃任务 + 其他任务.
   `OPEN_FILTER` is deliberately broader than the single ACTIVE state so BLOCKED work is never hidden. */
export const OPEN_FILTER = '__open__';
export const OTHER_FILTER = '__other__';
export function isOpenTask(row: TaskIndexRow): boolean {
    return !row.retired && row.state !== 'COMPLETED' && row.state !== 'CANCELLED';
}
/* Generic over the row type so a caller that carries extra fields (a search hit carries its
   project) gets them back instead of a widened `TaskIndexRow`. */
export function filterTasks<T extends TaskIndexRow>(rows: T[], query: string, state: string): T[] {
    const q = query.trim().toLocaleLowerCase();
    return rows.filter(row => {
        const open = isOpenTask(row);
        const stateMatch = !state || (state === OPEN_FILTER ? open : state === OTHER_FILTER ? !open : row.state === state);
        const queryMatch = !q || `${row.task_id}\n${row.title}\n${row.owner ?? ''}`.toLocaleLowerCase().includes(q);
        return stateMatch && queryMatch;
    });
}
