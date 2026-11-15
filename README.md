# 校园二手交易系统（实验三）

软件工程实验三：根据实验二的 UML 设计，实现一个可运行的校园二手交易系统。

技术栈：Python 3.13 + Flask + SQLAlchemy + SQLite + Jinja2。

## 本地运行

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows Git Bash 也可直接调用 .venv/Scripts/python.exe
pip install -r requirements.txt

flask --app run.py reset-db   # 第一次或改了模型后：重建并写入示例数据
flask --app run.py run --debug
```

打开 http://127.0.0.1:5000/ 。

## 测试与代码风格

```bash
pytest
pylint app
black --check app tests
```

## 演示账号

| 账号 | 密码 | 角色 |
|---|---|---|
| admin | admin12345 | 管理员 |
| buyer01 | buyer12345 | 买家 |
| seller01 | seller12345 | 卖家 + 买家 |
| disabled01 | disabled12345 | 已禁用买家 |

## 演示流程

1. `seller01` 发布商品 → 提交审核；
2. `admin` 在“审核”页通过；
3. `buyer01` 在商品详情页“立即预约”，商品转为已预约并锁定 48 小时；
4. `seller01` 在“预约处理”确认，商品转为已确认；
5. `buyer01` 在“我的预约”确认完成，商品转为已完成。

## 目录

```text
app/
├── auth/           # 注册、登录、锁定
├── common/         # 错误、权限、时钟、分页
├── main/           # 首页
├── reservations/   # 预约、确认、取消、完成、失效、仲裁
├── reports/        # 举报提交与管理员处理
├── admin/          # 管理后台：用户、日志、统计
├── models.py       # User/Category/Item/ItemImage/Reservation/Report/OperationLog/IdempotencyRecord
├── enums.py        # 角色与状态
├── templates/      # Jinja2 页面
└── static/         # CSS
tests/              # pytest
seed.py             # 演示数据
run.py              # 开发入口
```

## 当前进度

- [x] 应用工厂、配置、数据库模型、枚举
- [x] 注册/登录/登出、角色、登录锁定
- [x] 健康检查、初始化与种子数据
- [x] 商品管理
- [x] 商品查询
- [x] 预约与交易（幂等预约、48 小时惰性失效、卖家确认/取消、买家完成、管理员仲裁）
- [x] 举报与处理（举报商品、管理员成立/不成立、成立自动下架）
- [x] 用户治理（搜索、禁用/恢复、解除登录锁定）
- [x] 操作日志查询与统计报表
- [x] 管理后台页面
- [ ] 代码风格与测试收尾
