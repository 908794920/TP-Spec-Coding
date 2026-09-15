import { createRoot } from 'react-dom/client';
import App from './App';
import './styles/tokens.css';
import './styles/workbench.css';

const root = document.getElementById('root');
if (!root) throw new Error('工作台挂载点不存在');
createRoot(root).render(<App />);
