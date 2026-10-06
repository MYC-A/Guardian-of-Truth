cd /data/ur
export PYTHONPATH=$PWD:$PWD/src
set -a; . /data/.guardian_secrets.env; set +a
while kill -0 2757 2>/dev/null; do sleep 30; done
for sr in hold_tau2h:1 hold_tau2h:2 hold_tau2h:3 valid46:2 valid46:3; do for arm in V4r R_comb; do
python -X utf8 -m experiments.universal_repair.run --set ${sr%:*} --rep ${sr#*:} --arm $arm --workers 3 --live 2>&1 | tail -1; done; done
echo QUEUE2_DONE
