
import pandas as pd, json, hashlib
df = pd.read_parquet("valid.parquet")
pred = pd.read_csv("outputs/baseline_ifc/predictions.csv")
m = df[["id","label"]].merge(pred, on="id", suffixes=("_gold","_pred"))
tp = int(((m.label_gold==1)&(m.label_pred==1)).sum()); fp = int(((m.label_gold==0)&(m.label_pred==1)).sum())
fn = int(((m.label_gold==1)&(m.label_pred==0)).sum()); tn = int(((m.label_gold==0)&(m.label_pred==0)).sum())
f1 = 2*tp/(2*tp+fp+fn) if (2*tp+fp+fn) else 0.0
print(json.dumps({"tp":tp,"fp":fp,"fn":fn,"tn":tn,"f1":round(f1,4),"n":len(m)}))
print("pred label counts:", pred.label.value_counts().to_dict())
