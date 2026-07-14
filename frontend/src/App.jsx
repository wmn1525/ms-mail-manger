import React, { useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { Spin } from "@douyinfe/semi-ui";
import { api, clearSession, getToken } from "./api";
import { AdminShell } from "./components/AdminShell";
import { Login } from "./components/Login";
import { PublicCodePage } from "./components/PublicCodePage";

// 入口路由只负责认证状态和页面分发，业务 UI 拆在组件内维护。
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/code" element={<PublicCodePage />} />
        <Route path="/login" element={<AuthApp initialPage="login" />} />
        <Route path="/admin" element={<Navigate to="/admin/mailboxes" replace />} />
        <Route path="/admin/mailboxes" element={<AuthApp initialPage="admin" />} />
        <Route path="/admin/icloud-mailboxes" element={<AuthApp initialPage="admin" />} />
        <Route path="/admin/third-party-icloud" element={<AuthApp initialPage="admin" />} />
        <Route path="/admin/imap-configs" element={<AuthApp initialPage="admin" />} />
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
        if (initialPage === "admin") navigate("/login", { replace: true });
        setChecking(false);
        return;
      }
      try {
        const data = await api.me();
        setUsername(data.username);
        if (initialPage === "login") navigate("/admin/mailboxes", { replace: true });
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
    <AdminShell
      username={username}
      onLogout={() => {
        clearSession();
        setUsername("");
        navigate("/login", { replace: true });
      }}
    />
  );
}
