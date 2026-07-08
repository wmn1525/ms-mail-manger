import React, { useState } from "react";
import { Button, Form, Toast, Typography } from "@douyinfe/semi-ui";
import { IconMail } from "@douyinfe/semi-icons";
import { useNavigate } from "react-router-dom";
import { api, setSession } from "../api";

const { Text } = Typography;

// 管理员登录页，登录成功后写入本地会话并进入后台。
export function Login({ onLogin }) {
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
            <h1 className="page-title center">邮件取件后台</h1>
            <Text type="tertiary">Sign in to mail console</Text>
          </div>
        </div>
        <Form className="login-form" onSubmit={handleSubmit} labelPosition="top">
          <Form.Input field="username" label="管理员账号" placeholder="admin" rules={[{ required: true }]} />
          <Form.Input field="password" label="密码" mode="password" rules={[{ required: true }]} />
          <Button theme="solid" type="primary" htmlType="submit" loading={loading} block>
            登录
          </Button>
        </Form>
      </div>
    </div>
  );
}
