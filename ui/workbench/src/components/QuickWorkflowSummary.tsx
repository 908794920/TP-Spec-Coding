import { Alert, Button } from 'antd';
import { record, text } from '../facts';
import type { FactRecord } from '../types';
import { Disclosure, Fields } from './Facts';
import { strings } from './executionView';

const verificationNames: Record<string, string> = {
    PASS: '通过', FAIL: '失败', NEEDS_FIX: '需要修复', NOT_RECORDED: '尚未记录',
    PASS_STALE: '历史通过，当前已过期', INVALID: '记录无效，当前适用性未确认',
};
export function QuickWorkflowSummary({ workflow, terminal = false, onDocuments }: {
    workflow: FactRecord; terminal?: boolean; onDocuments?: () => void;
}) {
    const status = record(workflow.quick_status), checks = strings(status.checks), unverified = strings(status.unverified_items);
    const deliveryCurrent = status.delivery_status === 'READY' && status.delivery_current === true;
    const title = terminal ? '快速任务的历史结果'
        : deliveryCurrent && status.awaiting_completion === true ? '已交付，待用户结单'
        : deliveryCurrent ? '已记录交付'
        : status.delivery_status === 'READY_STALE' ? '历史交付已过期，当前适用性未确认'
        : status.delivery_status === 'BLOCKED' ? '交付受阻'
        : status.delivery_status === 'NOT_RECORDED' ? '尚未记录交付' : '交付适用性尚未确认';
    return <div className="quick-workflow-summary">
      <div className="task-assessment"><div><span className="eyebrow">处理模式</span><strong className="assessment-level">快速开发</strong></div></div>
      <Alert type={status.delivery_status === 'BLOCKED' && !terminal ? 'warning' : 'info'} showIcon title={title}/>
      <Fields value={{ verification_result: status.verification_decision === 'PASS' && status.verification_current !== true
          ? '历史通过，当前适用性未确认' : verificationNames[text(status.verification_decision)] || '尚未取得当前判定',
        verification_scope: status.verification_scope === 'technical' ? '技术范围' : status.verification_scope === 'full' ? '完整范围' : '尚未记录',
        verification_current: status.verification_current, recorded_delivery_status: status.recorded_delivery_status,
        delivery_current: status.delivery_current,
        verification_event_id: status.verification_event_id, delivery_event_id: status.delivery_event_id }}
        labels={{ verification_result: terminal ? '历史验证结果' : '当前验证结果', verification_scope: '实际验证范围',
          verification_current: '本次验证绑定适用', recorded_delivery_status: '原记录交付状态', delivery_current: '本次交付绑定适用',
          verification_event_id: '验证事件', delivery_event_id: '交付事件' }}/>
      {!!checks.length && <><h4>实际检查</h4><ul>{checks.map((check, index) => <li key={index}>{check}</li>)}</ul></>}
      {!!unverified.length && <><h4>真实未验证项</h4><ul>{unverified.map((item, index) => <li key={index}>{item}</li>)}</ul></>}
      {onDocuments && <Button size="small" type="link" onClick={onDocuments}>查看当前任务文档</Button>}
      <Disclosure label="模式选择与结果来源"><Fields value={{ mode_source: workflow.mode_source,
        applicable_obligations: workflow.applicable_obligations, quick_status: workflow.quick_status }}/></Disclosure>
    </div>;
}
