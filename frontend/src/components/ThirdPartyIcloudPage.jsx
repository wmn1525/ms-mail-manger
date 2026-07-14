// 第三方 iCloud 页面负责导入敏感取码链接、实时取码和分裂导出。
import React, { useEffect, useMemo, useState } from "react";
import { Button, Card, Empty, Input, Modal, Popconfirm, Space, Table, Tag, TextArea, Toast, Tooltip, Typography } from "@douyinfe/semi-ui";
import { IconCopy, IconDelete, IconDownload, IconSearch, IconUpload } from "@douyinfe/semi-icons";
import { api } from "../api";
import { DEFAULT_MAILBOX_PAGE_SIZE } from "../constants/mailbox";
import { exportSplitMailboxes } from "../utils/export";
import { MailboxPagination } from "./MailboxPagination";

const { Text } = Typography;

// 第三方 iCloud 管理页只展示邮箱，敏感取码链接由后端加密保存。
export function ThirdPartyIcloudPage() {
  const [mailboxes, setMailboxes] = useState([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_MAILBOX_PAGE_SIZE);
  const [total, setTotal] = useState(0);
  const [selectedRowKeys, setSelectedRowKeys] = useState([]);
  const [importVisible, setImportVisible] = useState(false);
  const [splitVisible, setSplitVisible] = useState(false);
  const [splitCount, setSplitCount] = useState("5");
  const [fetchingId, setFetchingId] = useState(null);
  const [codes, setCodes] = useState({});

  // 按当前分页和邮箱条件刷新列表，取码链接不会下发到浏览器。
  async function loadMailboxes() {
    setLoading(true);
    try {
      const data = await api.thirdPartyIcloudMailboxes(page, pageSize, search);
      setMailboxes(data.items);
      setTotal(data.total);
    } catch (error) {
      Toast.error(error.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadMailboxes();
  }, [page, pageSize, search]);

  // 验证码只在本次页面会话中保留，复制后不写入本地存储。
  async function copyCode(code) {
    await navigator.clipboard.writeText(code);
    Toast.success("验证码已复制");
  }

  // 点击取码时由后端代理第三方请求，避免浏览器 CORS 和链接泄露。
  async function handleFetchCode(record) {
    setFetchingId(record.id);
    try {
      const result = await api.thirdPartyIcloudCode(record.id);
      setCodes((current) => ({ ...current, [record.id]: result.code }));
      Toast.success(`验证码：${result.code}`);
    } catch (error) {
      Toast.error(error.message);
    } finally {
      setFetchingId(null);
    }
  }

  // 没有勾选邮箱时不打开导出弹窗，避免生成空文件。
  function openSplitExport() {
    if (!selectedRowKeys.length) {
      Toast.warning("请先选择要导出的第三方 iCloud 邮箱");
      return;
    }
    setSplitVisible(true);
  }

  // 复用邮箱分裂工具，默认次数为 5 且允许用户在弹窗中调整。
  function handleSplitExport() {
    const count = Number.parseInt(splitCount, 10);
    if (!Number.isInteger(count) || count < 1 || count > 10000) {
      Toast.warning("分裂次数请输入 1-10000 之间的整数");
      return;
    }
    const selectedKeys = new Set(selectedRowKeys.map(String));
    const selected = mailboxes.filter((item) => selectedKeys.has(String(item.id)));
    const exported = exportSplitMailboxes(selected, count, "third-party-icloud-split");
    Toast.success(`已导出 ${exported} 条邮箱`);
    setSplitVisible(false);
  }

  const columns = useMemo(
    () => [
      {
        title: "iCloud 邮箱",
        render: (_, record) => (
          <div className="mail-cell">
            <Text strong>{record.email}</Text>
            <Text type="tertiary">第三方链接取码</Text>
          </div>
        ),
      },
      {
        title: "取码链接",
        width: 150,
        render: () => <Tag color="blue">已加密保存</Tag>,
      },
      {
        title: "最近取码",
        width: 180,
        render: (_, record) => codes[record.id] ? (
          <Tooltip content="复制验证码">
            <Button size="small" icon={<IconCopy />} onClick={() => copyCode(codes[record.id])}>
              {codes[record.id]}
            </Button>
          </Tooltip>
        ) : <Text type="tertiary">尚未取码</Text>,
      },
      { title: "创建时间", width: 190, render: (_, record) => new Date(record.created_at).toLocaleString() },
      {
        title: "操作",
        width: 170,
        render: (_, record) => (
          <Space>
            <Button theme="solid" loading={fetchingId === record.id} onClick={() => handleFetchCode(record)}>
              取码
            </Button>
            <Popconfirm
              title="删除第三方 iCloud 邮箱"
              content="删除后需要重新导入取码链接。"
              onConfirm={() => api.deleteThirdPartyIcloudMailbox(record.id).then(loadMailboxes)}
            >
              <Button icon={<IconDelete />} type="danger" />
            </Popconfirm>
          </Space>
        ),
      },
    ],
    [codes, fetchingId],
  );

  return (
    <>
      <section className="page-hero">
        <div>
          <h1 className="page-title">第三方 iCloud</h1>
          <Text type="tertiary">导入 icloudapi.xyz 取码链接，实时读取验证码并导出 +alias 分裂地址。</Text>
        </div>
        <Space className="page-actions">
          <Button icon={<IconDownload />} onClick={openSplitExport}>分裂导出 CSV</Button>
          <Button theme="solid" icon={<IconUpload />} onClick={() => setImportVisible(true)}>批量导入</Button>
        </Space>
      </section>
      <Card
        className="table-card"
        title={(
          <div className="mailbox-toolbar">
            <div className="mailbox-toolbar__text">
              <Text strong>邮箱列表</Text>
              <Text type="tertiary">共 {total} 个，当前显示 {mailboxes.length} 个</Text>
            </div>
            <Input
              className="mail-search"
              value={search}
              onChange={(value) => {
                setPage(1);
                setSearch(value);
              }}
              showClear
              prefix={<IconSearch />}
              placeholder="输入原始邮箱或分裂邮箱查询"
            />
          </div>
        )}
        bodyStyle={{ padding: 0 }}
      >
        <Table
          rowKey="id"
          columns={columns}
          dataSource={mailboxes}
          loading={loading}
          pagination={false}
          rowSelection={{ selectedRowKeys, onChange: setSelectedRowKeys }}
          empty={<Empty title={search.trim() ? "未找到原始邮箱" : "暂无第三方 iCloud 邮箱"} />}
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
      <ThirdPartyImportModal
        visible={importVisible}
        onClose={() => setImportVisible(false)}
        onDone={() => {
          setImportVisible(false);
          loadMailboxes();
        }}
      />
      <Modal
        title="分裂导出 CSV"
        visible={splitVisible}
        onCancel={() => setSplitVisible(false)}
        onOk={handleSplitExport}
        okText="导出"
      >
        <div className="split-export-panel">
          <Text type="secondary">已选择 {selectedRowKeys.length} 个邮箱，每个邮箱会导出本体和指定次数的 +4 位随机字母别名。</Text>
          <div className="split-export-field">
            <Text strong>分裂次数</Text>
            <Input type="number" min={1} max={10000} value={splitCount} onChange={setSplitCount} />
          </div>
        </div>
      </Modal>
    </>
  );
}

// 批量导入弹窗严格提示“邮箱----取码链接”格式。
function ThirdPartyImportModal({ visible, onClose, onDone }) {
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(false);

  // 导入完成后清空敏感输入，避免链接继续停留在页面状态中。
  async function handleImport() {
    if (!content.trim()) {
      Toast.warning("请输入要导入的邮箱和取码链接");
      return;
    }
    setLoading(true);
    try {
      const result = await api.importThirdPartyIcloudMailboxes(content);
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
    <Modal
      title="批量导入第三方 iCloud"
      visible={visible}
      onCancel={onClose}
      onOk={handleImport}
      okText="导入"
      confirmLoading={loading}
    >
      <Text type="secondary">每行格式：邮箱----icloudapi.xyz 取码链接</Text>
      <TextArea
        value={content}
        onChange={setContent}
        autosize={{ minRows: 8, maxRows: 14 }}
        placeholder="user@icloud.com----http://icloudapi.xyz/show/token/user@icloud.com"
      />
    </Modal>
  );
}
