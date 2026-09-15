import { Fields, Problems, ReadStatus } from '../components/Facts';
import type { Envelope, GlobalData, ReadState } from '../types';
const groups = [['base', '安装与基座'], ['wiki', 'Wiki'], ['knowledge', 'Knowledge'], ['workspace', '工作区清单'], ['resolver', 'Resolver'], ['registry', '注册表'], ['autonomy', '自主配置'], ['skill_topology', '能力定义与来源']] as const;
export function GlobalConfigPage({ read }: {
    read: ReadState<Envelope<GlobalData>>;
}) {
    const data = read.data?.data;
    return <div className="page config-page"><div className="page-heading"><div><span className="eyebrow">全局配置</span><h2>配置值与来源</h2><p>只读查看。未声明不等于开启；这里不修改安装、项目或执行策略。</p></div></div><ReadStatus {...read}/>
    {data && <><Problems items={data.problems}/><section className="section"><h3>当前读取身份</h3><Fields value={{ version: data.version, user_root: data.user_root, active_source_root: data.active_source_root }} labels={{ version: '产品版本', user_root: '用户根目录', active_source_root: '本次执行源码' }}/></section>
      <nav className="section-links" aria-label="配置分组">{groups.map(([key, label]) => <a key={key} href={`#config-${key}`}>{label}</a>)}</nav>
      {groups.map(([key, label]) => <section id={`config-${key}`} className="section" key={key}><h3>{label}</h3><Fields value={data[key]}/></section>)}
      <section className="section"><h3>已注册项目</h3><Fields value={{ registered_projects: data.registered_projects }} labels={{ registered_projects: '项目记录（不是自动发现结果）' }}/></section></>}
  </div>;
}
