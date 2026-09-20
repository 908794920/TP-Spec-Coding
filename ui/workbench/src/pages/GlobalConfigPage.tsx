import { Card, Tabs } from 'antd';
import { record } from '../facts';
import { Fields, Problems, ReadStatus } from '../components/Facts';
import { SkillTopology } from '../components/SkillTopology';
import type { Envelope, GlobalData, Health, ReadState } from '../types';
const groups = [['base', '安装与基座'], ['wiki', 'Wiki'], ['knowledge', 'Knowledge'], ['autonomy', '自主配置'], ['skill_topology', '能力定义与来源']] as const;
/* Labels for the keys that would be ambiguous once merged into one table (`path`, `status`) or are
   absent from the field-name vocabulary entirely (`python_executable`). */
const carriedLabels = { path: '注册表路径', status: '解析器状态', user_root: '用户根目录', python_executable: '本机 Python 解释器' };
export function GlobalConfigPage({ read, health }: {
    read: ReadState<Envelope<GlobalData>>;
    health: ReadState<Health>;
}) {
    const data = read.data?.data;
    /* Groups that lost their own tab, each for a reason that is checkable:
       - 工作区清单: its records ARE the project list the sidebar already shows, so `workspaces` and
         its `count` go; the inventory's own facts stay.
       - Resolver: `base_root` repeats the install group's 根目录 verbatim, so only its status stays.
       - 注册表 / 已注册项目: `project_count` is the sidebar's 项目 count and the records are that same
         list; `exists` / `status` / `error` are implied by the registry working at all — a broken one
         is reported in the page's problems — while the registry's own `path` is worth keeping.
       Destructuring rather than fixed field lists keeps anything the API adds later visible. */
    const { workspaces: _records, count: _count, configured: _configured, ...workspaceFacts } = record(data?.workspace);
    const { base_root: _baseRoot, ...resolverFacts } = record(data?.resolver);
    const registryFacts = { path: record(data?.registry).path };
    /* The merged table is ordered by what each fact answers. Merging four payloads has no order of
       its own — that is what put 基座版本 and 版本是否匹配 on opposite sides of three unrelated rows,
       so the version mismatch read as two unrelated values. The order below runs: which install this
       is and where it came from → where the base sits and whether that location is usable → which
       versions it holds and whether they agree → the inventory that declares the default workspace →
       the resolver and registry it reads through → the runtime reading it → the one failure string.
       `_declared` companions stay adjacent automatically: they are ranked by their own key, not here. */
    const baseOrder = ['configured', 'source',
        'root', 'exists', 'valid',
        'contract_version', 'base_version', 'version_match', 'configuration_error',
        'inventory_path', 'default_workspace', 'default_workspace_status',
        'status', 'path', 'user_root', 'python_executable', 'error'];
    const rank = (key: string) => {
        const index = baseOrder.indexOf(key);
        /* Unknown keys sort last but keep their payload order (`sort` is stable). A fact the API adds
           later therefore still shows up at the end instead of vanishing behind a fixed field list. */
        return index < 0 ? baseOrder.length : index;
    };
    /* One object, so the install facts, every carried-over fact and the two read-identity facts
       render as a single table. */
    const baseFacts = Object.fromEntries(Object.entries({ ...record(data?.base), ...workspaceFacts, ...resolverFacts, ...registryFacts,
        user_root: data?.user_root, python_executable: health.data?.python_executable }).sort(([a], [b]) => rank(a) - rank(b)));
    return <div className="page config-page"><div className="page-heading"><div><span className="eyebrow">全局配置</span><h2>配置值与来源</h2><p>只读查看。未声明不等于开启；这里不修改安装、项目或执行策略。</p></div></div><ReadStatus {...read}/>
    {data && <><Problems items={data.problems}/>
      {/* One group at a time, picked from a tab bar at the top: the groups used to be stacked as
          sections under a side anchor list, so a visit rendered the whole configuration to answer one
          question. Panels carry no card title — the selected tab has just named the group. */}
      <Tabs className="config-tabs" defaultActiveKey={groups[0][0]} items={groups.map(([key, label]) => ({ key, label,
          children: <Card size="small">{key === 'skill_topology'
              ? <SkillTopology value={data.skill_topology}/>
              : <Fields value={key === 'base' ? baseFacts : data[key]} labels={key === 'base' ? carriedLabels : undefined}/>}</Card> }))}/>
    </>}
  </div>;
}
