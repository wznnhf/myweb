# 拾题：阿里云 Ubuntu 24.04 初次部署

这份包包含本地版的数学、408、题图、解析和记忆卡。它不包含本地或 Sites 云端的学习记录，也不包含服务器密码、私钥、虚拟环境和测试输出。部署后再通过网页导入所需记录。原本地网站和 Sites 网站不会被本安装程序修改。

这是没有域名时使用的私有预览安装：网站只监听服务器的 `127.0.0.1:8765`，通过 SSH 隧道访问。尚未配置公网 HTTPS、网站登录或域名，不能直接开放 8765 端口用于公网访问。

## 1. 连接服务器

在阿里云 ECS 控制台选择实例所在地域，找到运行中的实例，通过“远程连接 → Workbench”登录。查看系统和登录账号：

```sh
cat /etc/os-release
whoami
```

Ubuntu 24.04 才能使用本安装程序。不要把密码、私钥或阿里云 AccessKey 发到聊天里。

## 2. 上传并安装

通过 Workbench 文件传输或本机 scp，将 `shiti-ubuntu24.tar.gz` 和对应 `.sha256` 文件上传到服务器自己的新建目录。若用 Mac 终端，以下地址、用户名须替换为实例的真实信息；示例中的尖括号不能原样保留。

```sh
scp /Users/fenglang/cuoti/output/aliyun/shiti-ubuntu24.tar.gz /Users/fenglang/cuoti/output/aliyun/shiti-ubuntu24.tar.gz.sha256 <登录用户名>@<服务器公网IP>:~/
```

如需使用密钥，在 scp 或 ssh 后添加 `-i /本机/私钥路径`。SSH 安全组仅允许你当前的可信公网 IP；也可以先使用 Workbench 上传，不需要向全网放开 SSH。

在服务器终端、压缩包所在目录运行：

```sh
sha256sum -c shiti-ubuntu24.tar.gz.sha256
mkdir shiti-upload
tar -xzf shiti-ubuntu24.tar.gz -C shiti-upload
cd shiti-upload/shiti-deploy
sudo bash deploy/install-ubuntu.sh
```

安装程序需联网安装系统与 Python 依赖。它创建专用服务账号、安装到 `/opt/shiti`，把学习数据库保存在 `/var/lib/shiti`。若检测到已有目录或服务会停止，不会覆盖旧学习记录。安装中断时先查看原因；不要为了重试直接删除 `/var/lib/shiti`。

## 3. 在 Mac 上预览

在 Mac 自带“终端”中执行，替换真实账号和 IP：

```sh
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -L 18765:127.0.0.1:8765 <登录用户名>@<服务器公网IP>
```

保持这个终端窗口运行，在 Mac 浏览器打开 `http://127.0.0.1:18765`。命令连接成功后不出现提示是正常的；关闭窗口会结束连接。这一步不需要域名，也没有把网站发布到公网。手机尚不能直接使用这个地址。

## 4. 导入记录并验证

先在你最近实际使用的网站，通过“备份与恢复”导出 JSON；本地版与 Sites 版各保留一份。不要直接合并两份数据库。将选定的备份导入新网站前先查看导入预览，核对笔记、错题夹、每日一练和记忆卡。Sites 旧版备份与新版题库仍需实际导入验证，不保证所有旧数据都能直接合并。

JSON 不包含题图和原卷，本部署包已包含这些资源。安装包本身没有导入你的学习记录。测试期间以一处为主要使用站点，避免三份进度同时变化。

## 5. 备份与维护

每天北京时间 04:00 使用 SQLite 在线备份，保留最近 14 个日期的副本，目录为 `/var/lib/shiti/backups`。同一天重复运行会替换当天副本。它支持运行中的数据库和 WAL，不能用直接复制单个数据库文件替代。

```sh
sudo systemctl status shiti --no-pager
sudo journalctl -u shiti -n 60 --no-pager
sudo systemctl start shiti-backup.service
sudo systemctl list-timers shiti-backup.timer
```

这些副本仍在同一台服务器上；请定期通过网页导出 JSON 保存到自己的电脑。数据库目录不应被配置为公开静态目录。

## 6. 正式域名访问

购买并实名自己的域名，在阿里云办理适用的备案。通过后配置域名解析、HTTPS、个人登录和反向代理，并相应调整应用的允许域名及原站校验。完成登录、笔记保存、交卷、图片和备份的验证后再开放使用。当前部署没有完成这些公网步骤，不要直接把 8765 暴露给公网。
