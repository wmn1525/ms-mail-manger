import React from "react";
import { Button, Layout, Nav, Space, Typography } from "@douyinfe/semi-ui";
import { IconExit, IconInbox, IconMail, IconRefresh } from "@douyinfe/semi-icons";
import { useLocation, useNavigate } from "react-router-dom";
import { ApiKeyPage } from "./ApiKeyPage";
import { IcloudMailboxesPage } from "./IcloudMailboxesPage";
import { ImapConfigsPage } from "./ImapConfigsPage";
import { MailboxesPage } from "./MailboxesPage";
import { ThirdPartyIcloudPage } from "./ThirdPartyIcloudPage";

const { Header, Sider, Content } = Layout;
const { Text } = Typography;

function getActivePage(pathname) {
  if (pathname.includes("/third-party-icloud")) return "third-party-icloud";
  if (pathname.includes("/icloud-mailboxes")) return "icloud-mailboxes";
  if (pathname.includes("/imap-configs")) return "imap-configs";
  if (pathname.includes("/api-keys")) return "api-keys";
  return "mailboxes";
}

// 后台布局负责导航和退出，具体业务页面保持独立。
export function AdminShell({ username, onLogout }) {
  const location = useLocation();
  const navigate = useNavigate();
  const activePage = getActivePage(location.pathname);

  function refreshCurrentPage() {
    window.location.reload();
  }

  return (
    <Layout className="app-layout">
      <Header className="app-header">
        <Nav
          mode="horizontal"
          className="header-nav"
          header={{
            logo: <div className="brand-mark small"><IconMail /></div>,
            text: "Mail Admin",
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
          selectedKeys={[activePage]}
          onSelect={(item) => navigate(`/admin/${item.itemKey}`)}
          mode="vertical"
          className="side-nav"
          items={[
            { itemKey: "mailboxes", text: "微软邮箱", icon: <IconInbox /> },
            { itemKey: "icloud-mailboxes", text: "iCloud 邮箱", icon: <IconMail /> },
            { itemKey: "third-party-icloud", text: "第三方 iCloud", icon: <IconMail /> },
            { itemKey: "imap-configs", text: "IMAP 配置", icon: <IconInbox /> },
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
          {activePage === "mailboxes" && <MailboxesPage />}
          {activePage === "icloud-mailboxes" && <IcloudMailboxesPage />}
          {activePage === "third-party-icloud" && <ThirdPartyIcloudPage />}
          {activePage === "imap-configs" && <ImapConfigsPage />}
          {activePage === "api-keys" && <ApiKeyPage />}
        </Content>
      </Layout>
    </Layout>
  );
}
