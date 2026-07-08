import React, { useEffect, useMemo, useState } from "react";
import { Button, Card, Empty, Form, Popconfirm, Space, Table, Tag, Toast, Typography } from "@douyinfe/semi-ui";
import { IconCopy, IconDelete, IconPlus } from "@douyinfe/semi-icons";
import { api } from "../api";
import { API_DOC } from "../docs/apiDoc";
import { MarkdownDoc } from "./MarkdownDoc";

const { Text } = Typography;

// API Key 管理页，包含创建、启停、删除和公开接口说明。
export function ApiKeyPage() {
  const [apiKeys, setApiKeys] = useState([]);
  const [loading, setLoading] = useState(false);
  const [newApiKeyName, setNewApiKeyName] = useState("default");
  const [createdApiKey, setCreatedApiKey] = useState(null);

  async function loadApiKeys() {
    setLoading(true);
    try {
      setApiKeys(await api.apiKeys());
    } catch (error) {
      Toast.error(error.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadApiKeys();
  }, []);

  async function handleCreateApiKey() {
    setLoading(true);
    try {
      const result = await api.createApiKey(newApiKeyName);
      setCreatedApiKey(result.api_key);
      Toast.success("API Key 已创建，请立即复制保存");
      await loadApiKeys();
    } catch (error) {
      Toast.error(error.message);
    } finally {
      setLoading(false);
    }
  }

  async function copyText(value) {
    if (!value) return;
    await navigator.clipboard.writeText(value);
    Toast.success("已复制");
  }

  const columns = useMemo(
    () => [
      { title: "名称", dataIndex: "name" },
      { title: "前缀", dataIndex: "key_prefix", render: (value) => <Tag color="blue">{value}...</Tag> },
      {
        title: "状态",
        dataIndex: "enabled",
        render: (value) => <Tag color={value ? "green" : "grey"}>{value ? "启用" : "禁用"}</Tag>,
      },
      { title: "最后使用", dataIndex: "last_used_at", render: (value) => (value ? new Date(value).toLocaleString() : "-") },
      { title: "创建时间", dataIndex: "created_at", render: (value) => (value ? new Date(value).toLocaleString() : "-") },
      {
        title: "操作",
        width: 180,
        render: (_, record) => (
          <Space>
            <Button onClick={() => api.updateApiKey(record.id, !record.enabled).then(loadApiKeys)}>
              {record.enabled ? "禁用" : "启用"}
            </Button>
            <Popconfirm title="删除 API Key" content="删除后程序将无法访问接口。" onConfirm={() => api.deleteApiKey(record.id).then(loadApiKeys)}>
              <Button type="danger" icon={<IconDelete />} />
            </Popconfirm>
          </Space>
        ),
      },
    ],
    [],
  );

  return (
    <>
      <section className="page-hero">
        <div>
          <h1 className="page-title">API Key 管理</h1>
          <Text type="tertiary">创建程序访问用 API Key，并查看公开接口文档。</Text>
        </div>
      </section>
      <Card className="doc-card">
        <div className="card-title standalone">
          <div>
            <Text strong>API Key 管理</Text>
            <Text type="tertiary">完整 key 只在创建时显示一次</Text>
          </div>
        </div>
        <div className="api-key-toolbar">
          <Form layout="horizontal" labelPosition="left">
            <Form.Input field="api_key_name" label="名称" value={newApiKeyName} onChange={setNewApiKeyName} />
          </Form>
          <Button theme="solid" icon={<IconPlus />} loading={loading} onClick={handleCreateApiKey}>
            创建 API Key
          </Button>
        </div>
        {createdApiKey && (
          <div className="created-key-box">
            <Text strong>新 API Key</Text>
            <code>{createdApiKey}</code>
            <Button icon={<IconCopy />} onClick={() => copyText(createdApiKey)}>
              复制
            </Button>
          </div>
        )}
        <Table rowKey="id" columns={columns} dataSource={apiKeys} loading={loading} pagination={false} empty={<Empty title="暂无 API Key" />} />
      </Card>
      <Card className="doc-card">
        <div className="card-title standalone">
          <Text strong>API Key 接口文档</Text>
        </div>
        <MarkdownDoc content={API_DOC} />
      </Card>
    </>
  );
}
