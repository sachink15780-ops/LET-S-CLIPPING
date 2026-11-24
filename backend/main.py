import os, uuid, shutil, subprocess, re
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

STORAGE = Path(os.getenv("STORAGE_DIR", "/app/storage"))
STORAGE.mkdir(parents=True, exist_ok=True)
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "500"))
app = FastAPI(title="LET'S CLIPPING API", version="1.0")
origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "*").split(",") if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"], allow_headers=["*"])

def run(cmd, timeout=3600):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError((p.stderr or "Processing failed")[-1800:])

def duration(path):
    out = subprocess.check_output(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(path)], text=True, timeout=60)
    d = float(out.strip())
    if d <= 0 or d > 6*3600: raise ValueError("Video must be under 6 hours.")
    return d

def highlights(path, d):
    try:
        from faster_whisper import WhisperModel
        model_name = os.getenv("WHISPER_MODEL", "base")
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        segs, info = model.transcribe(str(path), vad_filter=True)
        segs = [{"start":float(s.start),"end":float(s.end),"text":s.text.strip()} for s in segs]
        windows=[]
        width=45
        for start in range(0,max(1,int(d-width+1)),30):
            end=min(start+width,d)
            contained=[s for s in segs if s["end"]>start and s["start"]<end]
            text=" ".join(s["text"] for s in contained)
            if text:
                score=len(text.split()) + sum(5 for s in contained if re.search(r"[!?]",s["text"])) + sum(2 for s in contained if re.search(r"\b(what|wow|amazing|really|never|secret|important|crazy)\b",s["text"],re.I))
                windows.append((score,start,end,text))
        selected=[]
        for w in sorted(windows,key=lambda x:x[0],reverse=True):
            if all(abs(w[1]-v[1])>=30 for v in selected): selected.append(w)
            if len(selected)>=5: break
        if selected: return sorted([{"start":a,"end":b,"transcript":t} for _,a,b,t in selected],key=lambda x:x["start"]),segs
    except Exception as exc:
        print("Transcription/highlight fallback:", str(exc)[:300])
    length=min(45,d); count=min(5,max(1,int(d//length)))
    return [{"start":min(i*length,max(0,d-length)),"end":min(i*length,max(0,d-length))+length,"transcript":""} for i in range(count)],[]

def render(src, job, idx, start, end, ratio):
    out=STORAGE/job/f"clip_{idx}_{ratio.replace(':','x')}.mp4"
    vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920" if ratio=="9:16" else "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2"
    run(["ffmpeg","-y","-ss",str(start),"-i",str(src),"-t",str(end-start),"-vf",vf,"-c:v","libx264","-preset","veryfast","-crf","23","-c:a","aac","-movflags","+faststart",str(out)],timeout=1800)
    return out

def process(src, ratio):
    if ratio not in ("9:16","16:9"): raise HTTPException(400,"Choose 9:16 or 16:9.")
    job=uuid.uuid4().hex[:12]; folder=STORAGE/job; folder.mkdir(parents=True,exist_ok=True)
    d=duration(src); wins, transcript=highlights(src,d); clips=[]
    for i,w in enumerate(wins,1):
        out=render(src,job,i,w["start"],w["end"],ratio)
        clips.append({"id":i,"start":w["start"],"end":w["end"],"transcript":w.get("transcript",""),"download":f"/api/jobs/{job}/files/{out.name}"})
    return {"job_id":job,"duration":d,"ratio":ratio,"clips":clips,"transcript_segments":transcript,"note":"AI-assisted highlight selection is heuristic; review before publishing."}

@app.get("/health")
def health(): return {"ok":True,"service":"lets-clipping","version":"1.0"}

@app.post("/api/clip")
async def clip_upload(file: UploadFile=File(...), ratio: str=Form("9:16")):
    if not file.filename: raise HTTPException(400,"Select a video file.")
    if not (file.content_type or "").startswith("video/"): raise HTTPException(400,"Upload a video file only.")
    job=uuid.uuid4().hex[:12]; folder=STORAGE/job; folder.mkdir(parents=True,exist_ok=True)
    src=folder/"source_video"
    size=0
    try:
        with src.open("wb") as f:
            while chunk:=await file.read(1024*1024):
                size+=len(chunk)
                if size>MAX_UPLOAD_MB*1024*1024: raise HTTPException(413,f"Video exceeds {MAX_UPLOAD_MB} MB limit.")
                f.write(chunk)
        return process(src,ratio)
    except HTTPException: raise
    except Exception as e: raise HTTPException(500,f"Processing error: {str(e)[:700]}")
    finally:
        await file.close()

@app.post("/api/clip-url")
async def clip_url(url: str=Form(...), ratio: str=Form("9:16")):
    parsed=urlparse(url.strip())
    host=(parsed.hostname or "").lower()
    allowed={"youtube.com","www.youtube.com","m.youtube.com","youtu.be","www.youtu.be"}
    if parsed.scheme not in ("http","https") or host not in allowed: raise HTTPException(400,"Paste a public YouTube video URL.")
    job=uuid.uuid4().hex[:12]; folder=STORAGE/job; folder.mkdir(parents=True,exist_ok=True)
    src=folder/"source_video.mp4"
    try:
        run(["yt-dlp","--no-playlist","--socket-timeout","30","--max-filesize",f"{MAX_UPLOAD_MB}M","-f","bestvideo[height<=1080]+bestaudio/best[height<=1080]","--merge-output-format","mp4","-o",str(src),url],timeout=1800)
        return process(src,ratio)
    except Exception as e: raise HTTPException(500,f"URL download/processing error: {str(e)[:700]}")

@app.get("/api/jobs/{job}/files/{name}")
def download(job:str,name:str):
    if not re.fullmatch(r"[a-f0-9]{12}",job) or not re.fullmatch(r"clip_\d+_(9x16|16x9)\.mp4",name): raise HTTPException(400,"Invalid file request.")
    p=STORAGE/job/name
    if not p.is_file(): raise HTTPException(404,"Clip not found.")
    return FileResponse(p,filename=name,media_type="video/mp4")
