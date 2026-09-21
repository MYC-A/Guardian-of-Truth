
import pandas as pd
df = pd.read_parquet("/mnt/data/guardian/agent-workspace/guardian-repo/valid.parquet")[["id","prompt","response"]]
df.to_csv("/mnt/data/guardian/agent-workspace/guardian-repo/outputs/ifc_valid46_label_free.csv", index=False)
print("csv rows:", len(df))
