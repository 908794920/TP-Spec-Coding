import { Fields, Empty, Problems, ReadStatus } from '../components/Facts';
import { TaskIndex } from '../components/TaskIndex';
import type { Context, Envelope, ProjectData, ReadState } from '../types';
export function ProjectPage({ context, read, onSelectTask }: {
    context?: Context;
    read: ReadState<Envelope<ProjectData>>;
    onSelectTask: (id: string) => void;
}) {
    if (!context)
        return <Empty title="先选择项目与工作区">只展示已注册的真实上下文；工作台不会创建项目、任务或 Runtime。</Empty>;
    const data = read.data?.data;
    return <div className="page project-page"><div className="page-heading"><div><span className="eyebrow">项目总览</span><h2>{context.name}</h2><p className="path">{context.workspace_root}</p></div></div>
    <ReadStatus {...read}/>{data && <><Problems items={data.problems}/>
      <section className="section"><h3>项目身份与 Binding</h3><Fields value={data.project} labels={{ project_id: '项目 ID', name: '项目名称', root_path: '工作区根', base_version: '项目基座版本', contract_version: '活动契约版本', identity_source: '身份来源', binding: '项目 Binding', runtime_status: 'Runtime 状态', runtime_db: '实际数据库' }}/></section>
      <section className="section"><h3>任务索引</h3><p>{String(data.summary ?? '')}</p><details className="compact-details"><summary>已记录状态统计</summary><Fields value={data.task_statistics}/></details><TaskIndex key={context.context_key} rows={data.task_index ?? []} onSelect={onSelectTask}/></section>
      <section className="section"><h3>Wiki / Knowledge</h3><div className="two-columns"><div><h4>Wiki</h4><Fields value={data.wiki}/></div><div><h4>Knowledge</h4><Fields value={data.knowledge}/></div></div></section>
      <details className="section"><summary>注册表来源</summary><Fields value={data.registry}/></details>
    </>}</div>;
}
