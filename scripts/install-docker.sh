#!/bin/bash
# Docker Engine 安装脚本（Ubuntu WSL2）
# 用法：sudo bash scripts/install-docker.sh
set -euo pipefail

echo "=== 1/5 安装依赖 ==="
apt-get update -qq
apt-get install -y -qq ca-certificates curl gnupg

echo "=== 2/5 添加 Docker GPG key ==="
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

echo "=== 3/5 添加 Docker apt 源 ==="
# 优先用 resolute(26.04)，回退 noble(24.04)
. /etc/os-release
if apt-cache madison docker-ce 2>/dev/null | grep -q resolute; then
  CODENAME=resolute
else
  CODENAME=noble
fi
echo "使用 codename: $CODENAME"
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $CODENAME stable" \
  > /etc/apt/sources.list.d/docker.list

echo "=== 4/5 安装 Docker ==="
apt-get update -qq
apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

echo "=== 5/5 配置用户组 + 启动服务 ==="
USER_NAME="${SUDO_USER:-$USER}"
usermod -aG docker "$USER_NAME"

# WSL2 启动 docker 服务
service docker start 2>/dev/null || dockerd >/dev/null 2>&1 &
sleep 3

echo ""
echo "=== 验证 ==="
docker --version
docker compose version
docker run --rm hello-world 2>&1 | head -5

echo ""
echo "✅ Docker 安装完成。"
echo "请重新登录（或运行 newgrp docker）让用户组生效。"
