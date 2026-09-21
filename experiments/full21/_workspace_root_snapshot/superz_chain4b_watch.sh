#!/bin/bash
# ждёт ПОЛНОГО завершения chain4 (процесс исчез), затем запускает chain4b
for i in $(seq 1 240); do
  if ! pgrep -f "superz_chain4.sh" > /dev/null; then
    # убедимся, что chain4 не в паузе запуска
    sleep 30
    if ! pgrep -f "superz_chain4.sh" > /dev/null; then
      echo "[watch] chain4 finished, launching chain4b $(date)"
      bash /mnt/data/guardian/agent-workspace/superz_chain4b.sh
      exit 0
    fi
  fi
  sleep 60
done
echo "[watch] timeout $(date)"
