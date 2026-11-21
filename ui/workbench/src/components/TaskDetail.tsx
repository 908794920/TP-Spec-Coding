import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Tabs } from 'antd';
import type { GraphObject } from '../graph/model';
import type { CloseoutData, DetailData, Envelope, ReadState, TaskData } from '../types';
import { record, stateLabel, stageLabel, workflowNextResponsibility } from '../facts';
import { CopyText, Disclosure, Fields, Problems, ReadStatus } from './Facts';
import { VerificationDetail, Outcome } from './VerificationDetail';
import { EvidenceList } from './EvidenceList';
import { CloseoutPanel } from './CloseoutPanel';
import { CurrentBlockers, responsibilityLabel } from './ExecutionWorkflow';
import { QuickWorkflowSummary } from './QuickWorkflowSummary';
const tabs = [['overview', '概况'], ['blockers', '阻塞'], ['verification', '验证与验收'], ['evidence', '证据与交付']] as const;
export type TaskDetailTab = typeof tabs[number][0];
type Tab = TaskDetailTab;
interface Props {
  object: GraphObject;
  snapshot: Envelope<TaskData>;
  /** 详情入口打开或调用方再次请求时切换到指定页签。 */
  initialTab?: Tab;
  /** 仅需要稳定默认页签的调用方使用的回退入口。 */
  defaultTab?: Tab;
  details: ReadState<Envelope<DetailData>>;
  onDetails: () => void;
  onRefreshDetails: () => void;
  closeout: ReadState<Envelope<CloseoutData>>;
  closeoutRequested: boolean;
  onCloseout: () => void;
  onClose: () => void;
}
export function TaskDetail({ object, snapshot, initialTab, defaultTab, details, onDetails, onRefreshDetails, closeout, closeoutRequested, onCloseout, onClose }: Props) {
  const dialog = useRef<HTMLDialogElement>(null), close = useRef<HTMLButtonElement | HTMLAnchorElement>(null);
  const requestedTab = initialTab ?? defaultTab ?? 'overview';
  const [tab, setTab] = useState<Tab>(requestedTab);
  useEffect(() => {
    const element = dialog.current!;
    const present = () => {
      if (!element.open) element.showModal();
      close.current?.focus();
    };
    present();
    /* Ant Design's Tabs exposes no prop for naming the tablist, and the hand-rolled bar this
       replaced carried `aria-label="对象详情分类"`; set it so the group name survives. */
    element.querySelector('.detail-tabs [role="tablist"]')?.setAttribute('aria-label', '对象详情分类');
    return () => { if (element.open) element.close(); };
  }, []);
  useEffect(() => {
    setTab(requestedTab);
    if (requestedTab !== 'overview') onDetails();
    close.current?.focus();
  }, [object.id, requestedTab, onDetails]);
  function selectTab(next: Tab) { setTab(next); if (next !== 'overview') onDetails(); }
  const data = details.data?.data, task = record(snapshot.data.task), workflow = record(snapshot.data.workflow);
  const execution = record(workflow.execution);
  const terminal = task.state === 'COMPLETED' || task.state === 'CANCELLED' || workflow.retired === true || execution.terminal === true;
  const quick = workflow.workflow_mode === 'quick';
  const video = task.domain === 'video';
  const retired = workflow.retired === true;
  const mismatch = !!details.data && details.data.read.task_revision !== snapshot.read.task_revision;
  const preflight = <CloseoutPanel read={closeout} requested={closeoutRequested} onRequest={onCloseout}
    taskRevision={snapshot.read.task_revision} currentStep={record(execution.current_step)}/>;
  return <dialog className="task-detail task-detail-modal" ref={dialog} aria-labelledby="detail-heading" onCancel={e => { e.preventDefault(); onClose(); }} onKeyDown={e => { if (e.key === 'Escape') { e.preventDefault(); onClose(); } }}>
    <header className="detail-heading"><div><span className="eyebrow">{object.kind === 'task' ? 'Task' : 'WorkItem'} 详情</span><h3 id="detail-heading">{object.title || '标题未记录'}</h3></div><Button size="small" ref={close} onClick={onClose} aria-label="关闭详情并返回节点">关闭</Button></header>
    {/* Ant Design's Tabs owns the tablist/tab/tabpanel roles and the arrow/Home/End keys that the
        previous roving tabindex implemented; `destroyOnHidden` keeps exactly one pane mounted. */}
    <Tabs className="detail-tabs" activeKey={tab} onChange={key => selectTab(key as Tab)} destroyOnHidden
      items={tabs.map(([key, label]) => ({ key, label, children: key === tab ? <div className="detail-body nowheel nopan">
      {retired && <Alert type="info" showIcon title="已退休 · 历史只读"
        description={`最后正式工作流状态：${stateLabel('task', task.state)}。`}/>}
      {tab === 'overview' ? <>
        <CopyText value={object.objectId}/><p>{stateLabel(object.kind, object.status)}</p>
        {object.kind !== 'task' && <p>归属 Task：{object.parentTaskId || '未确认'}{!object.belongs && ' · 归属未核实'}</p>}
        {!!object.issues.length && <ul className="blocker-list">{object.issues.map((issue, index) => <li key={index}>{issue}</li>)}</ul>}
        {object.kind === 'task' && <>
          {quick && <QuickWorkflowSummary workflow={workflow} terminal={terminal}/>}
          <Fields value={{ current: terminal ? '任务已结束' : stageLabel(workflow.current_step) || '未记录',
            next: terminal ? '无后续执行' : stageLabel(workflow.next_step) || '未记录',
            ...(!terminal ? { next_responsibility: responsibilityLabel(workflowNextResponsibility(workflow, false)) } : {}),
            ...(terminal ? { completed_at: task.completed_at } : {}) }}
            labels={{ current: '当前步骤', next: '下一步', completed_at: '正式结束时间' }}/>
        </>}
        {video && <section className="detail-section"><h4>媒体导出与检查</h4>
          <Fields value={record(workflow.media)} labels={{ version: '导出版本', main: '主文件', status: '记录状态',
            event_id: '导出事件', recorded_at: '登记时间', hashes_rechecked: '本次重查文件哈希',
            qc: '当前导出的检查记录', delivery_status: '交付记录', issues: '当前待处理事项' }}/></section>}
        <Disclosure label="对象与任务来源">
          <Fields value={{ owner: object.owner, latest_checkpoint: snapshot.data.latest_checkpoint, summary: snapshot.data.summary,
            summary_source: snapshot.data.summary_source, work_sessions: snapshot.data.work_sessions, records: object.records }}
            labels={{ owner: '登记负责人', latest_checkpoint: '最近 checkpoint 记录', summary: 'Task 摘要', work_sessions: '已记录工作段', records: '所选对象原始记录' }}/>
        </Disclosure>
      </> : <>
        {object.kind !== 'task' && <p className="detail-scope">所属 Task：<strong>{String(task.task_id ?? '')}</strong></p>}
        {tab === 'blockers' && <CurrentBlockers workflow={workflow} task={task} blockers={snapshot.data.blockers}/>}
        <Button onClick={onRefreshDetails} disabled={details.loading}>重新读取详情</Button>
        <ReadStatus {...details} showDetails={false}/>
        {mismatch && <p className="warning" role="status">详情与当前任务的读取版本不同。请关闭详情，重新读取任务。</p>}
        {data && <Problems items={data.problems}/>}
        {data && tab === 'verification' && record(data.acceptance).visual_evidence_pending === true &&
          <Alert type="info" showIcon title="页面视觉验收待完成" description="证据清单尚未登记。"/>}
        {tab === 'blockers' && <>
          {preflight}
          {data && <Disclosure label="阻塞来源与专业记录"><Fields value={{ ...data.blockers,
            verification: record(record(data.verification).recorded).detail, review: record(record(data.review).recorded).detail,
            delivery: record(record(data.delivery).recorded).detail }}/></Disclosure>}
        </>}
        {tab === 'verification' && data && <VerificationDetail data={data}/>}
        {tab === 'evidence' && data && <>
          <EvidenceList value={data.evidence}/><Outcome title={video ? '媒体交付记录' : '交付记录'} value={data.delivery}/>
          <p>用户接收：未记录</p>
          {preflight}
        </>}
      </>}
    </div> : null, }))}/>
  </dialog>;
}
