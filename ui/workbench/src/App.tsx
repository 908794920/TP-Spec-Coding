import { useState } from 'react';
import { api } from './api';
import { useRead } from './useRead';
import { ProjectPage } from './pages/ProjectPage';
import { GlobalConfigPage } from './pages/GlobalConfigPage';
import { TaskPage } from './pages/TaskPage';
import { TaskIndex } from './components/TaskIndex';
import { Fields, Problems } from './components/Facts';
type Page = 'project' | 'task' | 'global';
export default function App() {
    const [revision, refresh] = useState(0), [contextKey, selectContext] = useState(''), [selectedTask, selectTask] = useState('');
    const [page, setPage] = useState<Page>('project'), [navOpen, setNavOpen] = useState(false);
    const health = useRead('health', revision, api.health), global = useRead('global', revision, api.global);
    const contexts = global.data?.data.contexts ?? [];
    const context = contexts.find(c => c.context_key === contextKey);
    const project = useRead(contextKey, revision, signal => api.project(contextKey, signal));
    const task = useRead(page === 'task' && contextKey && selectedTask ? JSON.stringify([contextKey, selectedTask]) : '', revision, signal => api.task(contextKey, selectedTask, signal));
    const rows = project.data?.data.task_index ?? [];
    function switchPage(next: Page) { setPage(next); setNavOpen(false); }
    function openTask(id: string) { selectTask(id); switchPage('task'); }
    return <div className="app"><a className="skip-link" href="#main-content">跳到主内容</a>
    <header className="app-header"><button type="button" className="nav-toggle" aria-expanded={navOpen} aria-controls="workbench-navigation" onClick={() => setNavOpen(v => !v)}>{navOpen ? '收起导航' : '项目 / 导航'}</button>
      <div className="brand"><strong>TP-Spec</strong><span>本地工作台</span></div><span className="header-meta">只读 · {health.data?.version ?? '版本未读取'}</span>
      <button type="button" className="refresh-button" onClick={() => refresh(n => n + 1)}>重新读取</button>
    </header>
    {health.error && <p className="error app-alert" role="alert">{health.error}</p>}
    <div className={`shell ${navOpen ? 'navigation-open' : ''}`}>
      <aside className="navigation" id="workbench-navigation" aria-label="工作台导航">
        <h2>项目与工作区</h2><label htmlFor="context">真实上下文</label><select id="context" value={contextKey} onChange={e => { selectContext(e.target.value); selectTask(''); setPage('project'); }}><option value="">请选择项目</option>{contexts.map(c => <option key={c.context_key} value={c.context_key}>{c.name} · {c.workspace_root}</option>)}</select>
        {global.loading && <p className="muted" role="status">正在读取注册表…</p>}{global.error && <p className="error" role="alert">{global.error}</p>}
        {!global.loading && global.data && !contexts.length && <p className="muted">没有已注册项目。工作台不会自动初始化。</p>}
        {contextKey && !context && global.data && <p className="error" role="alert">原选中上下文已不在注册表，请重新选择。</p>}
        <nav className="primary-nav" aria-label="主页面">{([['project', '项目总览'], ['task', '任务工作区'], ['global', '全局配置']] as const).map(([key, label]) => <button type="button" key={key} onClick={() => switchPage(key)} className={page === key ? 'selected' : ''} aria-current={page === key ? 'page' : undefined}>{label}</button>)}</nav>
        {context && <div className="navigation-tasks"><h3>任务索引</h3>{project.error && <p className="error" role="alert">{project.error}</p>}<TaskIndex key={contextKey} rows={rows} selected={selectedTask} onSelect={openTask} compact/></div>}
        <Problems items={global.data?.data.problems}/>
        <details className="source-details"><summary>活动源码与来源</summary><Fields value={health.data ? { source_root: health.data.source_root, python_executable: health.data.python_executable, registry_path: health.data.registry_path, read_only: health.data.read_only } : {}}/></details>
      </aside>
      <main id="main-content" tabIndex={-1}>{page === 'global' ? <GlobalConfigPage read={global}/> : page === 'task' ? <TaskPage context={context} taskId={selectedTask} read={task} revision={revision}/> : <ProjectPage context={context} read={project} onSelectTask={openTask}/>}</main>
    </div>
  </div>;
}
