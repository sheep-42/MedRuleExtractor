# Dockerfile for Frontend (Vue/React) - Updated for Node.js v22

# --- Stage 1: Build the application ---
# 使用与本地开发环境匹配的 Node.js 版本
# 你的本地版本是 v22.17.0，我们使用 node:22-alpine
FROM node:22-alpine as builder

# 设置前端项目目录为工作目录
WORKDIR /app

# 拷贝 package.json 和 lock 文件
COPY package*.json ./

# 安装依赖
# 注意：高版本的 npm 可能需要 --force 或 --legacy-peer-deps 选项
# 如果 npm install 失败，可以尝试下面的命令
# RUN npm ci --legacy-peer-deps
RUN npm ci

# 拷贝所有源代码
COPY . .

# 构建生产版本的静态文件
RUN npm run build

# --- Stage 2: Serve the application with Nginx ---
FROM nginx:stable-alpine

# 将构建好的静态文件从 builder 阶段拷贝到 Nginx 的默认 web 根目录
COPY --from=builder /app/dist /usr/share/nginx/html

# 设置文件权限，这是一个好习惯
RUN chmod -R 755 /usr/share/nginx/html && \
    chown -R nginx:nginx /usr/share/nginx/html

# (可选) 如果你有自定义的 Nginx 配置，可以取消下面这行的注释
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 暴露 Nginx 的默认端口
EXPOSE 80

# 启动 Nginx (Nginx官方镜像通常会处理这个，但明确写出也无妨)
CMD ["nginx", "-g", "daemon off;"]