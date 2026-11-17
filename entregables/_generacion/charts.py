import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt, csv, sys
G=sys.argv[1]
NAVY="#0B1B33"; BLUE="#1F5FBF"; CYAN="#2BB3C0"; GREEN="#1D7A46"; RED="#B3261E"; AMBER="#A86200"; GREY="#5B6573"; GRID="#E3E7ED"
plt.rcParams.update({"font.family":"DejaVu Sans","font.size":11,"axes.edgecolor":GRID,"axes.labelcolor":GREY,"xtick.color":GREY,"ytick.color":GREY,"axes.spines.top":False,"axes.spines.right":False})
def T(ax,t,loc=None,**kw):
    ax.figure.suptitle(t,x=0.01,ha="left",**kw)
def save(fig,name,src):
    fig.text(0.01,0.01,"Fuente: "+src,fontsize=8,color=GREY)
    fig.tight_layout(rect=(0,0.03,1,1)); fig.savefig(f"{G}/{name}.png",dpi=200); plt.close(fig)
def hbar(ax,labels,vals,colors):
    b=ax.barh(labels,vals,color=colors,height=0.6); ax.invert_yaxis(); ax.xaxis.grid(True,color=GRID); ax.set_axisbelow(True)
    for r,v in zip(b,vals): ax.text(r.get_width()+max(vals)*0.01,r.get_y()+r.get_height()/2,str(v),va="center",fontsize=10,color=NAVY,fontweight="bold")
# 1 tests
lab=["Backend · módulos y unitarias","Backend · E2E (flujos, salida, intrusión)","Backend · regresiones de seguridad","Firmware · nativas (Unity)","Firmware · integración con gateway"]
val=[179,31,12,86,13]
fig,ax=plt.subplots(figsize=(9,3.6)); hbar(ax,lab,val,[BLUE,BLUE,BLUE,CYAN,CYAN]); T(ax,"Pruebas automatizadas ejecutadas: 321 aprobadas, 0 fallidas",loc="left",color=NAVY,fontweight="bold")
save(fig,"g1_pruebas_por_suite","ejecución de pytest y pio test el 15-11-2026 (árbol de trabajo actual)")
# 2 sessions
rows=list(csv.DictReader(open(f"{G}/datos_sesiones_acceso_reales.csv")))
name={"CONCEDIDO_Y_CERRADO":"Concedido y cerrado","UNKNOWN_CARD":"Tarjeta no registrada","NOBODY_INSIDE":"Botón de salida sin nadie dentro","CARD_LOCKED":"Tarjeta bloqueada temporalmente","NO_VALID_AUTH":"Sin autorización vigente","PRESENCE_LOST":"Presencia perdida","AUTH_NOT_STARTED":"Autorización aún no iniciada","FACE_MISMATCH":"Rostro no coincide"}
agg={}
for r in rows: k=name.get(r["motivo"],r["motivo"]); agg[k]=agg.get(k,0)+int(r["sesiones"])
items=sorted(agg.items(),key=lambda x:-x[1])
fig,ax=plt.subplots(figsize=(9,4)); hbar(ax,[k for k,_ in items],[v for _,v in items],[GREEN if k.startswith("Concedido") else RED for k,_ in items])
T(ax,"39 sesiones de acceso registradas con el ESP32 físico (11 concedidas, 28 denegadas)",loc="left",color=NAVY,fontweight="bold",fontsize=11)
save(fig,"g2_sesiones_por_resultado","BD local data/dcguardian.db, 15-11-2026 (firmware 1.0.0); agregados, sin datos personales")
# 3 face scores
rows=[r for r in csv.DictReader(open(f"{G}/datos_puntuaciones_faciales_reales.csv")) if r["accion"]!="access.face_retry"]
fig,ax=plt.subplots(figsize=(9,3.8))
xs=range(1,len(rows)+1); ys=[float(r["similitud"]) for r in rows]
cols=[GREEN if r["accion"]=="access.face_ok" else RED for r in rows]
ax.bar(xs,ys,color=cols,width=0.6); ax.axhline(0.45,color=AMBER,ls="--",lw=1.5); ax.text(len(rows)+0.4,0.46,"umbral 0,45",color=AMBER,fontsize=9,ha="right")
for x,y in zip(xs,ys): ax.text(x,y+0.015,f"{y:.2f}".replace(".",","),ha="center",fontsize=9,color=NAVY)
ax.set_ylim(0,1); ax.set_xticks(list(xs)); ax.set_xlabel("Verificación (orden cronológico)"); ax.set_ylabel("Similitud coseno 1:1"); ax.yaxis.grid(True,color=GRID); ax.set_axisbelow(True)
T(ax,"Similitud facial con InsightFace buffalo_l: 8 aceptadas (0,61–0,84) y 1 rechazada (0,29)",loc="left",color=NAVY,fontweight="bold",fontsize=11)
save(fig,"g3_similitud_facial","auditoría local (access.face_ok / access.denied), 15-11-2026; muestra pequeña, un solo usuario registrado")
# 4 timings
ent=[("E1",6.2,1.0),("S1",6.6,1.2),("E2",7.3,0.7),("S2",9.9,0.8),("E3",11.6,0.7),("S3·botón",0.4,0.8),("E4",12.7,0.8),("S4·botón",0.5,0.8),("E5",9.1,0.7),("S5·botón",1.5,0.7),("E6",7.1,0.9)]
fig,ax=plt.subplots(figsize=(9,3.8)); l=[e[0] for e in ent]
ax.bar(l,[e[1] for e in ent],color=BLUE,width=0.6,label="Tarjeta (o botón) → decisión")
ax.bar(l,[e[2] for e in ent],bottom=[e[1] for e in ent],color=CYAN,width=0.6,label="Decisión → puerta abierta")
for i,e in enumerate(ent): ax.text(i,e[1]+e[2]+0.2,f"{e[1]+e[2]:.1f} s".replace(".",","),ha="center",fontsize=9,color=NAVY)
ax.set_ylabel("segundos"); ax.yaxis.grid(True,color=GRID); ax.set_axisbelow(True); ax.legend(frameon=False,fontsize=9,loc="upper left")
T(ax,"Tiempos de las 11 aperturas reales (E = entrada con rostro, S = salida)",loc="left",color=NAVY,fontweight="bold",fontsize=11)
save(fig,"g4_tiempos_apertura","access_sessions (created_at, decided_at, opened_at), 15-11-2026; incluye el tiempo humano frente a la cámara")
# 5 alerts
rows=list(csv.DictReader(open(f"{G}/datos_alertas_reales.csv"))); agg={}
sev={}
for r in rows: agg[r["tipo"]]=agg.get(r["tipo"],0)+int(r["alertas"]); sev[r["tipo"]]=r["severidad"] if r["severidad"]=="CRITICAL" else sev.get(r["tipo"],r["severidad"])
items=sorted(agg.items(),key=lambda x:-x[1])
fig,ax=plt.subplots(figsize=(9,4)); hbar(ax,[k for k,_ in items],[v for _,v in items],[RED if sev[k]=="CRITICAL" else (AMBER if sev[k]=="WARN" else GREY) for k,_ in items])
T(ax,"38 alertas generadas por el sistema (rojo = CRITICAL, ámbar = WARN, gris = INFO)",loc="left",color=NAVY,fontweight="bold",fontsize=11)
save(fig,"g5_alertas_por_tipo","tabla alerts de data/dcguardian.db, 15-11-2026")
# 6 code size
lab=["Backend (app)","Pruebas backend","Frontend (JS+CSS+HTML)","Firmware (src+lib)","Pruebas firmware","Simulador ESP32","Documentación (docs)"]
val=[6937,2650,3760,3383,1771,353,1542]
fig,ax=plt.subplots(figsize=(9,3.6)); hbar(ax,lab,val,[BLUE,CYAN,BLUE,BLUE,CYAN,BLUE,GREY]); T(ax,"Tamaño del proyecto en líneas (≈ 20 400 en total)",loc="left",color=NAVY,fontweight="bold")
save(fig,"g6_lineas_por_componente","recuento con wc -l de los archivos versionados y modificados, 15-11-2026")
