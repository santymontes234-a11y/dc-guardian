import httpx, sys, time, datetime as dt
B="http://127.0.0.1:8765/api/v1"; pw=open(sys.argv[1]).read().strip()
c=httpx.Client(timeout=30)
r=c.post(B+"/auth/login",json={"username":"admin","password":pw}); r.raise_for_status()
def p(path,**kw):
    r=c.post(B+path,**kw); print(path,r.status_code,str(r.json())[:160]); return r.json()
p("/sim/enroll-demo-faces")
now=dt.datetime.now(dt.timezone.utc).isoformat()
r1=p("/requests",json={"engineer_id":"ENG-0001","card_uid":"04A1B2C3","area_id":1,"reason":"Mantenimiento preventivo de racks","start_at":now,"duration_minutes":120})
p(f"/requests/{r1['id']}/approve",json={"notes":"Aprobado para mantenimiento"})
r2=p("/requests",json={"engineer_id":"ENG-0002","card_uid":"93F2A1D7","area_id":1,"reason":"Revisión de switches del núcleo","start_at":now,"duration_minutes":60})
p(f"/requests/{r2['id']}/approve",json={"notes":"Aprobado"})
p("/requests",json={"engineer_id":"ENG-0003","card_uid":"5B7C9E01","area_id":3,"reason":"Inspección de baterías UPS","start_at":now,"duration_minutes":90})
D="/sim/DC-DOOR-01"
p(D+"/heartbeat")
def attempt(uid,mode):
    p(D+"/card",json={"uid":uid})
    if mode:
        p(D+"/face",json={"mode":mode})
        for _ in range(6):
            out=p(D+"/poll"); st=out["reply"]["data"].get("state") if isinstance(out.get("reply"),dict) and out["reply"].get("data") else None
            if st in ("GRANTED","DENIED","TIMEOUT") or out["device"].get("door")=="OPEN": break
            time.sleep(0.6)
        if out["device"].get("door")=="OPEN": p(D+"/close")
attempt("04A1B2C3","match")      # entry granted
attempt("0BADC0DE",None)         # unknown card
attempt("93F2A1D7","other")      # face mismatch
attempt("5B7C9E01",None)         # pending request
attempt("04A1B2C3","match")      # exit
attempt("93F2A1D7","match")      # entry granted (Carlos)
p(D+"/heartbeat")
