import { forwardRef } from 'react';
import type { FactRecord } from '../types';
import { ExecutionWorkflow } from './ExecutionWorkflow';
export interface WorkflowHandle { locateCurrent: () => void }
export interface WorkflowProps {
    workflow: FactRecord;
    task: FactRecord;
    blockers?: unknown;
    onDocuments?: () => void;
    onWorkItem?: (id: string) => void;
}
// 新旧任务共用信息层级；缺计划时不退回通用阶段流程。
export const WorkflowStrip = forwardRef<WorkflowHandle, WorkflowProps>((props, ref) =>
    <ExecutionWorkflow {...props} ref={ref}/>);
