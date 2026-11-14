"""paramiko SSH 助手（deploy.sh 调用）。

凭据仅从环境变量读取：TARGET_HOST / SSH_USER / SSH_PASS（可选，缺省用 SSH key）。
密码不作为命令行参数（避免出现在进程列表），不写入任何文件（DESIGN 8.9）。

用法:
  exec: REMOTE_CMD='...' python remote_exec.py exec      # 退出码 = 远端退出码
  put:  LOCAL_PATH=... REMOTE_PATH=... python remote_exec.py put
"""
import os
import sys

import paramiko


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


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("exec", "put"):
        print(__doc__)
        sys.exit(2)
    mode = sys.argv[1]
    client = connect()
    try:
        if mode == "exec":
            _, out, err = client.exec_command(os.environ["REMOTE_CMD"], timeout=900)
            stdout = out.read().decode("utf-8", "replace")
            stderr = err.read().decode("utf-8", "replace")
            code = out.channel.recv_exit_status()
            if stdout:
                print(stdout, end="")
            if stderr:
                print(stderr, end="", file=sys.stderr)
            sys.exit(code)
        sftp = client.open_sftp()
        try:
            sftp.put(os.environ["LOCAL_PATH"], os.environ["REMOTE_PATH"])
        finally:
            sftp.close()
            print(f"uploaded: {os.environ['LOCAL_PATH']} -> {os.environ['REMOTE_PATH']}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
