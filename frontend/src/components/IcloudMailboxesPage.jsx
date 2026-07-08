import React, { useEffect, useMemo, useState } from "react";
import { Button, Card, Empty, Form, Input, Modal, Popconfirm, Space, Table, Tag, TextArea, Toast, Tooltip, Typography } from "@douyinfe/semi-ui";
import { IconCopy, IconDelete, IconDownload, IconInbox, IconPlus, IconUpload } from "@douyinfe/semi-icons";
import { api } from "../api";
import { MailboxPagination } from "./MailboxPagination";
import { DEFAULT_MAILBOX_PAGE_SIZE } from "../constants/mailbox";
import { exportSplitMailboxes } from "../utils/export";
import { MessageDetail, MessagesSheet } from "./MailMessageViews";

const { Text } = Typography;

// iCloud 转发邮箱管理页，邮箱会绑定到指定 IMAP 接收箱。
export function IcloudMailboxesPage() {
  const [mailboxes, setMailboxes] = useState([]);
  const [configs, setConfigs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_MAILBOX_PAGE_SIZE);
  const [total, setTotal] = useState(0);
  const [selectedRowKeys, setSelectedRowKeys] = useState([]);
  const [importVisible, setImportVisible] = useState(false);
  const [addVisible, setAddVisible] = useState(false);
  const [splitVisible, setSplitVisible] = useState(false);
  const [splitCount, setSplitCount] = useState("5");
  const [messageVisible, setMessageVisible] = useState(false);
  const [activeMailbox, setActiveMailbox] = useState(null);
  const [messages, setMessages] = useState([]);
  const [messageLoading, setMessageLoading] = useState(false);
  const [detailVisible, setDetailVisible] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [activeMessage, setActiveMessage] = useState(null);

  async function loadMailboxes() {
    setLoading(true);
    try {
      const data = await api.icloudMailboxes(page, pageSize);
      setMailboxes(data.items);
      setTotal(data.total);
    } catch (error) {
      Toast.error(error.message);
    } finally {
      setLoading(false);
    }
  }

  async function loadConfigs() {
    try {
      setConfigs(await api.imapConfigs());
    } catch (error) {
      Toast.error(error.message);
    }
  }

  useEffect(() => {
    loadMailboxes();
  }, [page, pageSize]);

  useEffect(() => {
    loadConfigs();
  }, []);

  async function copyText(value) {
    if (!value) return;
    await navigator.clipboard.writeText(value);
    Toast.success("已复制");
  }

  function openSplitExport() {
    if (!selectedRowKeys.length) {
      Toast.warning("请先选择要导出的 iCloud 邮箱");
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
    const exported = exportSplitMailboxes(selected, count, "icloud-split");
    Toast.success(`已导出 ${exported} 条邮箱`);
    setSplitVisible(false);
  }

  async function openMessages(record) {
    setActiveMailbox(record);
    setMessageVisible(true);
    setActiveMessage(null);
    setMessageLoading(true);
    try {
      const data = await api.icloudMessages(record.id, 30);
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
      setActiveMessage(await api.icloudMessageDetail(activeMailbox.id, message.uid));
    } catch (error) {
      Toast.error(error.message);
    } finally {
      setDetailLoading(false);
    }
  }

  const columns = useMemo(
    () => [
      {
        title: "iCloud 邮箱",
        render: (_, record) => (
          <div className="mail-cell">
            <Text strong>{record.email}</Text>
            <Text type="tertiary">{record.remark || "iCloud 转发邮箱"}</Text>
          </div>
        ),
      },
      { title: "IMAP 配置", dataIndex: "imap_config_name", width: 180, render: (value) => <Tag color="blue">{value}</Tag> },
      {
        title: "公开 Token",
        width: 220,
        render: (_, record) => (
          <Space>
            <Tag color="blue">{record.public_token}</Tag>
            <Tooltip content="复制公开 Token">
              <Button icon={<IconCopy />} size="small" onClick={() => copyText(record.public_token)} />
            </Tooltip>
          </Space>
        ),
      },
      { title: "创建时间", width: 190, render: (_, record) => new Date(record.created_at).toLocaleString() },
      {
        title: "操作",
        width: 180,
        render: (_, record) => (
          <Space>
            <Button icon={<IconInbox />} theme="solid" onClick={() => openMessages(record)}>
              邮件
            </Button>
            <Popconfirm title="删除 iCloud 邮箱" content="删除后需要重新导入。" onConfirm={() => api.deleteIcloudMailbox(record.id).then(loadMailboxes)}>
              <Button icon={<IconDelete />} type="danger" />
            </Popconfirm>
          </Space>
        ),
      },
    ],
    [activeMailbox],
  );

  return (
    <>
      <section className="page-hero">
        <div>
          <h1 className="page-title">iCloud 邮箱</h1>
          <Text type="tertiary">导入已转发到 IMAP 收件箱的 iCloud 邮箱，并导出 +alias 分裂地址。</Text>
        </div>
        <Space className="page-actions">
          <Button icon={<IconDownload />} onClick={openSplitExport}>
            分裂导出 CSV
          </Button>
          <Button icon={<IconUpload />} onClick={() => setImportVisible(true)}>
            批量导入
          </Button>
          <Button theme="solid" icon={<IconPlus />} onClick={() => setAddVisible(true)}>
            新增邮箱
          </Button>
        </Space>
      </section>
      <Card className="table-card" bodyStyle={{ padding: 0 }}>
        <Table
          rowKey="id"
          columns={columns}
          dataSource={mailboxes}
          loading={loading}
          pagination={false}
          rowSelection={{ selectedRowKeys, onChange: (keys) => setSelectedRowKeys(keys) }}
          empty={<Empty title="暂无 iCloud 邮箱" description="请先新增 IMAP 配置，再导入 iCloud 邮箱" />}
        />
        <MailboxPagination
          currentPage={page}
          pageSize={pageSize}
          total={total}
          currentCount={mailboxes.length}
          onPageChange={setPage}
          onPageSizeChange={(value) => {
            setPage(1);
            setPageSize(Number(value));
          }}
        />
      </Card>
      <IcloudImportModal visible={importVisible} configs={configs} onClose={() => setImportVisible(false)} onDone={() => {
        setImportVisible(false);
        loadMailboxes();
      }} />
      <IcloudAddModal visible={addVisible} configs={configs} onClose={() => setAddVisible(false)} onDone={() => {
        setAddVisible(false);
        loadMailboxes();
      }} />
      <Modal title="分裂导出 CSV" visible={splitVisible} onCancel={() => setSplitVisible(false)} onOk={handleSplitExport} okText="导出">
        <div className="split-export-panel">
          <Text type="secondary">已选择 {selectedRowKeys.length} 个邮箱，每个邮箱会导出本体和指定次数的 +4 位随机字母别名。</Text>
          <div className="split-export-field">
            <Text strong>分裂次数</Text>
            <Input type="number" min={1} max={10000} value={splitCount} onChange={setSplitCount} />
          </div>
        </div>
      </Modal>
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
      <MessageDetail
        visible={detailVisible}
        message={activeMessage}
        loading={detailLoading}
        onClose={() => setDetailVisible(false)}
        onCopy={copyText}
      />
    </>
  );
}

function IcloudImportModal({ visible, configs, onClose, onDone }) {
  const [content, setContent] = useState("");
  const [imapConfigId, setImapConfigId] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleImport() {
    if (!imapConfigId) {
      Toast.warning("请选择 IMAP 配置");
      return;
    }
    setLoading(true);
    try {
      const result = await api.importIcloudMailboxes({ content, imap_config_id: Number(imapConfigId) });
      Toast.success(`新增 ${result.created}，更新 ${result.updated}，跳过 ${result.skipped}`);
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
    <Modal title="批量导入 iCloud 邮箱" visible={visible} onCancel={onClose} onOk={handleImport} okText="导入" confirmLoading={loading}>
      <Form labelPosition="top">
        <Form.Select field="imap_config_id" label="IMAP 配置" value={imapConfigId} onChange={setImapConfigId} optionList={configs.map((item) => ({ label: item.name, value: item.id }))} />
      </Form>
      <TextArea value={content} onChange={setContent} autosize={{ minRows: 8, maxRows: 14 }} placeholder={"user@icloud.com\nuser2@icloud.com----备注"} />
    </Modal>
  );
}

function IcloudAddModal({ visible, configs, onClose, onDone }) {
  const [loading, setLoading] = useState(false);

  async function handleSubmit(values) {
    setLoading(true);
    try {
      await api.createIcloudMailbox({ ...values, imap_config_id: Number(values.imap_config_id) });
      Toast.success("已保存");
      onDone();
    } catch (error) {
      Toast.error(error.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <Modal title="新增 iCloud 邮箱" visible={visible} onCancel={onClose} footer={null}>
      <Form onSubmit={handleSubmit} labelPosition="top">
        <Form.Input field="email" label="邮箱" rules={[{ required: true, type: "email" }]} />
        <Form.Select field="imap_config_id" label="IMAP 配置" rules={[{ required: true }]} optionList={configs.map((item) => ({ label: item.name, value: item.id }))} />
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
