"""提供邮箱地址查询所需的标准化规则。"""


def remove_split_alias(email: str) -> str:
    """移除本地部分的 +alias，使分裂邮箱回源到原始邮箱。"""

    value = email.strip().lower()
    local, separator, domain = value.rpartition("@")
    if not separator:
        return value
    return f"{local.split('+', 1)[0]}@{domain}"
