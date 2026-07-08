import React from "react";
import { Button, Card, Descriptions, Empty, Modal, SideSheet, Spin, Tag, Typography } from "@douyinfe/semi-ui";
import { IconCopy, IconRefresh } from "@douyinfe/semi-icons";

const { Text } = Typography;

// 邮件列表抽屉和详情弹窗，供邮箱页面复用。
export function MessagesSheet({ visible, mailbox, loading, messages, onClose, onOpen, onCopy, onRefresh }) {
  return (
    <SideSheet title={mailbox ? `${mailbox.email} 的邮件` : "邮件列表"} visible={visible} width={760} onCancel={onClose} footer={null}>
      <div className="message-sheet-toolbar">
        <Button icon={<IconRefresh />} loading={loading} disabled={!mailbox} onClick={onRefresh}>
          刷新
        </Button>
      </div>
      {loading ? (
        <div className="center-box"><Spin /></div>
      ) : (
        <div className="message-list">
          {messages.length === 0 && <Empty title="暂无邮件" />}
          {messages.map((message) => (
            <Card key={message.uid} className="message-card clickable" onClick={() => onOpen(message)}>
              <div className="message-head">
                <div>
                  <Text strong>{message.subject || "无主题"}</Text>
                  <Text type="tertiary">{message.from || "-"}</Text>
                </div>
                {message.code ? (
                  <Button icon={<IconCopy />} onClick={(event) => {
                    event.stopPropagation();
                    onCopy(message.code);
                  }}>
                    {message.code}
                  </Button>
                ) : (
                  <Tag color="grey">查看详情</Tag>
                )}
              </div>
              <Text className="snippet" type="secondary">{message.snippet || "点击查看邮件详情"}</Text>
              <Descriptions size="small" data={[
                { key: "UID", value: message.uid },
                { key: "时间", value: message.date ? new Date(message.date).toLocaleString() : "-" },
              ]} />
            </Card>
          ))}
        </div>
      )}
    </SideSheet>
  );
}

// 展示邮件正文，优先渲染 HTML，避免丢失验证码上下文。
export function MessageDetail({ visible, message, loading, onClose, onCopy }) {
  return (
    <Modal title={message?.subject || "邮件详情"} visible={visible} onCancel={onClose} footer={null} width={760}>
      {loading ? (
        <div className="center-box"><Spin /></div>
      ) : message ? (
        <div className="detail-panel">
          <Descriptions size="small" data={[
            { key: "发件人", value: message.from || "-" },
            { key: "时间", value: message.date ? new Date(message.date).toLocaleString() : "-" },
            { key: "UID", value: message.uid },
          ]} />
          <div className="detail-code">
            {message.code ? (
              <Button theme="solid" icon={<IconCopy />} onClick={() => onCopy(message.code)}>
                复制验证码 {message.code}
              </Button>
            ) : (
              <Tag color="grey">未识别到验证码</Tag>
            )}
          </div>
          {message.html ? (
            <iframe className="message-html-frame" title="邮件 HTML 内容" sandbox="" srcDoc={message.html} />
          ) : (
            <pre className="message-body">{message.body || "无正文内容"}</pre>
          )}
        </div>
      ) : null}
    </Modal>
  );
}
