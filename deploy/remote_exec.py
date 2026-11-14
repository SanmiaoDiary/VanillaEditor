"""paramiko SSH 助手（deploy.sh 调用）。

凭据仅从环境变量读取：TARGET_HOST / SSH_USER / SSH_PASS（可选，缺省用 SSH key）。
密码不写入任何文件（DESIGN 8.9）。

用法:
  exec: REMOTE_CMD='...' python remote_exec.py exec              # 退出码 = 远端退出码
  put:  MSYS_NO_PATHCONV=1 python remote_exec.py put LOCAL REMOTE

sudo: 命令含 `sudo -S -p '[VE-SUDO]'` 且设置了 SUDO_PASS 时，经 pty 等提示符出现
      再从 stdin 发送密码（不进命令行参数，不出现在远端 ps，不落盘）。
"""
import os
import sys
import time

import paramiko

SUDO_PROMPT = "[VE-SUDO]"


def connect():
    host = os.environ["TARGET_HOST"]
    user = os.environ["SSH_USER"]
    pw = os.environ.get("SSH_PASS", "")
    client = paramiko.SSHClient()
    # 内网部署场景：首次连接自动接受主机指纹（如需严格校验请自行分发 known_hosts）
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kwargs = dict(username=user, timeout=15, allow_agent=False, look_for_keys=False)
    if pw:
        kwargs["password"] = pw
    client.connect(host, **kwargs)
    return client


def exec_with_sudo(client, cmd, sudo_pass):
    """执行命令；含 sudo -S 时经 pty 等提示符出现后发送密码。"""
    use_pty = bool(sudo_pass) and "sudo -S" in cmd
    _, out, err = client.exec_command(cmd, timeout=900, get_pty=use_pty)
    if use_pty:
        channel = out.channel
        buf = ""
        deadline = time.time() + 30
        while SUDO_PROMPT not in buf and time.time() < deadline:
            if channel.recv_ready():
                buf += channel.recv(1024).decode("utf-8", "replace")
            else:
                time.sleep(0.05)
        # 仅在内存与 SSH 通道中传递密码
        channel.send(sudo_pass + "\n")
    stdout = out.read().decode("utf-8", "replace")
    stderr = err.read().decode("utf-8", "replace")
    code = out.channel.recv_exit_status()
    if stdout:
        print(stdout, end="")
    if stderr:
        print(stderr, end="", file=sys.stderr)
    return code


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("exec", "put"):
        print(__doc__)
        sys.exit(2)
    mode = sys.argv[1]
    client = connect()
    try:
        if mode == "exec":
            code = exec_with_sudo(client, os.environ["REMOTE_CMD"],
                                  os.environ.get("SUDO_PASS", ""))
            sys.exit(code)
        sftp = client.open_sftp()
        try:
            sftp.put(sys.argv[2], sys.argv[3])
        finally:
            sftp.close()
            print(f"uploaded: {sys.argv[2]} -> {sys.argv[3]}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
