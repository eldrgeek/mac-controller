import importlib.util, pathlib
spec = importlib.util.spec_from_file_location(
    "mac_triage", pathlib.Path(__file__).with_name("mac-triage.py"))
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)

procs = t.list_procs()
ld = t.launchd_pid_labels()
print("parsed procs:", len(procs), "| our-daemon pids tracked:", len(ld))

# What would fire IF the machine were under memory pressure right now?
tg = t.find_targets(procs, ld, mem_pressure=True)
print("targets under simulated mem-pressure:", len(tg))
for c, a, p, r in tg:
    print(f"  [{c}] {a} pid={p['pid']} cpu={p['cpu']} rss={p['rss_mb']:.0f}MB :: {r}")

print("--- top 3 chrome renderers by CPU (detector sees these) ---")
rend = [p for p in procs if "--type=renderer" in p["cmd"] and "Google Chrome" in p["cmd"]]
for p in sorted(rend, key=lambda x: -x["cpu"])[:3]:
    print(f"  pid={p['pid']} cpu={p['cpu']} rss={p['rss_mb']:.0f}MB")

print("--- top 3 our-daemons by RSS (detector sees these) ---")
od = [(p, ld[p["pid"]]) for p in procs if p["pid"] in ld]
for p, l in sorted(od, key=lambda x: -x[0]["rss_mb"])[:3]:
    print(f"  {l} pid={p['pid']} cpu={p['cpu']} rss={p['rss_mb']:.0f}MB")

# Confirm protections: nothing protected ever appears as a target
prot = [p for p in procs if t.PROTECT.search(p["cmd"])]
print(f"protected procs matched (never targetable): {len(prot)} "
      f"(e.g. cc-bridge/mcp/Claude/zoom/screenpipe)")
