cd /data/ur
export PYTHONPATH=$PWD:$PWD/src
set -a; . /data/.guardian_secrets.env; set +a
for arm in R_fix R_comb; do for sr in valid46:1 valid46:2 valid46:3 lb_long:1 lb2_long:1 lb3_long:1 lb3_long:2 ext_tau2:1 ext_tau2:2 ext_tau2:3 hold_tau2h:1 hold_tau2h:2 hold_tau2h:3; do
python -X utf8 -m experiments.universal_repair.run --set ${sr%:*} --rep ${sr#*:} --arm $arm --workers 3 --live 2>&1 | tail -1; done; done
echo QUEUE5_DONE
