import React from "react";
import { Tag } from "@douyinfe/semi-ui";

// 将后端状态值转换成后台统一的可读标签。
export function StatusTag({ status }) {
  const config = {
    live: { color: "green", text: "正常" },
    dead: { color: "red", text: "失效" },
    unknown: { color: "grey", text: "未检测" },
    forwarded: { color: "blue", text: "转发" },
  }[status] || { color: "grey", text: status };
  return <Tag color={config.color}>{config.text}</Tag>;
}
