# MiniForum 开发会话摘要

## 项目概况
- **项目**: MiniForum - Flask 论坛应用
- **部署**: Render + Supabase PostgreSQL
- **仓库**: https://github.com/Eatjune/MiniForum

## 核心功能迭代记录

### 1. 初始部署 (已完成)
- 从 Vercel 迁移到 Render（Vercel 不支持 Flask，Fly.io 需信用卡）
- 数据库从 SQLite 迁移到 Supabase PostgreSQL
- 修复 `init_pool()` 不存在 bug
- 添加 `render.yaml` 配置

### 2. 嵌套回复功能 (已完成)
- `replies` 表新增 `parent_id` 字段实现 Reddit 式嵌套回复
- 添加自动迁移逻辑：检测列不存在则 `ALTER TABLE` 添加
- 修复回复成功后 redirect 锚点拼接 bug

### 3. 通知系统 (已完成)
- 新增 `notifications` 表
- 回复帖子/回复时自动创建通知
- 导航栏红点显示未读数量
- 「我的」页面新增「通知」tab，未读项高亮显示（蓝色背景+粗体）
- 进入通知页面自动标记全部已读

### 4. 个人中心「我的」页面 (已完成)
- 整合为统一入口，含三个 tab：
  - **我的帖子**: 可编辑、删除
  - **我的回复**: 可删除，点击跳转原帖位置
  - **通知**: 显示谁回复了你

### 5. 删除功能 (已完成)
- 帖子作者可删除自己的帖子
- 回复作者可删除自己的回复
- 管理员仍可删除任何内容
- 删除入口分布在：帖子页、「我的」页面

### 6. 后台管理功能 (已完成)
- 管理员可修改任意用户密码
- 管理员可删除用户/帖子/回复
- 管理员可设置/取消管理员权限

## 关键文件变更
- `app.py` - 核心路由逻辑、数据库迁移
- `templates/my.html` - 个人中心三 tab 页面
- `templates/post.html` - 嵌套回复、删除按钮
- `templates/base.html` - 导航栏红点
- `templates/admin.html` - 后台管理
- `templates/admin_change_password.html` - 改密码页面
- `templates/edit_post.html` - 编辑帖子

## 数据库 Schema
```sql
users: id, username, password_hash, is_admin, created_at
posts: id, user_id, title, content, created_at
replies: id, post_id, user_id, parent_id, content, created_at
notifications: id, user_id, type, from_user_id, post_id, reply_id, is_read, created_at
```

## 当前状态
- 所有功能已开发完成并推送到 GitHub
- Render 自动部署
- 已知问题：无

## 待办
- 无
