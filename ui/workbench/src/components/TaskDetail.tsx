import { useEffect, useRef, useState } from 'react';
import { Button, Tabs } from 'antd';
import type { GraphObject } from '../graph/model';
import type { CloseoutData, DetailData, Envelope, ReadState, TaskData } from '../types';
import { record, stateLabel, stageLabel } from '../facts';
import { CopyText, Disclosure, Fields, Problems, ReadStatus } from './Facts';
import { VerificationDetail, Outcome } from './VerificationDetail';
import { EvidenceList } from './EvidenceList';
import { CloseoutPanel } from './CloseoutPanel';
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
  const terminal = task.state === 'COMPLETED' || task.state === 'CANCELLED' || workflow.retired === true;
  const mismatch = !!details.data && details.data.read.task_revision !== snapshot.read.task_revision;
  return <dialog className="task-detail task-detail-modal" ref={dialog} aria-labelledby="detail-heading" onCancel={e => { e.preventDefault(); onClose(); }} onKeyDown={e => { if (e.key === 'Escape') { e.preventDefault(); onClose(); } }}>
    <header className="detail-heading"><div><span className="eyebrow">{object.kind === 'task' ? 'Task' : 'WorkItem'} 详情</span><h3 id="detail-heading">{object.title || '标题未记录'}</h3></div><Button size="small" ref={close} onClick={onClose} aria-label="关闭详情并返回节点">关闭</Button></header>
    {/* Ant Design's Tabs owns the tablist/tab/tabpanel roles and the arrow/Home/End keys that the
        previous roving tabindex implemented; `destroyOnHidden` keeps exactly one pane mounted. */}
    <Tabs className="detail-tabs" activeKey={tab} onChange={key => selectTab(key as Tab)} destroyOnHidden
      items={tabs.map(([key, label]) => ({ key, label, children: key === tab ? <div className="detail-body nowheel nopan">
      <CopyText value={object.objectId}/><p>{stateLabel(object.kind, object.status)}</p>
      {tab === 'overview' ? <>
        <Fields value={{ object_type: object.kind, owner: object.owner, parent_task: object.parentTaskId,
          relationship: object.kind === 'task' ? '当前 Task' : object.belongs ? '由正式 task_id 确认' : '归属未确认', issues: object.issues }}
          labels={{ object_type: '对象类型', owner: object.kind === 'task' && terminal ? 'Task 责任记录（历史，不是当前执行者）' : '对象负责人', parent_task: '父 Task', relationship: '归属依据', issues: '数据问题' }}/>
        <section className="detail-section"><h4>当前 Task 的实际流程</h4>
          <Fields value={{ task_state: stateLabel('task', task.state), current: terminal ? '无（任务已结束）' : stageLabel(workflow.current_step) || '当前步骤未解析', next: terminal ? '无（任务已结束）' : stageLabel(workflow.next_step) || '下一步未解析',
            current_source: workflow.current_step_source, next_source: workflow.next_step_source, effective_level: workflow.effective_level,
            coordinator: record(workflow.execution).coordinator,
            completed_at: task.completed_at, read_at: snapshot.read.completed_at }} labels={{ task_state: 'Task 正式状态', current: '当前步骤', next: '下一步', current_source: '当前步骤来源', next_source: '下一步来源', effective_level: '有效流程等级', coordinator: 'Task 协调责任（独立于本步角色）', completed_at: '正式结束时间', read_at: '读取时间' }}/>
          <Disclosure label="路由与来源字段"><Fields value={{ current: workflow.current_step, next: workflow.next_step, route: workflow.route }}/></Disclosure>
        </section>
        <Disclosure label="Task 最近记录与工作段（只读）">
          <p className="muted">以下属于父 Task {String(task.task_id ?? '')}，不是所选 WorkItem 的独立结论；摘要不决定 PASS，工作段不证明执行者在线。</p>
          <Fields value={{ latest_checkpoint: snapshot.data.latest_checkpoint, summary: snapshot.data.summary,
            summary_source: snapshot.data.summary_source, work_sessions: snapshot.data.work_sessions }}
            labels={{ latest_checkpoint: '最近 checkpoint 记录', summary: 'Task 摘要', summary_source: '摘要来源', work_sessions: '已记录工作段' }}/>
        </Disclosure>
        <Disclosure label={<>本次对象原始字段{object.records.length > 1 ? ` · ${object.records.length} 条歧义记录` : ''}</>}>{object.records.map((row, i) => <div className="record-block" key={i}><Fields value={row}/></div>)}</Disclosure>
        <p className="muted">WorkItem 完成不代表 Task 已结单；没有可信执行器观察时，负责人也不代表正在运行。</p>
      </> : <>
        <p className="detail-scope">以下是 <strong>Task {String(task.task_id ?? '')}</strong> 的读取结果{object.kind === 'work_item' ? '，不是所选 WorkItem 的独立验收或交付结论' : ''}。</p>
        <Button onClick={onRefreshDetails} disabled={details.loading}>重新读取详情</Button>
        <ReadStatus {...details}/>
        {mismatch && <p className="warning" role="status">详情与画布的账本版本不同，不能合并为同一次快照。请重新读取页面，以下保留各自读取时间。</p>}
        {data && <Problems items={data.problems}/>}
        {tab === 'blockers' && <>
          {data && <><Fields value={data.blockers} labels={{ waiting: '当前结构化等待', legacy_blocker: '历史自由文本阻塞', source: '来源', note: '解释边界' }}/>
            <Disclosure label="Verification / Review / Delivery 的原始阻塞字段"><Fields value={{ verification: record(record(data.verification).recorded).detail, review: record(record(data.review).recorded).detail, delivery: record(record(data.delivery).recorded).detail }}/></Disclosure></>}
          <CloseoutPanel read={closeout} requested={closeoutRequested} onRequest={onCloseout} taskRevision={snapshot.read.task_revision}/>
        </>}
        {tab === 'verification' && data && <VerificationDetail data={data}/>}
        {tab === 'evidence' && data && <>
          <EvidenceList value={data.evidence}/><Outcome title="Delivery（不等于正式结单或已上线）" value={data.delivery}/>
          {/* `stateLabel` needs the object kind, which `Fields` cannot know, so the kind is applied here. */}
          <Fields value={{ ...record(data.task), state: stateLabel('task', record(data.task).state) }} labels={{ task_id: '正式 Task', state: '正式状态', phase: '阶段', owner: terminal ? 'Task 责任记录（历史）' : 'Task 负责人', completed_at: '正式结束时间' }}/>
          <p className="muted">未取得单独的“用户接收交付”事实时保持未记录，不从 Owner accept、Delivery READY 或 WorkItem 完成推断。</p>
          <CloseoutPanel read={closeout} requested={closeoutRequested} onRequest={onCloseout} taskRevision={snapshot.read.task_revision}/>
        </>}
      </>}
    </div> : null, }))}/>
  </dialog>;
}
