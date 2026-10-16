"""管理员命令行工具（在 backend 目录执行）。

  python3 -m app.admin create-admin <用户名> <密码>     创建管理员（已存在则提升为管理员并重置密码）
  python3 -m app.admin invite [数量] [每个可用次数] [有效天数]   生成邀请码（默认 1 个、用 1 次、永不过期）
  python3 -m app.admin users                            列出用户
"""
import sys

from .db import init_db
from .services import auth


def main(argv):
    init_db()
    if len(argv) >= 3 and argv[0] == "create-admin":
        u = auth.ensure_admin(argv[1], argv[2], reset_password=True)
        print(f"管理员已就绪：{u['username']}（id={u['id']}）")
    elif argv and argv[0] == "invite":
        nums = [int(x) for x in argv[1:4]] + [1, 1, 0][len(argv[1:4]):]
        admins = [u for u in auth.list_users() if u["role"] == "admin"]
        admin_id = admins[-1]["id"] if admins else None
        for i in auth.create_invites(admin_id, count=nums[0], max_uses=nums[1], expires_days=nums[2], note="命令行生成"):
            print(f"{i['code']}  可用 {i['max_uses']} 次  过期：{i['expires_at'] or '永不'}")
    elif argv and argv[0] == "users":
        for u in auth.list_users():
            print(f"{u['id']:>4}  {u['username']:<16} {u['role']:<6} {u['status']:<9} 训练 {u['sessions']} 次  注册 {u['created_at']}")
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
