import React, { useEffect, useMemo, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import {
  Button,
  Card,
  Descriptions,
  Empty,
  Form,
  Layout,
  Modal,
  Nav,
  Popconfirm,
  SideSheet,
  Space,
  Spin,
  Table,
  Tag,
  TextArea,
  Toast,
  Tooltip,
  Typography,
} from "@douyinfe/semi-ui";
import {
  IconCopy,
  IconDelete,
  IconExit,
  IconInbox,
  IconMail,
  IconPlus,
  IconRefresh,
  IconUpload,
} from "@douyinfe/semi-icons";
import { api, clearSession, getToken, setSession } from "./api";

const { Header, Sider, Content } = Layout;
const { Text } = Typography;

function Login({ onLogin }) {
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  async function handleSubmit(values) {
    setLoading(true);
    try {
      const data = await api.login(values);
      setSession(data.access_token, data.username);
      Toast.success("登录成功");
      onLogin(data.username);
      navigate("/admin/mailboxes", { replace: true });
    } catch (error) {
      Toast.error(error.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-screen">
      <div className="login-backdrop" />
      <div className="login-panel">
        <div className="login-logo">
          <div className="brand-mark">
            <IconMail size="extra-large" />
          </div>
          <div className="login-title">
            <h1 className="page-title center">Microsoft 邮件取件后台</h1>
            <Text type="tertiary">Sign in to mail console</Text>
          </div>
        </div>
        <Form className="login-form" onSubmit={handleSubmit} labelPosition="top">
          <Form.Input field="username" label="管理员账号" placeholder="admin" rules={[{ required: true }]} />
          <Form.Input
            field="password"
            label="密码"
            mode="password"
            placeholder="请输入密码"
            rules={[{ required: true }]}
          />
          <Button theme="solid" type="primary" htmlType="submit" loading={loading} block>
            登录
          </Button>
        </Form>
      </div>
    </div>
  );
}

function StatusTag({ status }) {
  const config = {
    live: { color: "green", text: "正常" },
    dead: { color: "red", text: "失效" },
    unknown: { color: "grey", text: "未检测" },
  }[status] || { color: "grey", text: status };
  return <Tag color={config.color}>{config.text}</Tag>;
}

const API_DOC = `# API Key 接口文档

API Key 用于程序访问接口，可访问邮箱列表、邮箱详情、邮件列表、邮件详情和验证码接口。

可使用请求头或 query 参数：

\`\`\`http
X-API-Key: your_api_key
\`\`\`

也可以：

\`\`\`http
?api_key=your_api_key
\`\`\`

## 邮箱列表

\`\`\`http
GET /api/public/mailboxes
\`\`\`

返回字段包含 \`email\`、\`public_token\`、\`status\`、\`last_checked_at\`。

## 邮箱详情

\`\`\`http
GET /api/public/mailboxes/{tk_xxxx}
\`\`\`

## 邮件列表

\`\`\`http
GET /api/public/mailboxes/{tk_xxxx}/messages?limit=30
\`\`\`

邮件列表只读取邮件头，速度更快。

## 邮件详情

\`\`\`http
GET /api/public/mailboxes/{tk_xxxx}/messages/{uid}
\`\`\`

返回 \`body\` 和 \`html\`，HTML 邮件可用于前端渲染。

## 获取最近验证码

\`\`\`http
GET /api/public/mailboxes/{tk_xxxx}/code?limit=10
\`\`\`

会从最近邮件中寻找 4-8 位数字验证码。

## 前端取码页

\`\`\`text
/code
\`\`\`

公开取码页只需要输入邮箱 \`tk_xxxx\`，不需要 API Key。tk 页面入口和 API Key 是两个独立功能。`;

function MarkdownDoc({ content }) {
  const lines = content.split("\n");
  const blocks = [];
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    if (line.startsWith("```")) {
      const codeLines = [];
      index += 1;
      while (index < lines.length && !lines[index].startsWith("```")) {
        codeLines.push(lines[index]);
        index += 1;
      }
      blocks.push(
        <pre className="doc-code" key={`code-${index}`}>
          {codeLines.join("\n")}
        </pre>,
      );
    } else if (line.startsWith("# ")) {
      blocks.push(<h2 key={index}>{line.slice(2)}</h2>);
    } else if (line.startsWith("## ")) {
      blocks.push(<h3 key={index}>{line.slice(3)}</h3>);
    } else if (line.trim()) {
      blocks.push(<p key={index}>{line.replaceAll("`", "")}</p>);
    }
  }
  return <div className="markdown-doc">{blocks}</div>;
}

function PublicCodePage() {
  const [token, setToken] = useState(localStorage.getItem("public_mailbox_token") || "");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);

  async function fetchCode() {
    setLoading(true);
    try {
      localStorage.setItem("public_mailbox_token", token.trim());
      const data = await api.tokenLatestCode(token.trim());
      setResult(data);
      if (data.code) {
        Toast.success(`验证码：${data.code}`);
      } else {
        Toast.warning("最近邮件未识别到验证码");
      }
    } catch (error) {
      Toast.error(error.message);
    } finally {
      setLoading(false);
    }
  }

  async function copyCode() {
    if (!result?.code) return;
    await navigator.clipboard.writeText(result.code);
    Toast.success("已复制");
  }

  return (
    <div className="public-code-page">
      <Card className="public-code-card">
        <div className="login-logo">
          <div className="brand-mark">
            <IconMail size="extra-large" />
          </div>
          <div className="login-title">
            <h1 className="page-title center">验证码获取</h1>
            <Text type="tertiary">输入邮箱 tk token 获取最近验证码</Text>
          </div>
        </div>
        <Form labelPosition="top">
          <Form.Input
            label="邮箱 Token"
            field="token"
            value={token}
            onChange={setToken}
            placeholder="tk_xxxxxxxxxxxx"
          />
          <Button theme="solid" icon={<IconRefresh />} loading={loading} onClick={fetchCode} block>
            获取验证码
          </Button>
        </Form>
        {result && (
          <div className="code-result">
            <Text type="tertiary">{result.email}</Text>
            <div className="code-value">{result.code || "未找到"}</div>
            <Space>
              <Button icon={<IconCopy />} disabled={!result.code} onClick={copyCode}>
                复制
              </Button>
              <Tag color={result.code ? "green" : "grey"}>{result.mailbox_token}</Tag>
            </Space>
            {result.message && <Text type="secondary">{result.message.subject || "无主题"}</Text>}
          </div>
        )}
      </Card>
    </div>
  );
}

function AppShell({ username, onLogout }) {
  const location = useLocation();
  const navigate = useNavigate();
  const activeAdminPage = location.pathname.includes("/api-keys") ? "api-keys" : "mailboxes";
  const [mailboxes, setMailboxes] = useState([]);
  const [apiKeys, setApiKeys] = useState([]);
  const [loading, setLoading] = useState(true);
  const [apiKeyLoading, setApiKeyLoading] = useState(false);
  const [newApiKeyName, setNewApiKeyName] = useState("default");
  const [createdApiKey, setCreatedApiKey] = useState(null);
  const [importVisible, setImportVisible] = useState(false);
  const [addVisible, setAddVisible] = useState(false);
  const [messageVisible, setMessageVisible] = useState(false);
  const [activeMailbox, setActiveMailbox] = useState(null);
  const [messages, setMessages] = useState([]);
  const [messageLoading, setMessageLoading] = useState(false);
  const [detailVisible, setDetailVisible] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [activeMessage, setActiveMessage] = useState(null);
  const [checkingId, setCheckingId] = useState(null);
  const [selectedRowKeys, setSelectedRowKeys] = useState([]);
  const [bulkChecking, setBulkChecking] = useState(false);
  const [removingAbnormal, setRemovingAbnormal] = useState(false);

  async function loadMailboxes() {
    setLoading(true);
    try {
      setMailboxes(await api.mailboxes());
    } catch (error) {
      Toast.error(error.message);
    } finally {
      setLoading(false);
    }
  }

  async function loadApiKeys() {
    setApiKeyLoading(true);
    try {
      setApiKeys(await api.apiKeys());
    } catch (error) {
      Toast.error(error.message);
    } finally {
      setApiKeyLoading(false);
    }
  }

  useEffect(() => {
    loadMailboxes();
    loadApiKeys();
  }, []);

  function refreshCurrentPage() {
    if (activeAdminPage === "api-keys") {
      loadApiKeys();
      return;
    }
    loadMailboxes();
  }

  async function handleCreateApiKey() {
    setApiKeyLoading(true);
    try {
      const result = await api.createApiKey(newApiKeyName);
      setCreatedApiKey(result.api_key);
      Toast.success("API Key 已创建，请立即复制保存");
      await loadApiKeys();
    } catch (error) {
      Toast.error(error.message);
    } finally {
      setApiKeyLoading(false);
    }
  }

  async function handleUpdateApiKey(record, enabled) {
    try {
      await api.updateApiKey(record.id, enabled);
      Toast.success(enabled ? "已启用" : "已禁用");
      await loadApiKeys();
    } catch (error) {
      Toast.error(error.message);
    }
  }

  async function handleDeleteApiKey(record) {
    try {
      await api.deleteApiKey(record.id);
      Toast.success("已删除");
      await loadApiKeys();
    } catch (error) {
      Toast.error(error.message);
    }
  }

  async function handleCheck(record) {
    setCheckingId(record.id);
    try {
      const result = await api.checkMailbox(record.id);
      Toast[result.status === "live" ? "success" : "warning"](
        result.status === "live" ? "邮箱可用" : result.error || "邮箱不可用",
      );
      await loadMailboxes();
    } catch (error) {
      Toast.error(error.message);
    } finally {
      setCheckingId(null);
    }
  }

  async function handleBulkCheck() {
    if (!selectedRowKeys.length) {
      Toast.warning("请先选择邮箱");
      return;
    }
    setBulkChecking(true);
    try {
      const result = await api.bulkCheckMailboxes(selectedRowKeys);
      Toast.success(`已测活 ${result.checked} 个：正常 ${result.live}，异常 ${result.dead}`);
      setSelectedRowKeys([]);
      await loadMailboxes();
    } catch (error) {
      Toast.error(error.message);
    } finally {
      setBulkChecking(false);
    }
  }

  async function handleRemoveAbnormal() {
    setRemovingAbnormal(true);
    try {
      const result = await api.removeAbnormal();
      Toast.success(`已移除异常邮箱 ${result.removed} 个`);
      setSelectedRowKeys([]);
      await loadMailboxes();
    } catch (error) {
      Toast.error(error.message);
    } finally {
      setRemovingAbnormal(false);
    }
  }

  async function openMessages(record) {
    setActiveMailbox(record);
    setMessageVisible(true);
    setActiveMessage(null);
    setMessageLoading(true);
    try {
      const data = await api.messages(record.id, 30);
      setMessages(data.messages);
    } catch (error) {
      Toast.error(error.message);
      setMessages([]);
    } finally {
      setMessageLoading(false);
    }
  }

  async function openMessageDetail(message) {
    if (!activeMailbox) return;
    setActiveMessage(message);
    setDetailVisible(true);
    setDetailLoading(true);
    try {
      const data = await api.messageDetail(activeMailbox.id, message.uid);
      setActiveMessage(data);
    } catch (error) {
      Toast.error(error.message);
    } finally {
      setDetailLoading(false);
    }
  }

  async function copyText(value) {
    if (!value) return;
    await navigator.clipboard.writeText(value);
    Toast.success("已复制");
  }

  const stats = useMemo(() => {
    const live = mailboxes.filter((item) => item.status === "live").length;
    const dead = mailboxes.filter((item) => item.status === "dead").length;
    const withToken = mailboxes.filter((item) => item.has_token).length;
    return [
      { label: "邮箱总数", value: mailboxes.length, hint: "已导入账号", tone: "blue" },
      { label: "可用邮箱", value: live, hint: "最近测活正常", tone: "green" },
      { label: "异常邮箱", value: dead, hint: "需要更新凭据", tone: "red" },
      { label: "令牌账号", value: withToken, hint: "OAuth 凭据", tone: "amber" },
    ];
  }, [mailboxes]);

  const columns = useMemo(
    () => [
      {
        title: "邮箱",
        dataIndex: "email",
        render: (text, record) => (
          <div className="mail-cell">
            <Text strong>{text}</Text>
            <Text type="tertiary">{record.remark || "Microsoft IMAP"}</Text>
          </div>
        ),
      },
      {
        title: "凭据",
        width: 180,
        render: (_, record) => (
          <Space>
            {record.has_password && <Tag>密码</Tag>}
            {record.has_client_id && <Tag>client_id</Tag>}
            {record.has_token && <Tag>令牌</Tag>}
          </Space>
        ),
      },
      {
        title: "公开 Token",
        width: 220,
        render: (_, record) => (
          <Space>
            <Tag color="blue">{record.public_token}</Tag>
            <Button
              icon={<IconCopy />}
              size="small"
              onClick={() => copyText(record.public_token)}
              aria-label="复制公开 Token"
              title="复制公开 Token"
            />
          </Space>
        ),
      },
      {
        title: "状态",
        width: 110,
        render: (_, record) => <StatusTag status={record.status} />,
      },
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
        width: 280,
        render: (_, record) => (
          <Space>
            <Tooltip content="测活">
              <Button
                icon={<IconRefresh />}
                loading={checkingId === record.id}
                onClick={() => handleCheck(record)}
              />
            </Tooltip>
            <Button icon={<IconInbox />} theme="solid" onClick={() => openMessages(record)}>
              邮件
            </Button>
            <Popconfirm
              title="删除邮箱"
              content="删除后需要重新导入凭据。"
              onConfirm={async () => {
                await api.deleteMailbox(record.id);
                Toast.success("已删除");
                loadMailboxes();
              }}
            >
              <Tooltip content="删除">
                <Button icon={<IconDelete />} type="danger" />
              </Tooltip>
            </Popconfirm>
          </Space>
        ),
      },
    ],
    [checkingId],
  );

  const apiKeyColumns = useMemo(
    () => [
      { title: "名称", dataIndex: "name" },
      {
        title: "前缀",
        dataIndex: "key_prefix",
        render: (value) => <Tag color="blue">{value}...</Tag>,
      },
      {
        title: "状态",
        dataIndex: "enabled",
        render: (value) => <Tag color={value ? "green" : "grey"}>{value ? "启用" : "禁用"}</Tag>,
      },
      {
        title: "最后使用",
        dataIndex: "last_used_at",
        render: (value) => (value ? new Date(value).toLocaleString() : "-"),
      },
      {
        title: "创建时间",
        dataIndex: "created_at",
        render: (value) => (value ? new Date(value).toLocaleString() : "-"),
      },
      {
        title: "操作",
        width: 180,
        render: (_, record) => (
          <Space>
            <Button onClick={() => handleUpdateApiKey(record, !record.enabled)}>
              {record.enabled ? "禁用" : "启用"}
            </Button>
            <Popconfirm
              title="删除 API Key"
              content="删除后使用该 key 的程序将无法访问接口。"
              onConfirm={() => handleDeleteApiKey(record)}
            >
              <Button type="danger" icon={<IconDelete />} />
            </Popconfirm>
          </Space>
        ),
      },
    ],
    [],
  );

  return (
    <Layout className="app-layout">
      <Header className="app-header">
        <Nav
          mode="horizontal"
          className="header-nav"
          header={{
            logo: (
              <div className="brand-mark small">
                <IconMail />
              </div>
            ),
            text: "Microsoft Mail Admin",
          }}
          footer={
            <Space className="header-actions">
              <Button icon={<IconRefresh />} onClick={refreshCurrentPage} aria-label="刷新" title="刷新" />
              <Button icon={<IconExit />} onClick={onLogout} aria-label="退出" title="退出" />
            </Space>
          }
        />
      </Header>
      <Sider className="sidebar">
        <Nav
          defaultSelectedKeys={["mailboxes"]}
          selectedKeys={[activeAdminPage]}
          onSelect={(item) => {
            if (item.itemKey === "api-keys") {
              navigate("/admin/api-keys");
            } else {
              navigate("/admin/mailboxes");
            }
          }}
          mode="vertical"
          className="side-nav"
          items={[
            { itemKey: "mailboxes", text: "邮箱管理", icon: <IconInbox /> },
            { itemKey: "api-keys", text: "API Key", icon: <IconMail /> },
          ]}
          footer={{
            collapseButton: false,
            children: (
              <div className="side-footer">
                <Text type="tertiary">管理员</Text>
                <Text strong>{username}</Text>
              </div>
            ),
          }}
        />
      </Sider>
      <Layout className="workspace">
        <Content className="content">
          {activeAdminPage === "mailboxes" ? (
            <>
              <section className="page-hero">
                <div>
                  <h1 className="page-title">邮箱取件工作台</h1>
                  <Text type="tertiary">导入 Microsoft 邮箱，检测状态，读取邮件并复制验证码。</Text>
                </div>
                <Space className="page-actions">
                  <Button icon={<IconRefresh />} loading={bulkChecking} onClick={handleBulkCheck}>
                    批量测活
                  </Button>
                  <Popconfirm
                    title="移除异常邮箱"
                    content="将删除所有状态为异常的邮箱。"
                    onConfirm={handleRemoveAbnormal}
                  >
                    <Button type="danger" icon={<IconDelete />} loading={removingAbnormal}>
                      移除异常
                    </Button>
                  </Popconfirm>
                  <Button icon={<IconUpload />} onClick={() => setImportVisible(true)}>
                    批量导入
                  </Button>
                  <Button theme="solid" icon={<IconPlus />} onClick={() => setAddVisible(true)}>
                    新增邮箱
                  </Button>
                </Space>
              </section>

              <section className="stat-grid">
                {stats.map((item) => (
                  <Card key={item.label} className={`stat-card ${item.tone}`} bodyStyle={{ padding: 20 }}>
                    <Text type="tertiary">{item.label}</Text>
                    <div className="stat-value">{item.value}</div>
                    <Text type="tertiary">{item.hint}</Text>
                  </Card>
                ))}
              </section>

              <Card
                className="table-card"
                title={
                  <div className="card-title">
                    <div>
                      <Text strong>邮箱列表</Text>
                      <Text type="tertiary">支持密码或 Microsoft OAuth IMAP 凭据</Text>
                    </div>
                  </div>
                }
                bodyStyle={{ padding: 0 }}
              >
                <Table
                  rowKey="id"
                  columns={columns}
                  dataSource={mailboxes}
                  loading={loading}
                  rowSelection={{
                    selectedRowKeys,
                    onChange: (keys) => setSelectedRowKeys(keys),
                  }}
                  pagination={{ pageSize: 10 }}
                  empty={<Empty title="暂无邮箱" description="请先导入 Microsoft 邮箱凭据" />}
                />
              </Card>
            </>
          ) : (
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
                    <Form.Input
                      field="api_key_name"
                      label="名称"
                      value={newApiKeyName}
                      onChange={setNewApiKeyName}
                      placeholder="default"
                      style={{ width: 240 }}
                    />
                  </Form>
                  <Button theme="solid" icon={<IconPlus />} loading={apiKeyLoading} onClick={handleCreateApiKey}>
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
                <Table
                  rowKey="id"
                  columns={apiKeyColumns}
                  dataSource={apiKeys}
                  loading={apiKeyLoading}
                  pagination={false}
                  empty={<Empty title="暂无 API Key" description="创建一个 key 后即可访问公开 API" />}
                />
              </Card>

              <Card className="doc-card">
                <div className="card-title standalone">
                  <div>
                    <Text strong>API Key 接口文档</Text>
                  </div>
                </div>
                <MarkdownDoc content={API_DOC} />
              </Card>
            </>
          )}
        </Content>
      </Layout>

      <ImportModal
        visible={importVisible}
        onClose={() => setImportVisible(false)}
        onDone={() => {
          setImportVisible(false);
          loadMailboxes();
        }}
      />
      <AddModal
        visible={addVisible}
        onClose={() => setAddVisible(false)}
        onDone={() => {
          setAddVisible(false);
          loadMailboxes();
        }}
      />
      <SideSheet
        title={activeMailbox ? `${activeMailbox.email} 的邮件` : "邮件列表"}
        visible={messageVisible}
        width={760}
        onCancel={() => setMessageVisible(false)}
        footer={null}
      >
        {messageLoading ? (
          <div className="center-box">
            <Spin />
          </div>
        ) : (
          <div className="message-list">
            {messages.length === 0 && <Empty title="暂无邮件" />}
            {messages.map((message) => (
              <Card
                key={message.uid}
                className="message-card clickable"
                onClick={() => openMessageDetail(message)}
              >
                <div className="message-head">
                  <div>
                    <Text strong>{message.subject || "无主题"}</Text>
                    <Text type="tertiary">{message.from || "-"}</Text>
                  </div>
                  {message.code ? (
                    <Button
                      icon={<IconCopy />}
                      onClick={(event) => {
                        event.stopPropagation();
                        copyText(message.code);
                      }}
                    >
                      {message.code}
                    </Button>
                  ) : (
                    <Tag color="grey">查看详情</Tag>
                  )}
                </div>
                <Text className="snippet" type="secondary">
                  {message.snippet || "点击查看邮件详情"}
                </Text>
                <Descriptions
                  size="small"
                  data={[
                    { key: "UID", value: message.uid },
                    { key: "时间", value: message.date ? new Date(message.date).toLocaleString() : "-" },
                  ]}
                />
              </Card>
            ))}
          </div>
        )}
      </SideSheet>
      <Modal
        title={activeMessage?.subject || "邮件详情"}
        visible={detailVisible}
        onCancel={() => setDetailVisible(false)}
        footer={null}
        width={760}
      >
        {detailLoading ? (
          <div className="center-box">
            <Spin />
          </div>
        ) : activeMessage ? (
          <div className="detail-panel">
            <Descriptions
              size="small"
              data={[
                { key: "发件人", value: activeMessage.from || "-" },
                { key: "时间", value: activeMessage.date ? new Date(activeMessage.date).toLocaleString() : "-" },
                { key: "UID", value: activeMessage.uid },
              ]}
            />
            <div className="detail-code">
              {activeMessage.code ? (
                <Button theme="solid" icon={<IconCopy />} onClick={() => copyText(activeMessage.code)}>
                  复制验证码 {activeMessage.code}
                </Button>
              ) : (
                <Tag color="grey">未识别到验证码</Tag>
              )}
            </div>
            {activeMessage.html ? (
              <iframe
                className="message-html-frame"
                title="邮件 HTML 内容"
                sandbox=""
                srcDoc={activeMessage.html}
              />
            ) : (
              <pre className="message-body">{activeMessage.body || "无正文内容"}</pre>
            )}
          </div>
        ) : null}
      </Modal>
    </Layout>
  );
}

function ImportModal({ visible, onClose, onDone }) {
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleImport() {
    setLoading(true);
    try {
      const result = await api.importMailboxes(content);
      Toast.success(
        `测活 ${result.checked}，新增 ${result.created}，更新 ${result.updated}，失败 ${result.failed}，跳过 ${result.skipped}`,
      );
      if (result.errors.length) {
        Toast.warning(result.errors.slice(0, 3).join("；"));
      }
      setContent("");
      onDone();
    } catch (error) {
      Toast.error(error.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <Modal
      title="批量导入邮箱"
      visible={visible}
      onCancel={onClose}
      onOk={handleImport}
      okText="导入"
      confirmLoading={loading}
    >
      <TextArea
        value={content}
        onChange={setContent}
        autosize={{ minRows: 8, maxRows: 14 }}
        placeholder={"邮箱----密码----client_id----令牌\nuser@outlook.com----password----client-id----refresh-token"}
      />
    </Modal>
  );
}

function AddModal({ visible, onClose, onDone }) {
  const [loading, setLoading] = useState(false);

  async function handleSubmit(values) {
    setLoading(true);
    try {
      await api.createMailbox(values);
      Toast.success("已保存");
      onDone();
    } catch (error) {
      Toast.error(error.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <Modal title="新增邮箱" visible={visible} onCancel={onClose} footer={null}>
      <Form onSubmit={handleSubmit} labelPosition="top">
        <Form.Input field="email" label="邮箱" rules={[{ required: true, type: "email" }]} />
        <Form.Input field="password" label="密码" mode="password" />
        <Form.Input field="client_id" label="client_id" />
        <Form.TextArea field="token" label="令牌" autosize={{ minRows: 3, maxRows: 6 }} />
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

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/code" element={<PublicCodePage />} />
        <Route path="/login" element={<AuthApp initialPage="login" />} />
        <Route path="/admin" element={<Navigate to="/admin/mailboxes" replace />} />
        <Route path="/admin/mailboxes" element={<AuthApp initialPage="admin" />} />
        <Route path="/admin/api-keys" element={<AuthApp initialPage="admin" />} />
        <Route path="/" element={<Navigate to={getToken() ? "/admin/mailboxes" : "/login"} replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

function AuthApp({ initialPage }) {
  const [username, setUsername] = useState(localStorage.getItem("ms_mail_username") || "");
  const [checking, setChecking] = useState(Boolean(getToken()));
  const navigate = useNavigate();

  useEffect(() => {
    async function verify() {
      if (!getToken()) {
        if (initialPage === "admin") {
          navigate("/login", { replace: true });
        }
        setChecking(false);
        return;
      }
      try {
        const data = await api.me();
        setUsername(data.username);
        if (initialPage === "login") {
          navigate("/admin/mailboxes", { replace: true });
        }
      } catch {
        clearSession();
        setUsername("");
        navigate("/login", { replace: true });
      } finally {
        setChecking(false);
      }
    }
    verify();
  }, [initialPage, navigate]);

  if (checking) {
    return (
      <div className="center-box full-screen">
        <Spin />
      </div>
    );
  }

  if (!username) {
    return <Login onLogin={setUsername} />;
  }

  return (
    <AppShell
      username={username}
      onLogout={() => {
        clearSession();
        setUsername("");
        navigate("/login", { replace: true });
      }}
    />
  );
}
