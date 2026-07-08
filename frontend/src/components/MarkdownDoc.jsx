import React from "react";

// 渲染内置 API 文档所需的极小 Markdown 子集。
export function MarkdownDoc({ content }) {
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
