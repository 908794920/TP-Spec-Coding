import { Alert, Tag } from 'antd';
import { record, records, text } from '../facts';
import { CopyText, Disclosure, Fields } from './Facts';

const states: Record<string, string> = { PENDING: '待认领', ACTIVE: '已认领', COMPLETED: '结果已提交' };
const actions: Record<string, string> = { create: '登记范围', claim: '认领', release: '失败 / 释放',
  retry: '同一问题重试', result: '提交结果', receive: '协调者接收' };

/** Existing ledger facts only: no agent liveness, automatic merging or approval controls. */
export function WorkResults({ value }: { value: unknown }) {
  const facts = record(value), items = records(facts.items), integration = record(facts.integration);
  const candidate = record(integration.candidate);
  return <section className="detail-section work-results" aria-label="子工作与集成候选">
    <h3>子工作与集成候选</h3>
    <p className="muted">结果提交、协调者接收、集成候选与 Task 验收是不同事实。登记的角色 / 工作区不证明进程在线或宿主强隔离。</p>
    {Array.isArray(facts.issues) && facts.issues.length > 0 && <Alert type="warning" showIcon title="子工作记录待核对" description={facts.issues.map(text).join('；')}/>}
    {!items.length ? <p role="status">未登记子工作；不从 Wxx 名称或旧事件猜测 Fix 与父 Task 关系。</p> :
      items.map(item => {
        const unit = record(item.work_unit), spec = record(unit.spec), result = record(unit.result), receipt = record(unit.receipt);
        const output = record(result.result), wid = text(item.item_id);
        return <details className="record-block" id={`work-unit-${wid}`} key={wid}>
          <summary><Tag>{spec.kind === 'FIX' ? 'Fix' : 'Work'}</Tag><strong>{wid}</strong> · {text(item.title)} · {item.current === false ? '历史：' : ''}{states[text(item.status)] || text(item.status)}{receipt.event_id ? ' · 已接收' : unit.spec && item.status === 'COMPLETED' ? ' · 待接收' : ''}</summary>
          <CopyText value={wid} label="复制 Work ID"/>
          {!unit.spec ? <p>历史 WorkItem 未记录范围结果契约；不补造隔离、结果或验收证据。</p> : <>
            <Fields value={{ scope: spec.scope, scope_refs: spec.scope_refs, issue: spec.issue_key,
              original_step: spec.step_id, waiting_step: unit.waiting_step_id, attempt: unit.attempt,
              actor: item.owner_role, executor: item.owner_agent, roles: spec.roles,
              dependencies: item.depends_on, unresolved_dependencies: item.unresolved_dependencies,
              paths: spec.paths, ac_refs: spec.ac_refs, shared_paths: spec.shared_paths,
              repo_root: spec.repo_root, target_root: spec.target_root, isolation: spec.isolation }}
              labels={{ scope_refs: '已登记范围依据（不是授权）', issue: '同一问题标识', original_step: '初始父步骤',
                waiting_step: '当前接续步骤', attempt: '已登记尝试次数', executor: '执行者标识', roles: '计划参与角色',
                dependencies: 'Work 依赖', paths: '允许路径', shared_paths: '共享路径所有者',
                repo_root: '结果工作区', target_root: 'Task 集成位置', isolation: '隔离声明（不证明宿主强制）' }}/>
            <h4>结果与回收</h4>
            {result.event_id ? <Fields value={{ result_event: result.event_id, summary: output.summary,
              changed_paths: output.changed_paths, output_digest: output.output_digest, artifact: output.artifact,
              evidence: output.evidence_items, limitations: output.limitations,
              receipt_event: receipt.event_id, received_by: receipt.actor, received_at: receipt.created_at }}
              labels={{ result_event: '精确结果事件', output_digest: '声明输出内容摘要', artifact: '实际结果载体',
                evidence: '登记时证据绑定（不代替当前适用性检查）', receipt_event: '接收事件', received_by: '协调角色', received_at: '接收时间' }}/>
              : <p>本次尝试尚无结果，旧尝试保留在下方历史。</p>}
            <Disclosure label={`尝试、失败恢复与接收历史 · ${records(unit.history).length} 条`}>
              {records(unit.history).map(row => <div className="record-block" key={text(row.event_id)}>
                <h4>{actions[text(row.action)] || text(row.action)} · #{text(row.event_id)}</h4>
                <Fields value={{ created_at: row.created_at, actor: row.actor, actor_agent: row.agent,
                  summary: row.summary, recovery_condition: row.recovery_condition, attempt: row.attempt,
                  step_id: row.step_id, result_event_id: row.result_event_id }}/>
              </div>)}
            </Disclosure>
          </>}
        </details>;
      })}
    <h4>Task 集成候选</h4>
    {candidate.event_id ? <>
      <p role="status">已登记候选 #{text(candidate.event_id)}；不是当前验证 PASS。当前源码 / AC / 证据适用性由正式只读结单预检核对。</p>
      <CopyText value={candidate.change_set_id} label="复制候选摘要"/>
      <Disclosure label="集成输入、冲突处置与实际来源">
        <Fields value={{ created_at: candidate.created_at, summary: candidate.summary, receipts: candidate.receipts,
          repo_roots: candidate.repo_roots, change_set: candidate.change_set, integrated_outputs: candidate.integrated_outputs,
          resolutions: candidate.resolutions, evidence: candidate.evidence_items,
          outstanding_at_recording: candidate.outstanding_work_items, effect_scope: candidate.effect_scope }}/>
      </Disclosure>
    </> : <p role="status">{integration.status === 'NOT_REQUIRED' ? '没有采用结果契约的 Work；不追加旧任务义务。' : '尚未登记 Task 集成候选，不能将各 Work 结果相加当成整任务通过。'}</p>}
    <p className="muted">工作台只读，不在此执行认领、批准、合并或结单。</p>
  </section>;
}
