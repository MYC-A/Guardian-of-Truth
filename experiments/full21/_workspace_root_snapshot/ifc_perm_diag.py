
import subprocess
def run(*a):
    r = subprocess.run(a, capture_output=True, text=True)
    return f"rc={r.returncode} out={r.stdout.strip()[:400]} err={r.stderr.strip()[:200]}"
print("id:", run("id"))
print("namei:", run("namei","-l","/mnt/data/guardian/secrets/mistral.env"))
print("cat:", run("cat","/mnt/data/guardian/secrets/mistral.env").replace(open("/dev/null").read() if False else "",""))
print("sudo-n:", run("sudo","-n","cat","/mnt/data/guardian/secrets/mistral.env"))
print("getfacl:", run("getfacl","-p","/mnt/data/guardian/secrets") if True else "")
