import os, uuid, shutil, subprocess, json, re
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
STORAGE=Path(os.getenv("STORAGE_DIR","storage")); STORAGE.mkdir(parents=True,exist_ok=True)
app=FastAPI(title="Let's Clipping API",version="0.1")
app.add_middleware(CORSMiddleware,allow_origins=os.getenv("CORS_ORIGINS","*").split(","),allow_methods=["*"],allow_headers=["*"])
def run(cmd):
 p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
 if p.returncode: raise RuntimeError(p.stderr[-2000:])
def duration(path):
 out=subprocess.check_output(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(path)],text=True)
 return float(out.strip())
def get_highlights(path):
 # Speech transcript timestamps via Whisper; fallback to evenly spaced windows if unavailable.
 try:
  from faster_whisper import WhisperModel
  model=WhisperModel(os.getenv("WHISPER_MODEL","base"),device="cpu",compute_type="int8")
  segments,info=model.transcribe(str(path),vad_filter=True)
  segs=[{"start":float(s.start),"end":float(s.end),"text":s.text.strip()} for s in segments]
  if segs:
   # score windows based on speech density and punctuation/emphasis; rank then de-overlap
   windows=[]
   step=45
   for st in range(0,max(1,int(info.duration)-20),step):
    en=min(st+45,float(info.duration))
    contained=[s for s in segs if s["end"]>st and s["start"]<en]
    text=" ".join(s["text"] for s in contained)
    if text:
     score=len(text.split())+sum(4 for s in contained if re.search(r"[!?]",s["text"]))
     windows.append((score,st,en,text))
   selected=[]
   for w in sorted(windows,reverse=True):
    if all(abs(w[1]-v[1])>30 for v in selected): selected.append(w)
    if len(selected)>=5: break
   return sorted([{"start":s,"end":e,"transcript":t} for _,s,e,t in selected],key=lambda x:x["start"]),segs
 except Exception as e:
  print("Whisper highlight fallback:",e)
 d=duration(path); length=min(45,d); clips=[]
 for i in range(min(5,max(1,int(d//length)))):
  start=min(i*length,max(0,d-length)); clips.append({"start":start,"end":start+length,"transcript":""})
 return clips,[]
def make_clip(src,jobid,index,start,end,ratio):
 out=STORAGE/jobid/f"clip_{index}_{ratio.replace(':','x')}.mp4"
 vf="scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920" if ratio=="9:16" else "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2"
 run(["ffmpeg","-y","-ss",str(start),"-i",str(src),"-t",str(end-start),"-vf",vf,"-c:v","libx264","-preset","veryfast","-crf","23","-c:a","aac","-movflags","+faststart",str(out)])
 return out
@app.get("/health")
def health(): return {"ok":True,"service":"lets-clipping","version":"0.1"}
@app.post("/api/clip")
async def clip_upload(file:UploadFile=File(...),ratio:str=Form("9:16")):
 if ratio not in ("9:16","16:9"): raise HTTPException(400,"ratio must be 9:16 or 16:9")
 job=uuid.uuid4().hex[:12]; folder=STORAGE/job; folder.mkdir(parents=True)
 src=folder/"source"; 
 with src.open("wb") as f: shutil.copyfileobj(file.file,f)
 try:
  dur=duration(src); windows,transcript=get_highlights(src)
  clips=[]
  for i,w in enumerate(windows,1):
   out=make_clip(src,job,i,w["start"],w["end"],ratio)
   clips.append({"id":i,"file":out.name,"start":w["start"],"end":w["end"],"transcript":w.get("transcript",""),"download":f"/api/jobs/{job}/files/{out.name}"})
  return {"job_id":job,"duration":dur,"ratio":ratio,"clips":clips,"transcript_segments":transcript,"note":"Highlight selection is heuristic and requires review."}
 except Exception as e: raise HTTPException(500,str(e))
@app.post("/api/clip-url")
async def clip_url(url:str=Form(...),ratio:str=Form("9:16")):
 if not url.startswith(("https://","http://")): raise HTTPException(400,"URL must be HTTP(S)")
 if ratio not in ("9:16","16:9"): raise HTTPException(400,"ratio must be 9:16 or 16:9")
 job=uuid.uuid4().hex[:12]; folder=STORAGE/job; folder.mkdir(parents=True)
 src=folder/"source.mp4"
 try:
  run(["yt-dlp","--no-playlist","-f","bestvideo[height<=1080]+bestaudio/best[height<=1080]","--merge-output-format","mp4","-o",str(src),url])
  dur=duration(src); windows,transcript=get_highlights(src); clips=[]
  for i,w in enumerate(windows,1):
   out=make_clip(src,job,i,w["start"],w["end"],ratio)
   clips.append({"id":i,"file":out.name,"start":w["start"],"end":w["end"],"transcript":w.get("transcript",""),"download":f"/api/jobs/{job}/files/{out.name}"})
  return {"job_id":job,"duration":dur,"ratio":ratio,"clips":clips,"transcript_segments":transcript,"note":"Only use videos you own or have permission to process; validate source/platform terms."}
 except Exception as e: raise HTTPException(500,str(e))
@app.get("/api/jobs/{job}/files/{name}")
def download(job:str,name:str):
 p=STORAGE/job/name
 if not p.exists() or p.parent!=STORAGE/job: raise HTTPException(404,"file not found")
 return FileResponse(p,filename=name)
