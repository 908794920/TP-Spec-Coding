import { useId, useState } from 'react';
import { Alert, Button, Flex, Input, Modal, Spin, Typography } from 'antd';
import { api, WorkbenchApiError } from '../api';
import type { TaskIndexRow, TaskNote } from '../types';
import { useRead } from '../useRead';

export function TaskNoteDialog({ contextKey, task, onClosed, onSaved }: {
    contextKey: string;
    task: TaskIndexRow;
    onClosed: () => void;
    onSaved: () => void;
}) {
    const inputId = useId();
    const [open, setOpen] = useState(true);
    const [reload, setReload] = useState(0);
    const [edit, setEdit] = useState<{ base: TaskNote; value: string }>();
    const [saving, setSaving] = useState(false);
    const [saveError, setSaveError] = useState<{ message: string; conflict: boolean }>();
    const read = useRead(JSON.stringify([contextKey, task.task_id]), reload, signal => api.taskNote(contextKey, task.task_id, signal));
    const current = !read.loading && !read.error ? read.data : undefined;
    // Keep the draft until a user-requested reload returns a valid new snapshot.
    const draft = edit && (!current || current === edit.base) ? edit.value : current?.note ?? '';
    const changed = !!current && current.note !== draft;
    const canSave = changed && !saving && !saveError?.conflict;

    async function save() {
        if (!canSave || !current) return;
        setSaving(true);
        setSaveError(undefined);
        try {
            await api.saveTaskNote(contextKey, task.task_id, draft, current.revision);
            onSaved();
            setOpen(false);
        } catch (error) {
            const conflict = error instanceof WorkbenchApiError && error.status === 409 && error.code === 'NOTE_CONFLICT';
            setSaveError({ message: error instanceof Error ? error.message : '保存失败', conflict });
        } finally {
            setSaving(false);
        }
    }

    return <Modal title="任务备注" open={open} afterClose={onClosed} onCancel={() => setOpen(false)} onOk={save}
      okText="保存" cancelText="取消" confirmLoading={saving} okButtonProps={{ disabled: !canSave }}
      cancelButtonProps={{ disabled: saving }} closable={!saving} keyboard={!saving} mask={{ closable: false }}
      footer={(_, { CancelBtn, OkBtn }) => <>
        <Button disabled={!current || !draft || saving} onClick={() => current && setEdit({ base: current, value: '' })}>清空草稿</Button>
        <CancelBtn/><OkBtn/>
      </>}>
      <Flex vertical gap={12}>
        <Typography.Text type="secondary">{task.title ? `${task.title} · ${task.task_id}` : task.task_id}</Typography.Text>
        {read.loading && <div role="status"><Spin size="small"/> 正在读取备注…</div>}
        {read.error && <Alert type="error" showIcon title="读取备注失败" description={read.error}/>}
        {saveError && <Alert type={saveError.conflict ? 'warning' : 'error'} showIcon
          title={saveError.conflict ? '备注已变化，草稿已保留' : '保存备注失败，草稿已保留'} description={saveError.message}/>}
        {(read.error || saveError?.conflict) && <div>
          <Button onClick={() => { setSaveError(undefined); setReload(value => value + 1); }}>
            {edit ? '放弃草稿并重新读取' : '重新读取'}
          </Button>
        </div>}
        <div>
          <label htmlFor={inputId}>备注内容</label>
          <Input.TextArea id={inputId} rows={6} value={draft} readOnly={!current || saving}
            onChange={event => current && setEdit({ base: current, value: event.target.value })}/>
        </div>
      </Flex>
    </Modal>;
}
