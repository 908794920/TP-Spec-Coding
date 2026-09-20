import { Card, Collapse } from 'antd';
import { Fields, Empty, Problems, ReadStatus } from '../components/Facts';
import { TaskIndex } from '../components/TaskIndex';
import type { Context, Envelope, ProjectData, ReadState } from '../types';
export function ProjectPage({ context, read, onSelectTask }: {
    context?: Context;
    read: ReadState<Envelope<ProjectData>>;
    onSelectTask: (id: string) => void;
}) {
    if (!context)
        return <div className="page project-page"><div className="page-heading"><div><span className="eyebrow">项目总览</span><h2>尚未选择项目</h2></div></div>
        <Empty title="先选择项目与工作区">从左侧项目列表展开一个项目，或点它的「项目总览」。只展示已注册的真实上下文；工作台不会创建项目、任务或 Runtime。</Empty></div>;
    const data = read.data?.data;
    return <div className="page project-page"><div className="page-heading"><div><span className="eyebrow">项目总览</span><h2>{context.name}</h2><p className="path">{context.workspace_root}</p></div></div>
    <ReadStatus {...read}/>{data && <><Problems items={data.problems}/>
      {/* The registry is the machine-level file this project was resolved from, so it sits next to
          「身份来源」 instead of in a collapsed section at the foot of the page: three rows, and merging
          removes the last click needed to see them. The label is overridden because the bare field name
          would read 「注册表」 here, where the point is where the identity came from. */}
      <Card size="small" title="项目身份与 Binding"><Fields value={{ ...data.project, registry: data.registry }} labels={{ project_id: '项目 ID', name: '项目名称', root_path: '工作区根', base_version: '项目基座版本', contract_version: '活动契约版本', identity_source: '身份来源', binding: '项目 Binding', runtime_status: 'Runtime 状态', runtime_db: '实际数据库', registry: '注册表来源' }}/></Card>
      <Card size="small" title="任务索引"><p>{String(data.summary ?? '')}</p><Collapse className="compact-details" size="small" items={[{ key: 'statistics', label: '已记录状态统计', children: <Fields value={data.task_statistics}/> }]}/><TaskIndex key={context.context_key} rows={data.task_index ?? []} onSelect={onSelectTask}/></Card>
      {/* Two separate cards, stacked rather than side by side: each source keeps its own head and
          border — so 「Wiki 读不到」 no longer looks like part of the Knowledge block — and the nested
          tables in Knowledge get the page's full width instead of half of it. They are direct children
          of `.project-page`, which already spaces sibling cards (`> .ant-card { margin-bottom: 12px }`),
          and each card now ends at its own content height instead of being stretched to match. */}
      <Card size="small" title="Wiki"><Fields value={data.wiki}/></Card>
      <Card size="small" title="Knowledge"><Fields value={data.knowledge}/></Card>
    </>}</div>;
}
