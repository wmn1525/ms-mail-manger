export const API_DOC = `# API Key 接口文档

API Key 用于程序访问接口，可访问邮箱列表、邮箱详情、邮件列表、邮件详情和验证码接口。

可使用请求头或 query 参数：

\`\`\`http
X-API-Key: your_api_key
\`\`\`

也可以：

\`\`\`http
?api_key=your_api_key
\`\`\`

## 邮箱列表

\`\`\`http
GET /api/public/mailboxes
\`\`\`

返回字段包含 \`email\`、\`public_token\`、\`status\`、\`last_checked_at\`。

## 按邮箱获取最新验证码

\`\`\`http
GET /api/public/mailboxes/by-email/code?email=user%40icloud.com&limit=10
X-API-Key: your_api_key
\`\`\`

支持 Microsoft 邮箱和已导入的 iCloud 转发邮箱。iCloud 邮箱会读取绑定的 IMAP 接收箱。

也支持自动识别分裂别名，例如 \`user+abcd@icloud.com\` 会回源查询 \`user@icloud.com\`。

## 按 Token 获取最近验证码

\`\`\`http
GET /api/public/mailboxes/{tk_xxxx}/code?limit=10
GET /api/token/{tk_xxxx}/code?limit=10
\`\`\`

接口会返回最近邮件中识别到的 4-8 位数字验证码。`;
