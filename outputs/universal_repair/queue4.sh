cd /data/ur
export PYTHONPATH=$PWD:$PWD/src
set -a; . /data/.guardian_secrets.env; set +a
for sr in valid46:2 valid46:3 hold_tau2h:1 hold_tau2h:2 hold_tau2h:3; do
python -X utf8 -m experiments.universal_repair.run --set ${sr%:*} --rep ${sr#*:} --arm R_fix --workers 3 --live 2>&1 | tail -1; done
echo QUEUE4_DONE
