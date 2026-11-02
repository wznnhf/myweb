#!/bin/zsh
set -eu

TASK_DIR="${0:A:h}"
cd "$TASK_DIR"

if [[ ! -x "$TASK_DIR/app/.venv/bin/python" ]]; then
  print '没有找到拾题的 Python 环境，请保留 app 文件夹。'
  read '?按回车关闭…'
  exit 1
fi

if "$TASK_DIR/app/.venv/bin/python" "$TASK_DIR/app/launch.py"; then
  TASK_RESULT=0
else
  TASK_RESULT=$?
  read '?启动失败，按回车关闭…'
fi
exit "$TASK_RESULT"
