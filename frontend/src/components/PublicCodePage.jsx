import React, { useState } from "react";
import { Button, Card, Form, Space, Tag, Toast, Typography } from "@douyinfe/semi-ui";
import { IconCopy, IconMail, IconRefresh } from "@douyinfe/semi-icons";
import { api } from "../api";

const { Text } = Typography;

// 公开取码页通过 tk token 获取最新验证码。
export function PublicCodePage() {
  const [token, setToken] = useState(localStorage.getItem("public_mailbox_token") || "");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);

  async function fetchCode() {
    setLoading(true);
    try {
      localStorage.setItem("public_mailbox_token", token.trim());
      const data = await api.tokenLatestCode(token.trim());
      setResult(data);
      Toast[data.code ? "success" : "warning"](data.code ? `验证码：${data.code}` : "最近邮件未识别到验证码");
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
          <Form.Input label="邮箱 Token" field="token" value={token} onChange={setToken} />
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
