import React, { useEffect, useMemo, useState } from "react";
import {
  Button,
  Card,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Space,
  Table,
  Tag,
  TextArea,
  Toast,
  Tooltip,
  Typography,
} from "@douyinfe/semi-ui";
import { IconCopy, IconDelete, IconDownload, IconInbox, IconPlus, IconRefresh, IconSearch, IconUpload } from "@douyinfe/semi-icons";
import { api } from "../api";
import { DEFAULT_MAILBOX_PAGE_SIZE } from "../constants/mailbox";
import { exportSplitMailboxes } from "../utils/export";
import { MailboxPagination } from "./MailboxPagination";
import { MessageDetail, MessagesSheet } from "./MailMessageViews";
import { StatusTag } from "./StatusTag";

const { Text } = Typography;

// Microsoft 邮箱管理页，保留原有导入、测活、读信和分裂导出能力。
export function MailboxesPage() {
  const [mailboxes, setMailboxes] = useState([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
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
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_MAILBOX_PAGE_SIZE);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState({ live: 0, dead: 0, withToken: 0 });
  const [splitVisible, setSplitVisible] = useState(false);
  const [splitCount, setSplitCount] = useState("5");

  async function loadMailboxes() {
    setLoading(true);
    try {
      const data = await api.mailboxes(page, pageSize);
      setMailboxes(data.items);
      setTotal(data.total);
      setStats({ live: data.live, dead: data.dead, withToken: data.with_token });
    } catch (error) {
      Toast.error(error.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadMailboxes();
  }, [page, pageSize]);

  async function handleCheck(record) {
    setCheckingId(record.id);
    try {
      const result = await api.checkMailbox(record.id);
      Toast[result.status === "live" ? "success" : "warning"](result.status === "live" ? "邮箱可用" : result.error);
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

  function openSplitExport() {
    if (!selectedRowKeys.length) {
      Toast.warning("请先选择要导出的邮箱");
      return;
    }
    setSplitVisible(true);
  }

  function handleSplitExport() {
    const count = Number.parseInt(splitCount, 10);
    if (!Number.isInteger(count) || count < 1 || count > 10000) {
      Toast.warning("分裂次数请输入 1-10000 之间的整数");
      return;
    }
    const selectedKeys = new Set(selectedRowKeys.map(String));
    const selected = mailboxes.filter((item) => selectedKeys.has(String(item.id)));
    const exported = exportSplitMailboxes(selected, count, "mailbox-split");
    Toast.success(`已导出 ${exported} 条邮箱`);
    setSplitVisible(false);
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
      setActiveMessage(await api.messageDetail(activeMailbox.id, message.uid));
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

  const statItems = useMemo(
    () => [
      { label: "邮箱总数", value: total, hint: "已导入账号", tone: "blue" },
      { label: "可用邮箱", value: stats.live, hint: "最近测活正常", tone: "green" },
      { label: "异常邮箱", value: stats.dead, hint: "需要更新凭据", tone: "red" },
      { label: "令牌账号", value: stats.withToken, hint: "OAuth 凭据", tone: "amber" },
    ],
    [stats, total],
  );

  const filtered = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    if (!keyword) return mailboxes;
    return mailboxes.filter((item) => [item.email, item.remark, item.public_token].some((value) => String(value || "").toLowerCase().includes(keyword)));
  }, [mailboxes, search]);

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
            <Button icon={<IconCopy />} size="small" onClick={() => copyText(record.public_token)} />
          </Space>
        ),
      },
      { title: "状态", width: 110, render: (_, record) => <StatusTag status={record.status} /> },
      {
        title: "最后检测",
        width: 190,
        render: (_, record) => <Text type={record.last_error ? "danger" : "tertiary"}>{record.last_error || (record.last_checked_at ? new Date(record.last_checked_at).toLocaleString() : "-")}</Text>,
      },
      {
        title: "操作",
        width: 280,
        render: (_, record) => (
          <Space>
            <Tooltip content="测活">
              <Button icon={<IconRefresh />} loading={checkingId === record.id} onClick={() => handleCheck(record)} />
            </Tooltip>
            <Button icon={<IconInbox />} theme="solid" onClick={() => openMessages(record)}>
              邮件
            </Button>
            <Popconfirm title="删除邮箱" content="删除后需要重新导入凭据。" onConfirm={() => api.deleteMailbox(record.id).then(loadMailboxes)}>
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
          <h1 className="page-title">微软邮箱</h1>
          <Text type="tertiary">导入 Microsoft 邮箱，检测状态，读取邮件并复制验证码。</Text>
        </div>
        <Space className="page-actions">
          <Button icon={<IconRefresh />} loading={bulkChecking} onClick={handleBulkCheck}>批量测活</Button>
          <Button icon={<IconDownload />} onClick={openSplitExport}>分裂导出 CSV</Button>
          <Popconfirm title="移除异常邮箱" content="将删除所有状态为异常的邮箱。" onConfirm={handleRemoveAbnormal}>
            <Button type="danger" icon={<IconDelete />} loading={removingAbnormal}>移除异常</Button>
          </Popconfirm>
          <Button icon={<IconUpload />} onClick={() => setImportVisible(true)}>批量导入</Button>
          <Button theme="solid" icon={<IconPlus />} onClick={() => setAddVisible(true)}>新增邮箱</Button>
        </Space>
      </section>
      <section className="stat-grid">
        {statItems.map((item) => (
          <Card key={item.label} className={`stat-card ${item.tone}`} bodyStyle={{ padding: 20 }}>
            <Text type="tertiary">{item.label}</Text>
            <div className="stat-value">{item.value}</div>
            <Text type="tertiary">{item.hint}</Text>
          </Card>
        ))}
      </section>
      <Card className="table-card" title={<MailboxToolbar total={total} count={filtered.length} search={search} onSearch={setSearch} />} bodyStyle={{ padding: 0 }}>
        <Table rowKey="id" columns={columns} dataSource={filtered} loading={loading} rowSelection={{ selectedRowKeys, onChange: setSelectedRowKeys }} pagination={false} empty={<Empty title={search.trim() ? "未找到匹配邮箱" : "暂无邮箱"} />} />
        <MailboxPagination currentPage={page} pageSize={pageSize} total={total} currentCount={filtered.length} onPageChange={setPage} onPageSizeChange={(value) => {
          setPage(1);
          setPageSize(Number(value));
        }} />
      </Card>
      <ImportModal visible={importVisible} onClose={() => setImportVisible(false)} onDone={() => {
        setImportVisible(false);
        loadMailboxes();
      }} />
      <AddModal visible={addVisible} onClose={() => setAddVisible(false)} onDone={() => {
        setAddVisible(false);
        loadMailboxes();
      }} />
      <SplitModal visible={splitVisible} count={splitCount} selectedCount={selectedRowKeys.length} onCount={setSplitCount} onClose={() => setSplitVisible(false)} onExport={handleSplitExport} />
      <MessagesSheet
        visible={messageVisible}
        mailbox={activeMailbox}
        loading={messageLoading}
        messages={messages}
        onClose={() => setMessageVisible(false)}
        onOpen={openMessageDetail}
        onCopy={copyText}
        onRefresh={() => activeMailbox && openMessages(activeMailbox)}
      />
      <MessageDetail visible={detailVisible} message={activeMessage} loading={detailLoading} onClose={() => setDetailVisible(false)} onCopy={copyText} />
    </>
  );
}

function MailboxToolbar({ total, count, search, onSearch }) {
  return (
    <div className="mailbox-toolbar">
      <div className="mailbox-toolbar__text">
        <Text strong>邮箱列表</Text>
        <Text type="tertiary">支持密码或 Microsoft OAuth IMAP 凭据 · 共 {total} 个，当前显示 {count} 个</Text>
      </div>
      <Input className="mail-search" value={search} onChange={onSearch} showClear prefix={<IconSearch />} placeholder="搜索邮箱、备注或 Token" />
    </div>
  );
}

function ImportModal({ visible, onClose, onDone }) {
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleImport() {
    setLoading(true);
    try {
      const result = await api.importMailboxes(content);
      Toast.success(`测活 ${result.checked}，新增 ${result.created}，更新 ${result.updated}，失败 ${result.failed}，跳过 ${result.skipped}`);
      if (result.errors.length) Toast.warning(result.errors.slice(0, 3).join("；"));
      setContent("");
      onDone();
    } catch (error) {
      Toast.error(error.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <Modal title="批量导入邮箱" visible={visible} onCancel={onClose} onOk={handleImport} okText="导入" confirmLoading={loading}>
      <TextArea value={content} onChange={setContent} autosize={{ minRows: 8, maxRows: 14 }} placeholder={"邮箱----密码----client_id----令牌\nuser@outlook.com----password----client-id----refresh-token"} />
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
        <Space className="modal-actions"><Button onClick={onClose}>取消</Button><Button theme="solid" htmlType="submit" loading={loading}>保存</Button></Space>
      </Form>
    </Modal>
  );
}

function SplitModal({ visible, count, selectedCount, onCount, onClose, onExport }) {
  return (
    <Modal title="分裂导出 CSV" visible={visible} onCancel={onClose} onOk={onExport} okText="导出">
      <div className="split-export-panel">
        <Text type="secondary">已选择 {selectedCount} 个邮箱，每个邮箱会导出本体和指定次数的 +4 位随机字母别名。</Text>
        <div className="split-export-field"><Text strong>分裂次数</Text><Input type="number" min={1} max={10000} value={count} onChange={onCount} /></div>
      </div>
    </Modal>
  );
}
