from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from curl_cffi import requests
from bs4 import BeautifulSoup
import re

app = FastAPI(title="XamToppr Rank Engine")

# CORS allow taaki aapka frontend bina kisi rukawat ke request bhej sake
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ScoreRequest(BaseModel):
    url: str
    category: str = "UR"
    zone: str = "General"

@app.get("/")
def root():
    return {"status": "online", "message": "XamToppr Backend Scraper Active"}

@app.post("/api/calculate")
def calculate_score(data: ScoreRequest):
    url = data.url.strip()
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid DigiALM URL")

    # Step 1: Chrome TLS Impersonation (Bypasses DigiALM / Cloudflare Firewall)
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
        }
        res = requests.get(url, impersonate="chrome120", headers=headers, timeout=12)
        if res.status_code != 200:
            raise HTTPException(status_code=400, detail=f"DigiALM returned status {res.status_code}")
        html_content = res.text
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch response sheet: {str(e)}")

    # Step 2: Parse Candidate Details & Questions
    soup = BeautifulSoup(html_content, "html.parser")

    # Extract Candidate Info
    cand_name = "Candidate"
    roll_number = "N/A"
    exam_name = "RRB / SSC Online Exam"
    exam_date = ""
    exam_time = ""

    for tr in soup.find_all("tr"):
        text = tr.get_text()
        cells = tr.find_all("td")
        if len(cells) >= 2:
            key = cells[0].get_text().strip()
            val = cells[1].get_text().strip()
            if "Candidate Name" in key: cand_name = val
            elif "Roll Number" in key or "Participant ID" in key: roll_number = val
            elif "Subject" in key or "Exam Name" in key: exam_name = val
            elif "Test Date" in key: exam_date = val
            elif "Test Time" in key: exam_time = val

    # Extract Question Panels
    panels = soup.find_all(lambda tag: tag.name == "div" and ("question-pnl" in tag.get("class", []) or "grp-cnt" in tag.get("class", [])))
    if not panels:
        panels = soup.find_all("table", class_="menu-tbl")
        # Fallback wrapper
        panels = [tbl.find_parent("div") for tbl in panels if tbl.find_parent("div")]

    questions = []
    correct_cnt = 0
    wrong_cnt = 0
    unatt_cnt = 0
    sections = {}

    for idx, panel in enumerate(panels):
        q_no = idx + 1
        menu_tbl = panel.find("table", class_="menu-tbl")
        
        chosen_opt = "--"
        if menu_tbl:
            menu_text = menu_tbl.get_text()
            m = re.search(r"Chosen Option\s*:\s*([1-4]|--)", menu_text)
            if m:
                chosen_opt = m.group(1)

        # Official Key (Green tick class rightAns)
        correct_opt = "1"
        right_td = panel.find(class_=re.compile(r"rightAns|correct"))
        if right_td:
            txt = right_td.get_text().strip()
            num_m = re.search(r"^([1-4])\.", txt)
            if num_m:
                correct_opt = num_m.group(1)

        # Status Check
        if chosen_opt == "--" or not chosen_opt:
            status = "UNATTEMPTED"
            unatt_cnt += 1
        elif chosen_opt == correct_opt:
            status = "RIGHT"
            correct_cnt += 1
        else:
            status = "WRONG"
            wrong_cnt += 1

        sec_name = "General Science" if q_no <= 25 else "Mathematics" if q_no <= 55 else "Reasoning" if q_no <= 85 else "General Awareness"
        if sec_name not in sections:
            sections[sec_name] = {"total": 0, "correct": 0, "wrong": 0, "unattempted": 0}
        sections[sec_name]["total"] += 1
        if status == "RIGHT": sections[sec_name]["correct"] += 1
        elif status == "WRONG": sections[sec_name]["wrong"] += 1
        else: sections[sec_name]["unattempted"] += 1

        # Extract Question Text
        stem_el = panel.find(class_=re.compile(r"qtext|question-text|bold"))
        stem_text = stem_el.get_text().strip() if stem_el else f"Question #{q_no}"

        questions.append({
            "qNo": q_no,
            "section": sec_name,
            "stem": stem_text,
            "chosen": chosen_opt,
            "correct": correct_opt,
            "status": status,
            "options": [
                {"id": "1", "text": "Option (A)"},
                {"id": "2", "text": "Option (B)"},
                {"id": "3", "text": "Option (C)"},
                {"id": "4", "text": "Option (D)"}
            ]
        })

    raw_score = round(correct_cnt * 1.0 - wrong_cnt * 0.33, 2)

    return {
        "candidate": {
            "name": cand_name,
            "rollNumber": roll_number,
            "examName": exam_name,
            "examDate": exam_date,
            "examTime": exam_time,
            "category": data.category,
            "zone": data.zone
        },
        "scores": {
            "totalScore": raw_score,
            "totalCorrect": correct_cnt,
            "totalWrong": wrong_cnt,
            "totalUnattempted": unatt_cnt,
            "totalQuestions": len(questions)
        },
        "sections": sections,
        "questions": questions
    }