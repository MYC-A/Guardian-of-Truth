cd /data/ur
export PYTHONPATH=$PWD:$PWD/src
set -a; . /data/.guardian_secrets.env; set +a
while kill -0 3393 2>/dev/null; do sleep 30; done
for arm in R_fix R_df R_comb; do for sr in valid46:1 lb_long:1 lb2_long:1 lb3_long:1 lb3_long:2 ext_tau2:1 ext_tau2:2 ext_tau2:3; do
python -X utf8 -m experiments.universal_repair.run --set ${sr%:*} --rep ${sr#*:} --arm $arm --workers 3 --live 2>&1 | tail -1; done; done
echo QUEUE3_DONE
