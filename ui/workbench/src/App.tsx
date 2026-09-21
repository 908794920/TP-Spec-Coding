import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { CSSProperties, KeyboardEvent, PointerEvent } from 'react';
import { Alert, Button, Space, Tag, Typography } from 'antd';
import { MenuFoldOutlined, MenuUnfoldOutlined, ReloadOutlined } from '@ant-design/icons';
import { api } from './api';
import { useRead } from './useRead';
import { ProjectPage } from './pages/ProjectPage';
import { GlobalConfigPage } from './pages/GlobalConfigPage';
import { TaskPage } from './pages/TaskPage';
import { SidebarProjects } from './components/SidebarProjects';
import { TaskSearch } from './components/TaskSearch';
import { ThemeControl } from './components/ThemeControl';
type Page = 'project' | 'task' | 'global';
/* Sidebar width and collapse are presentation preferences, so they live in local storage — never in
   Runtime facts. Both are clamped on read: a stored value must not be able to break the layout. */
const NAV_KEY = 'tp-spec.workbench.nav', NAV_DEFAULT = 260, NAV_MIN = 180, NAV_MAX = 420;
type NavPrefs = { width: number; collapsed: boolean };
const clampNav = (width: number) => Math.min(NAV_MAX, Math.max(NAV_MIN, Math.round(width)));
function readNavPrefs(): NavPrefs {
    const narrow = typeof window !== 'undefined' && window.innerWidth <= 800;
    try {
        const stored = JSON.parse(window.localStorage.getItem(NAV_KEY) || '{}') as Partial<NavPrefs>;
        return { width: typeof stored.width === 'number' && Number.isFinite(stored.width) ? clampNav(stored.width) : NAV_DEFAULT,
            collapsed: narrow || (typeof stored.collapsed === 'boolean' ? stored.collapsed : false) };
    }
    catch {
        // Absent or unreadable storage is not an error; the defaults are the behaviour without it.
        return { width: NAV_DEFAULT, collapsed: narrow };
    }
}
export default function App() {
    const [revision, refresh] = useState(0), [contextKey, selectContext] = useState(''), [selectedTask, selectTask] = useState('');
    /* Opens on 全局配置: it is the only page that needs no selected project, so the read-only
       values are visible immediately instead of an empty "pick a project" state. */
    const [page, setPage] = useState<Page>('global'), [nav, setNav] = useState<NavPrefs>(readNavPrefs);
    const drag = useRef<{ x: number; width: number } | null>(null);
    const [resizing, setResizing] = useState(false);
    const [narrow, setNarrow] = useState(() => matchMedia('(max-width: 800px)').matches);
    const navigation = useRef<HTMLDialogElement>(null);
    const navButton = useRef<HTMLButtonElement | HTMLAnchorElement>(null);
    useEffect(() => {
        const query = matchMedia('(max-width: 800px)');
        const update = () => { setNarrow(query.matches); if (query.matches) setNav(prev => ({ ...prev, collapsed: true })); };
        query.addEventListener('change', update);
        return () => query.removeEventListener('change', update);
    }, []);
    useLayoutEffect(() => {
        const element = navigation.current;
        if (!element) return;
        const containedFocus = element.contains(document.activeElement);
        if (narrow) {
            if (element.open && !element.matches(':modal')) element.close();
            if (nav.collapsed && element.open) element.close();
            if (!nav.collapsed && !element.open) element.showModal();
        } else {
            if (element.matches(':modal')) element.close();
            // 桌面导航只是常驻区域，设置 open 避免 show() 在首次进入时抢焦点。
            if (!element.open) element.open = true;
        }
        if (nav.collapsed && containedFocus) navButton.current?.focus();
    }, [narrow, nav.collapsed]);
    function closeNavigation() {
        setNav(prev => ({ ...prev, collapsed: true }));
        requestAnimationFrame(() => navButton.current?.focus());
    }
    useEffect(() => {
        try {
            window.localStorage.setItem(NAV_KEY, JSON.stringify(nav));
        }
        catch { /* storage may be unavailable (private mode); the layout still works without it */ }
    }, [nav]);
    const health = useRead('health', revision, api.health), global = useRead('global', revision, api.global);
    const contexts = global.data?.data.contexts ?? [];
    const context = contexts.find(c => c.context_key === contextKey);
    const project = useRead(contextKey, revision, signal => api.project(contextKey, signal));
    const task = useRead(page === 'task' && contextKey && selectedTask ? JSON.stringify([contextKey, selectedTask]) : '', revision, signal => api.task(contextKey, selectedTask, signal));
    // 窄屏选中目标后关闭覆盖式导航，并将焦点交给目标页面。
    function switchPage(next: Page) { setPage(next); if (narrow) { setNav(prev => ({ ...prev, collapsed: true })); requestAnimationFrame(() => document.getElementById('main-content')?.focus()); } }
    function resizeBy(delta: number) { setNav(prev => ({ ...prev, width: clampNav(prev.width + delta) })); }
    function startResize(event: PointerEvent<HTMLDivElement>) {
        event.currentTarget.setPointerCapture(event.pointerId);
        drag.current = { x: event.clientX, width: nav.width };
        setResizing(true);
    }
    function dragResize(event: PointerEvent<HTMLDivElement>) {
        if (!drag.current)
            return;
        setNav(prev => ({ ...prev, width: clampNav(drag.current!.width + event.clientX - drag.current!.x) }));
    }
    function stopResize(event: PointerEvent<HTMLDivElement>) {
        if (!drag.current)
            return;
        drag.current = null;
        setResizing(false);
        if (event.currentTarget.hasPointerCapture(event.pointerId))
            event.currentTarget.releasePointerCapture(event.pointerId);
    }
    /* A resize handle has to be reachable without a pointer: arrows move it, Shift widens the step. */
    function keyResize(event: KeyboardEvent<HTMLDivElement>) {
        const step = event.shiftKey ? 32 : 8;
        const delta = event.key === 'ArrowLeft' ? -step : event.key === 'ArrowRight' ? step : 0;
        if (!delta)
            return;
        event.preventDefault();
        resizeBy(delta);
    }
    function openTask(id: string) { selectTask(id); switchPage('task'); }
    /* The sidebar can open a task from any project, so the context travels with the click; the
       project page only ever opens tasks of the project it is already showing. */
    function openTaskInProject(key: string, id: string) { selectContext(key); selectTask(id); switchPage('task'); }
    return <div className="app"><a className="skip-link" href="#main-content">跳到主内容</a>
    {/* An icon-only control: the fold/unfold pair reads as "导航" without spending header width on a
        label, so the accessible name comes from `aria-label` plus the native tooltip. */}
    <header className="app-header">{/* The fold control and the task search read as one pair of chrome actions, so they
        share a tighter gap than the header's own. */}
      <span className="header-actions"><Button ref={navButton} type="text" className="nav-toggle" icon={nav.collapsed ? <MenuUnfoldOutlined/> : <MenuFoldOutlined/>} aria-expanded={!nav.collapsed} aria-controls="workbench-navigation" aria-label={nav.collapsed ? '显示导航' : '隐藏导航'} title={nav.collapsed ? '显示导航' : '隐藏导航'} onClick={() => setNav(prev => ({ ...prev, collapsed: !prev.collapsed }))}/>
        {/* `openTaskInProject` carries the context with the click, which is what a search hit needs:
            the hit may live in another project than the one currently selected. */}
        <TaskSearch contexts={contexts} revision={revision} onOpenTask={openTaskInProject}/></span>
      <div className="brand"><Typography.Text strong>TP-Spec</Typography.Text><Typography.Text type="secondary">本地工作台</Typography.Text></div>
      <Space className="header-right" size={8}><Space className="header-meta" size={8}><Tag variant="filled">只读</Tag><Typography.Text type="secondary">{health.data?.version ?? '版本未读取'}</Typography.Text></Space><ThemeControl/><Button type="text" className="refresh-button" icon={<ReloadOutlined/>} onClick={() => refresh(n => n + 1)}>重新读取</Button></Space>
    </header>
    {health.error && <Alert className="app-alert" banner role="alert" type="error" showIcon title={health.error}/>}
    <div className={`shell${nav.collapsed ? ' nav-collapsed' : ''}${resizing ? ' is-resizing' : ''}`} style={{ '--nav-w': `${nav.width}px` } as CSSProperties}>
      <dialog ref={navigation} className="navigation" id="workbench-navigation" role={narrow ? 'dialog' : 'complementary'} aria-label="工作台导航" inert={!narrow && nav.collapsed}
        onCancel={event => { event.preventDefault(); closeNavigation(); }} onClick={event => {
            const rect = event.currentTarget.getBoundingClientRect();
            if (narrow && event.target === event.currentTarget && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom)) closeNavigation();
        }}>
        {narrow && <div className="mobile-nav-heading"><strong>项目导航</strong><Button type="text" onClick={closeNavigation}>关闭导航</Button></div>}
        {global.loading && <Typography.Text type="secondary" role="status">正在读取注册表…</Typography.Text>}
        {global.error && <Alert role="alert" type="error" showIcon title={global.error}/>}
        {!global.loading && global.data && !contexts.length && <Typography.Text type="secondary">没有已注册项目。工作台不会自动初始化。</Typography.Text>}
        {contextKey && !context && global.data && <Alert role="alert" type="error" showIcon title="原选中上下文已不在注册表，请重新选择。"/>}
        {/* The project tree and its two icons now reach every page, so the separate page menu that
            used to sit here was a second, redundant path to the same three views. */}
        <SidebarProjects contexts={contexts} selectedKey={page === 'global' ? '' : contextKey} selectedTask={page === 'task' ? selectedTask : ''} revision={revision}
          onOpenProject={key => { selectContext(key); selectTask(''); switchPage('project'); }}
          onOpenConfig={() => switchPage('global')} onOpenTask={openTaskInProject}/>
        {/* The task index now lives under each project; the selected project's read error stays here
            as well because it is otherwise invisible while the task or config page is open. */}
        {context && project.error && <Alert role="alert" type="error" showIcon title={project.error}/>}
        {/* Global read problems (Base/contract mismatch, missing Wiki, …) belong to the 全局配置 page, not to every page's sidebar. */}
      </dialog>
      {/* The divider is its own grid column: the sidebar scrolls, so a handle positioned inside it
          would be clipped by its own overflow. */}
      <div className="nav-resizer" role="separator" aria-orientation="vertical" aria-label="调整导航宽度" aria-valuenow={nav.width} aria-valuemin={NAV_MIN} aria-valuemax={NAV_MAX} tabIndex={0} title="拖动调整宽度，双击恢复默认，方向键微调"
        onPointerDown={startResize} onPointerMove={dragResize} onPointerUp={stopResize} onPointerCancel={stopResize} onKeyDown={keyResize} onDoubleClick={() => setNav(prev => ({ ...prev, width: NAV_DEFAULT }))}/>
      <main id="main-content" tabIndex={-1}>{page === 'global' ? <GlobalConfigPage read={global} health={health}/> : page === 'task' ? <TaskPage context={context} taskId={selectedTask} read={task} revision={revision}/> : <ProjectPage context={context} read={project} onSelectTask={openTask}/>}</main>
    </div>
  </div>;
}
