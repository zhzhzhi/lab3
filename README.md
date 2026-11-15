# 校园二手交易系统（实验三）

软件工程实验三：根据实验二的 UML 设计，实现一个可运行的校园二手交易系统。

技术栈：Python 3.13 + Flask + SQLAlchemy + SQLite + Jinja2。

## 本地运行

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows Git Bash 也可直接调用 .venv/Scripts/python.exe
pip install -r requirements.txt

flask --app run.py init-db
flask --app run.py seed
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

## 目录

```text
app/
├── auth/           # 注册、登录、锁定
├── common/         # 错误、权限、时钟、分页
├── main/           # 首页
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
- [ ] 商品管理
- [ ] 商品查询
- [ ] 预约与交易
- [ ] 举报、用户治理、日志与统计
- [ ] 管理后台页面
- [ ] 代码风格与测试收尾
