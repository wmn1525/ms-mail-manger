import React from "react";
import { Pagination, Select, Space, Typography } from "@douyinfe/semi-ui";
import { MAILBOX_PAGE_SIZE_OPTIONS } from "../constants/mailbox";

const { Text } = Typography;

export function MailboxPagination({
  currentPage,
  pageSize,
  total,
  currentCount,
  onPageChange,
  onPageSizeChange,
}) {
  const start = total === 0 ? 0 : (currentPage - 1) * pageSize + 1;
  const end = total === 0 ? 0 : Math.min(total, start + currentCount - 1);

  return (
    <div className="mailbox-pagination">
      <Text type="tertiary">
        共 {total} 条 · 当前 {start}-{end}
      </Text>
      <Space className="mailbox-pagination__controls">
        <Space spacing={8}>
          <Text type="tertiary">每页</Text>
          <Select
            value={pageSize}
            onChange={(value) => onPageSizeChange(Number(value))}
            optionList={MAILBOX_PAGE_SIZE_OPTIONS.map((value) => ({
              label: `${value} 条`,
              value,
            }))}
            style={{ width: 104 }}
            aria-label="每页条数"
          />
        </Space>
        <Pagination
          currentPage={currentPage}
          pageSize={pageSize}
          total={total}
          showTotal
          onPageChange={onPageChange}
        />
      </Space>
    </div>
  );
}
