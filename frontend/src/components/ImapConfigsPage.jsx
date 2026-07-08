import React, { useEffect, useMemo, useState } from "react";
import { Button, Card, Empty, Form, Modal, Popconfirm, Space, Table, Toast, Tooltip, Typography } from "@douyinfe/semi-ui";
import { IconDelete, IconEdit, IconPlus, IconRefresh } from "@douyinfe/semi-icons";
import { api } from "../api";
import { StatusTag } from "./StatusTag";

const { Text } = Typography;

// 接码 IMAP 配置页，供 iCloud 转发邮箱选择接收箱。
export function ImapConfigsPage() {
  const [configs, setConfigs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [addVisible, setAddVisible] = useState(false);
  const [editConfig, setEditConfig] = useState(null);
  const [checkingId, setCheckingId] = useState(null);

  async function loadConfigs() {
    setLoading(true);
    try {
      setConfigs(await api.imapConfigs());
    } catch (error) {
      Toast.error(error.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadConfigs();
  }, []);

  async function handleCheck(record) {
    setCheckingId(record.id);
    try {
      const result = await api.checkImapConfig(record.id);
      Toast[result.status === "live" ? "success" : "warning"](result.status === "live" ? "IMAP 可用" : result.error);
      await loadConfigs();
    } catch (error) {
      Toast.error(error.message);
    } finally {
      setCheckingId(null);
    }
  }

  const columns = useMemo(
    () => [
      {
        title: "名称",
        render: (_, record) => (
          <div className="mail-cell">
            <Text strong>{record.name}</Text>
            <Text type="tertiary">{record.remark || record.username}</Text>
          </div>
        ),
      },
      { title: "服务器", render: (_, record) => `${record.host}:${record.port}` },
      { title: "状态", width: 110, render: (_, record) => <StatusTag status={record.status} /> },
      {
        title: "最后检测",
        width: 190,
        render: (_, record) => (
          <Text type={record.last_error ? "danger" : "tertiary"}>
            {record.last_error || (record.last_checked_at ? new Date(record.last_checked_at).toLocaleString() : "-")}
          </Text>
        ),
      },
      {
        title: "操作",
        width: 200,
        render: (_, record) => (
          <Space>
            <Tooltip content="修改">
              <Button icon={<IconEdit />} onClick={() => setEditConfig(record)} />
            </Tooltip>
            <Tooltip content="测活">
              <Button icon={<IconRefresh />} loading={checkingId === record.id} onClick={() => handleCheck(record)} />
            </Tooltip>
            <Popconfirm title="删除 IMAP 配置" content="已绑定 iCloud 邮箱的配置不能删除。" onConfirm={() => api.deleteImapConfig(record.id).then(loadConfigs)}>
              <Button icon={<IconDelete />} type="danger" />
            </Popconfirm>
          </Space>
        ),
      },
    ],
    [checkingId],
  );

  return (
    <>
      <section className="page-hero">
        <div>
          <h1 className="page-title">IMAP 配置</h1>
          <Text type="tertiary">维护接码收件箱，iCloud 邮箱导入时选择其中一个配置。</Text>
        </div>
        <Button theme="solid" icon={<IconPlus />} onClick={() => setAddVisible(true)}>
          新增 IMAP
        </Button>
      </section>
      <Card className="table-card" bodyStyle={{ padding: 0 }}>
        <Table rowKey="id" columns={columns} dataSource={configs} loading={loading} pagination={false} empty={<Empty title="暂无 IMAP 配置" />} />
      </Card>
      <ImapConfigModal
        visible={addVisible}
        onClose={() => setAddVisible(false)}
        onDone={() => {
          setAddVisible(false);
          loadConfigs();
        }}
      />
      <ImapConfigModal
        visible={Boolean(editConfig)}
        config={editConfig}
        onClose={() => setEditConfig(null)}
        onDone={() => {
          setEditConfig(null);
          loadConfigs();
        }}
      />
    </>
  );
}

function ImapConfigModal({ visible, config, onClose, onDone }) {
  const [loading, setLoading] = useState(false);
  const isEdit = Boolean(config);
  const initValues = config || { port: 993, use_ssl: true };

  async function handleSubmit(values) {
    setLoading(true);
    try {
      const payload = { ...values, port: Number(values.port || 993), use_ssl: values.use_ssl !== false };
      if (isEdit) {
        await api.updateImapConfig(config.id, payload);
      } else {
        await api.createImapConfig(payload);
      }
      Toast.success("已保存");
      onDone();
    } catch (error) {
      Toast.error(error.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <Modal title={isEdit ? "修改 IMAP 配置" : "新增 IMAP 配置"} visible={visible} onCancel={onClose} footer={null}>
      <Form key={config?.id || "new"} onSubmit={handleSubmit} labelPosition="top" initValues={initValues}>
        <Form.Input field="name" label="名称" rules={[{ required: true }]} />
        <Form.Input field="host" label="IMAP Host" placeholder="imap.example.com" rules={[{ required: true }]} />
        <Form.Input field="port" label="端口" rules={[{ required: true }]} />
        <Form.Input field="username" label="账号" rules={[{ required: true }]} />
        <Form.Input
          field="password"
          label={isEdit ? "密码（留空不修改）" : "密码"}
          mode="password"
          rules={isEdit ? [] : [{ required: true }]}
        />
        <Form.Switch field="use_ssl" label="SSL" />
        <Form.Input field="remark" label="备注" />
        <Space className="modal-actions">
          <Button onClick={onClose}>取消</Button>
          <Button theme="solid" htmlType="submit" loading={loading}>
            保存
          </Button>
        </Space>
      </Form>
    </Modal>
  );
}
