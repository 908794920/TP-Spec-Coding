import { createRoot } from 'react-dom/client';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import App from './App';
import { useWorkbenchTheme } from './theme';
import './styles/tokens.css';
import './styles/workbench.css';

function Root() {
    const theme = useWorkbenchTheme();
    return <ConfigProvider locale={zhCN} theme={theme}><App /></ConfigProvider>;
}

const root = document.getElementById('root');
if (!root) throw new Error('工作台挂载点不存在');
createRoot(root).render(<Root />);
