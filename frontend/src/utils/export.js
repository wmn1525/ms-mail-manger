const SPLIT_ALIAS_LENGTH = 4;

// 生成短随机后缀，用于邮箱 +alias 分裂导出。
export function randomLetters(length = SPLIT_ALIAS_LENGTH) {
  const alphabet = "abcdefghijklmnopqrstuvwxyz";
  let value = "";
  for (let index = 0; index < length; index += 1) {
    value += alphabet[Math.floor(Math.random() * alphabet.length)];
  }
  return value;
}

// 按邮箱本体构造加号别名，无法识别邮箱时保持原值。
export function buildSplitEmail(email, suffix) {
  const atIndex = email.lastIndexOf("@");
  if (atIndex <= 0) return email;
  return `${email.slice(0, atIndex)}+${suffix}${email.slice(atIndex)}`;
}

function escapeCsvCell(value) {
  return `"${String(value ?? "").replaceAll('"', '""')}"`;
}

// 使用浏览器下载 CSV，添加 BOM 以便 Excel 正确识别中文。
export function downloadCsv(filename, rows) {
  const csv = `\uFEFF${rows.map((row) => row.map(escapeCsvCell).join(",")).join("\r\n")}`;
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

// 导出每个邮箱本体和指定数量的 +alias 分裂地址。
export function exportSplitMailboxes(mailboxes, count, filenamePrefix) {
  const rows = [["email"]];
  mailboxes.forEach((mailbox) => {
    rows.push([mailbox.email]);
    const usedAliases = new Set();
    while (usedAliases.size < count) {
      const alias = randomLetters();
      if (usedAliases.has(alias)) continue;
      usedAliases.add(alias);
      rows.push([buildSplitEmail(mailbox.email, alias)]);
    }
  });
  downloadCsv(`${filenamePrefix}-${new Date().toISOString().slice(0, 10)}.csv`, rows);
  return rows.length - 1;
}
