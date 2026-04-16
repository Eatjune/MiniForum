# 论坛系统规格文档

## 1. 项目概述

- **项目名称**：MiniForum
- **类型**：轻量级社区论坛（Flask + SQLite，单文件后端 + 少量模板）
- **核心功能**：用户注册/登录（QQ号 或 邮箱+密码）、发帖/回帖、管理员后台
- **目标用户**：小型社区、自建论坛场景

---

## 2. 技术栈

| 层级 | 技术选型 | 说明 |
|------|---------|------|
| 后端 | Flask + SQLite | Python 标准库，无需安装数据库 |
| 前端 | 纯 HTML + CSS + Vanilla JS | 无框架，单文件便于部署 |
| 认证 | 会话 Cookie | Flask session，服务器存储 |
| 部署 | `python app.py` 单命令启动 | 端口 5000 |

---

## 3. 数据模型

### 用户表 (users)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增 |
| username | TEXT UNIQUE | 显示名 |
| email | TEXT UNIQUE | 可选，唯一 |
| qq | TEXT UNIQUE | 可选，唯一 |
| password_hash | TEXT | PBKDF2 哈希 |
| is_admin | INTEGER | 0/1 |
| created_at | TIMESTAMP | 注册时间 |

### 帖子表 (posts)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增 |
| user_id | INTEGER FK | 发帖人 |
| title | TEXT | 标题（max 200字） |
| content | TEXT | 正文（max 10000字） |
| created_at | TIMESTAMP | 发布时间 |

### 回复表 (replies)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增 |
| post_id | INTEGER FK | 所属帖子 |
| user_id | INTEGER FK | 回复人 |
| content | TEXT | 内容（max 5000字） |
| created_at | TIMESTAMP | 发布时间 |

---

## 4. 页面结构

### 4.1 首页 `/` — 帖子列表
- 标题 + 摘要（截取前100字）
- 作者 + 发布时间
- 回复数
- 分页（每页20条）
- 右侧：登录/注册入口 or 用户信息

### 4.2 帖子详情 `/post/<id>`
- 帖子完整内容 + 作者信息
- 回复列表
- 回复输入框（登录后可发）
- 管理员：显示「删除」按钮

### 4.3 发帖页 `/new`
- 仅登录用户可见
- 标题 + 内容（textarea）
- 发布按钮

### 4.4 登录页 `/login`
- 方式一：QQ号 + 密码
- 方式二：邮箱 + 密码
- 登录后跳回上一页或首页

### 4.5 注册页 `/register`
- 用户名（必填）
- 密码 + 确认密码
- QQ号（可选）
- 邮箱（可选，至少填一个 QQ 或邮箱）
- 提示：至少填写 QQ 或邮箱之一

### 4.6 管理后台 `/admin`
- 仅管理员可见
- 用户管理：查看用户列表、删除用户、设为/取消管理员
- 帖子管理：删除任意帖子
- 回复管理：删除任意回复

---

## 5. 安全设计

- 密码：PBKDF2 + 盐，100000 轮
- SQL 注入：SQLite 参数化查询
- XSS：Jinja2 自动转义
- CSRF：Flask-WTF 表单 token（简化版可跳过）
- 会话：Flask secret_key，服务器存储

---

## 6. 文件结构

```
forum/
├── app.py              # 主应用（所有路由 + 数据库 + 初始化）
├── init_db.py          # 数据库初始化脚本
└── templates/          # HTML 模板
    ├── base.html       # 基础模板（导航栏 + 页脚）
    ├── index.html      # 首页（帖子列表）
    ├── post.html       # 帖子详情 + 回复
    ├── new_post.html   # 发帖页
    ├── login.html      # 登录页
    ├── register.html   # 注册页
    └── admin.html      # 管理后台
```

---

## 7. 默认管理员

- 用户名：`admin`
- 密码：`admin123`
- 首次启动自动创建

---

## 8. 验收标准

- [ ] 启动后访问 `http://127.0.0.1:5000` 可见论坛首页
- [ ] 可以注册（用户名+密码+QQ或邮箱）
- [ ] 可以登录（QQ号 或 邮箱 + 密码）
- [ ] 可以发帖、查看帖子
- [ ] 可以回复（登录用户）
- [ ] admin 账号可登录后台，删除用户/帖子/回复
- [ ] 未登录用户不能发帖/回复
- [ ] 页面无明显排版问题，中文显示正常
